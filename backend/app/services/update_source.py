"""Read a Gitea update source without forwarding credentials or trusting DNS twice.

Only immutable commit archives with the workbench update marker are accepted.
This module never extracts archives, executes code, or changes running services.
"""

import base64
import binascii
import gzip
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import tarfile
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit, urlunsplit

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_EXPANDED_BYTES = 500 * 1024 * 1024
MAX_ARCHIVE_FILES = 20_000
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
REQUEST_TIMEOUT = 180
CHUNK_BYTES = 64 * 1024

_BAD_SOURCE = "Gitea 仓库地址无效，请填写完整的 HTTP(S) 仓库地址"
_BAD_ADDRESS = "此 Gitea 地址不可用于网页更新"
_NETWORK_ERROR = "无法读取 Gitea 更新来源，请检查地址、访问权限和网络"
_BAD_DATA = "Gitea 更新来源返回的数据无效"
_TOO_LARGE = "更新来源内容超过大小限制"
_UNSUPPORTED = "此仓库版本未支持网页更新"
_BAD_ARCHIVE = "更新源码包校验失败，包含不安全路径、文件类型或无效内容"
_SHA = re.compile(r"[0-9a-fA-F]{40}\Z")
_SEMVER = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-(?:(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)
_METADATA_IPS = {
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("fd00:ec2::254"),
}
_METADATA_HOSTS = {"metadata", "metadata.google.internal", "instance-data.ec2.internal"}


class UpdateSourceError(ValueError):
    """A fixed, public-safe failure; remote bodies and exception text stay private."""


class _NotFound(UpdateSourceError):
    pass


def _valid_ref(ref: str) -> str:
    if not isinstance(ref, str) or re.search(r"[\x00-\x1f\x7f]", ref):
        raise UpdateSourceError("分支或标签无效")
    ref = ref.strip()
    if (not ref or len(ref) > 256 or re.search(r"[\x00-\x20\x7f~^:?*\[\\]", ref)
            or ".." in ref or "@{" in ref or "//" in ref
            or ref.startswith(("/", "-")) or ref.endswith(("/", "."))
            or any(part.startswith(".") or part.endswith(".lock") for part in ref.split("/"))):
        raise UpdateSourceError("分支或标签无效")
    return ref


def _check_address(value: str) -> None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise UpdateSourceError(_BAD_ADDRESS) from None
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        _check_address(str(mapped))
        return
    six_to_four = getattr(address, "sixtofour", None)
    if six_to_four is not None:
        _check_address(str(six_to_four))
    teredo = getattr(address, "teredo", None)
    if teredo is not None:
        for endpoint in teredo:
            _check_address(str(endpoint))
    if (address.is_loopback or address.is_link_local or address.is_multicast
            or address.is_unspecified or address.is_reserved or address in _METADATA_IPS):
        raise UpdateSourceError(_BAD_ADDRESS)


def normalize_source(repository_url: str, ref: str = "main", allow_http: bool = False) -> dict:
    """Normalize a repository URL, preserving a Gitea installation's subpath.

    No network is used here. DNS results are checked immediately before each
    connection, and the connection uses those exact numeric socket addresses.
    """
    if (not isinstance(repository_url, str) or type(allow_http) is not bool
            or re.search(r"[\x00-\x1f\x7f\\]", repository_url)):
        raise UpdateSourceError(_BAD_SOURCE)
    text = repository_url.strip()
    if not text or len(text) > 2048 or any(mark in text for mark in ("?", "#")) or " " in text:
        raise UpdateSourceError(_BAD_SOURCE)
    try:
        parsed = urlsplit(text)
        host, port = parsed.hostname, parsed.port
        if parsed.scheme not in ("https", "http") or not host or parsed.username is not None or parsed.password is not None:
            raise ValueError
        if "%" in host or (port is not None and not 1 <= port <= 65535):
            raise ValueError
        host = host.rstrip(".").encode("idna").decode("ascii").lower()
        try:
            numeric = ipaddress.ip_address(host)
        except ValueError:
            if (len(host) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                                       for label in host.split("."))):
                raise ValueError
        else:
            _check_address(str(numeric))
            host = str(numeric)
        if host == "localhost" or host.endswith(".localhost") or host in _METADATA_HOSTS:
            raise UpdateSourceError(_BAD_ADDRESS)
        # Reject encoded separators, dot aliases, and URL routing ambiguity.
        path = parsed.path.rstrip("/")
        if not path.startswith("/") or "//" in path:
            raise ValueError
        parts = [unquote(part, errors="strict") for part in path[1:].split("/")]
        if len(parts) < 2 or any(not re.fullmatch(r"[\w.-]+", part) or part in (".", "..") for part in parts):
            raise ValueError
        if parts[-1].endswith(".git"):
            parts[-1] = parts[-1][:-4]
        if not parts[-1] or parts[-1] in (".", ".."):
            raise ValueError
    except UpdateSourceError:
        raise
    except (ValueError, UnicodeError):
        raise UpdateSourceError(_BAD_SOURCE) from None
    if parsed.scheme == "http" and not allow_http:
        raise UpdateSourceError("HTTP 更新来源需显式允许，建议使用 HTTPS")
    normalized_ref = _valid_ref(ref)
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and port != (443 if parsed.scheme == "https" else 80):
        netloc += f":{port}"
    origin = urlunsplit((parsed.scheme, netloc, "", "", ""))
    escaped = [quote(part, safe="") for part in parts]
    prefix = "/" + "/".join(escaped[:-2]) if len(parts) > 2 else ""
    owner, repo = parts[-2:]
    return {
        "repository_url": origin + "/" + "/".join(escaped),
        "base_url": origin + prefix,
        "api_base": origin + prefix + f"/api/v1/repos/{quote(owner, safe='')}/{quote(repo, safe='')}",
        "owner": owner, "repo": repo, "ref": normalized_ref, "allow_http": allow_http,
    }


