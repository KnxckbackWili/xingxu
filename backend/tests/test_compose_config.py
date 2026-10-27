"""docker-compose.multica.yml 通知配置闭环（HYPE-58 二返 REJECT 项）。

唯一 8002 验收部署路径（docker/docker-compose.multica.yml）必须透传通用 JSON 渠道
与出站投递参数，且默认值与 backend/app/config.py 完全一致——否则一键 compose 部署下
config.JSON_WEBHOOK_URL 恒为空，JSON webhook 实际不可用。本测试只读仓库文件，无副作用。
"""
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker" / "docker-compose.multica.yml"
CONFIG_FILE = REPO_ROOT / "backend" / "app" / "config.py"

# compose 必须透传的通知相关环境变量（键 -> 未设置时应落进容器的默认值）
EXPECTED_NOTIFY_ENV = {
    "JSON_WEBHOOK_URL": "",
    "JSON_WEBHOOK_TOKEN": "",
    "JSON_WEBHOOK_TOKEN_FILE": "",
    "NOTIFY_RETRY_MAX_ATTEMPTS": "3",
    "NOTIFY_RETRY_BASE_SECONDS": "60",
    "NOTIFY_DELIVERY_BATCH_SIZE": "50",
}


def _compose_env() -> list[str]:
    with open(COMPOSE_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["services"]["agv-pm"]["environment"]


def _compose_default(env: list[str], key: str) -> str:
    """取出 `${KEY:-default}` 形式透传行的 default 部分。"""
    prefix = f"{key}="
    line = next((ln for ln in env if ln.startswith(prefix)), None)
    assert line is not None, f"docker-compose.multica.yml 未透传环境变量 {key}"
    expr = line.split("=", 1)[1]
    assert expr.startswith("${") and ":-" in expr, f"{key} 应采用 ${{{key}:-default}} 透传写法"
    return expr.split(":-", 1)[1].rstrip("}")


def _config_getenv_default(key: str) -> str:
    """从 config.py 源码提取 os.getenv(key, "默认") 的默认值字符串。"""
    src = CONFIG_FILE.read_text(encoding="utf-8")
    m = re.search(rf'os\.getenv\(\s*"{re.escape(key)}"\s*,\s*"([^"]*)"\s*\)', src)
    assert m is not None, f"config.py 未通过 os.getenv 读取 {key}"
    return m.group(1)


def test_compose_passes_through_all_notify_env():
    env = _compose_env()
    for key in EXPECTED_NOTIFY_ENV:
        assert any(ln.startswith(f"{key}=") for ln in env), f"compose 缺少 {key} 透传"


def test_compose_defaults_match_config_py():
    env = _compose_env()
    # 直接 os.getenv 读取的变量：compose 默认值必须与 config.py 源码默认值一致
    for key in ("JSON_WEBHOOK_URL", "NOTIFY_RETRY_MAX_ATTEMPTS",
                "NOTIFY_RETRY_BASE_SECONDS", "NOTIFY_DELIVERY_BATCH_SIZE"):
        assert _compose_default(env, key) == _config_getenv_default(key), \
            f"{key} 的 compose 默认值与 config.py 不一致"
    # 密钥走 _load_notify_secret 双通道：env/文件均缺省时为空字符串
    for key in ("JSON_WEBHOOK_TOKEN", "JSON_WEBHOOK_TOKEN_FILE"):
        assert _compose_default(env, key) == ""


def test_compose_enables_scheduler_for_delivery():
    # 出站队列投递由独立 scheduler 进程承担（docs/notifications.md 要求 SCHEDULER_ENABLED=1）
    env = _compose_env()
    assert "SCHEDULER_ENABLED=1" in env, "compose 未开启 SCHEDULER_ENABLED=1，outbox 不会自动投递"


def test_env_example_lists_same_defaults():
    txt = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for key, default in EXPECTED_NOTIFY_ENV.items():
        assert f"{key}={default}" in txt, f".env.example 缺少或默认值不一致: {key}"


def test_docs_notifications_mentions_all_keys():
    txt = (REPO_ROOT / "docs" / "notifications.md").read_text(encoding="utf-8")
    for key in EXPECTED_NOTIFY_ENV:
        assert key in txt, f"docs/notifications.md 未说明 {key}"


# HYPE-99：浏览器会话改 HttpOnly Cookie 承载后，8002 compose 必须透传 COOKIE_SECURE /
# COOKIE_SAMESITE——NPM/nginx 终止 HTTPS 后容器内仍是 http，仅 FORCE_HTTPS=1 不会让
# Set-Cookie 带 Secure，https 页面下浏览器拒绝非 Secure 的 HttpOnly Cookie → 登录即 401。
# 默认值必须与 config.py 源码一致（本测试只读仓库文件，无副作用）。
EXPECTED_COOKIE_ENV = {
    "COOKIE_SECURE": "0",
    "COOKIE_SAMESITE": "lax",
}


def test_compose_passes_through_cookie_env():
    env = _compose_env()
    for key in EXPECTED_COOKIE_ENV:
        assert any(ln.startswith(f"{key}=") for ln in env), f"compose 缺少 {key} 透传"


def test_compose_cookie_defaults_match_config_py():
    env = _compose_env()
    for key in EXPECTED_COOKIE_ENV:
        assert _compose_default(env, key) == _config_getenv_default(key), \
            f"{key} 的 compose 默认值与 config.py 不一致"


def test_docker_env_example_lists_cookie_defaults():
    """8002 部署从 docker/.env.example 复制 docker/.env，示例文件需列同默认值。"""
    txt = (REPO_ROOT / "docker" / ".env.example").read_text(encoding="utf-8")
    for key, default in EXPECTED_COOKIE_ENV.items():
        assert f"{key}={default}" in txt, f"docker/.env.example 缺少或默认值不一致: {key}"
