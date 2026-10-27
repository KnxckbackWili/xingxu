"""Persistent, administrator-controlled updates; no Docker access in the web process.

The host runner crosses the same file-lock seam through system_update_bridge.
Configuration survives backup; transient jobs deliberately do not get replayed
by a restored system backup. Network calls never hold the cross-process lock.
"""
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
import time
import unicodedata
import uuid

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app import config
from app.services import update_source

PROTOCOL = 1
TRUST_PROTOCOL = 1
TRUST_MESSAGES = {
    "pending": "等待宿主验证此仓库版本",
    "commit": "宿主已登记此仓库的完整提交",
    "signed_tag": "标签签名已由宿主验证",
    "not_configured": "宿主尚未配置更新信任，请联系部署管理员登记提交或签名公钥",
    "source_not_allowed": "此更新仓库未被宿主信任，网页不能添加信任",
    "commit_not_allowed": "此提交未在宿主登记，也不是可验证的签名标签",
    "signature_invalid": "标签未签名、签名不匹配或签名公钥未被宿主信任",
    "target_changed": "签名标签、提交或版本与检查结果不一致，请重新检查",
    "policy_changed": "宿主信任配置已变化，请重新检查此版本",
    "receipt_invalid": "缺少有效的宿主检查记录，请重新检查",
    "content_changed": "已验证源码内容发生变化，拒绝安装",
    "tool_unavailable": "宿主缺少 Git 或配置的签名验证工具，请联系部署管理员",
    "fetch_failed": "宿主无法读取仓库的 Git 对象，请检查网络和读取权限",
}
HEARTBEAT_TTL = 60
CHECK_TTL = 30 * 60
SOURCE_SCHEMA = 2
MAX_SOURCES = 20
DEFAULT_SOURCE_ID = "default-gitea"
DEFAULT_REPOSITORY_URL = "https://gitea.arrowwood.top:8773/codex-mac/agv-project-workflow"
_SOURCE_FIELDS = ("id", "name", "is_default", "repository_url", "ref", "allow_http", "token_encrypted")
TERMINAL = {"succeeded", "failed", "rolled_back", "needs_attention"}
STAGES = {"downloading", "building", "backing_up", "installing", "verifying"}
MESSAGES = {
    "queued": "更新请求已保存，等待更新服务处理",
    "downloading": "正在下载并校验已确认的版本",
    "building": "正在准备新版本，当前应用仍可使用",
    "backing_up": "正在保存更新前备份，应用将短暂不可用",
    "installing": "正在切换版本，请等待应用恢复",
    "verifying": "正在确认新版本运行状态",
    "succeeded": "更新完成，可以刷新页面使用新版本",
    "failed": "更新未完成，原版本保持运行；请查看更新服务日志",
    "rolled_back": "更新失败，已恢复更新前版本与数据",
    "needs_attention": "更新恢复未完成，请联系部署管理员检查备份和日志；不要直接重启应用",
}


class UpdateError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.now(timezone.utc).isoformat()


def _timestamp(value):
    try:
        return datetime.fromisoformat(value).timestamp()
    except (ValueError, TypeError):
        return 0


def _data_dir():
    return config.DATA_DIR


def _directory():
    path = _data_dir() / "system-updates"
    if path.is_symlink():
        raise UpdateError("更新目录异常，请联系部署管理员", 503)
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def _read(path, default):
    try:
        if path.is_symlink():
            raise ValueError("symlink")
        if not path.exists():
            return default
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("oversized state")
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError("invalid state")
        return value
    except (OSError, ValueError):
        raise UpdateError("更新配置或记录无法读取，请联系部署管理员", 503) from None


