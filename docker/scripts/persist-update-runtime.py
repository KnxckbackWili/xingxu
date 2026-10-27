#!/usr/bin/env python3
"""Atomically pin a verified installation without evaluating or printing its env."""
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


def persist(env_file, container):
    path = Path(env_file)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("installation env must be a regular file")
    values = dict(item.split("=", 1) for item in container["Config"]["Env"] if "=" in item)
    runtime = {"AGV_IMAGE": container["Image"], "APP_VERSION": values["APP_VERSION"], "GIT_SHA": values["GIT_SHA"]}
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", runtime["AGV_IMAGE"]):
        raise ValueError("invalid image identity")
    if not re.fullmatch(r"[0-9A-Za-z.+-]{1,128}", runtime["APP_VERSION"]):
        raise ValueError("invalid application version")
    if not re.fullmatch(r"[0-9a-f]{7,40}|unknown", runtime["GIT_SHA"]):
        raise ValueError("invalid source identity")
    # Compose dotenv uses the last assignment. Append the three controlled,
    # newline-free values, preserving arbitrary existing quoted/multiline values
    # byte-for-byte rather than attempting to parse or rewrite secret settings.
    original = path.read_bytes()
    block = b"# Verified application image; maintained by the host updater.\n" + b"".join(
        (key + "=" + value + "\n").encode("ascii") for key, value in runtime.items()
    )
    data = original + (b"" if not original or original.endswith(b"\n") else b"\n") + block
    fd, temporary = tempfile.mkstemp(prefix=".runtime-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        if os.geteuid() == 0:
            os.fchown(fd, info.st_uid, info.st_gid)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        persist(sys.argv[1], json.load(sys.stdin))
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        print("无法持久保存已核验的安装版本；维护状态保持，请检查宿主安装配置权限。", file=sys.stderr)
        raise SystemExit(1)
