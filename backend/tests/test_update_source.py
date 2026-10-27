"""Gitea update transport, identity, and archive boundaries; no real network."""

import base64
import gzip
import hashlib
import io
import json
import socket
import tarfile
import traceback
from types import SimpleNamespace

import pytest

from app.services import update_source as updates

SHA = "a" * 40
TOKEN = "test-only-gitea-secret-token"
MARKER = {"protocol": 1, "application": "xingxu-workbench"}
PACKAGE = {"name": "agv-pm-frontend", "version": "2.4.0-rc.1+build.12"}


class Response:
    def __init__(self, body=b"", status=200, headers=None):
        self.status = status
        self.body = io.BytesIO(body)
        self.headers = headers or {}

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, count):
        return self.body.read(count)


def json_response(data):
    return Response(json.dumps(data).encode())


def file_response(data):
    encoded = base64.b64encode(json.dumps(data).encode()).decode()
    return json_response({"type": "file", "encoding": "base64", "content": encoded[:20] + "\n" + encoded[20:]})


@pytest.fixture()
def transport(monkeypatch):
    replies, calls, connections = [], [], []
    monkeypatch.setattr(updates, "_resolve_addresses", lambda *args: [(socket.AF_INET, socket.SOCK_STREAM, 6, ("192.168.1.20", 443))])

    class Connection:
        def __init__(self, host, port, addresses, tls):
            self.host, self.port, self.addresses, self.tls = host, port, addresses, tls
            self.sock = SimpleNamespace(settimeout=lambda value: None)
            self.closed = False
            connections.append(self)

        def request(self, method, path, headers):
            calls.append((method, path, headers))

        def getresponse(self):
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        def close(self):
            self.closed = True

    monkeypatch.setattr(updates, "_PinnedConnection", Connection)
    return SimpleNamespace(replies=replies, calls=calls, connections=connections)


def source():
    return updates.normalize_source("https://git.example.test/gitea/team/workbench.git", "feature/safe")


def archive_bytes(extra=(), package=PACKAGE, marker=MARKER):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        root = tarfile.TarInfo("workbench-main")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        entries = []
        if package is not None:
            entries.append(("workbench-main/frontend/package.json", json.dumps(package).encode()))
        if marker is not None:
            entries.append(("workbench-main/docker/update-protocol.json", json.dumps(marker).encode()))
        entries.extend(extra)
        for name, data in entries:
            member = name if isinstance(name, tarfile.TarInfo) else tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return output.getvalue()


def test_normalizes_subpath_git_suffix_default_ports_and_ref():
    result = updates.normalize_source("https://Git.Example.test:443/tools/gitea/team/repo.git/", "release/2.4")
    assert result == {
        "repository_url": "https://git.example.test/tools/gitea/team/repo",
        "base_url": "https://git.example.test/tools/gitea",
        "api_base": "https://git.example.test/tools/gitea/api/v1/repos/team/repo",
        "owner": "team", "repo": "repo", "ref": "release/2.4", "allow_http": False,
    }


def test_private_lan_ipv4_and_ipv6_are_supported_only_with_explicit_http():
    with pytest.raises(updates.UpdateSourceError, match="显式允许"):
        updates.normalize_source("http://192.168.1.20:3000/team/repo")
    assert updates.normalize_source("http://192.168.1.20:3000/team/repo", allow_http=True)["base_url"] == "http://192.168.1.20:3000"
    assert updates.normalize_source("https://[fd12:3456::20]/team/repo")["repository_url"] == "https://[fd12:3456::20]/team/repo"


def test_unicode_and_percent_encoded_repository_names_have_one_canonical_url():
    result = updates.normalize_source("https://git.example.test/gitea/team/行序.git")
    assert result["repository_url"] == "https://git.example.test/gitea/team/%E8%A1%8C%E5%BA%8F"
    assert updates.normalize_source(result["repository_url"]) == result


