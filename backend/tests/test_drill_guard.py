"""演练隔离守卫（guard-drill.sh / drill.sh）的 fail-closed 回归测试。

背景（HYPE-19）：演练曾以 compose override 叠加到生产 compose（项目名 docker），
把生产容器 agv-pm-8002 重建为演练容器、端口与卷错配。本守卫对演练使用的
container / volume / port / compose project 逐一校验，命中生产标识即 FAIL-CLOSED
退出，且该过程不执行任何 docker 操作（守卫本身是纯 bash 静态校验）。
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "docker" / "scripts" / "guard-drill.sh"
DRILL = REPO_ROOT / "docker" / "scripts" / "drill.sh"
DRILL_COMPOSE = REPO_ROOT / "docker" / "docker-compose.drill.yml"

ISOLATED_ENV = {
    "AGV_DRILL_CONTAINER": "agv-pm-drill",
    "AGV_DRILL_VOLUME": "agvpm-drill-data",
    "AGV_DRILL_PORT": "8003",
    "AGV_DRILL_PROJECT": "agvpm-drill",
}


def run_guard(env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", str(GUARD)],
        env=full_env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def assert_fail_closed(proc: subprocess.CompletedProcess, label: str) -> None:
    assert proc.returncode != 0, f"守卫应拒绝，但返回了 {proc.returncode}:\n{proc.stdout}\n{proc.stderr}"
    assert "FAIL-CLOSED" in proc.stderr, proc.stderr
    assert label.lower() in proc.stderr.lower(), f"FAIL-CLOSED 信息应指明 {label}:\n{proc.stderr}"


# ---- 隔离标识应放行 ----

def test_guard_isolated_defaults_pass():
    proc = run_guard(ISOLATED_ENV)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "export AGV_DRILL_CONTAINER='agv-pm-drill'" in proc.stdout
    assert "export AGV_DRILL_PROJECT='agvpm-drill'" in proc.stdout


# ---- 生产标识应 FAIL-CLOSED ----

def test_guard_rejects_prod_container_name():
    proc = run_guard({**ISOLATED_ENV, "AGV_DRILL_CONTAINER": "agv-pm-8002"})
    assert_fail_closed(proc, "container")


def test_guard_rejects_prod_container_name_suffixed():
    proc = run_guard({**ISOLATED_ENV, "AGV_DRILL_CONTAINER": "agv-pm-8002-drill"})
    assert_fail_closed(proc, "container")


def test_guard_rejects_prod_volume_name():
    proc = run_guard({**ISOLATED_ENV, "AGV_DRILL_VOLUME": "agv-pm-multica-data"})
    assert_fail_closed(proc, "volume")


def test_guard_rejects_prod_volume_prefixed():
    proc = run_guard({**ISOLATED_ENV, "AGV_DRILL_VOLUME": "docker_agv-pm-multica-data"})
    assert_fail_closed(proc, "volume")


def test_guard_rejects_prod_port():
    proc = run_guard({**ISOLATED_ENV, "AGV_DRILL_PORT": "8002"})
    assert_fail_closed(proc, "port")


def test_guard_rejects_port_containing_prod():
    proc = run_guard({**ISOLATED_ENV, "AGV_DRILL_PORT": "18002"})
    assert_fail_closed(proc, "port")


def test_guard_rejects_non_numeric_port():
    proc = run_guard({**ISOLATED_ENV, "AGV_DRILL_PORT": "http"})
    assert_fail_closed(proc, "port")


@pytest.mark.parametrize("project", ["docker", "agv-pm"])
def test_guard_rejects_prod_compose_project(project):
    proc = run_guard({**ISOLATED_ENV, "AGV_DRILL_PROJECT": project})
    assert_fail_closed(proc, "project")


def test_guard_empty_container_falls_back_to_isolated_default():
    # 空值按 fail-safe 语义回退到隔离默认（agv-pm-drill），而不是失败——回退值是安全的。
    proc = run_guard({**ISOLATED_ENV, "AGV_DRILL_CONTAINER": ""})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "export AGV_DRILL_CONTAINER='agv-pm-drill'" in proc.stdout


# ---- 演练 compose 文件本身不得含生产标识 ----

def test_guard_drill_compose_has_no_prod_tokens():
    text = DRILL_COMPOSE.read_text()
    for token in ("agv-pm-8002", "agv-pm-multica-data", "8002:8000", "0.0.0.0:8002"):
        assert token not in text, f"演练 compose 不应引用生产标识: {token}"


def test_guard_rejects_poisoned_drill_compose(tmp_path):
    # 演练 compose 文件一旦出现生产卷名，守卫必须 fail-closed（防止后续改动把生产标识抄进来）。
    poisoned = tmp_path / "docker-compose.drill.yml"
    poisoned.write_text(DRILL_COMPOSE.read_text().replace("agvpm-drill-data", "agv-pm-multica-data"))
    proc = run_guard({**ISOLATED_ENV, "AGV_DRILL_COMPOSE": str(poisoned)})
    assert proc.returncode != 0
    assert "FAIL-CLOSED" in proc.stderr
    assert "compose" in proc.stderr.lower()


# ---- drill.sh 入口：命中生产标识时先于任何 docker 操作终止 ----

def test_drill_script_fail_closed_before_docker():
    """AGV_DRILL_CONTAINER=agv-pm-8002 时 drill.sh 必须立刻终止，绝不接触 docker。"""
    assert GUARD.exists(), "守卫脚本缺失，测试无法执行守卫路径"
    env = dict(os.environ)
    env.update({
        "AGV_DRILL_CONTAINER": "agv-pm-8002",
        "AGV_DRILL_VOLUME": "agvpm-drill-data",
        "AGV_DRILL_PORT": "8003",
        "AGV_DRILL_PROJECT": "agvpm-drill",
    })
    proc = subprocess.run(
        ["bash", str(DRILL), "backups/agv-pm-nonexistent.tar.gz"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode != 0, f"drill.sh 应在守卫处终止:\n{proc.stdout}\n{proc.stderr}"
    # 守卫自身的 FAIL-CLOSED 明细（container 命中）必须出现在 stderr，证明是守卫拦截而非文件缺失
    assert "container" in proc.stderr, f"守卫应拦截 container，实际 stderr:\n{proc.stderr}"
    assert "docker compose" not in proc.stdout  # 未走到任何编排步骤
