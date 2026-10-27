"""Host-owned update trust and Git object verification; never loaded from a package.

The web process supplies candidates, never trust roots. Each authorization binds
one canonical repository to a full commit or a locally verified annotated tag.
Build archives are generated locally from verified Git objects, not a remote
archive bearing an unproven commit name. Python standard library only.
"""
from contextlib import contextmanager
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import signal
import time
import stat
import subprocess
import tempfile
from urllib.parse import quote, unquote, urlsplit, urlunsplit

TRUST_PROTOCOL = 1
SHA = re.compile(r"[a-f0-9]{40}\Z")
MAX_FETCH_BYTES = 512 * 1024 * 1024
PUBLIC_REASONS = {
    "not_configured": "宿主尚未配置更新信任，请联系部署管理员登记此仓库提交或签名公钥",
    "source_not_allowed": "此更新仓库未被宿主信任，网页不能添加信任",
    "commit_not_allowed": "此提交未在宿主登记，也不是可验证的签名标签",
    "signature_invalid": "标签未签名、签名不匹配或签名公钥未被宿主信任",
    "target_changed": "签名标签、目标提交或版本与检查结果不一致，请重新检查",
    "policy_changed": "宿主信任配置已变化，请重新检查此版本",
    "receipt_invalid": "缺少有效的宿主检查记录，旧检查或修改后的任务不能安装",
    "content_changed": "已验证源码内容发生变化，拒绝安装",
    "tool_unavailable": "宿主缺少 Git 或配置的签名验证工具，请联系部署管理员",
    "fetch_failed": "宿主无法取得受信任仓库的 Git 对象，请检查网络和读取权限",
}


class TrustError(RuntimeError):
    def __init__(self, reason):
        self.reason = reason if reason in PUBLIC_REASONS else "receipt_invalid"
        super().__init__(PUBLIC_REASONS[self.reason])


def repository_identity(value):
    try:
        if not isinstance(value, str) or len(value) > 2048 or re.search(r"[\x00-\x20\x7f\\]", value):
            raise ValueError()
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise ValueError()
        host = parsed.hostname.rstrip('.').encode('idna').decode('ascii').lower()
        if '%' in host or not host:
            raise ValueError()
        port = parsed.port
        parts = [unquote(part, errors='strict') for part in parsed.path.rstrip('/').split('/')[1:]]
        if len(parts) < 2 or any(not re.fullmatch(r"[\w.-]+", part) or part in {'.', '..'} for part in parts):
            raise ValueError()
        if parts[-1].endswith('.git'):
            parts[-1] = parts[-1][:-4]
        if not parts[-1]:
            raise ValueError()
        authority = '[' + host + ']' if ':' in host else host
        if port and port != (443 if parsed.scheme == 'https' else 80):
            authority += ':' + str(port)
        return urlunsplit((parsed.scheme, authority, '/' + '/'.join(quote(part, safe='') for part in parts), '', ''))
    except (ValueError, UnicodeError, TypeError):
        raise TrustError('source_not_allowed') from None


def private_file(path, limit=1024 * 1024):
    """Read only administrator-owned, non-writable-by-other regular files."""
    path = Path(path)
    if not path.is_absolute() or path.is_symlink():
        raise TrustError('not_configured')
    try:
        resolved = path.resolve(strict=True)
        for parent in resolved.parents:
            info = parent.stat()
            # Root-owned sticky /tmp is safe for an owner's private directory.
            if info.st_uid not in {0, os.getuid()} or (info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX)):
                raise TrustError('not_configured')
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid not in {0, os.getuid()} or info.st_mode & 0o022 or info.st_size > limit:
                raise TrustError('not_configured')
            result = stream.read(limit + 1)
        if len(result) > limit:
            raise TrustError('not_configured')
        return result
    except (OSError, ValueError):
        raise TrustError('not_configured') from None


