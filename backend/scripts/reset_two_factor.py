#!/usr/bin/env python3
"""Trusted-host recovery only. Never called by HTTP or update job payloads."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description='受信宿主重置二次验证（撤销该账号全部会话和Agent凭据）')
    parser.add_argument('--username', required=True)
    parser.add_argument('--confirm-username', required=True)
    args = parser.parse_args()
    if not getattr(sys, '_xingxu_host_auth_recovery', False):
        parser.error('恢复工具必须作为独立宿主命令运行')
    data = Path(os.getenv('DATA_DIR', str(Path(__file__).resolve().parents[1] / 'data')))
    pending = data / 'restore-pending.tar.gz'
    if pending.exists() or pending.is_symlink():
        parser.error('存在待恢复请求；请先完成受信恢复，再重置二次验证')
    if args.username != args.confirm_username:
        parser.error('两次账号确认必须一致')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.db import SessionLocal
    from app.models import User
    from app.services.two_factor import host_reset
    with SessionLocal() as db:
        user = db.query(User).filter_by(username=args.username).first()
        if not user:
            parser.error('账号不存在')
        host_reset(db, user.id)
    print('二次验证已重置，旧会话及Agent凭据已撤销。公开部署的管理员/PM下次登录必须重新登记。')


if __name__ == '__main__':
    # Only this trusted standalone process may bypass config's restore bootstrap.
    # A race staging pending after the explicit check must never apply a snapshot.
    sys._xingxu_host_auth_recovery = True
    main()
