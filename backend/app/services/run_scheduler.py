"""独立调度器进程入口（A2：单容器由 supervisord 托管，避免多 worker 各起一个调度器导致重复通知）。

用法：python -m app.services.run_scheduler
Web worker（uvicorn）内保持 SCHEDULER_ENABLED=0；本进程负责日报/周报/SLA 扫描。
"""

import logging
import time

logger = logging.getLogger("scheduler.runner")


def main():
    from app.services.report_scheduler import start_scheduler
    from app.services.system_updates import is_maintenance

    # The replacement container starts before the host completes verification.
    # Do not run scheduled business writes until that maintenance window ends.
    while is_maintenance():
        time.sleep(2)
    sched = start_scheduler()
    logger.info("独立调度器已启动（daily/weekly/issue_sla）")
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("独立调度器退出")
        sched.shutdown(wait=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    main()