def _normalized(source: dict) -> dict:
    try:
        return normalize_source(source["repository_url"], source.get("ref", "main"), source.get("allow_http", False))
    except (KeyError, TypeError, AttributeError):
        raise UpdateSourceError(_BAD_SOURCE) from None


def _resolve_addresses(host: str, port: int) -> list:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except OSError:
        raise UpdateSourceError(_NETWORK_ERROR) from None
    addresses = []
    for family, kind, protocol, _, address in infos:
        if family not in (socket.AF_INET, socket.AF_INET6):
            raise UpdateSourceError(_BAD_ADDRESS)
        _check_address(address[0])
        pinned = (address[0], port, 0, 0) if family == socket.AF_INET6 else (address[0], port)
        item = (family, kind, protocol, pinned)
        if item not in addresses:
            addresses.append(item)
    if not addresses or len(addresses) > 16:
        raise UpdateSourceError(_BAD_ADDRESS)
    return addresses


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host, port, addresses, tls):
        super().__init__(host, port, timeout=CONNECT_TIMEOUT)
        self.addresses = addresses
        self.tls = tls

    def connect(self):
        for family, kind, protocol, address in self.addresses:
            raw = socket.socket(family, kind, protocol)
            try:
                raw.settimeout(CONNECT_TIMEOUT)
                raw.connect(address)
                self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host) if self.tls else raw
                self.sock.settimeout(READ_TIMEOUT)
                return
            except (OSError, ValueError):
                raw.close()
        raise UpdateSourceError(_NETWORK_ERROR)


@contextmanager
def _response(source: dict, token: str, suffix: str, limit: int):
    if not isinstance(token, str) or len(token) > 4096 or any(not 33 <= ord(char) <= 126 for char in token):
        raise UpdateSourceError("更新访问令牌格式无效")
    parsed = urlsplit(source["api_base"])
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = _resolve_addresses(parsed.hostname, port)
    connection = _PinnedConnection(parsed.hostname, port, addresses, parsed.scheme == "https")
    try:
        headers = {"Accept": "application/json", "Accept-Encoding": "identity", "User-Agent": "xingxu-workbench-updater/1"}
        if token:
            headers["Authorization"] = "token " + token
        connection.request("GET", parsed.path + suffix, headers=headers)
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise UpdateSourceError("Gitea 更新来源不允许重定向，请填写最终仓库地址")
        if response.status == 404:
            raise _NotFound(_NETWORK_ERROR)
        if response.status != 200:
            raise UpdateSourceError(_NETWORK_ERROR)
        encoding = response.getheader("Content-Encoding", "identity")
        if encoding.lower() not in ("", "identity"):
            raise UpdateSourceError(_BAD_DATA)
        length = response.getheader("Content-Length")
        if length is not None:
            if not re.fullmatch(r"[0-9]+", length):
                raise UpdateSourceError(_BAD_DATA)
            if int(length) > limit:
                raise UpdateSourceError(_TOO_LARGE)
        yield response, connection
    except UpdateSourceError:
        raise
    except (OSError, ValueError, http.client.HTTPException):
        raise UpdateSourceError(_NETWORK_ERROR) from None
    finally:
        connection.close()


