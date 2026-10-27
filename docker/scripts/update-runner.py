#!/usr/bin/env python3
"""Host-only updater for an explicitly enrolled Compose installation.

No Docker socket or host command endpoint is exposed to the application. Tokens
cross only the local stdin bridge into host memory, never argv/logs/job files.
Git objects and signatures are independently verified against host trust roots.
Running this file is an explicit host-administrator action, never an app startup
side effect. Standard-library-only; Linux/macOS (fcntl.flock).
"""
import argparse
from contextlib import contextmanager
import fcntl
import importlib.util
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid


# Always use the installed host module, never an update's downloaded copy.
_trust_spec = importlib.util.spec_from_file_location("xingxu_host_update_trust", Path(__file__).with_name("update-trust.py"))
TRUST = importlib.util.module_from_spec(_trust_spec)
_trust_spec.loader.exec_module(TRUST)


MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_SOURCE_BYTES = 1024 * 1024 * 1024
MAX_SOURCE_FILES = 30000
SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?")
TERMINAL = {"succeeded", "failed", "rolled_back", "needs_attention"}
MESSAGES = {
    "downloading": "正在准备已确认版本的源码包。",
    "building": "正在构建新镜像，当前应用继续运行。",
    "backing_up": "正在停止写入并创建更新前备份。",
    "installing": "正在切换应用版本，请稍候。",
    "verifying": "正在检查新版本运行状态。",
    "succeeded": "更新完成，应用已通过健康检查。",
    "failed": "更新未完成；请由宿主管理员检查本机更新日志。",
    "rolled_back": "更新未完成，已恢复原镜像和更新前数据。",
    "needs_attention": "更新状态需要宿主管理员确认，请勿重复安装或手动启动写入服务。",
}


class UpdateError(RuntimeError):
    pass


def private_dir(path):
    path = Path(path)
    if path.is_symlink():
        raise UpdateError("更新工作目录不能是符号链接。")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(value, output, ensure_ascii=False)
            output.flush(); os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


@contextmanager
def bounded_tar(archive, directory, max_bytes, max_files):
    # Count the gzip stream itself, including PAX/long-name headers. Summing
    # only yielded members misses metadata bombs processed by tarfile first.
    with tempfile.TemporaryFile(dir=directory) as expanded:
        limit = max_bytes + max_files * 4096
        total = 0
        with gzip.open(archive, "rb") as compressed:
            while block := compressed.read(1024 * 1024):
                total += len(block)
                if total > limit: raise UpdateError("源码包解压数据超出限制。")
                expanded.write(block)
        expanded.seek(0)

        class ReadGuard:
            def read(self, size=-1):
                # Regular file contents are copied in 1 MiB chunks below.
                # Tar extension metadata must never allocate an arbitrary size.
                if size < 0 or size > 1024 * 1024:
                    raise UpdateError("源码包扩展元数据超出限制。")
                return expanded.read(size)

            def __getattr__(self, name):
                return getattr(expanded, name)

        with tarfile.open(fileobj=ReadGuard(), mode="r:") as package:
            yield package


