"""容器内健康看门狗（O2：unhealthy 自愈）。

背景：`restart: unless-stopped` 只在容器进程退出时生效，`/health` 失败不会触发重启，
容器可能带病运行（服务可响应但已异常，或完全挂起）。可选方案权衡：
- autoheal sidecar：需要额外常驻容器 + 挂载 Docker socket，改变单容器部署形态；
- 宿主 watchdog：需要 NAS 上额外 systemd/cron，逻辑不在仓库内；
- 本方案：保持单容器形态，由 supervisord 托管轻量看门狗进程，周期性 GET /health——
    连续失败 HEALTH_FAIL_THRESHOLD 次 → supervisorctl restart web（快速恢复 web 挂起）；
    同一窗口内 web 重启达 HEALTH_WEB_RESTART_LIMIT 次仍未恢复 → supervisorctl shutdown
    （容器主进程退出 → Docker 按 restart: unless-stopped 重建容器，覆盖 PG/整体性故障）。

启动窗口：应用首次成功前 HEALTH_START_GRACE 秒内只观察不动作，避免 PG 初始化/迁移
阶段误判；应用成功过一次后（ever_healthy）立即进入正常自愈判断。

用法：python -m app.services.healthwatch（supervisord [program:healthwatch]）。
"""

import logging
import os
import subprocess
import time
import urllib.request

logger = logging.getLogger(__name__)

HEALTH_URL = os.getenv("HEALTH_CHECK_URL", "http://127.0.0.1:8000/health")
CHECK_INTERVAL = max(5, int(os.getenv("HEALTH_CHECK_INTERVAL", "15")))
FAIL_THRESHOLD = max(1, int(os.getenv("HEALTH_FAIL_THRESHOLD", "3")))
WEB_RESTART_LIMIT = max(1, int(os.getenv("HEALTH_WEB_RESTART_LIMIT", "2")))
START_GRACE = max(0, int(os.getenv("HEALTH_START_GRACE", "180")))
HTTP_TIMEOUT = 5
SUPERVISOR_CONF = os.getenv("SUPERVISOR_CONF", "/app/supervisord.conf")


class HealthWatchdog:
    """健康看门狗状态机。

    decide(healthy) 做单轮决策，返回动作：''（继续观察）/ 'restart_web' / 'shutdown'。
    纯逻辑可单测；动作副作用（supervisorctl）由调用方执行。
    """

    def __init__(self, fail_threshold: int = FAIL_THRESHOLD,
                 web_restart_limit: int = WEB_RESTART_LIMIT,
                 start_grace: int = START_GRACE,
                 now=time.monotonic) -> None:
        self.fail_threshold = fail_threshold
        self.web_restart_limit = web_restart_limit
        self.start_grace = start_grace
        self._now = now
        self.started = self._now()
        self.consecutive_failures = 0
        self.web_restarts = 0
        self.ever_healthy = False

    def decide(self, healthy: bool) -> str:
        if healthy:
            self.consecutive_failures = 0
            self.web_restarts = 0
            self.ever_healthy = True
            return ""
        # 启动窗口：应用尚未成功过且未超过宽限期 → 只观察，不累计。
        if not self.ever_healthy and self._now() - self.started < self.start_grace:
            return ""
        self.consecutive_failures += 1
        if self.consecutive_failures < self.fail_threshold:
            return ""
        self.consecutive_failures = 0
        self.web_restarts += 1
        if self.web_restarts > self.web_restart_limit:
            return "shutdown"
        return "restart_web"


def is_healthy(url: str = HEALTH_URL, timeout: int = HTTP_TIMEOUT) -> bool:
    """GET /health 是否 200。显式禁用代理，直连本容器 8000。"""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def supervisorctl(*args: str) -> bool:
    """执行 supervisorctl 子命令（restart web / shutdown 等），失败仅记日志。"""
    try:
        subprocess.run(
            ["supervisorctl", "-c", SUPERVISOR_CONF, *args],
            check=False, capture_output=True, text=True,
        )
        return True
    except Exception:
        logger.exception("supervisorctl %s 调用失败", " ".join(args))
        return False


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    wd = HealthWatchdog()
    logger.info(
        "健康看门狗启动 url=%s interval=%s fail_threshold=%s web_restart_limit=%s start_grace=%s",
        HEALTH_URL, CHECK_INTERVAL, FAIL_THRESHOLD, WEB_RESTART_LIMIT, START_GRACE,
    )
    while True:
        action = wd.decide(is_healthy())
        if action == "restart_web":
            logger.warning("/health 连续失败，重启 web 进程（第 %s 次）", wd.web_restarts)
            supervisorctl("restart", "web")
        elif action == "shutdown":
            logger.error("/health 持续失败且 web 多次重启未恢复，关停容器触发 restart: unless-stopped")
            supervisorctl("shutdown")
            return
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