@pytest.mark.parametrize("url", [
    "git@git.example.test:team/repo", "file:///team/repo", "ftp://git.example.test/team/repo",
    "https://token@git.example.test/team/repo", "https://user:pass@git.example.test/team/repo",
    "https://git.example.test/team/repo?token=hidden", "https://git.example.test/team/repo?",
    "https://git.example.test/team/repo#", "https://git.example.test/team/repo\r\nX-Bad:yes",
    "https://git.example.test/team", "https://git.example.test/", "https://git.example.test/team/.git",
    "https://git.example.test/team/%2e%2e/repo", "https://git.example.test/team//repo",
    "https://git.example.test/team%2Frepo/another", "https://git.example.test/team/%252e%252e",
    "https://git.example.test/a/../team/repo", "https://git.example.test/team\\repo",
    "https://git.example.test:99999/team/repo",
])
def test_rejects_ambiguous_or_credential_bearing_repository_urls(url):
    with pytest.raises(updates.UpdateSourceError):
        updates.normalize_source(url)


@pytest.mark.parametrize("host", [
    "localhost", "alias.localhost", "127.0.0.1", "[::1]", "[::ffff:127.0.0.1]",
    "169.254.169.254", "0.0.0.0", "224.0.0.1", "[ff02::1]", "[::]",
    "100.100.100.200", "[fd00:ec2::254]", "metadata.google.internal",
    "[2002:7f00:1::]", "[2002:a9fe:a9fe::]",
])
def test_rejects_loopback_metadata_and_special_literal_addresses(host):
    with pytest.raises(updates.UpdateSourceError):
        updates.normalize_source(f"https://{host}/team/repo")


@pytest.mark.parametrize("ref", ["", "main\r\n", "../main", "x//y", "x?ref=y", "x.lock", "/main"])
def test_rejects_invalid_refs(ref):
    with pytest.raises(updates.UpdateSourceError):
        updates.normalize_source("https://git.example.test/team/repo", ref)


def test_dns_rejects_a_mixed_safe_and_link_local_answer(monkeypatch):
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443)),
    ]
    monkeypatch.setattr(updates, "socket", SimpleNamespace(
        getaddrinfo=lambda *args, **kwargs: answers, AF_INET=socket.AF_INET,
        AF_INET6=socket.AF_INET6, SOCK_STREAM=socket.SOCK_STREAM, IPPROTO_TCP=socket.IPPROTO_TCP,
    ))
    with pytest.raises(updates.UpdateSourceError):
        updates._resolve_addresses("git.example.test", 443)


def test_connection_uses_exact_validated_ip_and_original_tls_hostname(monkeypatch):
    events = []

    class RawSocket:
        def settimeout(self, value):
            events.append(("timeout", value))

        def connect(self, address):
            events.append(("connect", address))

        def close(self):
            events.append(("close",))

    raw = RawSocket()
    # Replacing this module's socket object cannot affect other HTTP clients.
    # No getaddrinfo is available here: connect must use the resolved address.
    monkeypatch.setattr(updates, "socket", SimpleNamespace(socket=lambda *args: raw))

    def wrap(sock, *, server_hostname):
        events.append(("tls", server_hostname))
        assert sock is raw
        return raw

    monkeypatch.setattr(updates.ssl, "create_default_context", lambda: SimpleNamespace(wrap_socket=wrap))
    connection = updates._PinnedConnection("git.example.test", 443, [(socket.AF_INET, socket.SOCK_STREAM, 6, ("192.168.1.20", 443))], True)
    connection.connect()
    assert ("connect", ("192.168.1.20", 443)) in events
    assert ("tls", "git.example.test") in events
    assert connection.sock is raw


