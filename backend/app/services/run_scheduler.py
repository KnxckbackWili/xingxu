"""The background process: once an hour, empty what has been in the trash for 30 days."""
import sys
import time


def main() -> None:
    from app.db import SessionLocal
    from app.services.cleanup import purge_expired
    from app.services.system_updates import is_maintenance

    time.sleep(60)  # the web process creates or upgrades the database first
    while True:
        try:
            if not is_maintenance():
                with SessionLocal() as db:
                    removed = purge_expired(db)
                if any(removed.values()):
                    print(f"[cleanup] 已清除 {removed}", file=sys.stderr, flush=True)
        except Exception as error:  # keep running; the next hour tries again
            print(f"[cleanup] 本次清理失败（{type(error).__name__}: {error}）", file=sys.stderr, flush=True)
        time.sleep(3600)


if __name__ == "__main__":
    main()