def candidate_identity(candidate):
    try:
        result = {key: candidate[key] for key in ('check_id', 'source_id', 'source_revision', 'repository_url', 'ref', 'commit', 'version')}
        if (not isinstance(result['check_id'], str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', result['check_id'])
                or not isinstance(result['source_id'], str) or not re.fullmatch(r'[a-z0-9-]{1,64}', result['source_id'])
                or type(result['source_revision']) is not int or result['source_revision'] < 0
                or not SHA.fullmatch(result['commit']) or not isinstance(result['version'], str) or len(result['version']) > 128
                or not isinstance(result['ref'], str) or not result['ref'] or len(result['ref']) > 256
                or re.search(r'[\x00-\x20\x7f~^:?*\[\\]', result['ref']) or '..' in result['ref'] or '@{' in result['ref']
                or result['ref'].startswith(('/', '-'))):
            raise ValueError()
        result['repository_url'] = repository_identity(result['repository_url'])
        return result
    except (KeyError, TypeError, ValueError):
        raise TrustError('receipt_invalid') from None


def source_fingerprint(directory):
    digest = hashlib.sha256()
    directory = Path(directory)
    for path in sorted(directory.rglob('*')):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise TrustError('content_changed')
        relative = path.relative_to(directory).as_posix().encode('utf-8')
        digest.update(len(relative).to_bytes(4, 'big') + relative)
        if path.is_file():
            digest.update(b'file' + bytes([bool(path.stat().st_mode & 0o111)]) + path.stat().st_size.to_bytes(8, 'big'))
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
        else:
            digest.update(b'dir')
    return digest.hexdigest()


class Verifier:
    def __init__(self, policy_file, work):
        self.policy_file = Path(policy_file).absolute()
        self.work = Path(work).resolve()
        self.forbidden = []

    def _boundary(self, path):
        resolved = Path(path).resolve()
        for forbidden in self.forbidden:
            if resolved == forbidden or forbidden in resolved.parents:
                raise TrustError('not_configured')
        # Downloaded job directories are never a root-of-trust location.
        if self.work in resolved.parents:
            relative = resolved.relative_to(self.work)
            if relative.parts[0].startswith('.trust-git-') or re.fullmatch(r'[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', relative.parts[0]):
                raise TrustError('not_configured')

    def load(self):
        self._boundary(self.policy_file)
        raw = private_file(self.policy_file)
        digest = hashlib.sha256(raw)
        try:
            document = json.loads(raw)
            if not isinstance(document, dict) or set(document) != {'version', 'repositories'} or document['version'] != 1 or type(document['version']) is not int or not isinstance(document['repositories'], list):
                raise ValueError()
            repositories = {}
            for entry in document['repositories']:
                if not isinstance(entry, dict) or set(entry) - {'repository_url', 'allowed_commits', 'ssh_allowed_signers', 'openpgp_public_keys'}:
                    raise ValueError()
                repository = repository_identity(entry['repository_url'])
                commits = entry.get('allowed_commits', [])
                keys = entry.get('openpgp_public_keys', [])
                if repository in repositories or not isinstance(commits, list) or any(not isinstance(commit, str) or not SHA.fullmatch(commit) for commit in commits) or not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
                    raise ValueError()
                paths = keys + ([entry['ssh_allowed_signers']] if entry.get('ssh_allowed_signers') else [])
                if not commits and not paths:
                    raise ValueError()
                for name in paths:
                    self._boundary(name)
                    digest.update(str(Path(name).resolve()).encode() + b'\0' + private_file(name))
                repositories[repository] = {**entry, 'allowed_commits': set(commits)}
            if not repositories:
                raise ValueError()
            return repositories, digest.hexdigest()
        except (ValueError, KeyError, TypeError):
            raise TrustError('not_configured') from None

    def configured(self):
        try:
            self.load()
            return True
        except TrustError:
            return False

    def entry(self, candidate):
        identity = candidate_identity(candidate)
        repositories, digest = self.load()
        if identity['repository_url'] not in repositories:
            raise TrustError('source_not_allowed')
        return identity, repositories[identity['repository_url']], digest

    @staticmethod
    def _environment(home, token):
        if not isinstance(token, str) or len(token) > 4096 or any(not 33 <= ord(char) <= 126 for char in token):
            raise TrustError('fetch_failed')
        env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_') and key not in {'GNUPGHOME', 'SSH_AUTH_SOCK', 'GPG_AGENT_INFO'}}
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home), GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_CONFIG_SYSTEM=os.devnull, GIT_TERMINAL_PROMPT='0', GIT_ASKPASS='/usr/bin/false', GIT_NO_REPLACE_OBJECTS='1',
                   GIT_ALLOW_PROTOCOL='https:http', GIT_ATTR_NOSYSTEM='1', LC_ALL='C', GNUPGHOME=str(home / 'gnupg'))
        # Authorization is scoped to the approved origin and remains in memory.
        return env

    @staticmethod
    def _git(repo, args, env, *, limit=2 * 1024 * 1024):
        command = ['git', '-c', 'core.hooksPath=' + os.devnull, '-c', 'http.followRedirects=false', '-c', 'http.sslVerify=true',
                   '-c', 'credential.helper=', '-c', 'core.attributesFile=' + os.devnull, '-c', 'transfer.fsckObjects=true', '-c', 'fetch.fsckObjects=true',
                   '--git-dir=' + str(repo), *args]
        process = None
        try:
            # Bound output and object storage DURING transfer, before either
            # can exhaust memory/disk. These are disposable Git subprocesses,
            # never deployment/restore children.
            with tempfile.TemporaryFile(dir=repo.parent) as output, tempfile.TemporaryFile(dir=repo.parent) as errors:
                process = subprocess.Popen(command, env=env, stdout=output, stderr=errors, start_new_session=True)
                deadline = time.monotonic() + 180
                archive_output = next((Path(arg.split('=', 1)[1]) for arg in args if arg.startswith('--output=')), None)
                while True:
                    objects = 0
                    for path in repo.rglob('*'):
                        try:
                            info = path.stat()
                        except FileNotFoundError:
                            continue  # Git atomically renames pack/index files.
                        if stat.S_ISREG(info.st_mode):
                            objects += info.st_size
                    if (time.monotonic() > deadline or os.fstat(output.fileno()).st_size > limit or os.fstat(errors.fileno()).st_size > limit
                            or objects > MAX_FETCH_BYTES or (archive_output and archive_output.exists() and archive_output.stat().st_size > 256 * 1024 * 1024)):
                        raise TrustError('fetch_failed')
                    code = process.poll()
                    if code is not None:
                        break
                    time.sleep(0.05)
                if code or os.fstat(output.fileno()).st_size > limit or os.fstat(errors.fileno()).st_size > limit:
                    raise TrustError('fetch_failed')
                output.seek(0)
                return output.read(limit + 1)
        except (OSError, subprocess.TimeoutExpired):
            raise TrustError('fetch_failed') from None
        finally:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()

    @contextmanager
    def verified(self, candidate, token=''):
        identity, entry, policy_digest = self.entry(candidate)
        self.work.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.trust-git-', dir=self.work) as temporary:
            home = Path(temporary)
            repo = home / 'repository.git'
            env = self._environment(home, token)
            if not shutil.which('git'):
                raise TrustError('tool_unavailable')
            try:
                result = subprocess.run(['git', 'init', '--bare', '--object-format=sha1', str(repo)], env=env, capture_output=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                raise TrustError('fetch_failed') from None
            if result.returncode:
                raise TrustError('fetch_failed')
            env['GIT_CONFIG_COUNT'] = '1'
            env['GIT_CONFIG_KEY_0'] = 'http.' + identity['repository_url'] + '.extraHeader'
            env['GIT_CONFIG_VALUE_0'] = 'Authorization: Basic ' + base64.b64encode(('git:' + token).encode()).decode('ascii') if token else ''
            commit = identity['commit']
            if commit in entry['allowed_commits']:
                self._git(repo, ['fetch', '--quiet', '--depth=1', '--no-tags', identity['repository_url'], commit], env)
                method = 'commit'
            else:
                ref = 'refs/tags/trusted-release'
                try:
                    self._git(repo, ['fetch', '--quiet', '--depth=1', '--no-tags', identity['repository_url'], '+refs/tags/' + identity['ref'] + ':' + ref], env)
                    if self._git(repo, ['cat-file', '-t', ref], env).strip() != b'tag':
                        raise TrustError('signature_invalid')
                    tag = self._git(repo, ['cat-file', 'tag', ref], env)
                    if self._git(repo, ['rev-parse', ref + '^{commit}'], env).decode().strip() != commit:
                        raise TrustError('target_changed')
                    if b'-----BEGIN SSH SIGNATURE-----' in tag and entry.get('ssh_allowed_signers'):
                        if not shutil.which('ssh-keygen'):
                            raise TrustError('tool_unavailable')
                        try:
                            self._git(repo, ['-c', 'gpg.format=ssh', '-c', 'gpg.ssh.program=ssh-keygen', '-c', 'gpg.ssh.allowedSignersFile=' + entry['ssh_allowed_signers'], 'verify-tag', '--raw', ref], env)
                        except TrustError:
                            raise TrustError('signature_invalid') from None
                    elif b'-----BEGIN PGP SIGNATURE-----' in tag and entry.get('openpgp_public_keys'):
                        if not shutil.which('gpg'):
                            raise TrustError('tool_unavailable')
                        # GnuPG creates Unix sockets even during public-key
                        # import on some supported versions. A short, private
                        # host temporary home avoids path-length failures and
                        # never uses the operator's keyring or agent.
                        if not shutil.which('gpgconf'):
                            raise TrustError('tool_unavailable')
                        with tempfile.TemporaryDirectory(prefix='agv-trust-gpg-', dir='/tmp') as key_temp:
                            keyring = Path(key_temp)
                            self._boundary(keyring)
                            env['GNUPGHOME'] = str(keyring)
                            (keyring / 'gpg.conf').write_text('no-auto-key-retrieve\nno-auto-key-import\n')
                            (keyring / 'gpg.conf').chmod(0o600)
                            verifier = home / 'verify-gpg'
                            verifier.write_text('#!/bin/sh\nexec ' + shlex.quote(shutil.which('gpg')) + ' --no-autostart "$@"\n')
                            verifier.chmod(0o700)
                            try:
                                for key in entry['openpgp_public_keys']:
                                    try:
                                        imported = subprocess.run(['gpg', '--batch', '--homedir', str(keyring), '--import', key], env=env, capture_output=True, timeout=30)
                                    except (OSError, subprocess.TimeoutExpired):
                                        raise TrustError('signature_invalid') from None
                                    if imported.returncode:
                                        raise TrustError('signature_invalid')
                                try:
                                    self._git(repo, ['-c', 'gpg.format=openpgp', '-c', 'gpg.program=' + str(verifier), 'verify-tag', '--raw', ref], env)
                                except TrustError:
                                    raise TrustError('signature_invalid') from None
                            finally:
                                # Only the isolated verification home's agent is
                                # addressed; never kill/use the user's agent.
                                try:
                                    subprocess.run(['gpgconf', '--homedir', str(keyring), '--kill', 'gpg-agent'], env=env,
                                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                                except (OSError, subprocess.TimeoutExpired):
                                    pass

                    else:
                        raise TrustError('signature_invalid')
                    method = 'signed_tag'
                except TrustError as error:
                    if error.reason in {'target_changed', 'signature_invalid', 'tool_unavailable'}:
                        raise
                    raise TrustError('commit_not_allowed') from None
            if self._git(repo, ['cat-file', '-t', commit], env).strip() != b'commit':
                raise TrustError('target_changed')
            try:
                package = json.loads(self._git(repo, ['show', commit + ':frontend/package.json'], env))
                marker = json.loads(self._git(repo, ['show', commit + ':docker/update-protocol.json'], env))
                if package.get('name') != 'agv-pm-frontend' or package.get('version') != identity['version'] or marker != {'application': 'xingxu-workbench', 'protocol': 1} or type(marker.get('protocol')) is not int:
                    raise ValueError()
            except (ValueError, AttributeError):
                raise TrustError('target_changed') from None
            metadata = {'method': method, 'policy_digest': policy_digest,
                        'tree': self._git(repo, ['rev-parse', commit + '^{tree}'], env).decode().strip()}
            self.assert_policy(policy_digest)
            yield repo, env, metadata

    def assert_policy(self, digest):
        if self.load()[1] != digest:
            raise TrustError('policy_changed')

    def export(self, repo, env, commit, destination):
        destination = Path(destination)
        if destination.exists() or destination.is_symlink():
            raise TrustError('content_changed')
        self._git(repo, ['archive', '--format=tar.gz', '--prefix=repository/', '--output=' + str(destination), commit], env)
        destination.chmod(0o600)
        if destination.stat().st_size > 256 * 1024 * 1024:
            raise TrustError('fetch_failed')


def main():
    """Explicit host-admin enrollment; never reachable through the web bridge."""
    import argparse
    import fcntl
    parser = argparse.ArgumentParser(description='Manage the host-owned repository/commit trust policy')
    parser.add_argument('--trust-file', type=Path, required=True)
    command = parser.add_subparsers(dest='action', required=True)
    command.add_parser('verify-policy')
    allow = command.add_parser('allow-commit')
    allow.add_argument('--repository', required=True)
    allow.add_argument('--commit', required=True)
    args = parser.parse_args()
    if args.action == 'allow-commit' and not SHA.fullmatch(args.commit):
        parser.error('--commit 必须是 40 位小写的完整提交 SHA')
    os.umask(0o077)
    path = args.trust_file.absolute()
    try:
        if args.action == 'verify-policy':
            Verifier(path, path.parent / '.verification-work').load()
            print('宿主信任策略及公钥文件验证通过。')
            return
        if not SHA.fullmatch(args.commit):
            raise TrustError('receipt_invalid')
        repository = repository_identity(args.repository)
        if path.is_symlink() or path.parent.is_symlink():
            raise TrustError('not_configured')
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path.with_suffix(path.suffix + '.lock'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'a+b') as lock:
            if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
                raise TrustError('not_configured')
            fcntl.flock(lock, fcntl.LOCK_EX)
            if path.exists():
                Verifier(path, path.parent / '.verification-work').load()
                policy = json.loads(private_file(path))
            else:
                policy = {'version': 1, 'repositories': []}
            entry = next((item for item in policy['repositories'] if repository_identity(item['repository_url']) == repository), None)
            if entry is None:
                entry = {'repository_url': repository, 'allowed_commits': []}
                policy['repositories'].append(entry)
            entry['allowed_commits'] = sorted(set(entry.get('allowed_commits', [])) | {args.commit})
            fd, name = tempfile.mkstemp(prefix='.trust-policy-', dir=path.parent)
            temporary = Path(name)
            try:
                with os.fdopen(fd, 'w') as output:
                    json.dump(policy, output, ensure_ascii=False, indent=2)
                    output.write('\n'); output.flush(); os.fsync(output.fileno())
                # Validate BEFORE replacing an existing root of trust.
                Verifier(temporary, path.parent / '.verification-work').load()
                temporary.replace(path)
                directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                temporary.unlink(missing_ok=True)
        print('已在宿主登记此仓库的完整提交；请在网页重新检查版本。')
    except (TrustError, OSError, ValueError) as error:
        print(str(error) if isinstance(error, TrustError) else '宿主信任策略无法保存；原策略未被替换。', file=__import__('sys').stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