def test_tls_verification_failure_closes_socket_without_exposing_exception(monkeypatch):
    closed = []
    raw = SimpleNamespace(settimeout=lambda value: None, connect=lambda address: None, close=lambda: closed.append(True))
    monkeypatch.setattr(updates, "socket", SimpleNamespace(socket=lambda *args: raw))

    def reject(*args, **kwargs):
        raise updates.ssl.SSLCertVerificationError("certificate details " + TOKEN)

    monkeypatch.setattr(updates.ssl, "create_default_context", lambda: SimpleNamespace(wrap_socket=reject))
    connection = updates._PinnedConnection("git.example.test", 443, [(socket.AF_INET, socket.SOCK_STREAM, 6, ("192.168.1.20", 443))], True)
    with pytest.raises(updates.UpdateSourceError) as exc:
        connection.connect()
    assert closed == [True]
    assert TOKEN not in "".join(traceback.format_exception(exc.value))


def test_inspection_pins_both_metadata_files_to_one_resolved_commit(transport):
    transport.replies.extend([json_response({"sha": SHA.upper()}), file_response(PACKAGE), file_response(MARKER)])
    assert updates.inspect_source(source(), TOKEN) == {"commit": SHA, "version": PACKAGE["version"]}
    paths = [call[1] for call in transport.calls]
    assert paths == [
        "/gitea/api/v1/repos/team/workbench/git/commits/feature%2Fsafe",
        f"/gitea/api/v1/repos/team/workbench/contents/frontend/package.json?ref={SHA}",
        f"/gitea/api/v1/repos/team/workbench/contents/docker/update-protocol.json?ref={SHA}",
    ]
    assert all(call[2]["Authorization"] == "token " + TOKEN for call in transport.calls)
    assert all(connection.closed for connection in transport.connections)


@pytest.mark.parametrize("version", ["2.4", "v2.4.0", "02.4.0", "2.4.0-01", "2.4.0-", "2.4.0+", "2.4.0\n"])
def test_inspection_requires_strict_semver(transport, version):
    transport.replies.extend([json_response({"sha": SHA}), file_response({**PACKAGE, "version": version}), file_response(MARKER)])
    with pytest.raises(updates.UpdateSourceError, match="未支持网页更新"):
        updates.inspect_source(source(), TOKEN)


@pytest.mark.parametrize("version", ["0.0.0", "2.4.0", "2.4.0-0", "2.4.0-alpha-1", "2.4.0-1a.2+001.build"])
def test_valid_stable_prerelease_and_build_versions_are_supported(transport, version):
    transport.replies.extend([json_response({"sha": SHA}), file_response({**PACKAGE, "version": version}), file_response(MARKER)])
    assert updates.inspect_source(source())["version"] == version


@pytest.mark.parametrize("package,marker", [
    ({**PACKAGE, "name": "another-application"}, MARKER),
    (PACKAGE, {"protocol": True, "application": "xingxu-workbench"}),
    (PACKAGE, {"protocol": 2, "application": "xingxu-workbench"}),
    (PACKAGE, {"protocol": 1, "application": "another-application"}),
])
def test_inspection_requires_workbench_name_and_update_protocol(transport, package, marker):
    transport.replies.extend([json_response({"sha": SHA}), file_response(package), file_response(marker)])
    with pytest.raises(updates.UpdateSourceError, match="未支持网页更新"):
        updates.inspect_source(source(), TOKEN)


def test_missing_update_marker_has_explicit_unsupported_error(transport):
    transport.replies.extend([json_response({"sha": SHA}), file_response(PACKAGE), Response(status=404)])
    with pytest.raises(updates.UpdateSourceError, match="未支持网页更新"):
        updates.inspect_source(source(), TOKEN)


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirects_never_forward_the_token(transport, status):
    transport.replies.append(Response(status=status, headers={"Location": "https://other.example.test/steal"}))
    with pytest.raises(updates.UpdateSourceError, match="不允许重定向"):
        updates.inspect_source(source(), TOKEN)
    assert len(transport.calls) == 1
    assert transport.connections[0].host == "git.example.test"


