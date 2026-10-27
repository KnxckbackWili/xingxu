#!/usr/bin/env python3
"""安全兜底改密工具（HYPE-19）。

用途：实施人员在部署主机受限终端，为忘记密码的账号重置口令。
适用：账号持有人无法自助改密、也无管理员可在用户管理中代改的兜底路径。

安全约束（全部满足）：
  - 用户名作为命令行参数（用户名非机密）；
  - 新密码经 TTY 隐藏输入（getpass），两次一致且长度>=6；
    口令绝不进入命令行参数、环境变量、shell 历史、日志或 issue 评论；
  - 容器内 DB 更新通过 stdin 传递（第 1 行 DATABASE_URL、第 2 行新密码）：
    容器侧 python 先据此设置 DATABASE_URL 再读取 stdin 写入 DB，
    密码与连接串均不落 docker exec 进程参数（进程参数只有无机密的代码与用户名）；
  - 成功后原子同步 .secrets/ 对应条目（临时文件 + os.replace，保持 0600）。

用法：
  python3 docker/scripts/reset_password.py <username>

环境变量：
  AGV_CONTAINER    目标容器（默认 agv-pm-8002）
  AGV_SECRETS_DIR  凭据目录（默认 <部署目录>/.secrets；隔离验证可指向临时目录）
"""
import getpass
import os
import subprocess
import sys
import tempfile
from pathlib import Path

MIN_LEN = 6

# 与 docker/start.sh 一致的容器内数据库连接模板；USE_POSTGRES 经 docker inspect 探测，
# 连接串只经 stdin 传入容器，绝不写入命令行参数或环境变量。
_PG_URL = "postgresql+psycopg2://agv:agv@127.0.0.1:5432/agvpm"
_SQLITE_URL = "sqlite:////app/data/agvpm.db"


def _container_use_postgres(container: str) -> bool:
    """探测运行中容器的 USE_POSTGRES（只匹配开关，不打印任何环境变量）。"""
    proc = subprocess.run(
        ["docker", "inspect", container, "--format", "{{.Config.Env}}"],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"docker inspect {container} 失败: {proc.stderr.strip()}")
    return "USE_POSTGRES=1" in proc.stdout


def main() -> int:
    if len(sys.argv) != 2:
        print(f"用法: python3 {sys.argv[0]} <username>", file=sys.stderr)
        return 2
    username = sys.argv[1]

    container = os.environ.get("AGV_CONTAINER", "agv-pm-8002")
    project_dir = Path(__file__).resolve().parents[2]  # docker/scripts -> 部署目录
    secrets_dir = Path(os.environ.get("AGV_SECRETS_DIR", str(project_dir / ".secrets")))

    # 1) TTY 隐藏输入：两次一致才继续
    pw1 = getpass.getpass("新密码（输入不回显）: ")
    pw2 = getpass.getpass("再次输入确认: ")
    if pw1 != pw2:
        print("两次输入不一致，已放弃，未做任何修改。", file=sys.stderr)
        return 1
    if len(pw1) < MIN_LEN:
        print(f"密码至少 {MIN_LEN} 位，已放弃，未做任何修改。", file=sys.stderr)
        return 1
    if "\n" in pw1:
        print("密码不得包含换行符，已放弃，未做任何修改。", file=sys.stderr)
        return 1
    pw = pw1
    pw1 = pw2 = ""  # 尽早释放重复副本

    # 2) 容器内 DB 更新：DATABASE_URL 与新密码均经 stdin 传入，用户名经参数传入（非机密）。
    #    docker exec 进程参数里只有 python 代码与用户名，无任何口令或连接串。
    db_url = _PG_URL if _container_use_postgres(container) else _SQLITE_URL
    snippet = (
        "import os, sys\n"
        "# stdin 第 1 行: DATABASE_URL；其余: 新密码\n"
        "line1 = sys.stdin.readline()\n"
        "if not line1:\n"
        "    raise SystemExit('bad-stdin')\n"
        "os.environ['DATABASE_URL'] = line1.rstrip('\\n')\n"
        "pw = sys.stdin.read().rstrip('\\n')\n"
        "from app.db import SessionLocal\n"
        "from app.models import User\n"
        "from passlib.context import CryptContext\n"
        "db = SessionLocal()\n"
        "u = db.query(User).filter_by(username=sys.argv[1]).first()\n"
        "if u is None:\n"
        "    raise SystemExit('user-not-found')\n"
        "u.password_hash = CryptContext(schemes=['bcrypt']).hash(pw)\n"
        "u.token_version = (u.token_version or 0) + 1\n"
        "db.commit()\n"
        "print('ok')\n"
    )
    proc = subprocess.run(
        ["docker", "exec", "-i", container, "python", "-c", snippet, username],
        input=(db_url + "\n" + pw + "\n"),  # 字符串经 stdin 传入，不落命令行参数/环境变量
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        err = proc.stderr.strip()
        if "user-not-found" in err:
            print(f"容器 {container} 中不存在用户「{username}」，未做任何修改。", file=sys.stderr)
        else:
            print(f"容器内改密失败（{container}）：{err}", file=sys.stderr)
        pw = ""
        return 1

    # 3) 原子同步 .secrets/ 对应条目（需使用 pw，故在此之后才清空）
    cred_name = "admin-credentials.txt" if username == "admin" else "demo-credentials.txt"
    cred_file = secrets_dir / cred_name
    if not cred_file.is_file():
        print(f"密码已重置；但未找到 {cred_file}，跳过凭据文件同步。", file=sys.stderr)
        pw = ""
        return 0
    marker = f"{username}: "
    lines = cred_file.read_text(encoding="utf-8").splitlines(keepends=True)
    found = False
    for i, line in enumerate(lines):
        if line.startswith(marker):
            lines[i] = marker + pw + "\n"
            found = True
            break
    if not found:
        lines.append(marker + pw + "\n")
    # 原子写入：同目录临时文件 -> fsync -> os.replace，保持 0600
    fd, tmp = tempfile.mkstemp(dir=str(secrets_dir), prefix=".secrets.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(lines)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, cred_file)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    pw = ""

    print(f"「{username}」密码已重置并同步 {cred_file}（token_version 已递增，旧会话全部失效）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
