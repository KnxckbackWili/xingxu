"""Pure verification guards. Run with unittest, never pytest on backup clones."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from copy import deepcopy

SCRIPT = Path(__file__).resolve().parents[1] / "verify_v3_migration.py"
spec = importlib.util.spec_from_file_location("verify_v3_migration", SCRIPT)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class MigrationVerificationGuards(unittest.TestCase):
    def archive(self, root, entries):
        path = root / "backup.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, value, kind in entries:
                item = tarfile.TarInfo(name)
                item.type = kind
                item.size = len(value) if kind == tarfile.REGTYPE else 0
                item.linkname = "../outside"
                archive.addfile(item, io.BytesIO(value) if kind == tarfile.REGTYPE else None)
        return path

    def test_rejects_traversal_links_duplicate_members_and_devices(self):
        cases = [[("../outside", b"x", tarfile.REGTYPE)],
                 [("uploads/link", b"", tarfile.SYMTYPE)],
                 [("uploads/link", b"", tarfile.LNKTYPE)],
                 [("uploads/a", b"1", tarfile.REGTYPE), ("uploads/a", b"2", tarfile.REGTYPE)],
                 [("uploads/device", b"", tarfile.CHRTYPE)]]
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / "data"
                target.mkdir()
                with self.assertRaises(verify.VerificationError):
                    verify.extract_backup(self.archive(root, entries), target)
                self.assertFalse((root / "outside").exists())

    def test_extracts_private_regular_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "data"
            target.mkdir()
            backup = self.archive(root, [("manifest.json", json.dumps({"type": "agvpm-system-backup"}).encode(), tarfile.REGTYPE),
                                         ("secret.key", b"test-installation-key", tarfile.REGTYPE),
                                         ("uploads/a", b"abc", tarfile.REGTYPE)])
            verify.extract_backup(backup, target)
            self.assertEqual((target / "uploads/a").read_bytes(), b"abc")
            self.assertEqual((target / "uploads/a").stat().st_mode & 0o777, 0o600)

    def test_rejected_existing_work_directory_is_never_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            sentinel = root / "sentinel"
            sentinel.write_bytes(b"unchanged")
            result = subprocess.run([sys.executable, str(SCRIPT), "--backup", str(root / "does-not-exist"),
                                     "--work-dir", str(root)], capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"WORK_DIRECTORY_MUST_BE_NEW", result.stdout)
            self.assertEqual(list(root.iterdir()), [sentinel])
            self.assertEqual(sentinel.read_bytes(), b"unchanged")
            self.assertNotIn(str(root).encode(), result.stdout + result.stderr)

    def test_work_directory_cannot_be_inside_git(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / ".git").mkdir()
            with self.assertRaises(verify.VerificationError):
                verify.new_private_directory(root / "new")
            self.assertFalse((root / "new").exists())

    def test_unknown_field_mutation_or_row_loss_fails(self):
        before = {"projects": [{"id": "p", "name": "customer", "status": "draft"}]}
        _, failures = verify.verify_fields(before, {"projects": [{"id": "p", "name": "changed", "status": "preparing"}]}, {})
        self.assertEqual(len(failures), 2)
        _, failures = verify.verify_fields(before, {}, {})
        self.assertEqual(failures[0]["kind"], "unpreserved_row")
        self.assertNotIn("customer", json.dumps(failures))

    def test_g01_unknown_added_business_fact_fails(self):
        additions, failures = verify.t01_additions({"projects": [{"id": "p"}]},
            {"projects": [{"id": "p"}], "daily_progress": [{"id": "fabricated", "completed_quantity": 1}]})
        self.assertEqual(len(additions), 1)
        self.assertEqual(failures[0]["kind"], "t01_unexplained_added_row")

    def test_g01_known_definition_cannot_claim_historical_completion(self):
        from migrations.v243_data import DEFAULT_ITEMS
        category, name, required = DEFAULT_ITEMS[0]
        row = {"id": "seed", "project_id": "p", "category": category, "item_name": name,
               "is_required": required, "sort_order": 0, "is_done": False}
        _, failures = verify.t01_additions({"projects": [{"id": "p"}]}, {"archive_checklists": [row]})
        self.assertFalse(failures)
        _, failures = verify.t01_additions({"projects": [{"id": "p"}]}, {"archive_checklists": [{**row, "is_done": True}]})
        self.assertEqual(failures[0]["kind"], "t01_unexplained_added_row")

    def test_g01_unknown_field_change_and_false_hours_reset_fail(self):
        _, failures = verify.t01_dispositions({"projects": [{"id": "p", "name": "old"}]}, {"projects": [{"id": "p", "name": "changed"}]}, False)
        self.assertEqual(failures[0]["kind"], "t01_unexplained_field_change")
        before = {"tasks": [{"id": "t", "project_id": None, "standard_hours": 5}]}
        after = {"tasks": [{"id": "t", "project_id": None, "standard_hours": None}]}
        self.assertFalse(verify.t01_dispositions(before, after, True, 0)[1])
        self.assertTrue(verify.t01_dispositions(before, after, True, 2)[1])

    def test_existing_same_named_template_module_keeps_its_own_identity(self):
        rows = [{"id": "custom", "name": "自动充电", "project_id": None, "phase_id": "custom-phase"},
                {"id": "mod-15", "name": "自动充电", "project_id": None, "phase_id": "other-phase"}]
        changes, failures = verify.t01_dispositions({"modules": rows}, {"modules": rows}, False)
        self.assertFalse(changes)
        self.assertFalse(failures)

    def test_final_acceptance_requires_all_pinned_conditions(self):
        args = SimpleNamespace(final_head=None, expected_sha256=None, fresh_backup_attested=False)
        self.assertFalse(verify.final_acceptance(args, "2.4.2", "head", True))
        args.final_head = "head"
        with self.assertRaises(verify.VerificationError):
            verify.final_acceptance(args, "2.4.3", "head", True)
        args.expected_sha256 = "known-sha"
        args.fresh_backup_attested = True
        with self.assertRaises(verify.VerificationError):
            verify.final_acceptance(args, "2.4.2", "head", True)
        with self.assertRaises(verify.VerificationError):
            verify.final_acceptance(args, "2.4.3", "other-head", True)
        self.assertFalse(verify.final_acceptance(args, "2.4.3", "head", False))
        self.assertTrue(verify.final_acceptance(args, "2.4.3", "head", True))

    def test_unknown_status_text_is_never_printed(self):
        self.assertEqual(verify.status_counts([{"status": "PRIVATE-CUSTOMER"}, {"status": "preparing"}]),
                         {"unknown_redacted": 1, "preparing": 1})

    def test_encrypted_retirement_requires_exact_original_row(self):
        row = {"id": "demo", "name": "original", "status": "executing"}
        destinations, failures = verify.verify_fields({"projects": [row]}, {}, {"projects": [dict(row)]})
        self.assertFalse(failures)
        self.assertEqual(destinations[0]["destination"], "t03_encrypted_owner_export")
        _, failures = verify.verify_fields({"projects": [row]}, {}, {"projects": [{**row, "name": "changed"}]})
        self.assertEqual(failures[0]["kind"], "unpreserved_row")

    def test_missing_snapshot_key_cannot_claim_preservation_of_null(self):
        before = {"tasks": [{"id": "t", "manual_completed_by": None}]}
        after = {"tasks": [{"id": "t", "manual_completed_by": "invented-actor", "legacy_work_snapshot": {}}]}
        _, failures = verify.verify_fields(before, after, {})
        self.assertEqual(failures[0]["kind"], "unexplained_field_change")

    def test_duplicate_named_deliverables_need_distinct_exact_source_positions(self):
        old = [{"name": "same", "done": True}, {"name": "same", "done": False}]
        task = {"id": "t", "deliverables": old}
        rules = [{"source_metadata": {"kind": "task_deliverable", "task": {"id": "t"}, "index": i, "original": v}}
                 for i, v in enumerate(old)]
        _, failures = verify.verify_fields({"tasks": [task]}, {"tasks": [{**task, "deliverables": []}], "document_requirements": rules}, {})
        self.assertFalse(failures)
        _, failures = verify.verify_fields({"tasks": [task]}, {"tasks": [{**task, "deliverables": []}], "document_requirements": rules[:1]}, {})
        self.assertTrue(failures)

    def test_quantity_credit_never_invents_vehicle_identity_or_date(self):
        task = {"id": "t", "project_id": "p", "module_id": "m", "name": "work", "quantity_type": "per_vehicle",
                "target_quantity": 3, "manually_completed": False, "unit": "台", "applicable_vehicle_types": []}
        before = {"tasks": [task], "modules": [{"id": "m", "phase_id": "ph"}], "phases": [{"id": "ph", "name": "现场"}],
                  "daily_progress": [{"task_id": "t", "completed_quantity": 2}]}
        metadata = {"task_id": "t", "task_name": "work", "target_quantity": 3, "completed_quantity": 2.0,
                    "rounded_target": 3, "rounded_completed": 2, "quantity_unknown": False, "unit": "台", "applicable_vehicle_types": [],
                    "target_rounding_difference": 0.0, "completion_rounding_difference": 0.0, "manually_completed": False,
                    "identity": "unknown", "date": "unknown"}
        credit = {"project_id": "p", "step_key": "legacy_t", "total_count": 2, "unassigned_count": 2, "source_metadata": metadata}
        after = {"projects": [{"id": "p"}], "vehicle_progress_migrations": [credit]}
        rows, failures = verify.vehicle_dispositions(before, after)
        self.assertFalse(failures)
        self.assertEqual(rows[0]["unassigned_count"], 2)
        credit["source_metadata"]["identity"] = "guessed-car"
        self.assertTrue(verify.vehicle_dispositions(before, after)[1])

    def t34_fixture(self):
        keys = 'id name description quantity_type target_quantity unit standard_hours sort_order safety_flag source_task_id source_vehicle_event_id manually_completed manual_completed_by manual_completed_role manual_completed_at manual_completed_reason depends_on applicable_vehicle_types manual_check_overrides'.split()
        task = {k: None for k in keys}
        task.update(id='t', name='work', project_id='p', module_id='m', quantity_type='fixed', target_quantity=1,
                    manually_completed=False, manual_completed_reason='', depends_on=None, applicable_vehicle_types=[])
        module = {'id': 'm', 'name': 'group', 'phase_id': 'ph', 'category': None, 'source_module_id': None, 'preparation_conditions': []}
        phase = {'id': 'ph', 'name': '现场', 'project_id': 'p'}
        before = {'tasks': [task], 'modules': [module], 'phases': [phase], 'daily_progress': [{'task_id': 't', 'completed_quantity': 1}]}
        reason = '迁移：原报工达到原目标且质量条件满足'
        source = {'kind': 't34_legacy_work', 'task': {k: task.get(k) for k in keys},
                  'module': {k: module.get(k) for k in ('id', 'name', 'category', 'phase_id', 'source_module_id')},
                  'phase': dict(phase), 'completed_quantity': 1, 'report_count': 1, 'scope_conditions': []}
        now = {**task, 'phase_id': 'ph', 'group_label': 'group', 'scope_conditions': [], 'legacy_work_snapshot': source,
               'manually_completed': True, 'manual_completed_reason': reason}
        audit = {'id': 'a', 'project_id': 'p', 'entity_type': 'task', 'entity_id': 't', 'action': 'migrate_work', 'operator_id': None,
                 'created_at': '2026-01-01T00:00:00', 'detail': reason, 'old_value': {'manually_completed': False},
                 'new_value': {'manually_completed': True, 'basis': 'legacy_verified_quantity', 'identity': 'unknown', 'date': 'unknown'}}
        return before, {'tasks': [now], 'phases': [phase], 'change_logs': [audit]}

    def test_t34_snapshot_and_real_quantity_quality_audit_all_required(self):
        before, after = self.t34_fixture()
        records, failures, verified = verify.verify_t34(before, after, True)
        self.assertFalse(failures)
        self.assertTrue(records[0]['effective_completion_converted'])
        self.assertIn(('tasks', 't', 'manually_completed'), verified)
        for mutation in ('not_enough_quantity', 'safety_pending', 'missing_audit', 'invented_actor'):
            with self.subTest(mutation=mutation):
                old, new = deepcopy(before), deepcopy(after)
                if mutation == 'not_enough_quantity':
                    old['daily_progress'][0]['completed_quantity'] = 0
                    new['tasks'][0]['legacy_work_snapshot']['completed_quantity'] = 0
                elif mutation == 'safety_pending':
                    old['check_items'] = [{'task_id': 't', 'is_safety_critical': True, 'is_applicable': True, 'is_done': False}]
                elif mutation == 'missing_audit':
                    new['change_logs'] = []
                else:
                    new['tasks'][0]['manual_completed_by'] = 'invented'
                _, errors, allowed = verify.verify_t34(old, new, True)
                self.assertTrue(errors)
                self.assertFalse(allowed)

    def test_t34_missing_null_and_changed_original_module_are_rejected(self):
        for mutation in ('missing_null', 'null_to_list', 'module_source_changed', 'boolean_count'):
            with self.subTest(mutation=mutation):
                before, after = self.t34_fixture()
                source = after['tasks'][0]['legacy_work_snapshot']
                if mutation == 'missing_null':
                    del source['task']['manual_completed_at']
                elif mutation == 'null_to_list':
                    source['task']['depends_on'] = []
                elif mutation == 'module_source_changed':
                    source['module']['phase_id'] = 'guessed'
                else:
                    source['report_count'] = True
                _, errors, allowed = verify.verify_t34(before, after, True)
                self.assertTrue(errors)
                self.assertFalse(allowed)

    def test_t34_existing_manual_fact_keeps_original_actor_time_without_migration_claim(self):
        before, after = self.t34_fixture()
        manual = {'manually_completed': True, 'manual_completed_by': 'old-user', 'manual_completed_role': 'pm',
                  'manual_completed_at': '2026-01-01T01:02:03', 'manual_completed_reason': 'old reason'}
        before['tasks'][0].update(manual)
        after['tasks'][0].update(manual)
        after['tasks'][0]['legacy_work_snapshot']['task'].update(manual)
        after['change_logs'] = []
        records, errors, allowed = verify.verify_t34(before, after, True)
        self.assertFalse(errors)
        self.assertFalse(records[0]['effective_completion_converted'])
        self.assertFalse(allowed)

    def test_attachment_metadata_sha_cannot_mask_missing_or_wrong_bytes(self):
        old = {"attachments": [{"id": "a", "stored_name": "file", "file_size": 3}]}
        proof = {"file": {"sha256": "expected", "size": 3}}
        now = {"attachments": [{**old["attachments"][0], "sha256": "expected"}]}
        self.assertFalse(verify.attachment_integrity(old, now, proof, proof))
        self.assertTrue(verify.attachment_integrity(old, now, proof, {}))
        self.assertTrue(verify.attachment_integrity(old, now, proof, {"file": {"sha256": "wrong", "size": 3}}))

    def test_new_document_fact_without_real_legacy_source_is_rejected(self):
        after = {'project_documents': [{'id': 'fake-doc', 'instance_key': 'invented'}],
                 'project_document_definitions': [{'id': 'fake-rule', 'source_key': 'invented'}]}
        _, _, failures = verify.document_dispositions({}, after)
        self.assertEqual({r['kind'] for r in failures},
                         {'unexplained_migrated_document', 'unexplained_migrated_document_definition'})

    def test_full_sqlite_fixture_runs_real_chain_and_preserves_unknown_car_and_old_done(self):
        import sqlalchemy as sa
        from migrations.v243_schema import metadata
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            source.mkdir()
            (source / "uploads").mkdir()
            (source / "uploads/file.bin").write_bytes(b"real fixture evidence")
            (source / "secret.key").write_text("fixture-installation-key-do-not-print")
            (source / "manifest.json").write_text(json.dumps({"type": "agvpm-system-backup", "database": "sqlite", "app_version": "2.4.3"}))
            engine = sa.create_engine("sqlite:///" + str(source / "agvpm.db"))
            metadata.create_all(engine)
            with engine.begin() as connection:
                t = metadata.tables
                connection.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
                connection.execute(sa.text("INSERT INTO alembic_version VALUES ('d2e7f9a103b4')"))
                connection.execute(t["users"].insert().values(id="u", username="PRIVATE-USER-NO-LOG", password_hash="PRIVATE-HASH-NO-LOG", display_name="PRIVATE-NAME-NO-LOG"))
                connection.execute(t["projects"].insert().values(id="p", name="PRIVATE-CUSTOMER-NO-LOG", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status="commissioning", created_by="u"))
                connection.execute(t["phases"].insert().values(id="ph", name="现场", project_id="p", sort_order=1))
                connection.execute(t["modules"].insert().values(id="m", name="历史模块", project_id="p", phase_id="ph"))
                connection.execute(t["tasks"].insert().values(id="t", module_id="m", project_id="p", name="真实工作", target_quantity=3, quantity_type="per_vehicle",
                    deliverables=[{"name": "same", "done": True, "attachment_id": "a", "done_by": "u", "done_at": "2026-01-03T02:04:05"}, {"name": "same", "done": True}]))
                connection.execute(t["daily_progress"].insert().values(id="dp", client_uuid="fixture-report", project_id="p", task_id="t", user_id="u", work_date=date(2026, 1, 2), completed_quantity=2))
                connection.execute(t["tasks"].insert().values(id="completed-work", module_id="m", project_id="p", name="已达到原目标的非车辆工作", target_quantity=1, quantity_type="fixed"))
                connection.execute(t["daily_progress"].insert().values(id="dp2", client_uuid="fixture-report2", project_id="p", task_id="completed-work", user_id="u", work_date=date(2026, 1, 2), completed_quantity=1))
                connection.execute(t["attachments"].insert().values(id="a", project_id="p", entity_type="task", entity_id="t", filename="source.bin", stored_name="file.bin", file_size=21,
                                                                   uploaded_by="u", uploaded_at=datetime(2026, 1, 3, 2, 4, 5)))
                connection.execute(t["archive_checklists"].insert().values(id="ar", project_id="p", category="验收文件", item_name="旧done但无原件", is_done=True, done_by="u", done_at=datetime(2026, 1, 3)))
                connection.execute(t["vehicle_units"].insert().values(id="v", project_id="p", asset_code="CAR001", current_stage="old_stage"))
            engine.dispose()
            backup = root / "sqlite-fixture.tar.gz"
            with tarfile.open(backup, "w:gz") as archive:
                for path in source.rglob("*"):
                    archive.add(path, arcname=path.relative_to(source).as_posix(), recursive=False)
            work = root / "verification"
            result = subprocess.run([sys.executable, str(SCRIPT), "--backup", str(backup), "--work-dir", str(work)], capture_output=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout.decode() + result.stderr.decode())
            report = json.loads((work / "verification.private.json").read_text())
            summary = json.loads(result.stdout)
            self.assertTrue(summary["checks_passed"])
            self.assertFalse(summary["final_acceptance"])
            self.assertEqual(summary["schema_difference_count"], 0)
            self.assertTrue(summary["repeat_upgrade_unchanged"])
            self.assertEqual(summary["unknown_vehicle_assignments"]["units"], 2)
            self.assertEqual(summary["work_items"]["effective_completion_converted"], 1)
            self.assertEqual(summary["vehicles"], {"before": 1, "after": 1})
            sources = {r["source_key"]: r for r in report["document_destinations"]}
            self.assertEqual(sources["task:t:0"]["status"], "submitted")
            self.assertEqual(sources["task:t:1"]["status"], "pending")
            self.assertEqual(sources["archive:ar"]["status"], "pending")
            for secret in (b"PRIVATE-", b"fixture-installation-key-do-not-print"):
                self.assertNotIn(secret, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