def _copy_response(response, connection, target, limit: int) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    deadline = time.monotonic() + REQUEST_TIMEOUT
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise UpdateSourceError(_NETWORK_ERROR)
        if connection.sock is not None:
            connection.sock.settimeout(min(READ_TIMEOUT, remaining))
        chunk = response.read(min(CHUNK_BYTES, limit - size + 1))
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise UpdateSourceError(_TOO_LARGE)
        digest.update(chunk)
        target.write(chunk)
    length = response.getheader("Content-Length")
    if length is not None and size != int(length):
        raise UpdateSourceError(_NETWORK_ERROR)
    return digest.hexdigest(), size


def _get_json(source: dict, token: str, suffix: str) -> dict:
    from io import BytesIO
    try:
        with _response(source, token, suffix, MAX_JSON_BYTES) as (response, connection):
            output = BytesIO()
            _copy_response(response, connection, output, MAX_JSON_BYTES)
        result = json.loads(output.getvalue().decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError
        return result
    except UpdateSourceError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise UpdateSourceError(_BAD_DATA) from None


def _get_file(source: dict, token: str, path: str, commit: str) -> dict:
    try:
        result = _get_json(source, token, f"/contents/{path}?ref={commit}")
        content = result.get("content")
        if result.get("type") != "file" or result.get("encoding") != "base64" or not isinstance(content, str):
            raise ValueError
        decoded = base64.b64decode(re.sub(r"[\r\n\t ]", "", content), validate=True)
        if len(decoded) > MAX_JSON_BYTES:
            raise UpdateSourceError(_TOO_LARGE)
        data = json.loads(decoded.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError
        return data
    except _NotFound:
        raise UpdateSourceError(_UNSUPPORTED) from None
    except UpdateSourceError:
        raise
    except (ValueError, UnicodeError, binascii.Error, RecursionError):
        raise UpdateSourceError(_UNSUPPORTED) from None


def _package_version(package: dict) -> str:
    version = package.get("version")
    if (package.get("name") != "agv-pm-frontend" or not isinstance(version, str)
            or len(version) > 128 or not _SEMVER.fullmatch(version)):
        raise UpdateSourceError(_UNSUPPORTED)
    return version


def _check_marker(marker: dict) -> None:
    if type(marker.get("protocol")) is not int or marker["protocol"] != 1 or marker.get("application") != "xingxu-workbench":
        raise UpdateSourceError(_UNSUPPORTED)


def inspect_source(source: dict, token: str = "") -> dict:
    source = _normalized(source)
    data = _get_json(source, token, "/git/commits/" + quote(source["ref"], safe=""))
    commit = data.get("sha")
    if not isinstance(commit, str) or not _SHA.fullmatch(commit):
        raise UpdateSourceError(_BAD_DATA)
    commit = commit.lower()
    package = _get_file(source, token, "frontend/package.json", commit)
    marker = _get_file(source, token, "docker/update-protocol.json", commit)
    _check_marker(marker)
    return {"commit": commit, "version": _package_version(package)}


class _ExpandedReader:
    def __init__(self, source):
        self.source = source
        self.size = 0

    def read(self, size):
        data = self.source.read(min(size, MAX_EXPANDED_BYTES - self.size + 1))
        self.size += len(data)
        if self.size > MAX_EXPANDED_BYTES:
            raise UpdateSourceError(_TOO_LARGE)
        return data


def validate_archive(path: Path) -> None:
    """Validate the entire gzip stream, paths, member sizes, and update marker.

    Symlinks, hardlinks, special files, duplicate/aliased paths, multiple roots,
    malformed/truncated data, and missing workbench metadata are rejected.
    """
    try:
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise UpdateSourceError(_TOO_LARGE)
        required = {"frontend/package.json": None, "docker/update-protocol.json": None}
        root, names, parents, expanded, count = None, {}, set(), 0, 0
        with gzip.open(path, "rb") as compressed:
            reader = _ExpandedReader(compressed)
            # A single tar block prevents the stream reader from consuming
            # unexamined bytes after the end marker into a private buffer.
            with tarfile.open(fileobj=reader, mode="r|", bufsize=tarfile.BLOCKSIZE) as archive:
                for member in archive:
                    count += 1
                    if count > MAX_ARCHIVE_FILES:
                        raise UpdateSourceError(_TOO_LARGE)
                    name = member.name
                    item = PurePosixPath(name)
                    canonical = item.as_posix()
                    if (len(name) > 4096 or len(item.parts) > 128 or not item.parts or item.is_absolute()
                            or ".." in item.parts or any(re.search(r"[\x00-\x1f\x7f\\:]", part) for part in item.parts)
                            or not (name == canonical or member.isdir() and name == canonical + "/")
                            or canonical in names or not (member.isfile() or member.isdir()) or member.issparse()
                            or member.mode & 0o6000 or member.size < 0 or ".git" in item.parts):
                        raise UpdateSourceError(_BAD_ARCHIVE)
                    if root is None:
                        root = item.parts[0]
                    if item.parts[0] != root or (len(item.parts) == 1 and not member.isdir()):
                        raise UpdateSourceError(_BAD_ARCHIVE)
                    for parent in item.parents:
                        if parent.as_posix() in names and names[parent.as_posix()] == "file":
                            raise UpdateSourceError(_BAD_ARCHIVE)
                        parents.add(parent.as_posix())
                    if member.isfile() and canonical in parents:
                        raise UpdateSourceError(_BAD_ARCHIVE)
                    names[canonical] = "file" if member.isfile() else "dir"
                    expanded += member.size
                    if expanded > MAX_EXPANDED_BYTES:
                        raise UpdateSourceError(_TOO_LARGE)
                    relative = "/".join(item.parts[1:])
                    if relative in required:
                        if not member.isfile() or member.size > MAX_JSON_BYTES:
                            raise UpdateSourceError(_BAD_ARCHIVE)
                        content = archive.extractfile(member)
                        required[relative] = json.loads(content.read(MAX_JSON_BYTES + 1).decode("utf-8"))
                    elif member.isfile():
                        content = archive.extractfile(member)
                        while content.read(CHUNK_BYTES):
                            pass
            # tarfile may stop at the first zero block. Consume remaining gzip
            # data to verify CRC and reject concatenated/hidden tar payloads.
            while True:
                tail = reader.read(CHUNK_BYTES)
                if not tail:
                    break
                if tail.strip(b"\0"):
                    raise UpdateSourceError(_BAD_ARCHIVE)
        if not all(isinstance(value, dict) for value in required.values()):
            raise UpdateSourceError(_UNSUPPORTED)
        _package_version(required["frontend/package.json"])
        _check_marker(required["docker/update-protocol.json"])
    except UpdateSourceError:
        raise
    except (OSError, EOFError, ValueError, UnicodeError, tarfile.TarError, RecursionError):
        raise UpdateSourceError(_BAD_ARCHIVE) from None


def download_source(source: dict, token: str, commit: str, target: Path) -> dict:
    source = _normalized(source)
    if not isinstance(commit, str) or not _SHA.fullmatch(commit):
        raise UpdateSourceError("更新提交标识无效，必须使用已检查的完整提交")
    pending = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".update-source-", suffix=".tar.gz", dir=target.parent, delete=False) as output:
            pending = Path(output.name)
            with _response(source, token, "/archive/" + commit.lower() + ".tar.gz", MAX_ARCHIVE_BYTES) as (response, connection):
                digest, size = _copy_response(response, connection, output, MAX_ARCHIVE_BYTES)
            output.flush()
            os.fsync(output.fileno())
        validate_archive(pending)
        pending.replace(target)
        return {"sha256": digest, "bytes": size}
    except UpdateSourceError:
        raise
    except (OSError, ValueError):
        raise UpdateSourceError("更新源码包无法保存，请检查存储空间和目录权限") from None
    finally:
        if pending is not None:
            try:
                pending.unlink(missing_ok=True)
            except OSError:
                pass
