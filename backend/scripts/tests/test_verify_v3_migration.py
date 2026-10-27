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

    def t40_fixture(self):
        def entry(identity, task='t', day='2026-12-31', amount=1.0, confirmed=True, status='planned', owner='u'):
            return {'id': identity, 'project_id': 'p', 'task_id': task, 'work_date': day,
                'assignee_id': owner, 'planned_quantity': amount, 'status': status,
                'notes': None if identity == 'cancelled' else 'original-' + identity,
                'is_confirmed': confirmed, 'is_locked': identity == 'one', 'version': 4}
        rows = [entry('one'), entry('two', day='2027-01-01', amount=2.0, owner='v'),
            entry('fraction', amount=0.5, confirmed=False), entry('cancelled', amount=4.0, status='skipped', owner=None),
            entry('zero', task='other', day='2027-01-04', amount=0.0),
            entry('known-part', day='2027-01-04'), entry('unknown-part', day='2027-01-05', amount=None),
            entry('out-of-range', day='2027-01-11', amount=2147483648.0)]
        before = {'projects': [{'id': 'p'}], 'tasks': [
            {'id': 't', 'project_id': 'p', 'module_id': 'm', 'quantity_type': 'per_vehicle'},
            {'id': 'other', 'project_id': 'p', 'module_id': 'm', 'quantity_type': 'fixed'}],
            'modules': [{'id': 'm', 'phase_id': 'ph'}], 'phases': [{'id': 'ph', 'name': '现场'}],
            'schedule_entries': rows}
        cells = []
        def cell(identity, entries, known, target, *, week='2026-12-28', mode='finish', review=False, nulls=0):
            first = entries[0]
            published, cancelled = first['is_confirmed'], first['status'] == 'skipped'
            cells.append({'id': identity, 'project_id': 'p', 'task_id': first['task_id'],
                'scope_key': f"all:legacy:{'published' if published else 'draft'}:{'cancelled' if cancelled else 'active'}",
                'scope': {'vehicle_unit_ids': []}, 'vehicle_step_key': 'legacy_t' if first['task_id'] == 't' else None,
                'week_start': week, 'mode': mode, 'target_count': target,
                'assignee_ids': sorted({row['assignee_id'] for row in entries if row['assignee_id']}),
                'published': published, 'is_cancelled': cancelled, 'published_at': None, 'published_by': None,
                'created_by': None, 'updated_by': None, 'version': 0, 'intent_review_required': review,
                'created_at': '2026-10-27T00:00:00', 'updated_at': '2026-10-27T00:00:00',
                'source_metadata': {'kind': 't40_legacy_daily_rollup', 'original_entries': deepcopy(entries),
                    'original_entry_ids': [row['id'] for row in entries], 'original_planned_sum': None if nulls else known,
                    'known_planned_sum': known, 'unknown_quantity_count': nulls, 'null_quantity_count': nulls,
                    'invalid_quantity_count': 0, 'migration_review_required': review,
                    'publication_time': 'unknown', 'publication_actor': 'unknown'}})
        cell('integer', rows[:2], '3.0', 3)
        cell('fraction-cell', rows[2:3], '0.5', None, review=True)
        cell('cancelled-cell', rows[3:4], '4.0', 4)
        cell('zero-cell', rows[4:5], '0.0', None, week='2027-01-04', mode='in_progress')
        cell('mixed-null-cell', rows[5:7], '1.0', None, week='2027-01-04', review=True, nulls=1)
        cell('range-cell', rows[7:8], '2147483648.0', None, week='2027-01-11', review=True)
        after = {'projects': deepcopy(before['projects']), 'tasks': [
            {**before['tasks'][0], 'vehicle_step_key': 'legacy_t'}, {**before['tasks'][1], 'vehicle_step_key': None}],
            'schedule_entries': deepcopy(rows), 'weekly_plan_cells': cells, 'field_operations': [],
            'change_logs': [{'id': 'audit', 'project_id': 'p', 'entity_id': 'p', 'entity_type': 'weekly_plan',
                'action': 'migrate_weeks', 'operator_id': None, 'created_at': '2026-10-27T00:00:00',
                'old_value': {'source': 'schedule_entries', 'unchanged': True},
                'new_value': {'cell_ids': [row['id'] for row in cells], 'source_kind': 't40_legacy_daily_rollup'}},
                {'id': 'intent-audit', 'project_id': 'p', 'entity_id': 'p', 'entity_type': 'weekly_plan',
                'action': 'review_plan_intent', 'operator_id': None, 'created_at': '2026-10-27T00:00:01',
                'old_value': {'cells': [{'id': row['id'], 'previous_mode': row['mode'], 'previous_target_count': row['target_count'],
                    'previous_version': 0, 'unknown_quantity_count': row['source_metadata']['unknown_quantity_count']}
                    for row in cells if row['intent_review_required']]},
                'new_value': {'cell_ids': [row['id'] for row in cells if row['intent_review_required']], 'intent_review_required': True}}]}
        return before, after

    def test_t40_exact_sources_iso_weeks_publication_cancel_fraction_and_unknown(self):
        before, after = self.t40_fixture()
        records, failures = verify.verify_t40(before, after, True)
        self.assertFalse(failures)
        self.assertEqual(len(records), 6)
        self.assertEqual(sum(len(row['original_entry_ids']) for row in records), 8)
        self.assertEqual(next(row for row in records if row['cell_id'] == 'integer')['week_start'], '2026-12-28')
        self.assertEqual(next(row for row in records if row['cell_id'] == 'mixed-null-cell')['unknown_quantity_count'], 1)
        self.assertIsNone(next(row for row in records if row['cell_id'] == 'range-cell')['target_count'])
        # Raw SQLite SQL retains 0/1 booleans; reflected before/after are bool.
        for cell in after['weekly_plan_cells']:
            for row in cell['source_metadata']['original_entries']:
                row['is_confirmed'] = int(row['is_confirmed'])
                row['is_locked'] = int(row['is_locked'])
        self.assertFalse(verify.verify_t40(before, after, True)[1])

    def test_t40_missing_extra_duplicate_and_wrong_cell_fields_are_rejected(self):
        for mutation in ('missing_one', 'missing_all', 'duplicate', 'extra', 'quantity', 'owner', 'week',
                         'published', 'cancelled', 'scope', 'step', 'actor', 'version', 'intent_flag'):
            with self.subTest(mutation=mutation):
                before, after = self.t40_fixture()
                cell = after['weekly_plan_cells'][0]
                if mutation == 'missing_one':
                    after['weekly_plan_cells'].pop()
                elif mutation == 'missing_all':
                    after['weekly_plan_cells'] = []
                elif mutation in ('extra', 'duplicate'):
                    clone = deepcopy(cell); clone['id'] = 'extra'
                    if mutation == 'extra': clone['week_start'] = '2027-01-25'
                    after['weekly_plan_cells'].append(clone)
                elif mutation == 'quantity': cell['target_count'] = 2
                elif mutation == 'owner': cell['assignee_ids'] = ['u']
                elif mutation == 'week': cell['week_start'] = '2027-01-04'
                elif mutation == 'published': cell['published'] = False
                elif mutation == 'cancelled': cell['is_cancelled'] = True
                elif mutation == 'scope': cell['scope'] = {'vehicle_unit_ids': None}
                elif mutation == 'step': cell['vehicle_step_key'] = 'arrival_inspection'
                elif mutation == 'actor': cell['published_by'] = 'guessed-publisher'
                elif mutation == 'version': cell['version'] = True
                else: after['weekly_plan_cells'][4]['intent_review_required'] = False
                self.assertTrue(verify.verify_t40(before, after, True)[1])

    def test_t40_source_single_field_loss_and_colluding_metadata_are_rejected(self):
        for mutation in ('source_notes', 'missing_null', 'source_id', 'source_sum', 'source_bool',
                         'live_field', 'live_missing', 'new_daily', 'audit_missing', 'audit_owner',
                         'intent_audit_missing', 'intent_audit_snapshot', 'colluding_owner', 'fabricated_actual'):
            with self.subTest(mutation=mutation):
                before, after = self.t40_fixture()
                cell = after['weekly_plan_cells'][0]; source = cell['source_metadata']
                if mutation == 'source_notes': source['original_entries'][0]['notes'] = 'changed'
                elif mutation == 'missing_null': del after['weekly_plan_cells'][2]['source_metadata']['original_entries'][0]['notes']
                elif mutation == 'source_id': source['original_entry_ids'].reverse()
                elif mutation == 'source_sum': source['original_planned_sum'] = '0'
                elif mutation == 'source_bool': source['original_entries'][0]['is_confirmed'] = None
                elif mutation == 'live_field': after['schedule_entries'][0]['notes'] = 'changed'
                elif mutation == 'live_missing': after['schedule_entries'].pop()
                elif mutation == 'new_daily': after['schedule_entries'].append({**after['schedule_entries'][0], 'id': 'fabricated'})
                elif mutation == 'audit_missing': after['change_logs'].pop(0)
                elif mutation == 'audit_owner': after['change_logs'][0]['operator_id'] = 'guessed-actor'
                elif mutation == 'intent_audit_missing': after['change_logs'].pop()
                elif mutation == 'intent_audit_snapshot': after['change_logs'][1]['old_value']['cells'][0]['previous_target_count'] = 5
                elif mutation == 'colluding_owner':
                    cell['assignee_ids'] = ['rogue']
                    for row in source['original_entries']: row['assignee_id'] = 'rogue'
                else: after['field_operations'] = [{'id': 'fabricated', 'actor_id': 'u'}]
                self.assertTrue(verify.verify_t40(before, after, True)[1])

    def test_t40_null_does_not_become_zero_or_known_positive_target(self):
        before, after = self.t40_fixture()
        cell = after['weekly_plan_cells'][4]
        source = cell['source_metadata']
        # Recreate the original bug while retaining the exact NULL source row.
        cell.update(target_count=1, intent_review_required=False)
        source.update(original_planned_sum='1.0', unknown_quantity_count=0,
                      null_quantity_count=0, migration_review_required=False)
        failures = verify.verify_t40(before, after, True)[1]
        self.assertTrue(failures)
        self.assertTrue(any(row['kind'] == 't40_incorrect_quantity_or_source_disposition' for row in failures))
        before, after = self.t40_fixture()
        cell = after['weekly_plan_cells'][4]
        # Isolate a correct non-vehicle unknown cell before changing one field.
        before['tasks'] = [{**before['tasks'][0], 'quantity_type': 'fixed'}]
        before['schedule_entries'] = before['schedule_entries'][5:7]
        after['tasks'] = [{**before['tasks'][0], 'vehicle_step_key': None, 'manually_completed': True}]
        after['schedule_entries'] = deepcopy(before['schedule_entries'])
        cell['vehicle_step_key'] = None
        after['weekly_plan_cells'] = [cell]
        after['change_logs'][0]['new_value']['cell_ids'] = [cell['id']]
        after['change_logs'][1]['old_value']['cells'] = [row for row in after['change_logs'][1]['old_value']['cells'] if row['id'] == cell['id']]
        after['change_logs'][1]['new_value']['cell_ids'] = [cell['id']]
        self.assertFalse(verify.verify_t40(before, after, True)[1])
        # NULL remains an explicitly unknown intent even with a completed work bit.
        cell['mode'] = 'in_progress'
        failures = verify.verify_t40(before, after, True)[1]
        self.assertTrue(any(row['kind'] == 't40_wrong_weekly_cell_field' and row['column'] == 'mode' for row in failures))

    def test_t40_decimal_sums_do_not_round_large_known_parts_or_nonfinite_sources(self):
        from decimal import Decimal
        self.assertEqual(str(verify.exact_decimal_sum([Decimal('1e30'), Decimal('0.25')])),
                         '1000000000000000000000000000000.25')
        self.assertEqual(str(verify.exact_decimal_sum([Decimal('0.1'), Decimal('0.2')])), '0.3')
        self.assertEqual(verify.normalized(float('inf')), {'invalid_original_number': 'inf'})
        self.assertEqual(verify.normalized(float('nan')), {'invalid_original_number': 'nan'})
        self.assertNotIn(b'Infinity', verify.encoded({'value': float('inf')}))

    def test_t40_large_and_nonfinite_original_quantities_are_independently_recomputed(self):
        for special, known, invalid, review in ((1e30, '1000000000000000000000000000000.25', 0, True),
                                                (float('inf'), '0.25', 1, True)):
            with self.subTest(invalid=invalid):
                before, after = self.t40_fixture()
                before['schedule_entries'][0]['planned_quantity'] = verify.normalized(special)
                before['schedule_entries'][1]['planned_quantity'] = 0.25
                after['schedule_entries'] = deepcopy(before['schedule_entries'])
                cell = after['weekly_plan_cells'][0]
                cell.update(target_count=None, intent_review_required=review)
                source = cell['source_metadata']
                source.update(original_entries=deepcopy(before['schedule_entries'][:2]),
                    known_planned_sum=known, original_planned_sum=None if invalid else known,
                    unknown_quantity_count=invalid, invalid_quantity_count=invalid,
                    migration_review_required=review)
                audit = after['change_logs'][1]
                audit['old_value']['cells'].append({'id':cell['id'], 'previous_mode':'finish',
                    'previous_target_count':None, 'previous_version':0, 'unknown_quantity_count':invalid})
                audit['new_value']['cell_ids'].append(cell['id'])
                self.assertFalse(verify.verify_t40(before, after, True)[1])
                source['known_planned_sum'] = '1E+30' if not invalid else '0'
                self.assertTrue(verify.verify_t40(before, after, True)[1])

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
                for identity, task, day, amount, confirmed, status in (
                    ('plan-one', 't', date(2026,12,31), 1.0, True, 'planned'),
                    ('plan-two', 't', date(2027,1,1), 0.25, True, 'done'),
                    ('plan-null', 't', date(2027,1,1), None, False, 'planned'),
                    ('plan-zero', 'completed-work', date(2027,1,1), 0.0, True, 'planned'),
                    ('plan-other-null', 'completed-work', date(2027,1,1), None, True, 'skipped')):
                    connection.execute(t['schedule_entries'].insert().values(id=identity, project_id='p',
                        task_id=task, work_date=day, planned_quantity=amount, assignee_id='u',
                        is_confirmed=confirmed, is_locked=False, status=status, notes=None, version=3))
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
            self.assertEqual(summary['weekly_plans']['source_entries_verified'], 5)
            self.assertEqual(summary['weekly_plans']['cells_verified'], 4)
            self.assertEqual(summary['weekly_plans']['unknown_quantity_sources'], 2)
            self.assertEqual(summary['weekly_plans']['intent_review_cells'], 3)
            sources = {r["source_key"]: r for r in report["document_destinations"]}
            self.assertEqual(sources["task:t:0"]["status"], "submitted")
            self.assertEqual(sources["task:t:1"]["status"], "pending")
            self.assertEqual(sources["archive:ar"]["status"], "pending")
            for secret in (b"PRIVATE-", b"fixture-installation-key-do-not-print"):
                self.assertNotIn(secret, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
