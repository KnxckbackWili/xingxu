"""Failure-injection CLI regression: real Bash, fake Docker, no live data."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import sqlite3
import tempfile


FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
root = Path(os.environ["QA_RESTORE_ROOT"])
scenario = os.environ["QA_RESTORE_SCENARIO"]
case = scenario.removeprefix("sqlite_")
maintenance = case.startswith("maintenance_") or case == "already_stopped"
unknown_original = case.startswith("unknown_original_")
mixed_original = case.startswith("mixed_original_")
for prefix in ("maintenance_", "unknown_original_", "mixed_original_"):
    case = case.removeprefix(prefix)
def event(name, **details):
    with (root / "events.jsonl").open("a") as output:
        output.write(json.dumps({"event": name, **details}) + "\n")
if args[0] == "inspect":
    event("inspect_fixture"); sys.exit(0)
if args[0] == "cp":
    sys.stderr.write("container rootfs is marked read-only\n"); sys.exit(15)
if args[0] != "exec":
    raise RuntimeError("Unexpected fake Docker command")
def mapped(value):
    return value.replace("/app/data", str(root / "data")).replace("/tmp/.restore-passphrase-", str(root / ".restore-passphrase-"))
if "-c" in args and "AGV_STREAM_ARCHIVE" in args[args.index("-c") + 1]:
    source = args[args.index("-c") + 1]
    event("stream_archive")
    sys.argv = ["receive", mapped(args[-2]), args[-1]]
    exec(compile(source, "stream-fixture", "exec"), {})
    sys.exit(0)
if "supervisorctl" in args:
    operation = "stop" if "stop" in args else "status" if "status" in args else "start"
    prior = [json.loads(line)["event"] for line in (root / "events.jsonl").read_text().splitlines()]
    original = "supervisor_stop" not in prior
    names = args[args.index(operation) + 1:]
    event("supervisor_" + operation, services=names)
    assert set(names) <= {"web", "scheduler", "healthwatch"} and names
    if operation != "start":
        assert names == ["web", "scheduler", "healthwatch"]
    if operation == "stop" and (case in ("stop_failure", "stop_incomplete") or maintenance):
        sys.exit(3 if maintenance else 12)
    if operation == "status":
        sys.stderr.write("UserWarning: pkg_resources is deprecated as an API.\n")
        if (case == "stop_failure" and not original) or (unknown_original and original):
            sys.stderr.write("QA supervisor connection unavailable\n"); sys.exit(20)
        for name in ("web", "scheduler", "healthwatch"):
            running = (original and not maintenance and (not mixed_original or name == "web")) or (not original and case == "stop_incomplete" and name == "web")
            state = "RUNNING" if running else "STOPPED"
            print(name + " " + state)
        # Supervisor status returns 3 for non-running processes, including STOPPED.
        sys.exit(0 if original and not maintenance and not mixed_original else 3)
    if operation == "start" and case == "start_failure":
        sys.exit(18)
    sys.exit(0)
if "python" in args and "-" in args:
    import subprocess
    source = sys.stdin.read()
    action = args[args.index("-") + 1]
    event("archive_validation" if action == "extract" else "pre_restore_dump" if action == "create" else "stage_request" if action == "stage" else "codec_" + action)
    if action == "create" and case == "snapshot_failure": sys.exit(11)
    if action == "stage" and case == "stage_failure": sys.exit(19)
    options = [mapped(value) for value in args[args.index("-") + 1:]]
    options += ["--data-dir", str(root / "data")]
    child = subprocess.run([sys.executable, "-c", source, *options])
    if not child.returncode and action == "stage": event("stage_request_complete")
    if not child.returncode and action == "apply": event("restore_apply_complete")
    sys.exit(child.returncode)
if "python" in args and "-c" in args:
    import subprocess
    source = args[args.index("-c") + 1]
    options = [mapped(value) for value in args[args.index("-c") + 2:]]
    source = mapped(source)
    child = subprocess.run([sys.executable, "-c", source, *options])
    sys.exit(child.returncode)
source = args[args.index("-c") + 1] if "-c" in args else args[-1]
if "dropdb" in source and "pg_restore" in source:
    event("destructive_database_restore")
    if case == "database_failure":
        event("injected_database_failure"); sys.exit(17)
    event("database_restore_complete"); sys.exit(0)
if "project-deletion-backups" in source:
    event("destructive_file_restore")
    if case == "file_failure":
        event("injected_file_failure"); sys.exit(16)
    sys.exit(0)
raise RuntimeError("Unexpected fake Docker exec branch")
'''


def run_case(root, repo, scenario):
    directory = root / scenario
    directory.mkdir(mode=0o700)
    (directory / "bin").mkdir(mode=0o700)
    executable = directory / "bin/docker"
    # Ensure the replacement uses this same 3.12+ interpreter, not a host default.
    executable.write_text(FAKE_DOCKER.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1))
    executable.chmod(0o700)
    data = directory / "data"; data.mkdir(mode=0o700); (data / "backups").mkdir(mode=0o700)
    archive = directory / "backup.tar.gz"
    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location("codec_fixture", repo / "docker/scripts/backup_runtime.py")
    codec = module_from_spec(spec); spec.loader.exec_module(codec)
    codec.set_passphrase(data, "test-only-backup-password-2026")
    with sqlite3.connect(data / "agvpm.db") as db:
        db.executescript("CREATE TABLE users(id,username,password_hash,role,is_active); CREATE TABLE projects(id,name); CREATE TABLE tasks(id,project_id,module_id,name);")
    for tool in ("pg_dump", "pg_restore"):
        executable = directory / "bin" / tool
        executable.write_text("#!" + sys.executable + "\nimport sys\nfrom pathlib import Path\n" +
            ("Path(sys.argv[sys.argv.index('-f')+1]).write_bytes(b'PGDMPcontrolled-current-fixture')\n" if tool == "pg_dump" else "raise SystemExit(0)\n"))
        executable.chmod(0o700)
    sqlite = scenario.startswith("sqlite_")
    case = scenario.removeprefix("sqlite_")
    maintenance = case.startswith("maintenance_")
    unknown_original = case.startswith("unknown_original_")
    mixed_original = case.startswith("mixed_original_")
    for prefix in ("maintenance_", "unknown_original_", "mixed_original_"):
        case = case.removeprefix(prefix)
    with tarfile.open(archive, "w:gz") as bundle:
        contents = [
            ("manifest.json", json.dumps({"type": "agvpm-system-backup", "database": "sqlite" if sqlite else "postgres"}).encode()),
            ("agvpm.db" if sqlite else "agvpm.dump", (data / "agvpm.db").read_bytes() if sqlite else b"PGDMPcontrolled-restore-fixture"),
        ]
        if case == "archive_failure":
            contents.append(("../forbidden", b"must-not-extract"))
        for name, content in contents:
            item = tarfile.TarInfo(name)
            item.size = len(content)
            item.mode = 0o600
            bundle.addfile(item, io.BytesIO(content))
    encrypted = directory / "backup.tar.gz.agvenc"
    codec.encrypt_file(archive, encrypted, "test-only-backup-password-2026")
    archive = encrypted
    if case == "wrong_password":
        codec.set_passphrase(data, "different-test-only-password")
    if case == "tampered_tag":
        payload = archive.read_bytes()
        archive.write_bytes(payload[:-1] + bytes([payload[-1] ^ 1]))
    archive.with_name(archive.name + ".sha256").write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n"
    )
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
    env.update(
        PATH=str(directory / "bin") + ":" + env.get("PATH", "/usr/bin:/bin"),
        AGV_CONTAINER="qa-restore-fake-never-real-docker",
        BACKUP_DIR=str(directory / "snapshots"),
        QA_RESTORE_ROOT=str(directory),
        QA_RESTORE_REPO=str(repo),
        QA_RESTORE_SCENARIO=scenario,
        DATABASE_URL="sqlite",
        USE_POSTGRES=("1" if sqlite else "0") if case == "target_mismatch" else "0" if sqlite else "1",
    )
    result = subprocess.run(
        ["/bin/bash", str(repo / "docker/scripts/restore.sh"), str(archive)],
        env=env, capture_output=True, text=True,
    )
    (directory / "output.log").write_text(result.stdout + result.stderr)
    records = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    events = [row["event"] for row in records]
    started_services = [name for row in records if row["event"] == "supervisor_start" for name in row["services"]]
    succeeded = "恢复完成：" in result.stdout
    submitted = "恢复请求已提交" in result.stdout
    failures = []
    if case not in {"archive_failure", "wrong_password", "tampered_tag", "target_mismatch"} and "pkg_resources is deprecated" not in result.stderr:
        failures.append("Supervisor stderr warnings must remain available in the private restore log")
    if case not in {"archive_failure", "wrong_password", "tampered_tag", "target_mismatch"} and events.count("supervisor_stop") != (2 if case == "start_failure" else 1):
        failures.append("Restore must stop all three application services exactly once")
    if case in {"wrong_password", "tampered_tag", "target_mismatch"}:
        if not result.returncode or succeeded or submitted:
            failures.append("Authentication/type rejection must return nonzero without success")
        if any(name in events for name in ("supervisor_stop", "supervisor_start", "pre_restore_dump", "destructive_file_restore", "destructive_database_restore", "stage_request")):
            failures.append("Failed authentication/type gate must not stop writers or touch live data")
    elif case in ("stop_failure", "stop_incomplete"):
        if not result.returncode or succeeded or submitted:
            failures.append("Unconfirmed stopped services must abort without reporting success")
        if any(name in events for name in ("pre_restore_dump", "destructive_file_restore", "destructive_database_restore", "stage_request")):
            failures.append("Unconfirmed stopped services must not start the recovery/data pipeline")
        if "supervisor_start" in events:
            failures.append("Unknown maintenance state must not automatically start application services")
        if "服务停止状态" not in result.stderr:
            failures.append("Operator must see the stop-state verification failure")
    elif case in ("snapshot_failure", "archive_failure"):
        if not result.returncode or succeeded:
            failures.append("Pre-destructive failure must return nonzero without reporting success")
        if "destructive_file_restore" in events or "destructive_database_restore" in events:
            failures.append("Pre-destructive failure must not change files or database")
        expected_services = [] if case == "archive_failure" or maintenance or unknown_original else ["web"] if mixed_original else ["web", "scheduler", "healthwatch"]
        if started_services != expected_services:
            failures.append("Only services confirmed RUNNING before this attempt may resume")
    elif case in ("file_failure", "database_failure"):
        expected = 16 if case == "file_failure" else 17
        if result.returncode != expected or succeeded:
            failures.append("Destructive failure must preserve its nonzero exit code and not report success")
        if "supervisor_start" in events:
            failures.append("Destructive failure must keep web, scheduler and healthwatch stopped")
        if "服务保持停止" not in result.stderr:
            failures.append("Operator must see the maintenance-state recovery instructions")
        if not list((directory / "snapshots").glob("agvpm-pre-restore-*.tar.gz.agvenc")):
            failures.append("Recovery snapshot must remain available after destructive failure")
    elif case == "stage_failure":
        if result.returncode != 19 or succeeded or submitted or "supervisor_start" in events:
            failures.append("Failed staging must return nonzero and keep application services stopped")
    elif case == "start_failure":
        if result.returncode != 18 or succeeded or submitted:
            failures.append("Service-start failure must return nonzero without reporting restore success")
        if events.count("supervisor_start") != 1:
            failures.append("Failed startup must not be retried by the EXIT trap")
        if events.index("supervisor_start") < events.index("restore_apply_complete" if sqlite else "database_restore_complete"):
            failures.append("Startup must still follow a completed database restore")
    else:
        if result.returncode != 0 or not succeeded or submitted:
            failures.append("Complete restore must return zero and report success")
        if events.count("supervisor_start") != 1:
            failures.append("Complete restore must start application services exactly once")
        elif events.index("supervisor_start") < events.index("restore_apply_complete" if sqlite else "database_restore_complete"):
            failures.append("Services must start only after database restore completes")
    return {"scenario": scenario, "exit_code": result.returncode, "events": events,
            "started_services": started_services, "success_message": succeeded,
            "staged_request_message": submitted, "failures": failures, "passed": not failures}


def main():
    if sys.version_info < (3, 12):
        raise SystemExit("This real archive-validation test requires Python 3.12+")
    os.umask(0o077)
    if len(sys.argv) > 2:
        raise SystemExit("Usage: test-restore-maintenance.sh [new-output-directory]")
    if len(sys.argv) == 2:
        root = Path(sys.argv[1]).resolve()
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
    else:
        root = Path(tempfile.mkdtemp(prefix="agv-restore-maintenance-"))
    repo = Path(__file__).resolve().parents[2]
    cases = [run_case(root, repo, scenario) for scenario in (
        "wrong_password", "tampered_tag", "target_mismatch", "sqlite_target_mismatch",
        "snapshot_failure", "archive_failure", "file_failure", "database_failure", "success", "start_failure",
        "stop_failure", "stop_incomplete", "already_stopped",
        "maintenance_snapshot_failure", "maintenance_archive_failure", "unknown_original_snapshot_failure", "mixed_original_snapshot_failure",
        "sqlite_stop_failure", "sqlite_stop_incomplete", "sqlite_start_failure", "sqlite_stage_failure", "sqlite_success",
    )]
    receipt = {"restore_script_sha256": hashlib.sha256((repo / "docker/scripts/restore.sh").read_bytes()).hexdigest(),
               "actual_docker_invoked": False, "actual_database_accessed": False,
               "cases": cases, "passed": all(case["passed"] for case in cases)}
    (root / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    for case in cases:
        print(("PASS" if case["passed"] else "FAIL") + " " + case["scenario"])
        for failure in case["failures"]:
            print("  " + failure)
    print("Evidence: " + str(root / "receipt.json"))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
