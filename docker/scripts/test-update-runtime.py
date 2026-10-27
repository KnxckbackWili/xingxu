"""Verify persistent runtime settings without a Docker daemon or real secrets."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location("persist_runtime", Path(__file__).with_name("persist-update-runtime.py"))
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = self.root / "installed.env"
        self.original = b"# exact prior configuration\r\nAGV_IMAGE=old:1.0.0\r\nPRIVATE='one$\\two\nAPP_VERSION=secret-content'"
        self.env.write_bytes(self.original)
        self.inspected = {"Image": "sha256:" + "a" * 64,
                          "Config": {"Env": ["APP_VERSION=2.4.2", "GIT_SHA=" + "b" * 40, "PRIVATE=unprinted"]}}

    def test_appends_immutable_verified_identity_preserving_all_original_bytes(self):
        runtime.persist(self.env, self.inspected)
        value = self.env.read_bytes()
        self.assertTrue(value.startswith(self.original + b"\n"))
        self.assertTrue(value.endswith(("AGV_IMAGE=sha256:" + "a" * 64 + "\nAPP_VERSION=2.4.2\nGIT_SHA=" + "b" * 40 + "\n").encode()))
        self.assertNotIn(b"unprinted", value)
        self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.root.glob(".runtime-*")))

    def test_rollback_pin_becomes_last_assignment_and_keeps_configuration(self):
        runtime.persist(self.env, self.inspected)
        self.inspected["Image"] = "sha256:" + "c" * 64
        self.inspected["Config"]["Env"] = ["APP_VERSION=2.4.1", "GIT_SHA=" + "d" * 40]
        runtime.persist(self.env, self.inspected)
        self.assertTrue(self.env.read_bytes().startswith(self.original))
        values = dict(line.split("=", 1) for line in self.env.read_text().splitlines() if "=" in line)
        self.assertEqual(values["AGV_IMAGE"], "sha256:" + "c" * 64)
        self.assertEqual(values["APP_VERSION"], "2.4.1")
        self.assertEqual(values["GIT_SHA"], "d" * 40)

    def test_bad_metadata_never_changes_installation(self):
        for value in ("bad\nINJECTED=1", "unknown$variable", ""):
            with self.subTest(value=value):
                self.inspected["Config"]["Env"] = ["APP_VERSION=2.4.2", "GIT_SHA=" + value]
                with self.assertRaises(ValueError):
                    runtime.persist(self.env, self.inspected)
                self.assertEqual(self.env.read_bytes(), self.original)

    def test_symlink_is_rejected_without_replacing_target(self):
        alias = self.root / "alias.env"
        alias.symlink_to(self.env)
        with self.assertRaises(ValueError):
            runtime.persist(alias, self.inspected)
        self.assertEqual(self.env.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