def extract_source(archive, destination, version, *, max_bytes=MAX_SOURCE_BYTES, max_files=MAX_SOURCE_FILES):
    """Validate every member before writing; never use tar.extract/all."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise UpdateError("源码暂存目录已存在，拒绝覆盖。")
    try:
        with bounded_tar(archive, destination.parent, max_bytes, max_files) as package:
            members = []; seen = {}; prefix = None; total = 0
            for member in package:
                name = member.name.rstrip("/") if member.isdir() else member.name
                parts = name.split("/")
                if (not name or name.startswith("/") or "\\" in name or "\x00" in name
                        or any(part in ("", ".", "..") for part in parts)
                        or not (member.isfile() or member.isdir()) or member.issparse()):
                    raise UpdateError("源码包包含不安全的路径或文件类型。")
                if prefix is None: prefix = parts[0]
                if parts[0] != prefix or (len(parts) == 1 and not member.isdir()):
                    raise UpdateError("源码包必须只有一个仓库目录。")
                if name in seen:
                    raise UpdateError("源码包包含重复路径。")
                seen[name] = member.isdir()
                total += member.size
                if member.size < 0 or total > max_bytes or len(seen) > max_files:
                    raise UpdateError("源码包超出解压限制。")
                members.append(member)
            if not prefix: raise UpdateError("源码包为空。")
            for name in seen:
                for parent in PurePosixPath(name).parents:
                    if str(parent) in seen and not seen[str(parent)]:
                        raise UpdateError("源码包文件与目录冲突。")
            private_dir(destination)
            for member in members:
                relative = PurePosixPath(member.name).parts[1:]
                target = destination.joinpath(*relative)
                if member.isdir():
                    private_dir(target)
                else:
                    private_dir(target.parent)
                    source = package.extractfile(member)
                    if source is None: raise UpdateError("源码文件无法读取。")
                    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700 if member.mode & 0o111 else 0o600)
                    with source, os.fdopen(fd, "wb") as output:
                        remaining = member.size
                        while remaining:
                            chunk = source.read(min(remaining, 1024 * 1024))
                            if not chunk: raise UpdateError("源码包文件不完整。")
                            output.write(chunk); remaining -= len(chunk)
            package_file = destination / "frontend/package.json"
            if not package_file.is_file() or package_file.stat().st_size > 1024 * 1024:
                raise UpdateError("源码包缺少应用版本信息。")
            if json.loads(package_file.read_text())["version"] != version:
                raise UpdateError("源码版本与已确认版本不一致。")
            if not (destination / "docker/Dockerfile").is_file():
                raise UpdateError("源码包缺少 Docker 构建定义。")
            protocol_file = destination / "docker/update-protocol.json"
            if not protocol_file.is_file() or protocol_file.stat().st_size > 4096:
                raise UpdateError("目标源码不支持此更新协议。")
            protocol = json.loads(protocol_file.read_text())
            if protocol != {"application": "xingxu-workbench", "protocol": 1} or type(protocol.get("protocol")) is not int:
                raise UpdateError("目标源码更新协议不兼容。")
            return destination
    except (OSError, tarfile.TarError, ValueError, KeyError) as error:
        raise UpdateError("源码包校验或解压失败。") from error


class Docker:
    def call(self, args, *, payload=None, timeout=60):
        try:
            result = subprocess.run(["docker", *args], input=json.dumps(payload) if payload is not None else None,
                                    text=True, capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise UpdateError("宿主 Docker 调用未完成。") from error
        if result.returncode:
            # inspect/config stderr may contain installation paths or secrets.
            raise UpdateError("宿主 Docker 调用失败。")
        return result.stdout


class UpdateRunner:
    def __init__(self, project_dir, mode, container, env_file, work_dir, *, compose_file=None, docker=None, trust_file=None):
        self.project = Path(project_dir).resolve()
        self.mode = mode; self.container = container
        self.env_file = Path(env_file).resolve()
        self.work = private_dir(work_dir)
        self.docker = docker or Docker()
        self.verifier = TRUST.Verifier(trust_file or self.work / "trust.json", self.work)
        self._active_trust = None
        self._trust_failure_reason = None
        # Enrollment is a host-admin choice. A source archive never supplies
        # installation settings, volumes, ports, or the deployment entry point.
        self.custom_compose = compose_file is not None
        self.compose_file = Path(compose_file).resolve() if self.custom_compose else self.project / "docker" / ("docker-compose.multica.yml" if mode == "multica" else "docker-compose.yml")
        self.script = self.project / "docker/scripts" / ("deploy.sh" if mode == "multica" else "manage.sh")
        for path in (self.env_file, self.compose_file, self.script):
            if not path.is_file(): raise UpdateError("指定安装目录或配置文件不完整。")
        identity = self.work / "runner.json"
        if identity.exists():
            self.runner_id = str(uuid.UUID(json.loads(identity.read_text())["runner_id"]))
        else:
            self.runner_id = str(uuid.uuid4()); atomic_json(identity, {"runner_id": self.runner_id})
        self.journal_path = self.work / "active-job.json"
        self.compose_project = None

    def bridge(self, action, **fields):
        response = self.docker.call(["exec", "-i", self.container, "python", "-m", "app.services.system_update_bridge"],
                                   payload={"action": action, "runner_id": self.runner_id, **fields},
                                   timeout=900 if action == "prepare" else 30)
        try:
            value = json.loads(response)
            if not isinstance(value, dict) or value.get("ok") is False or value.get("error"):
                raise ValueError("bridge refused")
            return value
        except (ValueError, TypeError) as error:
            raise UpdateError("应用更新桥接返回无效结果。") from error

    def verify_managed(self):
        try:
            inspected = json.loads(self.docker.call(["inspect", self.container]))[0]
            labels = inspected["Config"].get("Labels") or {}
            project = labels.get("com.docker.compose.project", "")
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project) or labels.get("com.docker.compose.service") != "agv-pm":
                raise UpdateError("此容器不属于受支持的 Compose 安装。")
            config = json.loads(self.docker.call(["compose", "-p", project, "--env-file", str(self.env_file),
                                                  "-f", str(self.compose_file), "config", "--format", "json"]))
            service = config["services"]["agv-pm"]
            if self.custom_compose:
                enrolled_files = labels.get("com.docker.compose.project.config_files", "").split(",")
                if not enrolled_files[0] or Path(enrolled_files[0]).resolve() != self.compose_file:
                    raise UpdateError("当前容器不是由指定安装配置创建的。")
                if set(config["services"]) != {"agv-pm"}:
                    raise UpdateError("自定义安装配置只能管理单个 agv-pm 服务。")
                template = json.loads(self.docker.call(["compose", "-p", project, "--env-file", str(self.env_file),
                                                       "-f", str(self.compose_file), "config", "--no-interpolate", "--format", "json"]))["services"]["agv-pm"]
                if (template.get("image") != "${AGV_IMAGE}"
                        or template.get("environment", {}).get("APP_VERSION") != "${APP_VERSION}"
                        or template.get("environment", {}).get("GIT_SHA") != "${GIT_SHA}"):
                    raise UpdateError("安装配置必须通过 AGV_IMAGE、APP_VERSION、GIT_SHA 引用持久版本信息。")
            if service.get("container_name") != self.container:
                raise UpdateError("指定配置与当前应用容器不匹配。")
            expected = [v for v in service.get("volumes", []) if v.get("target") == "/app/data"]
            actual = [m for m in inspected.get("Mounts", []) if m.get("Destination") == "/app/data"]
            if len(expected) != 1 or len(actual) != 1 or not actual[0].get("RW") or expected[0].get("read_only"):
                raise UpdateError("不能确认当前应用的数据挂载。")
            e, a = expected[0], actual[0]
            if e["type"] == "bind":
                same = a["Type"] == "bind" and Path(e["source"]).resolve() == Path(a["Source"]).resolve()
            elif e["type"] == "volume":
                volume_name = config.get("volumes", {}).get(e["source"], {}).get("name")
                same = bool(volume_name) and a["Type"] == "volume" and a.get("Name") == volume_name
            else: same = False
            if not same: raise UpdateError("当前数据卷与指定 Compose 配置不匹配，拒绝更新。")
            # A web-writable host mount must not reach trust roots, receipts,
            # trusted scripts, or the enrolled Compose/environment settings.
            if (inspected.get("HostConfig") or {}).get("Privileged"):
                raise UpdateError("特权应用容器不能建立宿主更新信任边界。")
            management_sockets = {"docker.sock", "podman.sock", "containerd.sock"}
            for mounted in inspected.get("Mounts", []):
                if Path(mounted.get("Source", "")).name in management_sockets or Path(mounted.get("Destination", "")).name in management_sockets:
                    raise UpdateError("应用不能挂载宿主容器管理 socket，包括只读挂载。")
            self.verifier.forbidden = [Path(m["Source"]).resolve() for m in inspected.get("Mounts", []) if m.get("RW") and m.get("Source")]
            protected = [self.script.parent.resolve(), self.work.resolve(), self.env_file, self.compose_file]
            for mounted in self.verifier.forbidden:
                for path in protected:
                    if path == mounted or mounted in path.parents or (path in mounted.parents and path in {self.work.resolve(), self.script.parent.resolve()}):
                        raise UpdateError("网页可写挂载触及宿主更新信任或安装配置，拒绝接管。")
            self.verifier._boundary(self.verifier.policy_file)
            self.compose_project = project
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise UpdateError("无法确认受管容器身份。") from error

    def write_journal(self, value):
        atomic_json(self.journal_path, value)

    def report(self, job_id, status, reason=None):
        # Only this method publishes outcomes after the child has exited.
        # A lost bridge response can therefore retry the same terminal result.
        self.write_journal({"job_id": job_id, "status": status, "terminal": False, "outcome_ready": status in TERMINAL, "reason": reason})
        self.bridge("report", job_id=job_id, status=status, phase=status, message=MESSAGES[status], reason=reason)
        if status in TERMINAL:
            self.write_journal({"job_id": job_id, "status": status, "terminal": True})

    def heartbeat(self):
        return self.bridge("heartbeat", protocol=1, trust_protocol=TRUST.TRUST_PROTOCOL,
                           trust_configured=self.verifier.configured())

    def process_check(self):
        candidate = self.bridge("trust-request").get("candidate")
        if candidate is None:
            return
        identity = TRUST.candidate_identity(candidate)
        try:
            # Reject unapproved destinations before retrieving or using a token.
            self.verifier.entry(identity)
            credentials = self.bridge("trust-credentials", check_id=identity["check_id"])
            with self.verifier.verified(identity, credentials.get("token", "")) as (_, _, metadata):
                receipts = private_dir(self.work / "trust-checks")
                atomic_json(receipts / (identity["check_id"] + ".json"),
                            {"version": 1, "candidate": identity, "verified_at": time.time(), **metadata})
            self.bridge("trust-result", check_id=identity["check_id"], status="trusted", method=metadata["method"])
        except TRUST.TrustError as error:
            self.bridge("trust-result", check_id=identity["check_id"], status="rejected", reason=error.reason)

    def trusted_receipt(self, job):
        identity = TRUST.candidate_identity({**job, "commit": job.get("target_commit"), "version": job.get("target_version")})
        path = self.work / "trust-checks" / (identity["check_id"] + ".json")
        self.verifier._boundary(path)
        try:
            try:
                raw = TRUST.private_file(path)
            except TRUST.TrustError:
                raise TRUST.TrustError("receipt_invalid") from None
            receipt = json.loads(raw)
            if (receipt.get("version") != 1 or receipt.get("candidate") != identity
                    or not 0 <= time.time() - receipt.get("verified_at", 0) <= 30 * 60
                    or receipt.get("consumed_job_id") not in {None, job["id"]}):
                raise TRUST.TrustError("receipt_invalid")
            self.verifier.assert_policy(receipt["policy_digest"])
            receipt["consumed_job_id"] = job["id"]
            atomic_json(path, receipt)
            return identity, receipt
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise TRUST.TrustError("receipt_invalid") from None

    def assert_install_trust(self, source):
        authorization = self._active_trust
        if not authorization:
            raise TRUST.TrustError("receipt_invalid")
        self.verifier.assert_policy(authorization["policy_digest"])
        if TRUST.source_fingerprint(source) != authorization["source_fingerprint"]:
            raise TRUST.TrustError("content_changed")

    def run_deploy(self, job, source, job_dir):
        self.assert_install_trust(source)
        env = dict(os.environ)
        # Never inherit fault injection, unsafe checksum bypasses, or compose overrides.
        for key in list(env):
            if key.startswith(("FAULT_", "COMPOSE_")) or key in {"AGV_COMPOSE_FILE", "AGV_INSTALLED_COMPOSE_FILE", "SKIP_SHA_CHECK", "APP_VERSION", "AGV_IMAGE", "GIT_SHA", "AGV_BACKUP_STAMP", "AGV_ROLLBACK_REF"}:
                del env[key]
        event_read, event_write = os.pipe()
        env.update(AGV_BUILD_CONTEXT=str(source), APP_VERSION=job["target_version"], GIT_SHA=job["target_commit"],
                   AGV_IMAGE="agv-managed-update:" + job["id"], COMPOSE_PROJECT_NAME=self.compose_project,
                   AGV_CONTAINER_NAME=self.container, AGV_CONTAINER=self.container, AGV_ENV_FILE=str(self.env_file),
                   BACKUP_DIR=str(self.work / "backups"), AGV_UPDATE_MANAGED="1", AGV_UPDATE_EVENT_FD=str(event_write))
        if self.custom_compose:
            env["AGV_INSTALLED_COMPOSE_FILE"] = str(self.compose_file)
        log_path = job_dir / "deployment.log"
        log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        final = None; switched = False
        with os.fdopen(log_fd, "wb") as output, os.fdopen(event_read, "rb") as events:
            try:
                process = subprocess.Popen(["bash", str(self.script), "update"], cwd=self.project, env=env,
                                           stdin=subprocess.PIPE, stdout=output, stderr=output,
                                           pass_fds=(event_write,), start_new_session=True)
            finally:
                os.close(event_write)
            try:
                for raw in events:
                    # Only the installed helper writes this inherited pipe.
                    # Source-controlled build stdout cannot forge phase events.
                    line = raw.decode("ascii", errors="replace").strip()
                    if not line.startswith("AGV_UPDATE_PHASE="):
                        continue
                    phase = line.removeprefix("AGV_UPDATE_PHASE=")
                    if phase not in MESSAGES:
                        continue
                    final = phase
                    acknowledge = True
                    if phase in {"backing_up", "installing"}:
                        try:
                            self.assert_install_trust(source)
                        except TRUST.TrustError as error:
                            self._trust_failure_reason = error.reason
                            acknowledge = False
                    if phase in TERMINAL:
                        self.write_journal({"job_id": job["id"], "status": phase, "terminal": False})
                    elif acknowledge:
                        try:
                            self.report(job["id"], phase)
                        except UpdateError:
                            # Installing is already persisted before recreation.
                            # A broken new bridge must still allow trusted health
                            # checks and rollback; other phases fail closed.
                            acknowledge = phase == "verifying"
                        if phase == "installing" and acknowledge: switched = True
                    process.stdin.write(b"continue\n" if acknowledge else b"abort\n")
                    process.stdin.flush()
                code = process.wait()
            except BaseException:
                self.write_journal({"job_id": job["id"], "status": "needs_attention", "terminal": False})
                # EOF makes the helper's next barrier fail closed. Never kill a
                # restore halfway through; a restart must not blindly replay it.
                raise
            finally:
                process.stdin.close()
        if code == 0 and final == "succeeded": return "succeeded"
        if final in {"rolled_back", "needs_attention"}: return final
        return "needs_attention" if switched else "failed"

    def run_once(self):
        self._active_trust = None
        self._trust_failure_reason = None
        self.verify_managed()
        self.heartbeat()
        if self.journal_path.exists():
            prior = json.loads(self.journal_path.read_text())
            if not prior.get("terminal"):
                status = prior.get("status") if prior.get("outcome_ready") and prior.get("status") in TERMINAL else "needs_attention"
                self.report(prior["job_id"], status, prior.get("reason"))
                return
        self.process_check()
        job = self.bridge("claim").get("job")
        if job is None: return
        job_id = job.get("id", "")
        if not re.fullmatch(r"[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", job_id):
            raise UpdateError("更新任务编号无效。")
        self.write_journal({"job_id": job_id, "status": job.get("status"), "terminal": False})
        if job.get("status") != "downloading":
            self.report(job_id, "needs_attention")
            return
        try:
            if job.get("status") != "downloading" or not re.fullmatch(r"[a-f0-9]{40}", job.get("target_commit", "")):
                raise UpdateError("更新目标提交无效。")
            if not SEMVER.fullmatch(job.get("target_version", "")):
                raise UpdateError("更新目标版本无效。")
            job_dir = self.work / job_id
            if job_dir.exists(): raise UpdateError("此任务已有宿主记录，不可重复执行。")
            private_dir(job_dir)
            identity, receipt = self.trusted_receipt(job)
            # Git objects, signatures and the source/version binding are checked
            # again immediately before building. No app-supplied tar/hash wins.
            credentials = self.bridge("trust-credentials", job_id=job_id)
            local_archive = job_dir / "source.tar.gz"
            with self.verifier.verified(identity, credentials.get("token", "")) as (repo, env, metadata):
                if metadata["tree"] != receipt["tree"] or metadata["policy_digest"] != receipt["policy_digest"]:
                    raise TRUST.TrustError("target_changed")
                self.verifier.export(repo, env, identity["commit"], local_archive)
            source = extract_source(local_archive, job_dir / "source", job["target_version"])
            self._active_trust = {**metadata, "source_fingerprint": TRUST.source_fingerprint(source)}
            # Revalidate immediately before allowing any trusted deployment command.
            self.verify_managed()
            outcome = self.run_deploy(job, source, job_dir)
        except (UpdateError, TRUST.TrustError, OSError, ValueError, KeyError, TypeError) as error:
            if isinstance(error, TRUST.TrustError):
                self._trust_failure_reason = error.reason
            prior = json.loads(self.journal_path.read_text())
            outcome = "needs_attention" if prior.get("status") in {"backing_up", "installing", "verifying", "needs_attention"} else "failed"
        # Reconnection can lag Docker's health transition; report a fixed result
        # only, never stderr. Unpublished terminal records remain recoverable.
        deadline = time.monotonic() + 90
        while True:
            try:
                self.report(job_id, outcome, self._trust_failure_reason)
                break
            except UpdateError:
                if time.monotonic() >= deadline: raise
                time.sleep(3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("standard", "multica"))
    parser.add_argument("--container", required=True)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--compose-file", type=Path, help="trusted complete installation Compose file; never downloaded from the update source")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--trust-file", type=Path, help="host-owned trust policy; defaults to WORK_DIR/trust.json; never a downloaded file")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--once", action="store_true")
    action.add_argument("--probe", action="store_true", help="validate enrollment only; do not claim or install")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.container): parser.error("invalid container name")
    os.umask(0o077)
    base = private_dir(Path.home() / ".local/state/agv-update-runner")
    lock_key = hashlib.sha256((os.environ.get("DOCKER_HOST", "default") + ":" + args.container).encode()).hexdigest()
    lock_fd = os.open(base / (lock_key + ".lock"), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.exit(1, "已有更新器管理这个容器。\n")
    app = UpdateRunner(args.project_dir, args.mode, args.container, args.env_file, args.work_dir or base / lock_key,
                       compose_file=args.compose_file, trust_file=args.trust_file)
    stopping = threading.Event()
    heartbeat_stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    def heartbeat():
        # SIGTERM stops accepting jobs but lets an in-flight restore finish.
        # Keep ownership alive until that operation has actually completed.
        while not heartbeat_stopping.wait(15):
            try: app.heartbeat()
            except UpdateError: pass
    # Enrollment validation happens before advertising an available runner.
    app.verify_managed()
    if args.probe:
        print("受管安装身份与数据挂载验证通过。")
        os.close(lock_fd)
        return 0
    thread = threading.Thread(target=heartbeat, daemon=True); thread.start()
    try:
        while not stopping.is_set():
            try: app.run_once()
            except (UpdateError, TRUST.TrustError, OSError, ValueError):
                print("更新器暂时无法完成检查；任务不会自动重新安装。", flush=True)
                if args.once: return 1
            if args.once: break
            stopping.wait(5)
    finally:
        stopping.set(); heartbeat_stopping.set(); thread.join(timeout=1); os.close(lock_fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
