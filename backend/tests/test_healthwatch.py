"""健康看门狗（O2：unhealthy 自愈）状态机单测。

decide() 为纯逻辑，不含副作用；supervisorctl 调用由 main() 主循环触发，此处不覆盖。
"""

from app.services import healthwatch as hw


def _wd(clock, **kw):
    return hw.HealthWatchdog(now=lambda: clock["t"], **kw)


def test_startup_grace_ignores_failures():
    """启动宽限期且从未成功过：失败不累计、不动作。"""
    clock = {"t": 100.0}
    wd = _wd(clock, fail_threshold=3, web_restart_limit=2, start_grace=90)
    for _ in range(6):
        assert wd.decide(False) == ""
    assert wd.consecutive_failures == 0
    assert wd.web_restarts == 0


def test_grace_expiry_allows_action():
    """超过宽限期仍未成功：连续失败达阈值后触发 web 重启。"""
    clock = {"t": 100.0}
    wd = _wd(clock, fail_threshold=3, web_restart_limit=2, start_grace=90)
    for _ in range(5):
        assert wd.decide(False) == ""
    clock["t"] = 200.0
    assert wd.decide(False) == ""
    assert wd.decide(False) == ""
    assert wd.decide(False) == "restart_web"


def test_ever_healthy_triggers_web_restart():
    """应用成功过一次后：连续失败达阈值立即触发 web 重启（与宽限期无关）。"""
    clock = {"t": 100.0}
    wd = _wd(clock, fail_threshold=3, web_restart_limit=2, start_grace=3600)
    assert wd.decide(True) == ""
    assert wd.decide(False) == ""
    assert wd.decide(False) == ""
    assert wd.decide(False) == "restart_web"
    assert wd.web_restarts == 1


def test_web_restart_escalates_to_shutdown():
    """web 重启达上限仍未恢复 → 关停容器（shutdown）。"""
    clock = {"t": 100.0}
    wd = _wd(clock, fail_threshold=3, web_restart_limit=2, start_grace=3600)
    assert wd.decide(True) == ""  # ever_healthy
    # 第 1 轮 3 连败 → restart_web
    assert wd.decide(False) == ""
    assert wd.decide(False) == ""
    assert wd.decide(False) == "restart_web"
    assert wd.web_restarts == 1
    # 第 2 轮 3 连败 → restart_web
    assert wd.decide(False) == ""
    assert wd.decide(False) == ""
    assert wd.decide(False) == "restart_web"
    assert wd.web_restarts == 2
    # 第 3 轮 3 连败 → shutdown
    assert wd.decide(False) == ""
    assert wd.decide(False) == ""
    assert wd.decide(False) == "shutdown"


def test_recovery_resets_state():
    """恢复健康后计数清零，失败窗口从头开始。"""
    clock = {"t": 100.0}
    wd = _wd(clock, fail_threshold=3, web_restart_limit=2, start_grace=3600)
    assert wd.decide(True) == ""
    assert wd.decide(False) == ""
    assert wd.decide(False) == ""
    assert wd.decide(False) == "restart_web"
    assert wd.decide(True) == ""  # 恢复
    assert wd.consecutive_failures == 0
    assert wd.web_restarts == 0
    # 新的失败窗口从头计数
    assert wd.decide(False) == ""
    assert wd.decide(False) == ""
    assert wd.decide(False) == "restart_web"
    assert wd.web_restarts == 1
