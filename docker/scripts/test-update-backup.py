"""Exercise actual embedded backup/restore code using temporary local data only."""
import os
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parent


class UpdateBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name); self.data = self.root / "data"; self.data.mkdir()
        self.work = self.root / "restore-work"; self.work.mkdir()
        (self.data / "system-updates").mkdir(); (self.data / "system-updates/state.json").write_text('{"job":"must-not-replay"}')
        (self.data / "secret.key").write_text("fixture-key")

    def backup(self):
        connection = sqlite3.connect(self.data / "agvpm.db")
        connection.execute("CREATE TABLE IF NOT EXISTS fixture(id INTEGER)"); connection.commit(); connection.close()
        code = SCRIPTS / "backup_runtime.py"
        password = self.root / "password"
        password.write_text("test-only-backup-password-2026"); password.chmod(0o600)
        env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
        return subprocess.run([sys.executable, str(code), "create", "--data-dir", str(self.data),
                               "--passphrase-file", str(password), "--output", str(self.root / "fixture.agvenc")],
                              env=env, capture_output=True, text=True)

    def plaintext(self):
        sys.path.insert(0, str(SCRIPTS.parents[1] / "backend"))
        from app.services.backup_crypto import decrypted_file
        return decrypted_file(self.root / "fixture.agvenc", "test-only-backup-password-2026")

    def restore_files(self, maintenance=False):
        if maintenance: (self.data / "update-maintenance.json").write_text("{}")
        code = (SCRIPTS / "restore.sh").read_text().split("RESTORE_MUTATION_STARTED=1\n", 1)[1]
        code = code.split("sh -c '\n", 1)[1].split("\n  ' sh", 1)[0]
        code = code.replace("/app/data", str(self.data)).replace('work="$1"', "work=" + repr(str(self.work)))
        return subprocess.run(["bash", "-c", code], capture_output=True, text=True)

    def test_configuration_is_private_and_tasks_are_not_backed_up(self):
        (self.data / "system-update-config.json").write_text('{"encrypted_token":"fixture-ciphertext"}')
        result = self.backup(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("fixture-ciphertext", result.stdout + result.stderr)
        with self.plaintext() as plaintext, tarfile.open(plaintext) as archive:
            self.assertIn("system-update-config.json", archive.getnames())
            self.assertEqual(archive.getmember("system-update-config.json").mode, 0o600)
            self.assertFalse(any(n.startswith("system-updates") for n in archive.getnames()))

    def test_nonregular_config_is_rejected(self):
        for kind in ("symlink", "fifo", "directory"):
            with self.subTest(kind=kind):
                config = self.data / "system-update-config.json"
                if kind == "symlink": config.symlink_to(self.data / "secret.key")
                elif kind == "fifo": os.mkfifo(config)
                else: config.mkdir()
                result = self.backup(); self.assertNotEqual(result.returncode, 0)
                if config.is_dir(): config.rmdir()
                else: config.unlink()

    def test_multiple_sources_and_active_selection_survive_backup_restore(self):
        config = {
            "schema_version": 2,
            "id": "secondary", "name": "备用源", "is_default": False,
            "repository_url": "https://git.example.com/team/secondary",
            "ref": "stable", "allow_http": False, "revision": 8,
            "token_encrypted": "secondary-ciphertext",
            "active_source_id": "secondary",
            "sources": [
                {"id": "default-gitea", "name": "我的 Gitea", "is_default": True,
                 "repository_url": "https://git.example.com/team/default", "ref": "main",
                 "allow_http": False, "token_encrypted": "default-ciphertext"},
                {"id": "secondary", "name": "备用源", "is_default": False,
                 "repository_url": "https://git.example.com/team/secondary", "ref": "stable",
                 "allow_http": False, "token_encrypted": "secondary-ciphertext"},
            ],
        }
        path = self.data / "system-update-config.json"
        path.write_text(json.dumps(config, ensure_ascii=False))
        result = self.backup(); self.assertEqual(result.returncode, 0, result.stderr)
        with self.plaintext() as plaintext, tarfile.open(plaintext) as archive:
            archived = archive.extractfile("system-update-config.json").read()
            self.assertEqual(json.loads(archived), config)
            (self.work / "system-update-config.json").write_bytes(archived)
        path.unlink()
        result = self.restore_files(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(path.read_text()), config)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.data / "system-updates/state.json").exists())

    def test_pg_restore_copies_private_config_and_invalidates_old_queue(self):
        (self.work / "system-update-config.json").write_text('{"encrypted_token":"restored"}')
        result = self.restore_files(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.data / "system-update-config.json").stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.data / "system-updates/state.json").exists())

    def test_legacy_restore_removes_config_but_rollback_preserves_active_job(self):
        (self.data / "system-update-config.json").write_text('{"encrypted_token":"old-key"}')
        result = self.restore_files(maintenance=True); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.data / "system-update-config.json").exists())
        self.assertTrue((self.data / "system-updates/state.json").exists())

    def test_restore_does_not_follow_existing_config_symlink(self):
        outside = self.root / "outside"; outside.write_text("untouched")
        (self.data / "system-update-config.json").symlink_to(outside)
        (self.work / "system-update-config.json").write_text("{}")
        self.assertNotEqual(self.restore_files().returncode, 0)
        self.assertEqual(outside.read_text(), "untouched")

    def test_restore_does_not_follow_existing_secret_symlink(self):
        outside = self.root / "outside-key"; outside.write_text("untouched")
        (self.data / "secret.key").unlink()
        (self.data / "secret.key").symlink_to(outside)
        (self.work / "secret.key").write_text("restored-application-key")
        self.assertNotEqual(self.restore_files().returncode, 0)
        self.assertEqual(outside.read_text(), "untouched")


if __name__ == "__main__":
    unittest.main()
