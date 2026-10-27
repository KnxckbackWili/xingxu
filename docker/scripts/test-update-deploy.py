"""Run the installed deployment Bash against fake Docker, never a real daemon."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, shutil, sys
from pathlib import Path
args = sys.argv[1:]; root = Path(os.environ["QA_UPDATE_ROOT"])
scenario = os.environ["QA_UPDATE_CASE"]; statefile = root / "state.json"
state = json.loads(statefile.read_text())
def event(name, **details):
    with (root / "events.jsonl").open("a") as output:
        output.write(json.dumps({"event": name, **details}) + "\n")
def save(): statefile.write_text(json.dumps(state))
if args[0] == "inspect":
    if "--format" not in args and "-f" not in args: print("[]"); sys.exit(0)
    fmt = args[args.index("--format") + 1] if "--format" in args else args[args.index("-f") + 1]
    if fmt == "{{.Image}}": print("sha256:original")
    elif fmt == "{{.Config.Image}}": print(os.environ.get("QA_UPDATE_OLD_REF", "original:1.0.0"))
    elif ".State.Health" in fmt:
        print("dead" if (state["image"] == "new" and scenario == "health_fail") or state.get("restore_failed") else "healthy")
    elif ".State.Running" in fmt: print("true")
    elif fmt == "{{json .}}":
        new = state["image"] == "new"
        print(json.dumps({"Image": "sha256:" + ("c" if new else "a") * 64, "Config": {"Env": [
            "APP_VERSION=" + ("9.1.0" if new else "1.0.0"),
            "GIT_SHA=" + ("bad\nsecret" if scenario == "persist_fail" else "b" * 40 if new else "d" * 40)]}}))
    elif ".Config.Env" in fmt: print("USE_POSTGRES=1")
    else: raise RuntimeError("Unexpected inspect")
    sys.exit(0)
if args[0] == "image" and args[1] == "inspect":
    if "{{json .Config.Env}}" in args:
        print(json.dumps(["APP_VERSION=" + os.environ["APP_VERSION"], "GIT_SHA=" + ("wrong" if scenario == "metadata_fail" else os.environ["GIT_SHA"])])); sys.exit(0)
    print("GIT_SHA=" + "d" * 40 + "\nAPP_VERSION=1.0.0"); sys.exit(0)
if args[0] == "run":
    assert "--network" in args and "none" in args and "--read-only" in args
    event("check_pg_major")
    print("18" if scenario == "pg_major_fail" else "17"); sys.exit(0)
if args[0] == "tag" or args[:2] == ["image", "tag"]:
    event("tag", image=args[-2], target=args[-1])
    if args[-1].startswith("sha256:") or "@sha256:" in args[-1]:
        sys.stderr.write("invalid docker tag destination\n"); sys.exit(1)
    sys.exit(0)
if args[0] == "logs": print("fixture log"); sys.exit(0)
if args[0] == "stop": state["services"] = "STOPPED"; save(); event("container_stop"); sys.exit(0)
if args[0] == "compose":
    contexts = []
    for index, arg in enumerate(args):
        if arg == "-f" and Path(args[index + 1]).name.startswith("agv-build-context."):
            contexts.append(json.loads(Path(args[index + 1]).read_text())["services"]["agv-pm"]["build"]["context"])
    if "build" in args:
        event("build", contexts=contexts, version=os.getenv("APP_VERSION"), commit=os.getenv("GIT_SHA"))
        sys.exit(9 if scenario == "build_fail" else 0)
    if "up" in args:
        rollback = "rollback-" in os.getenv("AGV_IMAGE", "") or os.getenv("AGV_IMAGE") == "original:1.0.0"
        event("rollback" if rollback else "activate", contexts=contexts, commit=os.getenv("GIT_SHA"))
        assert (root / "data/update-maintenance.json").exists()
        state["image"] = "old" if rollback else "new"; state["services"] = "RUNNING"
        if not rollback: (root / "data/value").write_text("migrated")
        pending = root / "data/restore-pending.tar.gz"
        if rollback and pending.exists():
            event("restore")
            if scenario == "restore_fail": state["restore_failed"] = True
            else: (root / "data/value").write_text("original"); pending.unlink()
        save()
        sys.exit(7 if not rollback and scenario in ("partial_fail", "restore_fail") else 0)
    raise RuntimeError("Unexpected compose")
if args[0] == "cp":
    sys.stderr.write("container rootfs is marked read-only\n"); sys.exit(15)
if args[0] != "exec": raise RuntimeError("Unexpected Docker command")
if "supervisorctl" in args:
    if "status" in args:
        if scenario == "stderr_warning": sys.stderr.write("UserWarning: pkg_resources is deprecated as an API.\n")
        names = args[args.index("status") + 1:]
        for name in names: print(name, "RUNNING" if name == "postgres" else state["services"])
        sys.exit(0 if state["services"] == "RUNNING" or names == ["postgres"] else 3)
    action = "stop" if "stop" in args else "start"
    event(action)
    if action == "stop": state["services"] = "STOPPED"
    elif scenario == "resume_fail": sys.exit(15)
    else: state["services"] = "RUNNING"
    save(); sys.exit(0)
if "pg_isready" in args: sys.exit(0)
if "python" in args and "-" in args:
    source = sys.stdin.read()
    assert "Trusted, config-independent backup codec" in source
    if args[args.index("-") + 1] == "apply":
        pending = root / "data/restore-pending.tar.gz"
        assert pending.read_bytes() == b"controlled full snapshot"
        if scenario == "restore_fail": sys.exit(10)
        (root / "data/value").write_text("original"); pending.unlink(); event("restore"); sys.exit(0)
    assert args[args.index("-") + 1] == "stage"
    sourcepath = Path(args[args.index("--input") + 1].replace("/app/data", str(root / "data")))
    target = Path(args[args.index("--output") + 1].replace("/app/data", str(root / "data")))
    assert sourcepath.read_bytes() == b"controlled full snapshot"
    target.write_bytes(sourcepath.read_bytes()); event("stage"); sys.exit(0)
if "python" in args and "-c" in args:
    source = args[args.index("-c") + 1]
    if "PG_VERSION" in source: print("17"); sys.exit(0)
    if "AGV_STREAM_ARCHIVE" in source:
        assert state["services"] == "STOPPED"
        sys.argv = ["receive", args[-2].replace("/app/data", str(root / "data")), args[-1]]
        exec(compile(source, "stream-fixture", "exec"), {})
        event("stage"); sys.exit(0)
    source = source.replace("/app/data", str(root / "data"))
    event("marker_create" if "os.O_EXCL" in source else "marker_clear")
    exec(compile(source, "maintenance-fixture", "exec"), {}); sys.exit(0)
if "test" in args:
    sys.exit(1 if (root / "data/restore-pending.tar.gz").exists() else 0)
raise RuntimeError("Unexpected exec")
'''

BACKUP = r'''#!/usr/bin/env python3
import hashlib, json, os
from pathlib import Path
root = Path(os.environ["QA_UPDATE_ROOT"])
assert json.loads((root / "state.json").read_text())["services"] == "STOPPED"
assert (root / "data/update-maintenance.json").exists()
with (root / "events.jsonl").open("a") as out: out.write('{"event":"backup"}\n')
if os.environ["QA_UPDATE_CASE"] in ("backup_fail", "resume_fail"): raise SystemExit(8)
path = Path(os.environ["BACKUP_DIR"]) / ("agv-pm-" + os.environ["AGV_BACKUP_STAMP"] + ".tar.gz.agvenc")
path.parent.mkdir(exist_ok=True); path.write_bytes(b"controlled full snapshot")
path.with_name(path.name + ".sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name)
'''

RESTORE = r'''#!/usr/bin/env python3
import json, os
from pathlib import Path
root = Path(os.environ["QA_UPDATE_ROOT"])
assert (root / "data/update-maintenance.json").exists()
with (root / "events.jsonl").open("a") as out: out.write('{"event":"restore"}\n')
if os.environ["QA_UPDATE_CASE"] == "restore_fail": raise SystemExit(10)
(root / "data/value").write_text("original")
'''


class DeployTests(unittest.TestCase):
    def run_case(self, mode, scenario, *, custom=False, old_ref=None):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name); scripts = root / "docker/scripts"; scripts.mkdir(parents=True)
        installed = Path(__file__).resolve().parent
        for name in ("deploy.sh", "manage.sh", "update-common.sh", "backup-rotation.sh", "persist-update-runtime.py", "backup_runtime.py"):
            shutil.copy2(installed / name, scripts / name)
        for name, content in (("backup.sh", BACKUP), ("restore.sh", RESTORE)):
            (scripts / name).write_text(content.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1)); (scripts / name).chmod(0o700)
        for name in ("docker-compose.yml", "docker-compose.multica.yml"):
            (root / "docker" / name).write_text("services: {}")
        (root / "frontend").mkdir(); (root / "frontend/package.json").write_text('{"version":"1.0.0"}')
        source = root / "source"; (source / "frontend").mkdir(parents=True); (source / "docker").mkdir()
        (source / "frontend/package.json").write_text('{"version":"9.1.0"}')
        (source / "docker/Dockerfile").write_text("FROM scratch")
        envfile = root / "installed.env"; envfile.write_text("APP_VERSION=1.0.0\nAGV_IMAGE=original:1.0.0\n")
        (root / "data").mkdir(); (root / "data/value").write_text("original")
        (root / "state.json").write_text(json.dumps({"image": "old", "services": "RUNNING"}))
        (root / "bin").mkdir(); docker = root / "bin/docker"
        docker.write_text(FAKE_DOCKER.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1)); docker.chmod(0o700)
        curl = root / "bin/curl"; curl.write_text("#!/bin/sh\necho fixture-health\n"); curl.chmod(0o700)
        env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
        env.update(PATH=str(root / "bin") + ":" + env.get("PATH", "/usr/bin:/bin"), QA_UPDATE_ROOT=str(root),
                   QA_UPDATE_CASE=scenario, AGV_BUILD_CONTEXT=str(source), AGV_ENV_FILE=str(envfile),
                   BACKUP_DIR=str(root / "backups"), APP_VERSION="9.1.0", GIT_SHA="b" * 40,
                   AGV_IMAGE="target:9.1.0", AGV_CONTAINER="fixture", AGV_CONTAINER_NAME="fixture")
        if custom:
            env["AGV_INSTALLED_COMPOSE_FILE"] = str(root / "trusted-installation.json")
            (root / "trusted-installation.json").write_text("{}")
            envfile.write_text(envfile.read_text() + "PRIVATE='dollar$quote\\value\nAPP_VERSION=inside-secret'\n")
        if old_ref:
            env["QA_UPDATE_OLD_REF"] = old_ref
        result = subprocess.run(["bash", str(scripts / ("deploy.sh" if mode == "multica" else "manage.sh")), "update"],
                                env=env, capture_output=True, text=True, timeout=15)
        events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
        if not custom:
            self.assertEqual(envfile.read_text(), "APP_VERSION=1.0.0\nAGV_IMAGE=original:1.0.0\n", result.stderr)
        build = next(e for e in events if e["event"] == "build")
        self.assertEqual(build["contexts"], [str(source.resolve())])
        self.assertEqual(build["version"], "9.1.0"); self.assertEqual(build["commit"], "b" * 40)
        return root, result, events

    def test_consistent_backup_window_and_success_for_both_modes(self):
        for mode in ("standard", "multica"):
            with self.subTest(mode=mode):
                root, result, events = self.run_case(mode, "success")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                names = [e["event"] for e in events]
                for first, second in (("build", "marker_create"), ("marker_create", "stop"), ("stop", "backup"), ("backup", "activate"), ("activate", "marker_clear")):
                    self.assertLess(names.index(first), names.index(second))
                self.assertFalse((root / "data/update-maintenance.json").exists())
                self.assertIn("AGV_UPDATE_PHASE=succeeded", result.stdout)

    def test_supervisor_stderr_warning_preserves_status_and_remains_in_log(self):
        for mode in ("standard", "multica"):
            with self.subTest(mode=mode):
                root, result, events = self.run_case(mode, "stderr_warning")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("pkg_resources is deprecated", result.stderr)
                self.assertIn("AGV_UPDATE_PHASE=succeeded", result.stdout)
                self.assertNotIn("container_stop", [e["event"] for e in events])
                self.assertFalse((root / "data/update-maintenance.json").exists())

    def test_partial_compose_failure_recovers_data_even_when_command_failed(self):
        for mode in ("standard", "multica"):
            for failure in ("partial_fail", "health_fail"):
                with self.subTest(mode=mode, failure=failure):
                    root, result, events = self.run_case(mode, failure)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual((root / "data/value").read_text(), "original", result.stdout + result.stderr)
                    self.assertIn("restore", [e["event"] for e in events])
                    self.assertIn("AGV_UPDATE_PHASE=rolled_back", result.stdout)
                    self.assertFalse((root / "data/update-maintenance.json").exists())
                    self.assertEqual(next(e for e in events if e["event"] == "rollback")["commit"], "d" * 40)

    def test_recovery_failure_stays_stopped_and_never_claims_rollback(self):
        for mode in ("standard", "multica"):
            with self.subTest(mode=mode):
                root, result, events = self.run_case(mode, "restore_fail")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads((root / "state.json").read_text())["services"], "STOPPED")
                self.assertTrue((root / "data/update-maintenance.json").exists())
                self.assertIn("AGV_UPDATE_PHASE=needs_attention", result.stdout)
                self.assertNotIn("AGV_UPDATE_PHASE=rolled_back", result.stdout)

    def test_build_or_backup_failure_does_not_replace_original_container(self):
        for mode in ("standard", "multica"):
            for failure in ("build_fail", "metadata_fail", "pg_major_fail", "backup_fail", "resume_fail"):
                with self.subTest(mode=mode, failure=failure):
                    root, result, events = self.run_case(mode, failure)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("activate", [e["event"] for e in events])
                    self.assertEqual((root / "data/value").read_text(), "original")
                    self.assertEqual((root / "data/update-maintenance.json").exists(), failure == "resume_fail")
                    expected = "needs_attention" if failure == "resume_fail" else "failed"
                    self.assertIn("AGV_UPDATE_PHASE=" + expected, result.stdout)

    def test_custom_installation_persists_verified_image_and_rollback_without_touching_secrets(self):
        for mode in ("standard", "multica"):
            for scenario in ("success", "partial_fail", "health_fail"):
                with self.subTest(mode=mode, scenario=scenario):
                    root, result, events = self.run_case(mode, scenario, custom=True)
                    updated = (root / "installed.env").read_text()
                    self.assertIn("PRIVATE='dollar$quote\\value\nAPP_VERSION=inside-secret'\n", updated)
                    values = dict(line.split("=", 1) for line in updated.splitlines() if "=" in line)
                    success = scenario == "success"
                    self.assertEqual(values["AGV_IMAGE"], "sha256:" + ("c" if success else "a") * 64, result.stdout + result.stderr)
                    self.assertEqual(values["APP_VERSION"], "9.1.0" if success else "1.0.0")
                    self.assertEqual(values["GIT_SHA"], ("b" if success else "d") * 40)
                    self.assertEqual((root / "installed.env").stat().st_mode & 0o777, 0o600)
                    self.assertFalse((root / "data/update-maintenance.json").exists())

    def test_persistence_failure_keeps_maintenance_and_stops_writes(self):
        for mode in ("standard", "multica"):
            with self.subTest(mode=mode):
                root, result, events = self.run_case(mode, "persist_fail", custom=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue((root / "data/update-maintenance.json").exists())
                self.assertEqual(json.loads((root / "state.json").read_text())["services"], "STOPPED")
                self.assertIn("AGV_UPDATE_PHASE=needs_attention", result.stdout)
                self.assertNotIn("AGV_UPDATE_PHASE=succeeded", result.stdout)

    def test_immutable_previous_image_recovers_data_and_persists_original_runtime(self):
        for mode in ("standard", "multica"):
            for old_ref in ("sha256:" + "a" * 64, "registry.example/app@sha256:" + "a" * 64):
                for scenario in ("partial_fail", "health_fail"):
                    with self.subTest(mode=mode, old_ref=old_ref, scenario=scenario):
                        root, result, events = self.run_case(mode, scenario, custom=True, old_ref=old_ref)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("AGV_UPDATE_PHASE=rolled_back", result.stdout, result.stdout + result.stderr)
                        self.assertEqual((root / "data/value").read_text(), "original")
                        self.assertFalse((root / "data/update-maintenance.json").exists())
                        self.assertTrue(all(e["target"] != old_ref for e in events if e["event"] == "tag"))
                        values = dict(line.split("=", 1) for line in (root / "installed.env").read_text().splitlines() if "=" in line)
                        self.assertEqual(values["AGV_IMAGE"], "sha256:" + "a" * 64)
                        self.assertEqual(values["APP_VERSION"], "1.0.0")
                        self.assertEqual(values["GIT_SHA"], "d" * 40)


if __name__ == "__main__":
    unittest.main()
