"""Offline runner regressions: temporary repositories and a fake Docker boundary."""
import hashlib
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("update_runner", Path(__file__).with_name("update-runner.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def archive(path, extras=(), version="9.1.0"):
    with tarfile.open(path, "w:gz") as tar:
        for name, body in [("repository/frontend/package.json", json.dumps({"version": version}).encode()),
                           ("repository/docker/Dockerfile", b"FROM scratch\n"),
                           ("repository/docker/update-protocol.json", b'{"application":"xingxu-workbench","protocol":1}')]:
            member = tarfile.TarInfo(name); member.size = len(body)
            tar.addfile(member, io.BytesIO(body))
        for member, body in extras:
            tar.addfile(member, io.BytesIO(body))


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.package = self.root / "source.tar.gz"

    def test_accepts_one_repository_and_verifies_version(self):
        archive(self.package)
        source = runner.extract_source(self.package, self.root / "staging", "9.1.0")
        self.assertEqual(json.loads((source / "frontend/package.json").read_text())["version"], "9.1.0")
        self.assertEqual(source.stat().st_mode & 0o777, 0o700)

    def test_rejects_unsafe_paths_and_duplicate_or_nonregular_entries(self):
        cases = [("/escape", tarfile.REGTYPE), ("repository/../escape", tarfile.REGTYPE),
                 ("repository/a\\b", tarfile.REGTYPE), ("other/escape", tarfile.REGTYPE),
                 ("repository/frontend/package.json", tarfile.REGTYPE),
                 ("repository/link", tarfile.SYMTYPE), ("repository/link", tarfile.LNKTYPE),
                 ("repository/device", tarfile.CHRTYPE), ("repository/pipe", tarfile.FIFOTYPE)]
        for index, (name, kind) in enumerate(cases):
            with self.subTest(name=name, kind=kind):
                member = tarfile.TarInfo(name); member.type = kind; member.linkname = "/etc/passwd"
                archive(self.package, [(member, b"")])
                with self.assertRaises(runner.UpdateError):
                    runner.extract_source(self.package, self.root / f"stage-{index}", "9.1.0")
        self.assertFalse((self.root / "escape").exists())

    def test_rejects_size_count_bombs_and_wrong_version(self):
        archive(self.package)
        for kwargs in ({"max_bytes": 4}, {"max_files": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(runner.UpdateError):
                runner.extract_source(self.package, self.root / str(len(kwargs)) / str(kwargs), "9.1.0", **kwargs)
        with self.assertRaises(runner.UpdateError):
            runner.extract_source(self.package, self.root / "wrong-version", "9.2.0")

    def test_limits_compressed_extension_metadata_before_tarfile_allocates_it(self):
        with tarfile.open(self.package, "w:gz", format=tarfile.PAX_FORMAT) as package:
            member = tarfile.TarInfo("repository/file"); member.pax_headers = {"comment": "x" * (1024 * 1024 + 1)}
            package.addfile(member, io.BytesIO())
        with self.assertRaisesRegex(runner.UpdateError, "元数据"):
            runner.extract_source(self.package, self.root / "pax", "9.1.0")
        with gzip.open(self.package, "wb") as stream: stream.write(b"\0" * 100000)
        with self.assertRaisesRegex(runner.UpdateError, "解压数据"):
            runner.extract_source(self.package, self.root / "gzip", "9.1.0", max_bytes=1024, max_files=1)

    def test_boolean_protocol_is_not_compatible_with_integer_protocol_one(self):
        with tarfile.open(self.package, "w:gz") as package:
            for name, raw in [("repository/frontend/package.json", b'{"version":"9.1.0"}'),
                              ("repository/docker/Dockerfile", b"FROM scratch"),
                              ("repository/docker/update-protocol.json", b'{"application":"xingxu-workbench","protocol":true}')]:
                member = tarfile.TarInfo(name); member.size = len(raw); package.addfile(member, io.BytesIO(raw))
        with self.assertRaises(runner.UpdateError):
            runner.extract_source(self.package, self.root / "boolean-protocol", "9.1.0")


class FakeDocker:
    def __init__(self, root, package):
        self.root = root; self.package = package; self.actions = []; self.claimed = False
        self.labels = {"com.docker.compose.project": "owned-project", "com.docker.compose.service": "agv-pm"}
        self.mount = {"Type": "bind", "Source": str(root / "data"), "Destination": "/app/data", "RW": True}
        self.job = {"id": "a" * 32, "status": "downloading", "phase": "downloading", "target_version": "9.1.0", "target_commit": "b" * 40}
        self.job.update(check_id="00000000-0000-0000-0000-000000000001", source_id="default-gitea", source_revision=1,
                        repository_url="https://git.example.com/team/workbench", ref="main")
        self.candidate = {**self.job, "commit": self.job["target_commit"], "version": self.job["target_version"]}
        self.wrong_hash = False
        self.refuse_phase = None
        self.crash_after_terminal = False
        self.calls = []
        self.extra_mounts = []
        self.services = {"agv-pm": {"container_name": "fixture-app", "image": "${AGV_IMAGE}",
                                   "environment": {"APP_VERSION": "${APP_VERSION}", "GIT_SHA": "${GIT_SHA}"},
                                   "volumes": [{"type": "bind", "source": str(root / "data"), "target": "/app/data"}]}}

    def call(self, args, *, payload=None, timeout=60):
        self.calls.append(args)
        if args[0] == "inspect":
            return json.dumps([{"Id": "fixture-container", "Image": "sha256:old", "Config": {"Labels": self.labels}, "Mounts": [self.mount, *self.extra_mounts]}])
        if args[0] == "compose":
            return json.dumps({"name": "owned-project", "services": self.services})
        if args[0] == "cp":
            Path(args[-1]).write_bytes(self.package.read_bytes()); return ""
        if args[:2] == ["exec", "-i"]:
            action = payload["action"]; self.actions.append(dict(payload))
            if action == "heartbeat": return json.dumps({"ok": True})
            if action == "trust-request": return json.dumps({"candidate": self.candidate})
            if action == "trust-credentials": return json.dumps({"token": "test-only-repository-token"})
            if action == "trust-result": self.candidate = None; return json.dumps({"ok": True})
            if action == "claim":
                if self.claimed: return json.dumps({"job": None})
                self.claimed = True; return json.dumps({"job": self.job})
            if action == "prepare":
                return json.dumps({"archive_path": "/app/data/system-updates/packages/" + self.job["id"] + ".tar.gz", "sha256": "0" * 64 if self.wrong_hash else hashlib.sha256(self.package.read_bytes()).hexdigest(), "bytes": self.package.stat().st_size})
            if action == "report":
                if payload["status"] == self.refuse_phase: raise runner.UpdateError("fixture report unavailable")
                if self.crash_after_terminal and payload["status"] == "succeeded":
                    self.crash_after_terminal = False
                    raise SystemExit("fixture crash after remote terminal commit")
                return json.dumps({"job": {**self.job, "status": payload["status"]}})
        raise AssertionError(args)


class FixtureVerifier(runner.TRUST.Verifier):
    """Isolate existing Docker/phase tests; real Git/signature tests live separately."""
    def __init__(self, work, package):
        super().__init__(Path(work) / "trust.json", work)
        self.package = package
    def configured(self): return True
    def entry(self, candidate): return runner.TRUST.candidate_identity(candidate), {}, "c" * 64
    def assert_policy(self, digest):
        if digest != "c" * 64: raise runner.TRUST.TrustError("policy_changed")
    @contextmanager
    def verified(self, candidate, token=""):
        self.entry(candidate)
        yield None, None, {"method": "commit", "policy_digest": "c" * 64, "tree": "d" * 40}
    def export(self, repo, env, commit, destination):
        destination.write_bytes(self.package.read_bytes()); destination.chmod(0o600)



class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); scripts = self.root / "docker/scripts"; scripts.mkdir(parents=True)
        (self.root / "docker/docker-compose.yml").write_text("services: {}\n")
        (self.root / "installed.env").write_text("UNCHANGED=1\n")
        self.script = scripts / "manage.sh"
        self.script.write_text(self.phases("building", "backing_up", "installing", "verifying", "succeeded"))
        self.package = self.root / "source.tar.gz"; archive(self.package)
        self.docker = FakeDocker(self.root, self.package)

    @staticmethod
    def phases(*phases):
        return "#!/bin/bash\n" + "".join(
            f'printf "AGV_UPDATE_PHASE={phase}\\n" >&"$AGV_UPDATE_EVENT_FD"\n'
            'IFS= read -r ack && [ "$ack" = continue ] || exit 1\n'
            for phase in phases
        )

    def instance(self):
        app = runner.UpdateRunner(self.root, "standard", "fixture-app", self.root / "installed.env", self.root / "work", docker=self.docker)
        app.verifier = FixtureVerifier(app.work, self.package)
        return app

    def test_runs_fixed_source_without_changing_installed_workspace_or_leaking_logs(self):
        self.script.write_text(self.script.read_text() + "printf '%s' PRIVATE_TEST_LOG >&2\n")
        app = self.instance(); app.run_once()
        reports = [a for a in self.docker.actions if a["action"] == "report"]
        self.assertEqual(reports[-1]["status"], "succeeded")
        self.assertNotIn("PRIVATE_TEST_LOG", json.dumps(reports))
        self.assertEqual((self.root / "installed.env").read_text(), "UNCHANGED=1\n")
        self.assertEqual((self.root / "work").stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in (self.root / "work").rglob("*.log")))

    def test_rejects_unmanaged_or_mismatched_volume_before_claiming(self):
        for change in ("labels", "mount"):
            with self.subTest(change=change):
                docker = FakeDocker(self.root, self.package)
                if change == "labels": docker.labels = {}
                else: docker.mount["Source"] = "/unrelated-data"
                app = runner.UpdateRunner(self.root, "standard", "fixture-app", self.root / "installed.env", self.root / ("work-" + change), docker=docker)
                with self.assertRaises(runner.UpdateError): app.run_once()
                self.assertFalse(any(a["action"] == "claim" for a in docker.actions))

    def test_app_supplied_archive_hash_cannot_override_verified_host_git_content(self):
        self.docker.wrong_hash = True
        app = self.instance(); app.run_once()
        reports = [a for a in self.docker.actions if a["action"] == "report"]
        self.assertEqual(reports[-1]["status"], "succeeded")
        self.assertNotIn("prepare", [a["action"] for a in self.docker.actions])

    def test_interrupted_job_is_not_reclaimed_or_reinstalled(self):
        app = self.instance()
        app.write_journal({"job_id": "a" * 32, "status": "installing", "terminal": False})
        app.run_once()
        self.assertFalse(any(a["action"] == "claim" for a in self.docker.actions))
        self.assertEqual(self.docker.actions[-1]["status"], "needs_attention")

    def test_failed_restore_stays_needs_attention_not_rolled_back(self):
        self.script.write_text(self.phases("building", "installing", "needs_attention") + "exit 1\n")
        self.instance().run_once()
        self.assertEqual([a for a in self.docker.actions if a["action"] == "report"][-1]["status"], "needs_attention")

    def test_maintenance_report_must_be_acknowledged_before_script_can_continue(self):
        self.docker.refuse_phase = "backing_up"
        self.script.write_text(self.phases("building", "backing_up") + 'touch "$AGV_BUILD_CONTEXT/must-not-install"\n')
        self.instance().run_once()
        self.assertFalse(list((self.root / "work").rglob("must-not-install")))
        self.assertEqual(self.docker.actions[-1]["status"], "failed")

    def test_build_output_cannot_forge_phase_or_success(self):
        self.script.write_text(self.phases("building") + "printf 'AGV_UPDATE_PHASE=succeeded\\n'\nexit 1\n")
        self.instance().run_once()
        self.assertEqual(self.docker.actions[-1]["status"], "failed")
        self.assertNotIn("succeeded", [a.get("status") for a in self.docker.actions])

    def test_terminal_event_does_not_publish_success_before_process_exits(self):
        self.script.write_text(self.phases("building", "installing", "succeeded") + "exit 1\n")
        self.instance().run_once()
        self.assertEqual(self.docker.actions[-1]["status"], "needs_attention")

    def test_unavailable_new_bridge_still_allows_recovery(self):
        self.docker.refuse_phase = "verifying"
        self.script.write_text(self.phases("building", "backing_up", "installing", "verifying", "rolled_back") + "exit 1\n")
        self.instance().run_once()
        self.assertEqual(self.docker.actions[-1]["status"], "rolled_back")

    def test_committed_terminal_response_loss_replays_same_result_after_restart(self):
        self.docker.crash_after_terminal = True
        with self.assertRaises(SystemExit): self.instance().run_once()
        saved = json.loads((self.root / "work/active-job.json").read_text())
        self.assertTrue(saved["outcome_ready"])
        before = len([a for a in self.docker.actions if a["action"] == "claim"])
        self.instance().run_once()
        self.assertEqual(self.docker.actions[-1]["status"], "succeeded")
        self.assertEqual(before, len([a for a in self.docker.actions if a["action"] == "claim"]))

    def test_claimed_active_job_without_host_journal_is_not_reinstalled(self):
        self.docker.job["status"] = "installing"
        self.instance().run_once()
        self.assertEqual(self.docker.actions[-1]["status"], "needs_attention")
        self.assertNotIn("prepare", [a["action"] for a in self.docker.actions])

    def test_semver_accepts_prerelease_and_build_but_rejects_noncanonical_numbers(self):
        for version in ("2.4.0", "2.4.0-rc.1+build.12", "2.4.0+build.12"):
            self.assertIsNotNone(runner.SEMVER.fullmatch(version))
        for version in ("02.4.0", "2.4.0-01", "2.4.0-rc..1", "2.4.0+", "2.4.0-", "2.4"):
            self.assertIsNone(runner.SEMVER.fullmatch(version))

    def custom_instance(self):
        installed = self.root / "trusted installation.json"
        installed.write_text("{}")
        self.docker.labels["com.docker.compose.project.config_files"] = str(installed)
        app = runner.UpdateRunner(self.root, "standard", "fixture-app", self.root / "installed.env",
                                  self.root / "work", compose_file=installed, docker=self.docker)
        app.verifier = FixtureVerifier(app.work, self.package)
        return app

    def test_custom_installation_is_explicit_and_cannot_inherit_compose_override(self):
        app = self.custom_instance()
        self.script.write_text('''#!/bin/bash
test "$AGV_INSTALLED_COMPOSE_FILE" = "$EXPECTED_INSTALLATION" || exit 2
test -z "${AGV_COMPOSE_FILE:-}${COMPOSE_FILE:-}${COMPOSE_PROFILES:-}${FAULT_COMPOSE_UP:-}" || exit 3
''' + self.phases("building", "backing_up", "installing", "verifying", "succeeded"))
        with patch.dict(os.environ, {"EXPECTED_INSTALLATION": str(app.compose_file), "AGV_INSTALLED_COMPOSE_FILE": "/untrusted/installation",
                                     "AGV_COMPOSE_FILE": "/untrusted/override", "COMPOSE_FILE": "/untrusted/other",
                                     "COMPOSE_PROFILES": "unrelated", "FAULT_COMPOSE_UP": "1"}):
            app.run_once()
        self.assertEqual(self.docker.actions[-1]["status"], "succeeded")
        self.assertTrue(all(call[call.index("-f") + 1] == str(app.compose_file) for call in self.docker.calls if call[0] == "compose"))

    def test_custom_installation_rejects_wrong_labels_floating_settings_or_other_services(self):
        for problem in ("labels", "image", "version", "commit", "other-service", "read-only"):
            with self.subTest(problem=problem):
                self.docker = FakeDocker(self.root, self.package)
                app = self.custom_instance()
                service = self.docker.services["agv-pm"]
                if problem == "labels": self.docker.labels["com.docker.compose.project.config_files"] = "/different/compose.json"
                elif problem == "image": service["image"] = "fixed:old"
                elif problem == "version": service["environment"]["APP_VERSION"] = "1.0.0"
                elif problem == "commit": service["environment"]["GIT_SHA"] = "old-commit"
                elif problem == "other-service": self.docker.services["unrelated"] = {}
                else: service["volumes"][0]["read_only"] = True
                with self.assertRaises(runner.UpdateError): app.run_once()
                self.assertFalse(self.docker.actions)


class TrustGateRunnerTests(unittest.TestCase):
    """Real runner/state/phase barriers; crypto independently uses real Git tests."""
    setUp = RunnerTests.setUp
    instance = RunnerTests.instance
    phases = staticmethod(RunnerTests.phases)
    def test_old_check_without_host_receipt_never_starts_a_deployment(self):
        self.docker.candidate = None
        self.instance().run_once()
        self.assertEqual(self.docker.actions[-1]["status"], "failed")
        self.assertEqual(self.docker.actions[-1]["reason"], "receipt_invalid")
        self.assertNotIn("installing", [row.get("status") for row in self.docker.actions])
        self.assertFalse(list((self.root / "work").rglob("deployment.log")))

    def test_job_target_or_source_changes_cannot_reuse_a_host_check(self):
        for field, value in [("target_commit", "e" * 40), ("target_version", "9.2.0"),
                             ("repository_url", "https://evil.example/team/workbench"), ("ref", "other"),
                             ("source_id", "other"), ("source_revision", 2),
                             ("check_id", "00000000-0000-0000-0000-000000000002")]:
            with self.subTest(field=field):
                self.docker = FakeDocker(self.root, self.package)
                self.docker.job[field] = value
                app = runner.UpdateRunner(self.root, "standard", "fixture-app", self.root / "installed.env",
                                          self.root / ("work-" + field), docker=self.docker)
                app.verifier = FixtureVerifier(app.work, self.package)
                app.run_once()
                self.assertEqual(self.docker.actions[-1]["status"], "failed")
                self.assertNotIn("installing", [row.get("status") for row in self.docker.actions])

    def test_consumed_host_check_cannot_be_replayed_as_a_new_job(self):
        app = self.instance(); app.run_once()
        self.assertEqual(self.docker.actions[-1]["status"], "succeeded")
        self.docker.claimed = False; self.docker.job["id"] = "e" * 32
        app.run_once()
        self.assertEqual(self.docker.actions[-1]["status"], "failed")
        self.assertEqual(self.docker.actions[-1]["reason"], "receipt_invalid")

    def test_expired_private_receipt_never_reaches_install(self):
        app = self.instance(); app.process_check()
        path = next((app.work / "trust-checks").glob("*.json"))
        receipt = json.loads(path.read_text()); receipt["verified_at"] = 1; path.write_text(json.dumps(receipt))
        app.run_once()
        self.assertEqual(self.docker.actions[-1]["status"], "failed")
        self.assertEqual(self.docker.actions[-1]["reason"], "receipt_invalid")

    def test_policy_revoked_after_check_fails_before_building(self):
        app = self.instance(); app.process_check()
        app.verifier.assert_policy = lambda _: (_ for _ in ()).throw(runner.TRUST.TrustError("policy_changed"))
        app.run_once()
        self.assertEqual(self.docker.actions[-1]["status"], "failed")
        self.assertEqual(self.docker.actions[-1]["reason"], "policy_changed")
        self.assertFalse(list(app.work.rglob("deployment.log")))

    def test_source_changed_after_verification_fails_before_process_starts(self):
        app = self.instance(); deploy = app.run_deploy
        def mutate(job, source, directory):
            (source / "Dockerfile-injected").write_text("untrusted mutation")
            return deploy(job, source, directory)
        app.run_deploy = mutate
        app.run_once()
        self.assertEqual(self.docker.actions[-1]["status"], "failed")
        self.assertEqual(self.docker.actions[-1]["reason"], "content_changed")
        self.assertFalse(list(app.work.rglob("deployment.log")))

    def test_policy_revocation_during_build_stops_before_backup_or_switch(self):
        app = self.instance(); report = app.report
        def revoke_on_build(job_id, status, reason=None):
            result = report(job_id, status, reason)
            if status == "building":
                app.verifier.assert_policy = lambda _: (_ for _ in ()).throw(runner.TRUST.TrustError("policy_changed"))
            return result
        app.report = revoke_on_build
        app.run_once()
        self.assertEqual(self.docker.actions[-1]["status"], "failed")
        self.assertEqual(self.docker.actions[-1]["reason"], "policy_changed")
        self.assertNotIn("backing_up", [row.get("status") for row in self.docker.actions])
        self.assertNotIn("installing", [row.get("status") for row in self.docker.actions])

    def test_even_a_read_only_docker_socket_mount_breaks_the_host_trust_boundary(self):
        self.docker.extra_mounts = [{"Type": "bind", "Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock", "RW": False}]
        with self.assertRaisesRegex(runner.UpdateError, "socket"):
            self.instance().run_once()
        self.assertEqual(self.docker.actions, [])

    def test_web_writable_host_receipts_or_installed_scripts_are_rejected(self):
        for path in (self.root / "work", self.root / "work/trust-checks", self.script.parent):
            with self.subTest(path=path):
                self.docker = FakeDocker(self.root, self.package)
                self.docker.extra_mounts = [{"Type": "bind", "Source": str(path), "Destination": "/host-writable", "RW": True}]
                with self.assertRaises(runner.UpdateError):
                    self.instance().run_once()
                self.assertEqual(self.docker.actions, [])


if __name__ == "__main__":
    unittest.main()