@pytest.mark.parametrize("reply", [
    OSError("transport leaked " + TOKEN),
    Response(b"upstream leaked " + TOKEN.encode(), status=403),
    Response(b"upstream leaked " + TOKEN.encode(), status=500),
])
def test_transport_errors_and_remote_bodies_cannot_leak_secrets(transport, reply):
    transport.replies.append(reply)
    with pytest.raises(updates.UpdateSourceError) as exc:
        updates.inspect_source(source(), TOKEN)
    rendered = "".join(traceback.format_exception(exc.value))
    assert TOKEN not in str(exc.value)
    assert TOKEN not in rendered
    assert "https://" not in str(exc.value)


def test_token_header_injection_is_rejected_before_any_request(transport):
    with pytest.raises(updates.UpdateSourceError) as exc:
        updates.inspect_source(source(), TOKEN + "\r\nX-Steal: yes")
    assert TOKEN not in str(exc.value)
    assert not transport.calls


@pytest.mark.parametrize("headers", [{}, {"Content-Length": "1000"}])
def test_json_limit_applies_with_and_without_declared_length(transport, monkeypatch, headers):
    monkeypatch.setattr(updates, "MAX_JSON_BYTES", 32)
    transport.replies.append(Response(b"x" * 33, headers=headers))
    with pytest.raises(updates.UpdateSourceError, match="超过大小限制"):
        updates.inspect_source(source(), TOKEN)


def test_request_timeout_is_bounded_without_waiting(transport, monkeypatch):
    times = iter([0, updates.REQUEST_TIMEOUT + 1])
    monkeypatch.setattr(updates.time, "monotonic", lambda: next(times))
    transport.replies.append(json_response({"sha": SHA}))
    with pytest.raises(updates.UpdateSourceError, match="无法读取"):
        updates.inspect_source(source(), TOKEN)


@pytest.mark.parametrize("headers,body", [
    ({"Content-Length": "100"}, b"{}"),
    ({"Content-Length": "-1"}, b"{}"),
    ({"Content-Encoding": "gzip"}, b"{}"),
])
def test_malformed_or_incomplete_http_responses_are_rejected(transport, headers, body):
    transport.replies.append(Response(body, headers=headers))
    with pytest.raises(updates.UpdateSourceError):
        updates.inspect_source(source(), TOKEN)


def test_archive_download_is_pinned_validated_and_atomically_published(transport, tmp_path):
    body = archive_bytes(extra=[("workbench-main/backend/app/main.py", b"# application")])
    transport.replies.append(Response(body, headers={"Content-Length": str(len(body))}))
    target = tmp_path / "source.tar.gz"
    result = updates.download_source(source(), TOKEN, SHA.upper(), target)
    assert result == {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
    assert target.read_bytes() == body
    assert transport.calls[0][1].endswith(f"/archive/{SHA}.tar.gz")
    assert not list(tmp_path.glob(".update-source-*"))


def test_oversized_archive_transfer_keeps_existing_target(transport, tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "MAX_ARCHIVE_BYTES", 20)
    transport.replies.append(Response(b"x" * 21))
    target = tmp_path / "source.tar.gz"
    target.write_bytes(b"original")
    with pytest.raises(updates.UpdateSourceError, match="超过大小限制"):
        updates.download_source(source(), TOKEN, SHA, target)
    assert target.read_bytes() == b"original"
    assert not list(tmp_path.glob(".update-source-*"))


def test_caller_cannot_override_the_derived_api_origin(transport):
    candidate = {**source(), "api_base": "https://127.0.0.1/evil"}
    transport.replies.extend([json_response({"sha": SHA}), file_response(PACKAGE), file_response(MARKER)])
    updates.inspect_source(candidate)
    assert all(connection.host == "git.example.test" for connection in transport.connections)


@pytest.mark.parametrize("commit", ["main", "a" * 39, "a" * 41, "../" + SHA, SHA + "?steal=yes"])
def test_download_requires_full_pinned_sha_before_network(transport, tmp_path, commit):
    with pytest.raises(updates.UpdateSourceError, match="完整提交"):
        updates.download_source(source(), TOKEN, commit, tmp_path / "source.tar.gz")
    assert not transport.calls


@pytest.mark.parametrize("name", [
    "../escape", "/absolute", "workbench-main/../../escape", "workbench-main/./alias",
    "workbench-main//alias", "workbench-main/back\\slash", "C:/windows", "other-root/file",
    "workbench-main/.git/config", "workbench-main/frontend/package.json",
])
def test_unsafe_archive_paths_cannot_replace_an_existing_target(transport, tmp_path, name):
    transport.replies.append(Response(archive_bytes(extra=[(name, b"unsafe")])))
    target = tmp_path / "source.tar.gz"
    target.write_bytes(b"original")
    with pytest.raises(updates.UpdateSourceError):
        updates.download_source(source(), TOKEN, SHA, target)
    assert target.read_bytes() == b"original"
    assert not list(tmp_path.glob(".update-source-*"))
    assert not (tmp_path.parent / "escape").exists()


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE])
def test_archive_links_and_special_files_are_rejected(tmp_path, kind):
    member = tarfile.TarInfo("workbench-main/link")
    member.type, member.linkname = kind, "/etc/passwd"
    path = tmp_path / "source.tar.gz"
    path.write_bytes(archive_bytes(extra=[(member, b"")]))
    with pytest.raises(updates.UpdateSourceError):
        updates.validate_archive(path)


