#!/usr/bin/env python3
"""Test archive streaming in an isolated read-only container with tmpfs mounts."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile
import uuid


HELPER = Path(__file__).with_name("update-common.sh").resolve()


def command(args, *, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if check and result.returncode:
        raise AssertionError(result.stderr[-4000:])
    return result


def verify(base_image):
    container = "agv-archive-transfer-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="agv-transfer-") as temporary:
        archive = Path(temporary) / "backup.tar.gz"
        archive.write_bytes(b"controlled-backup-fixture\n" * 65536)
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()

        def receive(target, expected=checksum, check=True):
            return command(["bash", "-c", '. "$1"; CONTAINER="$2"; update_stream_archive "$3" "$4" "$5"',
                            "transfer-test", str(HELPER), container, str(archive), target, expected], check=check)

        def inspect(target):
            command(["docker", "exec", container, "python", "-c", """
import hashlib, pathlib, sys
p = pathlib.Path(sys.argv[1])
assert hashlib.sha256(p.read_bytes()).hexdigest() == sys.argv[2]
assert p.stat().st_mode & 0o777 == 0o600
assert not list(p.parent.glob('.archive-*.tmp'))
""", target, checksum])

        try:
            command(["docker", "run", "-d", "--name", container, "--network", "none", "--read-only",
                     "--tmpfs", "/tmp:rw,size=16m,mode=1777", "--tmpfs", "/app/data:rw,size=16m,mode=0700",
                     "--entrypoint", "sleep", base_image, "300"])
            control = command(["docker", "cp", str(archive), container + ":/tmp/control.tar.gz"], check=False)
            assert control.returncode != 0 and "read-only" in control.stderr.lower(), "docker cp control did not reproduce read-only-root rejection"
            for target in ("/tmp/restore-backup.tar.gz", "/app/data/restore-pending.tar.gz"):
                receive(target)
                inspect(target)
            assert receive("/tmp/restore-backup.tar.gz", "0" * 64, check=False).returncode != 0
            inspect("/tmp/restore-backup.tar.gz")
            command(["docker", "exec", container, "python", "-c",
                     "from pathlib import Path; Path('/tmp/victim').write_text('unchanged'); Path('/tmp/link').symlink_to('/tmp/victim')"])
            assert receive("/tmp/link", check=False).returncode != 0
            command(["docker", "exec", container, "python", "-c",
                     "from pathlib import Path; assert Path('/tmp/victim').read_text() == 'unchanged'; assert Path('/tmp/link').is_symlink(); assert not list(Path('/tmp').glob('.archive-*.tmp'))"])
            print("readonly rootfs: docker cp rejection reproduced; exec streaming into tmpfs and staged data passed")
            print("checksum mismatch preserved existing file; symlink refused; both published files 0600; no partial files")
        finally:
            command(["docker", "rm", "-f", container], check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-image", required=True)
    verify(parser.parse_args().base_image)
