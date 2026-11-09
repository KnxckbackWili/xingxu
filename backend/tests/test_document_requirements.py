"""T21 rules and portable files, through the interfaces used by users."""
import copy
import hashlib
import io
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook
from pydantic import ValidationError

from app.db import SessionLocal
from app.models import DocumentTemplateFile, Template, ChangeLog
from app.services.document_requirements import RequirementInput

BASE = '/api/templates/default/document-requirements'


def body(**changes):
    return {'stage_key': '6', 'code': '6.99', 'name': '调试证明', 'scope': 'project', 'timing_type': 'on_demand', **changes}


def list_rows(client, headers, tid='default'):
    result = client.get(f'/api/templates/{tid}/document-requirements', headers=headers)
    assert result.status_code == 200, result.text
    return result.json()


def clean_export(bundle):
    bundle = copy.deepcopy(bundle)
    files = bundle['document_template_files']
    for row in bundle['document_requirements']:
        row['file'] = files.get(row.pop('blank_file_key'))
    return bundle['document_requirements']


def test_default_carries_every_frozen_company_document_and_copies_keep_codes(client, admin_headers):
    """The merged built-in template still hands in all 53 company documents, with their frozen rules."""
    rows = list_rows(client, admin_headers)
    seeds = [seed for seed in json.loads((Path(__file__).parents[1] / 'app/seed/company_documents.json').read_text())
             if not seed.get('is_group')]
    assert len(rows) == len(seeds) == 53 and not any(row['is_group'] for row in rows)
    by_code = {row['code']: row for row in rows}
    rule_keys = ('name', 'required', 'scope', 'platform', 'timing_type', 'timing_event', 'timing_offset_hours', 'timing_weekday', 'trigger_type')
    for seed in seeds:
        assert all(by_code[seed['code']][key] == seed[key] for key in rule_keys if key in seed), seed['code']
    assert all(by_code[code]['confidential_default'] for code in ('6.11.6a', '6.11.6b', '6.11.6c'))
    assert all(row['source_metadata'] and row['source_metadata'].get('template_item_id') for row in rows)
    result = client.post('/api/templates', headers=admin_headers, json={'name': '资料完整副本'})
    assert result.status_code == 200, result.text
    copied = list_rows(client, admin_headers, result.json()['id'])
    assert sorted(row['code'] for row in copied) == sorted(by_code)
    assert not {row['id'] for row in copied} & {row['id'] for row in rows}


@pytest.mark.parametrize('changes', [
    {'timing_type': 'weekly'}, {'timing_type': 'weekly', 'timing_weekday': 0},
    {'timing_type': 'weekly', 'timing_weekday': 8}, {'timing_type': 'weekly', 'timing_weekday': 7, 'timing_event': 'ship'},
    {'timing_type': 'after_event', 'timing_event': 'vehicle_arrival', 'timing_offset_hours': 24},
    {'timing_type': 'before_event', 'timing_event': 'unknown', 'timing_offset_hours': 0},
    {'timing_type': 'after_event', 'timing_event': 'ship', 'timing_offset_hours': -1},
    {'timing_type': 'after_event', 'timing_event': 'ship', 'timing_offset_hours': 1.5},
    {'timing_type': 'on_trigger', 'trigger_type': 'bad', 'timing_offset_hours': 0},
    {'timing_type': 'on_demand', 'timing_weekday': 7}, {'stage_key': '3'}, {'code': '6 99'}, {'code': '6..9'},
    {'is_group': True, 'required': False, 'scope': None, 'timing_type': None, 'timing_event': 'ship'},
])
def test_invalid_rules_fail_before_writes(changes):
    with pytest.raises(ValidationError):
        RequirementInput.model_validate(body(**changes))


@pytest.mark.parametrize('field', ['parent_code', 'blank_file_key'])
@pytest.mark.parametrize('value', [[], ['bad'], {}, {'bad': 'ref'}, False, 0, '', ' ', 'x' * 41])
def test_portable_reference_shape_rejects_bad_types(field, value):
    from app.services.document_requirements import parse_bundle
    definition = body() | {field: value}
    with pytest.raises(ValueError, match='父编号|文件键'):
        parse_bundle({'document_requirements': [definition], 'document_template_files': {}})