@pytest.mark.parametrize("package,marker", [(None, MARKER), (PACKAGE, None), ({**PACKAGE, "name": "other"}, MARKER), (PACKAGE, {**MARKER, "protocol": 0})])
def test_archives_must_contain_supported_workbench_metadata(tmp_path, package, marker):
    path = tmp_path / "source.tar.gz"
    path.write_bytes(archive_bytes(package=package, marker=marker))
    with pytest.raises(updates.UpdateSourceError, match="未支持网页更新"):
        updates.validate_archive(path)


@pytest.mark.parametrize("limit,value", [("MAX_ARCHIVE_BYTES", 20), ("MAX_EXPANDED_BYTES", 512), ("MAX_ARCHIVE_FILES", 2)])
def test_archive_compressed_expanded_and_member_limits(tmp_path, monkeypatch, limit, value):
    path = tmp_path / "source.tar.gz"
    path.write_bytes(archive_bytes(extra=[("workbench-main/large.txt", b"x" * 1024)]))
    monkeypatch.setattr(updates, limit, value)
    with pytest.raises(updates.UpdateSourceError, match="超过大小限制"):
        updates.validate_archive(path)


def test_truncated_gzip_is_rejected_even_after_required_files_were_read(tmp_path):
    path = tmp_path / "source.tar.gz"
    path.write_bytes(archive_bytes()[:-8])
    with pytest.raises(updates.UpdateSourceError):
        updates.validate_archive(path)


@pytest.mark.parametrize("concatenate", [False, True])
def test_hidden_nonzero_tail_and_concatenated_gzip_archives_are_rejected(tmp_path, concatenate):
    if concatenate:
        body = archive_bytes() + archive_bytes()
    else:
        raw = bytearray(gzip.decompress(archive_bytes()))
        raw[-1000:-990] = b"unexpected"
        body = gzip.compress(bytes(raw))
    path = tmp_path / "source.tar.gz"
    path.write_bytes(body)
    with pytest.raises(updates.UpdateSourceError):
        updates.validate_archive(path)


def test_file_parent_conflicts_are_rejected_in_either_order(tmp_path):
    for entries in [
        [("workbench-main/conflict", b"file"), ("workbench-main/conflict/child", b"nested")],
        [("workbench-main/conflict/child", b"nested"), ("workbench-main/conflict", b"file")],
    ]:
        path = tmp_path / "source.tar.gz"
        path.write_bytes(archive_bytes(extra=entries))
        with pytest.raises(updates.UpdateSourceError):
            updates.validate_archive(path)