def _write(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".update-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def _locked():
    directory = _directory()
    fd = os.open(directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _default_source():
    return {"id": DEFAULT_SOURCE_ID, "name": "我的 Gitea", "is_default": True,
            "repository_url": DEFAULT_REPOSITORY_URL, "ref": "main", "allow_http": False,
            "token_encrypted": ""}


def _source_name(value):
    if (not isinstance(value, str) or not value.strip() or len(value.strip()) > 60
            or any(unicodedata.category(char).startswith("C") for char in value)):
        raise UpdateError("更新源名称须为 1–60 个可显示字符")
    return value.strip()


def _active_source(configuration):
    active = next(source for source in configuration["sources"]
                  if source["id"] == configuration["active_source_id"])
    return {**active, "revision": configuration["revision"]}


def _configuration():
    """Read old and new formats without rewriting backed-up configuration.

    The flat active source remains readable by 2.4.0 hosts. A 2.4.0 save
    replaces the entire file with the legacy shape, which we can migrate again.
    Mixed flat/list records are rejected rather than guessing which token wins.
    """
    raw = _read(_data_dir() / "system-update-config.json", None)
    default = _default_source()
    if raw is None:
        return {"schema_version": SOURCE_SCHEMA, "revision": 0,
                "active_source_id": DEFAULT_SOURCE_ID, "sources": [default]}
    try:
        revision = raw["revision"]
        if type(revision) is not int or revision < 0:
            raise ValueError()
        if "sources" not in raw:
            if "schema_version" in raw or "active_source_id" in raw:
                raise ValueError()
            legacy = {key: raw[key] for key in ("repository_url", "ref", "allow_http", "token_encrypted")}
            normalized = update_source.normalize_source(legacy["repository_url"], legacy["ref"], legacy["allow_http"])
            if not isinstance(legacy["token_encrypted"], str):
                raise ValueError()
            if (normalized["repository_url"], normalized["ref"]) == (default["repository_url"], default["ref"]):
                sources = [{**default, **legacy}]
            else:
                sources = [default, {"id": "legacy-source", "name": "原更新源", "is_default": False, **legacy}]
            return {"schema_version": SOURCE_SCHEMA, "revision": revision,
                    "active_source_id": sources[-1]["id"], "sources": sources}
        if raw.get("schema_version") != SOURCE_SCHEMA or type(raw.get("sources")) is not list:
            raise ValueError()
        if not 1 <= len(raw["sources"]) <= MAX_SOURCES:
            raise ValueError()
        sources, identifiers, identities = [], set(), set()
        for source in raw["sources"]:
            if not isinstance(source, dict) or set(source) != set(_SOURCE_FIELDS):
                raise ValueError()
            identifier = source["id"]
            if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", identifier):
                raise ValueError()
            if identifier in identifiers or type(source["is_default"]) is not bool:
                raise ValueError()
            if source["is_default"] != (identifier == DEFAULT_SOURCE_ID):
                raise ValueError()
            if _source_name(source["name"]) != source["name"] or not isinstance(source["token_encrypted"], str):
                raise ValueError()
            normalized = update_source.normalize_source(source["repository_url"], source["ref"], source["allow_http"])
            identity = (normalized["repository_url"], normalized["ref"])
            if identity in identities:
                raise ValueError()
            identifiers.add(identifier)
            identities.add(identity)
            sources.append({key: source[key] for key in _SOURCE_FIELDS})
        if DEFAULT_SOURCE_ID not in identifiers or raw.get("active_source_id") not in identifiers:
            raise ValueError()
        configuration = {"schema_version": SOURCE_SCHEMA, "revision": revision,
                         "active_source_id": raw["active_source_id"], "sources": sources}
        active = _active_source(configuration)
        if any(raw.get(key) != active[key] for key in _SOURCE_FIELDS):
            raise ValueError()
        return configuration
    except (KeyError, TypeError, ValueError):
        raise UpdateError("更新源列表或兼容配置不一致，请联系部署管理员检查配置", 503) from None


def _source():
    """Only the selected source; safe to freeze in an installation job."""
    return _active_source(_configuration())


def _state():
    return _read(_directory() / "state.json", {"check": None, "job": None, "runner": None})


def _save(state):
    _write(_directory() / "state.json", state)


def _fernet():
    key = HKDF(algorithm=hashes.SHA256(), length=32,
               salt=b"xingxu-update-source-v1", info=b"repository-access-token").derive(config.SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def _token(source):
    encrypted = source.get("token_encrypted", "")
    if not encrypted:
        return ""
    try:
        return _fernet().decrypt(encrypted.encode()).decode()
    except (InvalidToken, ValueError, UnicodeError):
        raise UpdateError("更新源凭据无法解密，请重新保存访问令牌", 409) from None


def _public_job(job):
    if not job:
        return None
    return {key: job[key] for key in (
        "id", "status", "phase", "message", "target_version", "target_commit", "created_at", "updated_at",
    )}


def _online(state):
    runner = state.get("runner") or {}
    age = time.time() - _timestamp(runner.get("last_seen"))
    return runner.get("protocol") == PROTOCOL and 0 <= age <= HEARTBEAT_TTL


def _public_source(source, revision):
    return {**{key: source[key] for key in _SOURCE_FIELDS if key != "token_encrypted"},
            "revision": revision, "has_token": bool(source.get("token_encrypted"))}


def _payload(state, configuration):
    source = _active_source(configuration)
    runner = state.get("runner") or {}
    check = state.get("check")
    if check and (check["source_revision"] != source["revision"]
                  or check.get("source_id", source["id"]) != source["id"]):
        check = None
    return {
        "current": {"version": config.APP_VERSION, "commit": os.getenv("GIT_SHA", "unknown")},
        "source": _public_source(source, source["revision"]),
        "sources": [_public_source(item, source["revision"]) for item in configuration["sources"]],
        "active_source_id": source["id"],
        "maintenance": is_maintenance(),
        "runner": {"online": _online(state), "last_seen": runner.get("last_seen"), "protocol": PROTOCOL,
                   "trust": {"configured": runner.get("trust_protocol") == TRUST_PROTOCOL and runner.get("trust_configured") is True,
                             "protocol": runner.get("trust_protocol", 0)}},
        "check": check,
        "job": _public_job(state.get("job")),
    }


def get_status():
    with _locked():
        return _payload(_state(), _configuration())


def is_maintenance():
    """Fail closed during the short data-preservation/switching window."""
    try:
        marker = _data_dir() / "update-maintenance.json"
        if marker.exists() or marker.is_symlink():
            return True
        # Normal requests must not create a directory/lock on installations
        # which have never enabled software updates.
        path = _data_dir() / "system-updates" / "state.json"
        state = _read(path, {})
        return (state.get("job") or {}).get("status") in {
            "backing_up", "installing", "verifying", "needs_attention",
        }
    except UpdateError:
        return True


def _busy(state):
    job = state.get("job")
    # A failed restoration must be resolved by the host operator, never by
    # starting another deployment on a potentially incompatible database.
    return job and (job["status"] not in TERMINAL or job["status"] == "needs_attention")


def _validated_source(values, previous=None):
    normalized = update_source.normalize_source(values["repository_url"], values["ref"], values["allow_http"])
    token = values.get("token")
    if token and (len(token) > 4096 or any(not 33 <= ord(c) <= 126 for c in token)):
        raise UpdateError("访问令牌格式不正确")
    if token and values.get("clear_token"):
        raise UpdateError("不能同时填写和清除访问令牌")
    previous = previous or {}
    encrypted = previous.get("token_encrypted", "")
    # Credentials belong to a repository and never cross source boundaries.
    if values.get("clear_token") or normalized["repository_url"] != previous.get("repository_url"):
        encrypted = ""
    if token:
        encrypted = _fernet().encrypt(token.encode()).decode()
    name = _source_name(values.get("name") if values.get("name") is not None else previous.get("name"))
    return {**{key: normalized[key] for key in ("repository_url", "ref", "allow_http")},
            "name": name, "token_encrypted": encrypted}


def _editable(configuration, state, revision):
    if _busy(state) or is_maintenance():
        raise UpdateError("更新正在进行或需要人工处理，暂时不能修改更新源", 409)
    if type(revision) is not int or revision != configuration["revision"]:
        raise UpdateError("更新配置已被修改，请刷新后重新保存", 409)


def _ensure_unique(configuration, source, ignored_id=None):
    for existing in configuration["sources"]:
        if existing["id"] == ignored_id:
            continue
        normalized = update_source.normalize_source(existing["repository_url"], existing["ref"], existing["allow_http"])
        if (normalized["repository_url"], normalized["ref"]) == (source["repository_url"], source["ref"]):
            raise UpdateError("相同仓库和分支的更新源已存在，请直接选择该更新源", 409)


def _persist_configuration(configuration, state):
    configuration["revision"] += 1
    _write(_data_dir() / "system-update-config.json", {**configuration, **_active_source(configuration)})
    state["check"] = None
    _save(state)
    return _payload(state, configuration)


def save_source(values):
    with _locked():
        configuration, state = _configuration(), _state()
        _editable(configuration, state, values["revision"])
        previous = _active_source(configuration)
        source = {**previous, **_validated_source(values, previous)}
        source.pop("revision")
        _ensure_unique(configuration, source, previous["id"])
        configuration["sources"] = [source if item["id"] == source["id"] else item
                                    for item in configuration["sources"]]
        return _persist_configuration(configuration, state)


def add_source(values):
    with _locked():
        configuration, state = _configuration(), _state()
        _editable(configuration, state, values["revision"])
        if len(configuration["sources"]) >= MAX_SOURCES:
            raise UpdateError(f"最多可以保存 {MAX_SOURCES} 个更新源")
        source = {"id": str(uuid.uuid4()), "is_default": False, **_validated_source(values)}
        _ensure_unique(configuration, source)
        configuration["sources"].append(source)
        configuration["active_source_id"] = source["id"]
        return _persist_configuration(configuration, state)


def select_source(source_id, revision):
    with _locked():
        configuration, state = _configuration(), _state()
        _editable(configuration, state, revision)
        if not any(source["id"] == source_id for source in configuration["sources"]):
            raise UpdateError("更新源不存在，请刷新后重试", 404)
        configuration["active_source_id"] = source_id
        return _persist_configuration(configuration, state)


def delete_source(source_id, revision):
    with _locked():
        configuration, state = _configuration(), _state()
        _editable(configuration, state, revision)
        if source_id == DEFAULT_SOURCE_ID:
            raise UpdateError("默认 Gitea 更新源不能删除")
        if not any(source["id"] == source_id for source in configuration["sources"]):
            raise UpdateError("更新源不存在，请刷新后重试", 404)
        configuration["sources"] = [source for source in configuration["sources"] if source["id"] != source_id]
        if configuration["active_source_id"] == source_id:
            configuration["active_source_id"] = DEFAULT_SOURCE_ID
        return _persist_configuration(configuration, state)


def _version(value):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?", value)
    if not match:
        raise UpdateError("版本号格式不受支持")
    major = tuple(int(match[i]) for i in range(1, 4))
    prerelease = match[4]
    parts = tuple((0, int(p)) if p.isdigit() else (1, p) for p in prerelease.split(".")) if prerelease else ()
    return major, prerelease is None, parts


def check_source(source_revision):
    with _locked():
        configuration, state = _configuration(), _state()
        source = _active_source(configuration)
        if _busy(state) or is_maintenance():
            raise UpdateError("更新正在进行或需要人工处理，暂时不能重新检查", 409)
        if source["revision"] != source_revision:
            raise UpdateError("配置已变化，请保存并重新检查", 409)
        if not source["repository_url"]:
            raise UpdateError("请先保存 Gitea 更新源")
    target = update_source.inspect_source(source, _token(source))
    # Branch movement between inspection and installation cannot change this SHA.
    current_commit = os.getenv("GIT_SHA", "unknown")
    same_commit = current_commit != "unknown" and len(current_commit) >= 7 and target["commit"].startswith(current_commit)
    available = _version(target["version"]) >= _version(config.APP_VERSION) and not same_commit
    with _locked():
        current, state = _configuration(), _state()
        if current["revision"] != source_revision or _busy(state) or is_maintenance():
            raise UpdateError("检查期间配置或更新状态已变化，请重新检查", 409)
        state["check"] = {
            "id": str(uuid.uuid4()), "source_revision": source_revision, "source_id": source["id"],
            "commit": target["commit"], "version": target["version"],
            "checked_at": _now(), "update_available": available,
            "trust": {"status": "pending", "message": TRUST_MESSAGES["pending"]},
        }
        _save(state)
        return _payload(state, current)


def request_install(check_id, actor_id):
    with _locked():
        configuration, state = _configuration(), _state()
        source = _active_source(configuration)
        previous = state.get("job")
        # Lost HTTP responses must not queue the same installation twice.
        if previous and previous.get("check_id") == check_id:
            return _payload(state, configuration)
        if _busy(state) or is_maintenance():
            raise UpdateError("已有更新正在执行或等待人工处理", 409)
        check = state.get("check")
        if (not check or check["id"] != check_id or check["source_revision"] != source["revision"]
                or check.get("source_id", source["id"]) != source["id"]):
            raise UpdateError("检查结果已失效，请重新检查更新", 409)
        age = time.time() - _timestamp(check["checked_at"])
        if age < 0 or age > CHECK_TTL:
            raise UpdateError("检查结果已过期，请重新检查更新", 409)
        if not check["update_available"]:
            raise UpdateError("当前没有可安装的新版本；不支持通过此入口降级", 409)
        if not _online(state):
            raise UpdateError("更新服务未连接，请先在部署主机启动更新服务", 409)
        runner = state.get("runner") or {}
        if runner.get("trust_protocol") != TRUST_PROTOCOL or runner.get("trust_configured") is not True:
            raise UpdateError(TRUST_MESSAGES["not_configured"], 409)
        if (check.get("trust") or {}).get("status") != "trusted":
            raise UpdateError("此版本尚未通过宿主信任校验，请等待验证或重新检查", 409)
        now = _now()
        state["job"] = {
            "id": str(uuid.uuid4()), "check_id": check_id, "actor_id": actor_id,
            "status": "queued", "phase": "queued", "message": MESSAGES["queued"],
            "target_version": check["version"], "target_commit": check["commit"],
            "created_at": now, "updated_at": now, "source": source,
        }
        _save(state)
        return _payload(state, configuration)


def _identity(value):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise UpdateError("更新任务标识无效") from None


def _owned(state, runner_id, job_id):
    _identity(runner_id)
    _identity(job_id)
    job = state.get("job")
    if not job or job["id"] != job_id or job.get("runner_id") != runner_id:
        raise UpdateError("更新任务不属于此更新服务", 409)
    return job


def heartbeat(runner_id, protocol, trust_protocol=None, trust_configured=False):
    _identity(runner_id)
    if type(protocol) is not int or protocol != PROTOCOL:
        raise UpdateError("更新服务协议不兼容，请更新宿主服务", 409)
    with _locked():
        state = _state()
        existing = state.get("runner") or {}
        if _online(state) and existing.get("id") != runner_id:
            raise UpdateError("已有另一个更新服务连接此应用", 409)
        state["runner"] = {"id": runner_id, "protocol": PROTOCOL, "last_seen": _now(),
                           "trust_protocol": TRUST_PROTOCOL if type(trust_protocol) is int and trust_protocol == TRUST_PROTOCOL else 0,
                           "trust_configured": trust_configured is True and type(trust_protocol) is int and trust_protocol == TRUST_PROTOCOL}
        _save(state)
    return {"ok": True}


def _host_runner(state, runner_id):
    _identity(runner_id)
    if not _online(state) or (state.get("runner") or {}).get("id") != runner_id:
        raise UpdateError("更新服务尚未连接", 409)


def _trusted_runner(state, runner_id):
    _host_runner(state, runner_id)
    runner = state.get("runner") or {}
    if runner.get("trust_protocol") != TRUST_PROTOCOL or runner.get("trust_configured") is not True:
        raise UpdateError(TRUST_MESSAGES["not_configured"], 409)


def _candidate(check, source):
    return {"check_id": check["id"], "source_id": source["id"], "source_revision": source["revision"],
            "repository_url": source["repository_url"], "ref": source["ref"],
            "commit": check["commit"], "version": check["version"]}


def trust_request(runner_id):
    with _locked():
        state, configuration = _state(), _configuration()
        _host_runner(state, runner_id)
        check = state.get("check")
        source = _active_source(configuration)
        if (not check or (check.get("trust") or {}).get("status") != "pending"
                or check.get("source_id") != source["id"] or check.get("source_revision") != source["revision"]
                or not 0 <= time.time() - _timestamp(check.get("checked_at")) <= CHECK_TTL):
            return {"candidate": None}
        return {"candidate": _candidate(check, source)}


def trust_credentials(runner_id, check_id=None, job_id=None):
    # Host-only stdin bridge. No HTTP handler returns repository credentials.
    with _locked():
        state = _state()
        _host_runner(state, runner_id)
        if job_id is not None:
            job = _owned(state, runner_id, job_id)
            if job["status"] != "downloading":
                raise UpdateError("此阶段不能读取源码凭据", 409)
            source = job["source"]
        else:
            check = state.get("check")
            source = _active_source(_configuration())
            if not check or check.get("id") != check_id or check.get("source_id") != source["id"] or check.get("source_revision") != source["revision"]:
                raise UpdateError("检查期间来源已变化", 409)
        return {"token": _token(source)}


def trust_result(runner_id, check_id, status, method=None, reason=None):
    if status not in {"trusted", "rejected"} or (status == "trusted" and method not in {"commit", "signed_tag"}):
        raise UpdateError("宿主信任结果无效")
    with _locked():
        state, configuration = _state(), _configuration()
        _host_runner(state, runner_id)
        check, source = state.get("check"), _active_source(configuration)
        if (not check or check.get("id") != check_id or check.get("source_id") != source["id"]
                or check.get("source_revision") != source["revision"]
                or not 0 <= time.time() - _timestamp(check.get("checked_at")) <= CHECK_TTL):
            raise UpdateError("宿主验证期间检查结果已变化，请重新检查", 409)
        code = method if status == "trusted" else reason if reason in TRUST_MESSAGES else "receipt_invalid"
        check["trust"] = {"status": status, "message": TRUST_MESSAGES[code]}
        if status == "trusted":
            check["trust"]["method"] = method
        else:
            check["trust"]["reason"] = code
        _save(state)
        return {"ok": True}


def _host_job(job):
    source = job["source"]
    return {**_public_job(job), "check_id": job["check_id"],
            "source_id": source["id"], "source_revision": source["revision"],
            "repository_url": source["repository_url"], "ref": source["ref"]}


def claim(runner_id):
    _identity(runner_id)
    with _locked():
        state = _state()
        if not _online(state) or (state.get("runner") or {}).get("id") != runner_id:
            raise UpdateError("更新服务尚未连接", 409)
        job = state.get("job")
        if not job or job["status"] in TERMINAL:
            return {"job": None}
        # A capable host may claim a previously queued job after policy
        # revocation in order to reject it and publish a terminal reason. Old
        # runners still cannot claim, and stage transitions require trust.
        if (state.get("runner") or {}).get("trust_protocol") != TRUST_PROTOCOL:
            raise UpdateError(TRUST_MESSAGES["not_configured"], 409)
        if job["status"] != "queued":
            # A claim response can be lost before the host persists its journal.
            # Only the original runner may recover it. The host may retry a
            # download, but must stop for operator review after later stages.
            if job.get("runner_id") == runner_id:
                return {"job": _host_job(job)}
            raise UpdateError("已有更新由其他更新服务处理，请恢复原更新服务", 409)
        job.update(runner_id=runner_id, status="downloading", phase="downloading",
                   message=MESSAGES["downloading"], updated_at=_now())
        _save(state)
        return {"job": _host_job(job)}


def prepare(runner_id, job_id):
    # The old runner trusted an app-supplied tar/hash. Capability flags in this
    # app-writable state cannot make that protocol safe: never provide a package
    # through it, including when the flags/job were forged. New hosts obtain
    # authenticated Git objects themselves and do not call this operation.
    raise UpdateError("旧版压缩包更新协议已停用，请升级宿主更新服务并重新检查版本", 409)


def report(runner_id, job_id, status, reason=None):
    if status not in STAGES | TERMINAL:
        raise UpdateError("更新状态无效")
    with _locked():
        state = _state()
        job = _owned(state, runner_id, job_id)
        if status in {"building", "backing_up", "installing"}:
            _trusted_runner(state, runner_id)
        if job["status"] in TERMINAL:
            if job["status"] != status:
                raise UpdateError("更新任务已结束，不能覆盖最终结果", 409)
            return {"job": _public_job(job)}
        sequence = ["downloading", "building", "backing_up", "installing", "verifying", "succeeded"]
        if status in sequence and sequence.index(status) < sequence.index(job["status"]):
            raise UpdateError("更新阶段不能倒退", 409)
        if status == "succeeded":
            actual = os.getenv("GIT_SHA", "unknown")
            if config.APP_VERSION != job["target_version"] or actual != job["target_commit"]:
                raise UpdateError("实际运行版本与目标提交不一致，不能报告更新成功", 409)
        message = MESSAGES[status]
        if status in {"failed", "needs_attention"} and reason in TRUST_MESSAGES:
            message += "；" + TRUST_MESSAGES[reason]
        job.update(status=status, phase=status, message=message, updated_at=_now())
        if status in TERMINAL:
            job.pop("source", None)
        _save(state)
        return {"job": _public_job(job)}
