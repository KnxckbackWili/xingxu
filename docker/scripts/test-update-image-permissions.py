#!/usr/bin/env python3
"""Exercise private archive permissions as postgres in disposable local images.

Usage: python3 docker/scripts/test-update-image-permissions.py --base-image IMAGE
The base image must already exist locally and contain the application's runtime.
Uses the caller's Docker connection; never mounts application data or publishes
ports. Both temporary containers/images are removed, including on failure.
"""
import argparse
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import uuid


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("update_runner", Path(__file__).with_name("update-runner.py"))
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def docker(*args, check=True):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=180)
    if check and result.returncode:
        raise AssertionError(f"isolated Docker check failed ({args[0]}): {result.stderr[-4000:]}")
    return result


def verify(base_image):
    image_id = docker("image", "inspect", "--format", "{{.Id}}", base_image).stdout.strip()
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", image_id), "base must resolve to a local immutable image"
    dockerfile = (ROOT / "docker/Dockerfile").read_text()
    fixed_commands = re.findall(r"^RUN chmod .*pg-entry\.sh$", dockerfile, re.MULTILINE)
    assert len(fixed_commands) == 1
    identifier = uuid.uuid4().hex
    images = [f"agv-permissions-regression:{identifier}-{mode}" for mode in ("control", "fixed")]
    containers = [f"agv-permissions-{identifier}-{mode}" for mode in ("control", "fixed")]
    try:
        with tempfile.TemporaryDirectory(prefix="agv-update-permissions-") as temporary:
            root = Path(temporary)
            archive = root / "source.tar.gz"
            version = json.loads((ROOT / "frontend/package.json").read_text())["version"]
            with tarfile.open(archive, "w:gz") as package:
                for relative in ("frontend/package.json", "docker/Dockerfile", "docker/update-protocol.json",
                                 "docker/start.sh", "docker/pg-entry.sh", "docker/supervisord.conf"):
                    data = (ROOT / relative).read_bytes()
                    member = tarfile.TarInfo("repository/" + relative)
                    member.mode = 0o755 if relative.endswith(".sh") else 0o644
                    member.size = len(data)
                    package.addfile(member, io.BytesIO(data))
            source = RUNNER.extract_source(archive, root / "source", version)
            assert source.stat().st_mode & 0o777 == 0o700
            assert (source / "docker/pg-entry.sh").stat().st_mode & 0o777 == 0o700
            assert (source / "docker/supervisord.conf").stat().st_mode & 0o777 == 0o600
            context = root / "context"
            context.mkdir(mode=0o700)
            for filename in ("start.sh", "pg-entry.sh"):
                shutil.copy2(source / "docker" / filename, context / filename)
            prefix = (f"FROM {image_id}\nCOPY start.sh /app/start.sh\nCOPY pg-entry.sh /app/pg-entry.sh\n"
                      "RUN chmod 0700 /app/start.sh /app/pg-entry.sh\n")
            for index, command in enumerate(("RUN chmod +x /app/start.sh /app/pg-entry.sh", fixed_commands[0])):
                (context / "Dockerfile").write_text(prefix + command + "\n")
                docker("build", "--network", "none", "--pull=false", "-t", images[index], str(context))

            common = ["run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,size=16m,mode=1777",
                      "--user", "postgres", "-e", "USE_POSTGRES=0"]
            control = docker(*common, "--name", containers[0], "--entrypoint", "/app/pg-entry.sh", images[0], check=False)
            assert control.returncode != 0 and "Permission denied" in control.stderr, "control did not reproduce unreadable shell entry"
            # Actually open all entries and execute pg-entry as postgres. This
            # detects the missing read bit that executable-bit checks miss.
            verification = """import os, pathlib, subprocess
for directory in ('/app',):
    assert os.access(directory, os.X_OK), directory
for name in ('/app/start.sh', '/app/pg-entry.sh'):
    path = pathlib.Path(name)
    assert path.stat().st_mode & 0o777 == 0o755, name
    assert os.access(path, os.X_OK), name
    with path.open('rb') as stream: assert stream.read(1), name
subprocess.run(['/app/pg-entry.sh'], check=True)
print('private archive: non-root read and PostgreSQL shell entry execution passed')
"""
            fixed = docker(*common, "--name", containers[1], "--entrypoint", "python", images[1], "-c", verification)
            print(fixed.stdout.strip())
            print("control: chmod +x reproduced Permission denied; fixed Dockerfile: both entries are readable/executable 0755")
    finally:
        for container in containers:
            docker("rm", "-f", container, check=False)
        for image in images:
            docker("image", "rm", image, check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-image", required=True)
    verify(parser.parse_args().base_image)
