"""Trusted, config-independent backup codec shared by the app and host scripts.

This file can run through ``docker exec -i ... python -`` in the retained old
image during rollback. It deliberately does not import app.config or open a DB
until an explicit backup command asks for a consistent snapshot.
"""
from contextlib import contextmanager
from datetime import datetime
import argparse
import base64
import io
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"XINGXU\x00\x01"
HEADER_BYTES = len(MAGIC) + 16 + 12
TAG_BYTES = 16
CHUNK_BYTES = 1024 * 1024
MAX_PLAINTEXT_BYTES = (1 << 36) - 32
MAX_ARCHIVE_MEMBERS = 100_000
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_EXPANDED_BYTES = max(1024, int(os.getenv("MAX_BACKUP_EXPANDED_MB", "8192"))) * 1024 * 1024
ALLOWED_ROOTS = {"manifest.json", "agvpm.db", "agvpm.dump", "secret.key", "system-update-config.json", "uploads", "project-deletion-backups", "migration-exports"}


class BackupError(ValueError):
    """A safe, user-facing backup failure; never include secrets in messages."""


def _open_regular(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise BackupError("备份相关文件必须是普通文件")
    return os.fdopen(fd, "rb")


def _read_small(path, limit=8192):
    with _open_regular(path) as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise BackupError("备份口令配置异常过大")
    return value


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_private(path, value):
    path = Path(path)
    if path.is_symlink():
        raise BackupError("备份配置路径不安全")
    fd, name = tempfile.mkstemp(prefix=".backup-config-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _key(data_dir, *, create=False):
    directory = Path(data_dir) / "backup-security"
    if directory.is_symlink():
        raise BackupError("备份口令目录不安全")
    if create:
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
    key_file = directory / "key"
    if create:
        try:
            fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(os.urandom(32))
                stream.flush()
                os.fsync(stream.fileno())
            _sync_directory(directory)
    value = _read_small(key_file, 32)
    if len(value) != 32:
        raise BackupError("备份口令密钥损坏，请重新设置备份口令")
    return value


def validate_passphrase(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 1024 or any(c in value for c in "\r\n\x00"):
        raise BackupError("备份口令应为 12–1024 个字符，不能包含换行或空字符")
    return value


def _set_passphrase(data_dir, value):
    validate_passphrase(value)
    nonce = os.urandom(12)
    sealed = nonce + AESGCM(_key(data_dir, create=True)).encrypt(nonce, value.encode("utf-8"), b"xingxu-backup-passphrase-v1")
    _atomic_private(Path(data_dir) / "backup-security" / "credentials.json", json.dumps({
        "version": 1, "sealed": base64.b64encode(sealed).decode("ascii"),
    }).encode("utf-8"))


@contextmanager
def passphrase_update(data_dir, value):
    """Serialize configuration and roll back its file if the caller's audit fails."""
    import fcntl
    validate_passphrase(value)
    directory = Path(data_dir) / "backup-security"
    if directory.is_symlink():
        raise BackupError("备份口令目录不安全")
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    descriptor = os.open(directory / "settings.lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        settings = directory / "credentials.json"
        previous = _read_small(settings) if settings.exists() or settings.is_symlink() else None
        try:
            _set_passphrase(data_dir, value)
            yield
        except Exception:
            if previous is None:
                settings.unlink(missing_ok=True)
                _sync_directory(directory)
            else:
                _atomic_private(settings, previous)
            raise
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def set_passphrase(data_dir, value):
    with passphrase_update(data_dir, value):
        pass


def _passphrase_file(path):
    with _open_regular(path) as stream:
        if stat.S_IMODE(os.fstat(stream.fileno()).st_mode) & 0o077:
            raise BackupError("备份口令文件权限必须为 0600")
        value = stream.read(8193)
    if len(value) > 8192:
        raise BackupError("备份口令文件过大")
    try:
        return validate_passphrase(value.decode("utf-8").rstrip("\r\n"))
    except UnicodeError:
        raise BackupError("备份口令文件必须为 UTF-8 文本") from None


def get_passphrase(data_dir, passphrase_file=None):
    if passphrase_file:
        return _passphrase_file(passphrase_file)
    settings = Path(data_dir) / "backup-security" / "credentials.json"
    if settings.exists() or settings.is_symlink():
        import fcntl
        directory = settings.parent
        if directory.is_symlink():
            raise BackupError("备份口令目录不安全")
        descriptor = os.open(directory / "settings.lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            try:
                document = json.loads(_read_small(settings))
                if document.get("version") != 1:
                    raise ValueError()
                sealed = base64.b64decode(document["sealed"], validate=True)
                return validate_passphrase(AESGCM(_key(data_dir)).decrypt(sealed[:12], sealed[12:], b"xingxu-backup-passphrase-v1").decode("utf-8"))
            except (InvalidTag, ValueError, KeyError, TypeError, AttributeError, UnicodeError, OSError):
                raise BackupError("备份口令配置无法解密，请由管理员重新设置") from None
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    if os.getenv("BACKUP_PASSPHRASE_FILE"):
        return _passphrase_file(os.environ["BACKUP_PASSPHRASE_FILE"])
    raise BackupError("尚未设置备份口令；请在系统备份设置中配置，或提供私有口令文件")


def passphrase_status(data_dir):
    try:
        get_passphrase(data_dir)
        source = "administrator" if (Path(data_dir) / "backup-security" / "credentials.json").exists() else "file"
        return {"configured": True, "source": source}
    except (BackupError, OSError):
        return {"configured": False, "source": None}


def _derive(passphrase, salt):
    if not isinstance(passphrase, str) or not passphrase or len(passphrase.encode("utf-8")) > 8192:
        raise BackupError("请输入备份口令")
    # OWASP's 32 MiB option keeps memory bounded on the NAS while retaining
    # its recommended work factor. Parameters are fixed by envelope version.
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=3).derive(passphrase.encode("utf-8"))


def is_encrypted(path):
    with _open_regular(path) as stream:
        return stream.read(len(MAGIC)) == MAGIC


@contextmanager
def encrypted_writer(destination, passphrase):
    """Stream an authenticated envelope, publish once, and never overwrite."""
    destination = Path(destination)
    salt, nonce = os.urandom(16), os.urandom(12)
    header = MAGIC + salt + nonce
    encryptor = Cipher(algorithms.AES(_derive(passphrase, salt)), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header)
    fd, name = tempfile.mkstemp(prefix=".backup-encrypted-", dir=destination.parent)
    temporary = Path(name)
    published = False
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(header)

            class Writer:
                count = 0

                def write(self, value):
                    self.count += len(value)
                    if self.count > MAX_PLAINTEXT_BYTES:
                        raise BackupError("备份超过单个加密文件大小限制")
                    output.write(encryptor.update(value))
                    return len(value)

                def flush(self):
                    output.flush()

            yield Writer()
            output.write(encryptor.finalize())
            output.write(encryptor.tag)
            output.flush()
            os.fsync(output.fileno())
        # link is an atomic no-replace publication, including concurrent callers.
        os.link(temporary, destination)
        published = True
        _sync_directory(destination.parent)
    except Exception:
        if published:
            destination.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def encrypt_file(source, destination, passphrase):
    with _open_regular(source) as stream, encrypted_writer(destination, passphrase) as output:
        shutil.copyfileobj(stream, output, CHUNK_BYTES)
    return Path(destination)


@contextmanager
def decrypted_file(source, passphrase, *, directory=None):
    """Yield plaintext only AFTER complete GCM authentication, in a 0700 scope."""
    source = Path(source)
    with tempfile.TemporaryDirectory(prefix=".backup-decrypt-", dir=directory or source.parent) as temp:
        plaintext = Path(temp) / "payload"
        try:
            with _open_regular(source) as stream:
                size = os.fstat(stream.fileno()).st_size
                header = stream.read(HEADER_BYTES)
                remaining = size - HEADER_BYTES - TAG_BYTES
                if not header.startswith(MAGIC) or len(header) != HEADER_BYTES or not 0 <= remaining <= MAX_PLAINTEXT_BYTES:
                    raise BackupError("备份加密格式不正确或文件已截断")
                stream.seek(-TAG_BYTES, os.SEEK_END)
                tag = stream.read(TAG_BYTES)
                stream.seek(HEADER_BYTES)
                decryptor = Cipher(algorithms.AES(_derive(passphrase, header[len(MAGIC):len(MAGIC) + 16])), modes.GCM(header[-12:], tag)).decryptor()
                decryptor.authenticate_additional_data(header)
                fd = os.open(plaintext, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as output:
                    while remaining:
                        value = stream.read(min(CHUNK_BYTES, remaining))
                        if not value:
                            raise BackupError("备份文件已截断")
                        remaining -= len(value)
                        output.write(decryptor.update(value))
                    output.write(decryptor.finalize())
                    output.flush()
                    os.fsync(output.fileno())
        except InvalidTag:
            raise BackupError("备份口令错误或文件已损坏（认证失败）") from None
        yield plaintext


@contextmanager
def plain_archive(path, passphrase=None, *, allow_legacy=False, directory=None):
    if is_encrypted(path):
        with decrypted_file(path, passphrase, directory=directory) as plaintext:
            yield plaintext
    elif allow_legacy:
        yield Path(path)
    else:
        raise BackupError("仅接受加密备份；历史明文备份请先加密或使用宿主恢复工具")


def safe_members(archive):
    members = []
    for member in archive:
        if len(members) >= MAX_ARCHIVE_MEMBERS:
            raise BackupError("备份包文件数量过多")
        members.append(member)
    total, names = 0, set()
    for member in members:
        path = PurePosixPath(member.name)
        normalized = path.as_posix()
        canonical = member.name == normalized or (member.isdir() and member.name == normalized + "/")
        if not canonical or "\\" in member.name:
            raise BackupError("备份包包含非标准路径")
        if normalized in names:
            raise BackupError("备份包包含重复路径")
        names.add(normalized)
        if (path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] not in ALLOWED_ROOTS
                or member.issym() or member.islnk() or not (member.isfile() or member.isdir())):
            raise BackupError("备份包包含不安全路径或文件类型")
        if path.parts[0] in {"manifest.json", "agvpm.db", "agvpm.dump", "secret.key", "system-update-config.json"} and (len(path.parts) != 1 or not member.isfile()):
            raise BackupError("备份包核心文件结构不正确")
        if path.parts[0] in {"uploads", "project-deletion-backups", "migration-exports"} and len(path.parts) == 1 and not member.isdir():
            raise BackupError("备份附件目录结构不正确")
        if path.parts[0] == "project-deletion-backups" and len(path.parts) > 1 and (len(path.parts) != 2 or not member.isfile() or not path.name.endswith((".zip", ".zip.agvenc"))):
            raise BackupError("项目删除备份目录结构不正确")
        # Legacy modes must not expose temporary or installed plaintext.
        member.mode = 0o700 if member.isdir() else 0o600
        member.uid = member.gid = 0
        member.uname = member.gname = ""
        total += max(member.size, 0)
        if total > MAX_EXPANDED_BYTES:
            raise BackupError(f"备份包解压后超过 {MAX_EXPANDED_BYTES // 1024 // 1024}MB")
        if member.name in {"manifest.json", "system-update-config.json"} and member.size > MAX_MANIFEST_BYTES:
            raise BackupError("备份清单或更新配置异常过大")
    return members


def validate_sqlite_member(archive, directory=None):
    database = archive.extractfile("agvpm.db")
    if database is None or database.read(16) != b"SQLite format 3\x00":
        raise BackupError("备份数据库格式不正确")
    with tempfile.TemporaryDirectory(prefix=".agvpm-check-backup-", dir=directory) as temp:
        path = Path(temp) / "agvpm.db"
        database.seek(0)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as output:
            shutil.copyfileobj(database, output, CHUNK_BYTES)
        try:
            connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
            try:
                if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise BackupError("备份数据库完整性检查失败")
                required = {"users": {"id", "username", "password_hash", "role", "is_active"}, "projects": {"id", "name"}, "tasks": {"id", "project_id", "module_id", "name"}}
                for table, columns in required.items():
                    actual = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                    if not columns.issubset(actual):
                        raise BackupError("备份数据库缺少 AGV 系统核心数据表或字段")
            finally:
                connection.close()
        except sqlite3.DatabaseError:
            raise BackupError("备份数据库不完整或已损坏") from None


def _pg_dump(target, database_url, *, custom=True, snapshot_id=None):
    url = urlparse(database_url)
    query = parse_qs(url.query)
    cmd = ["pg_dump", "-h", query.get("host", [url.hostname or "127.0.0.1"])[0], "-p", str(query.get("port", [url.port or 5432])[0]), "-U", unquote(url.username or "agv"), "-d", unquote((url.path or "/agvpm").lstrip("/")), "--no-owner", "--no-privileges"]
    if custom:
        cmd.append("-Fc")
    if snapshot_id is not None:
        cmd += ['--snapshot',snapshot_id]
    cmd += ["-f", str(target)]
    subprocess.run(cmd, env={**os.environ, "PGPASSWORD": unquote(url.password or "")}, check=True, capture_output=True, text=True)


def copy_project_deletion_backups(data_dir, work):
    source = Path(data_dir) / "project-deletion-backups"
    if source.is_symlink():
        raise BackupError("项目删除备份目录不安全")
    if not source.exists():
        return
    if not source.is_dir():
        raise BackupError("项目删除备份目录不安全")
    target = Path(work) / source.name
    target.mkdir(mode=0o700)
    for child in source.iterdir():
        if not child.name.endswith((".zip", ".zip.agvenc")):
            raise BackupError("项目删除备份包含不安全文件")
        with _open_regular(child) as stream, (target / child.name).open("xb") as output:
            os.chmod(output.name, 0o600)
            shutil.copyfileobj(stream, output, CHUNK_BYTES)


def _add_path(archive, source, name, *, expected=None, seen=None):
    source = Path(source)
    if source.is_symlink():
        raise BackupError("备份源包含不安全链接")
    if source.is_dir():
        member = tarfile.TarInfo(name)
        member.type, member.mode = tarfile.DIRTYPE, 0o700
        archive.addfile(member)
        for child in sorted(source.iterdir()):
            if name == "project-deletion-backups" and (not child.is_file() or not child.name.endswith((".zip", ".zip.agvenc"))):
                raise BackupError("项目删除备份包含不安全文件")
            _add_path(archive, child, name + "/" + child.name,expected=expected,seen=seen)
        return
    with _open_regular(source) as stream:
        member = tarfile.TarInfo(name)
        member.size, member.mode = os.fstat(stream.fileno()).st_size, 0o600
        evidence=(expected or {}).get(name)
        if evidence and evidence.get('size') is not None and member.size!=evidence['size']:
            raise BackupError('备份原件长度与数据库快照不一致，未发布备份')
        class HashReader:
            def __init__(self):self.digest=hashlib.sha256()
            def read(self,size=-1):
                value=stream.read(size);self.digest.update(value);return value
        reader=HashReader();archive.addfile(member,reader)
        if evidence and evidence.get('sha256') and reader.digest.hexdigest()!=evidence['sha256']:
            raise BackupError('备份原件SHA-256与数据库快照不一致，未发布备份')
        if seen is not None:seen.add(name)


def _storage_inventory(connection, *, postgres=False):
    """Read only frozen storage fields from THE SAME snapshot as the DB dump.

    Runs without importing app/ORM, including from a retained rollback image.
    Unknown old schemas may omit these tables; known rows never omit bytes just
    because the current filesystem happens to be missing their originals.
    """
    cursor=connection.cursor()
    def rows(table,fields):
        if postgres:
            cursor.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s',(table,))
            columns={row[0] for row in cursor.fetchall()}
        else:
            cursor.execute(f'PRAGMA table_info("{table}")');columns={row[1] for row in cursor.fetchall()}
        selected=[name for name in fields if name in columns]
        if not selected:return []
        cursor.execute('SELECT '+','.join('"'+name+'"' for name in selected)+' FROM "'+table+'"')
        return [dict(zip(selected,row)) for row in cursor.fetchall()]
    def obj(value):
        return json.loads(value) if isinstance(value,str) else value
    assets=rows('attachments',('id','project_id','stored_name','filename','sha256','file_size'))
    removals={row['attachment_id']:row for row in rows('file_removal_records',('id','attachment_id','project_id','receipt_id','stored_name','filename','sha256','file_size','reason','removed_at'))}
    receipts={row['id']:row for row in rows('file_cleanup_receipts',('id','project_id','policy','preview_sha256','reason','applied_at'))}
    def authorized(asset,record,receipt):
        if not asset or not record or not receipt:return False
        policy=obj(receipt.get('policy')) or {}
        proof=next((item for item in policy.get('candidates',[]) if item.get('attachment_id')==asset['id'] and item.get('removal_record_id')==record['id']),None)
        return bool(policy.get('kind')=='weekly_retention_v1' and policy.get('fingerprint')==receipt['preview_sha256']
            and record['attachment_id']==asset['id'] and receipt['project_id']==record['project_id']==asset['project_id'] and proof
            and record['reason'] and record['reason']==receipt['reason'] and str(record['removed_at'])==str(receipt['applied_at'])
            and all(asset.get(key)==record.get(key)==proof.get(key) for key in ('stored_name','filename','sha256','file_size')))
    expected={};removed=[]
    def require(stored,size=None,sha=None):
        if not isinstance(stored,str) or not stored or PurePosixPath(stored).name!=stored or '\\' in stored or stored in ('.','..'):
            raise BackupError('数据库快照包含不安全的原件路径')
        key='uploads/'+stored
        prior=expected.get(key,{})
        if prior and any(prior.get(field) is not None and value is not None and prior[field]!=value for field,value in [('size',size),('sha256',sha)]):
            raise BackupError('共享原件元数据不一致，未发布备份')
        expected[key]={'size':size if size is not None else prior.get('size'),'sha256':sha or prior.get('sha256')}
    for asset in assets:
        record=removals.get(asset.get('id'));receipt=receipts.get(record.get('receipt_id')) if record else None
        if authorized(asset,record,receipt):removed.append({'attachment_id':asset['id'],'record':record,'receipt':receipt})
        else:require(asset['stored_name'],asset.get('file_size'),asset.get('sha256'))
    for table in ('document_template_files','template_docs'):
        for row in rows(table,('stored_name','file_size','sha256')):require(row['stored_name'],row.get('file_size'),row.get('sha256'))
    for row in rows('tasks',('reference_docs',)):
        for ref in obj(row.get('reference_docs')) or []:
            if isinstance(ref,dict) and ref.get('stored_name'):require(ref['stored_name'])
    for row in rows('project_archives',('snapshot',)):
        snapshot=obj(row.get('snapshot')) or {};records=snapshot.get('records',{})
        aa={r['id']:r for r in records.get('attachments',[])};rr={r['id']:r for r in records.get('file_removal_records',[])};cc={r['id']:r for r in records.get('file_cleanup_receipts',[])}
        for ref in snapshot.get('binary_files',{}).get('manifest',[]):
            if not isinstance(ref,dict) or not ref.get('stored_name'):continue
            legitimate=ref.get('intentionally_removed') is True and bool(ref.get('references'))
            for owner in ref.get('references',[]):
                asset=aa.get(owner.get('id'));record=rr.get((ref.get('removal_record_ids') or {}).get(owner.get('id')))
                receipt=cc.get(record.get('receipt_id')) if record else None
                if (owner.get('table')!='attachments' or not authorized(asset,record,receipt)
                    or (ref.get('stored_name'),ref.get('sha256'),ref.get('size'))!=(record.get('stored_name'),record.get('sha256'),record.get('file_size'))):
                    legitimate=False;break
            if not legitimate:require(ref['stored_name'],ref.get('size'),ref.get('sha256'))
    cursor.close()
    disclosure={'policy_removed_files':len(removed),'policy_removed_bytes':sum(row['record']['file_size'] for row in removed),
        'removal_evidence_sha256':hashlib.sha256(json.dumps(removed,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest(),
        'byte_recovery':'所有未清理原件随备份保存；已明确授权清理的历史字节不在包内，数据库完整保留原提交元数据及清理凭据。未完成上传临时分片不作为正式原件备份，本地队列可续传缺片。'}
    return expected,disclosure


def create_archive(data_dir, destination, database_url, passphrase, *, label="manual", app_version="unknown"):
    data_dir, destination = Path(data_dir), Path(destination)
    if destination.parent.is_symlink():
        raise BackupError("备份目录不能是链接")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    database = "postgres" if database_url.startswith("postgresql") else "sqlite"
    with tempfile.TemporaryDirectory(prefix=".backup-snapshot-", dir=data_dir) as temp:
        work = Path(temp)
        snapshot = work / ("agvpm.dump" if database == "postgres" else "agvpm.db")
        fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        if database == "postgres":
            # Export one repeatable-read snapshot so both the portable dump and
            # storage proof agree even if a cleanup commits during tar creation.
            try:
                import psycopg2
                source=psycopg2.connect(database_url.replace('postgresql+psycopg2://','postgresql://'))
                try:
                    source.set_session(isolation_level='REPEATABLE READ',readonly=True)
                    with source.cursor() as cursor:
                        cursor.execute('SELECT pg_export_snapshot()');snapshot_id=cursor.fetchone()[0]
                    expected,storage=_storage_inventory(source,postgres=True)
                    _pg_dump(snapshot,database_url,snapshot_id=snapshot_id)
                finally:source.close()
            except ImportError:raise BackupError('PostgreSQL一致备份需要镜像内psycopg2运行库') from None
        else:
            source = sqlite3.connect(f"file:{(data_dir / 'agvpm.db').as_posix()}?mode=ro", uri=True)
            target = sqlite3.connect(snapshot)
            try:
                source.backup(target)
                if target.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise BackupError("SQLite 备份完整性检查失败")
                expected,storage=_storage_inventory(target)
            finally:
                target.close()
                source.close()
        manifest = json.dumps({"type": "agvpm-system-backup", "version": "3.0", "database": database,'storage':storage,
                               "app_version": app_version, "created_at": datetime.now().isoformat(), "label": label}, ensure_ascii=False).encode("utf-8")
        with encrypted_writer(destination, passphrase) as output:
            seen=set()
            with tarfile.open(fileobj=output, mode="w|gz") as archive:
                _add_path(archive, snapshot, snapshot.name)
                member = tarfile.TarInfo("manifest.json")
                member.size, member.mode = len(manifest), 0o600
                archive.addfile(member, io.BytesIO(manifest))
                for name in ["secret.key", "system-update-config.json", "uploads", "project-deletion-backups", "migration-exports"]:
                    path = data_dir / name
                    if path.exists() or path.is_symlink():
                        if name in {"secret.key", "system-update-config.json"} and (not path.is_file() or path.is_symlink()):
                            raise BackupError("备份配置必须为普通文件")
                    # The running app prefers an explicit environment secret over
                    # secret.key. Preserve that same effective key inside the
                    # encrypted stream, including when the file is stale/missing.
                    # Keep the existing regular-file/symlink check above.
                    effective_secret = os.getenv("SECRET_KEY") if name == "secret.key" else None
                    if effective_secret:
                        raw_key = effective_secret.encode("utf-8")
                        member = tarfile.TarInfo("secret.key")
                        member.size, member.mode = len(raw_key), 0o600
                        archive.addfile(member, io.BytesIO(raw_key))
                    elif path.exists() or path.is_symlink():
                        _add_path(archive, path, name,expected=expected,seen=seen)
                if set(expected)-seen:
                    raise BackupError('数据库快照引用的普通原件缺失或在备份期间被移除，未发布备份；请核对后重试')
    return destination


def validate_archive(path, passphrase=None, *, allow_legacy=True, directory=None):
    with plain_archive(path, passphrase, allow_legacy=allow_legacy, directory=directory) as plaintext:
        try:
            with tarfile.open(plaintext, "r:gz") as archive:
                names = {member.name for member in safe_members(archive)}
                if "manifest.json" not in names or len(names & {"agvpm.db", "agvpm.dump"}) != 1:
                    raise BackupError("备份包缺少数据库或清单")
                manifest = json.load(archive.extractfile("manifest.json"))
                if not isinstance(manifest, dict) or manifest.get("type") != "agvpm-system-backup":
                    raise BackupError("备份包类型不正确")
                database = "sqlite" if "agvpm.db" in names else "postgres"
                if manifest.get("database", database) != database:
                    raise BackupError("备份数据库类型与清单不一致")
                if database == "sqlite":
                    validate_sqlite_member(archive, directory=plaintext.parent)
                elif archive.extractfile("agvpm.dump").read(5) != b"PGDMP":
                    raise BackupError("PostgreSQL 备份格式不正确")
                return {**manifest, "database": database}
        except (tarfile.TarError, json.JSONDecodeError, UnicodeError):
            raise BackupError("不是有效的行序系统备份包") from None



def apply_pending_restore(data_dir: Path) -> bool:
    """Restore a staged archive once, serialized across processes.

    The container runs several Python processes at boot (uvicorn ``--workers 2``
    plus the scheduler) and each imports ``app.config``. Without a lock they all
    pass the initial ``pending.exists()`` check and concurrently replace the DB
    / uploads, corrupting the restore — so an exclusive file lock plus a second
    existence check is required.
    """
    pending = data_dir / "restore-pending.tar.gz"
    if pending.is_symlink():
        raise BackupError("待恢复路径不能是链接")
    if not pending.exists():
        return False
    try:
        import fcntl
    except ImportError:  # pragma: no cover - non-POSIX dev only
        fcntl = None
    lock = None
    if fcntl is not None:
        descriptor = os.open(data_dir / "restore-pending.lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        lock = os.fdopen(descriptor, "a+")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        # Another process already applied it while we waited for the lock.
        if not pending.exists():
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()
            return False
    try:
        _apply(data_dir, pending)
        return True
    finally:
        if lock is not None:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            finally:
                lock.close()


def _apply(data_dir: Path, pending: Path) -> None:
    backups = data_dir / "backups"
    if backups.is_symlink():
        raise BackupError("备份目录不能是链接")
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    with tarfile.open(pending, "r:gz") as archive:
        members = safe_members(archive)
        names = {member.name for member in members}
        if "manifest.json" not in names or "agvpm.db" not in names:
            raise ValueError("待恢复备份不完整")
        manifest_file = archive.extractfile("manifest.json")
        manifest = json.loads(manifest_file.read().decode("utf-8")) if manifest_file else {}
        if not isinstance(manifest, dict) or manifest.get("type") != "agvpm-system-backup":
            raise ValueError("待恢复备份类型不正确")
        validate_sqlite_member(archive, directory=data_dir)

    # Preserve the current installation before replacement.
    current_db = data_dir / "agvpm.db"
    if current_db.exists():
        # A failed/missing password must leave the pending request and current
        # installation intact. Only a fully published encrypted snapshot allows
        # the replacement below to proceed.
        create_archive(data_dir, backups / f"agvpm-pre-restore-{stamp}-{uuid4().hex}.tar.gz.agvenc",
                       "sqlite", get_passphrase(data_dir), label="pre-restore")

    # Prepare everything on the installation filesystem before touching live
    # files. A failed extraction/copy must leave the current installation intact.
    with tempfile.TemporaryDirectory(prefix=".agvpm-restore-", dir=data_dir) as temp:
        work = Path(temp)
        with tarfile.open(pending, "r:gz") as archive:
            archive.extractall(work, members=safe_members(archive), filter="data")
        (work / "uploads").mkdir(exist_ok=True)
        (work / "project-deletion-backups").mkdir(exist_ok=True, mode=0o700)
        (work / "migration-exports").mkdir(exist_ok=True, mode=0o700)
        _install_snapshot(data_dir, work)
    pending.unlink(missing_ok=True)


def _install_snapshot(data_dir: Path, work: Path) -> None:
    """Install prepared files with rollback if any replacement fails.

    Keep rollback files outside the extraction context so even a second I/O
    failure during rollback does not cause its cleanup to discard the originals.
    """
    previous = Path(tempfile.mkdtemp(prefix=".restore-rollback-", dir=data_dir))
    names = ["agvpm.db", "agvpm.db-wal", "agvpm.db-shm", "uploads", "project-deletion-backups", "migration-exports", "system-update-config.json",
             ".upload-sessions", ".storage-trash", ".export-staging"]
    marker = data_dir / "update-maintenance.json"
    if not (marker.exists() or marker.is_symlink()):
        # A normal restore starts a new installation history: never replay an
        # earlier queued update. Automatic update rollback keeps its journal so
        # the host can report the verified rollback after restarting the app.
        names.append("system-updates")
    if (work / "secret.key").exists():
        names.append("secret.key")
    moved, installed = [], set()
    try:
        for name in names:
            live = data_dir / name
            if live.exists():
                live.replace(previous / name)
            moved.append(name)
            staged = work / name
            if staged.exists():
                staged.replace(live)
                installed.add(name)
                if name == "system-update-config.json":
                    live.chmod(0o600)
    except Exception:
        # Reverse the partial swap, including SQLite WAL/SHM sidecars. If this
        # itself fails, retain `previous` for recovery instead of deleting it.
        for name in reversed(moved):
            live = data_dir / name
            if name in installed:
                if live.is_dir():
                    shutil.rmtree(live)
                else:
                    live.unlink(missing_ok=True)
            old = previous / name
            if old.exists():
                old.replace(live)
        shutil.rmtree(previous, ignore_errors=True)
        raise
    shutil.rmtree(previous, ignore_errors=True)

def runtime_database_url():
    # docker exec does not inherit the shell exports from start.sh. Mirror its
    # embedded-PG choice explicitly, without importing app.config at rollback.
    if os.getenv("USE_POSTGRES") == "1":
        return "postgresql://agv@127.0.0.1:5432/agvpm"
    return os.getenv("DATABASE_URL") or "sqlite"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "inspect", "decrypt", "configure", "encrypt", "status", "extract", "stage", "apply", "decrypt-file"])
    parser.add_argument("--data-dir", type=Path, default=Path("/app/data"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--passphrase-file", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "status":
            target_url = runtime_database_url()
            print(json.dumps({**passphrase_status(args.data_dir), "database": "postgres" if target_url.startswith("postgresql") else "sqlite",
                              "host_restore_supported": not target_url.startswith("postgresql") or os.getenv("USE_POSTGRES") == "1"}))
            return
        password = get_passphrase(args.data_dir, args.passphrase_file)
        if args.action == "configure":
            set_passphrase(args.data_dir, password)
            print(json.dumps({"configured": True}))
        elif args.action == "apply":
            print(json.dumps({"applied": apply_pending_restore(args.data_dir)}))
        elif args.action == "create":
            url = runtime_database_url()
            create_archive(args.data_dir, args.output, url, password, label="docker-script", app_version=os.getenv("APP_VERSION", "unknown"))
            print(json.dumps({"encrypted": True, "filename": args.output.name}))
        elif args.action == "encrypt":
            encrypt_file(args.input, args.output, password)
        elif args.action == "decrypt-file":
            # Explicit raw-file recovery for encrypted pre-migration SQL/SQLite
            # snapshots and reusable project archives; never an archive bypass.
            with decrypted_file(args.input, password, directory=args.data_dir) as plaintext:
                fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                try:
                    with _open_regular(plaintext) as source, os.fdopen(fd, "wb") as output:
                        shutil.copyfileobj(source, output, CHUNK_BYTES)
                        output.flush()
                        os.fsync(output.fileno())
                except Exception:
                    args.output.unlink(missing_ok=True)
                    raise
        else:
            manifest = validate_archive(args.input, password, directory=args.data_dir)
            if args.action in {"decrypt", "extract", "stage"}:
                with plain_archive(args.input, password, allow_legacy=True, directory=args.data_dir) as plaintext:
                    if args.action == "extract":
                        args.output.mkdir(mode=0o700, exist_ok=False)
                        with tarfile.open(plaintext, "r:gz") as archive:
                            archive.extractall(args.output, members=safe_members(archive), filter="data")
                        if manifest["database"] == "postgres":
                            try:
                                subprocess.run(["pg_restore", "--list", str(args.output / "agvpm.dump")],
                                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
                            except subprocess.CalledProcessError:
                                raise BackupError("PostgreSQL 备份完整性检查失败") from None
                    elif args.action == "stage":
                        if args.output.is_symlink():
                            raise BackupError("待恢复路径不安全")
                        fd, name = tempfile.mkstemp(prefix=".restore-verified-", dir=args.output.parent)
                        staged = Path(name)
                        try:
                            with _open_regular(plaintext) as source, os.fdopen(fd, "wb") as output:
                                shutil.copyfileobj(source, output, CHUNK_BYTES)
                                output.flush()
                                os.fsync(output.fileno())
                            staged.replace(args.output)
                            _sync_directory(args.output.parent)
                        finally:
                            staged.unlink(missing_ok=True)
                    else:
                        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                        try:
                            with _open_regular(plaintext) as source, os.fdopen(fd, "wb") as output:
                                shutil.copyfileobj(source, output, CHUNK_BYTES)
                                output.flush()
                                os.fsync(output.fileno())
                        except Exception:
                            args.output.unlink(missing_ok=True)
                            raise
            print(json.dumps(manifest, ensure_ascii=False))
    except Exception as error:
        # subprocess exception text can contain DB connection details; callers
        # get a safe error and an exit status, never a passphrase or environment.
        print(str(error) if isinstance(error, BackupError) else f"备份操作失败（{type(error).__name__}）", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
