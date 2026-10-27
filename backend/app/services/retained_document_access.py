"""Read frozen legacy evidence using the live document ACL, without rewriting it."""
from types import SimpleNamespace
from fastapi import HTTPException
from app.models import Attachment, ProjectDocument, ProjectDocumentDefinition
from app.services.project_documents import can_read_document, can_read_definition, can_read_file

_PRIVATE_CODES={'6.11.6','6.11.6a','6.11.6b','6.11.6c'}


def _rows(records, key):
    rows=records.get(key,[])
    if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):
        raise HTTPException(409,'归档资料权限记录不完整，请从私有加密备份恢复')
    return rows


def authorize_archive_content(archive, user, *, stored_name=None):
    snapshot=archive.snapshot or {}
    if not isinstance(snapshot,dict):raise HTTPException(409,'归档结构无法核对')
    raw_project=snapshot.get('project') or {}
    records=snapshot.get('records') or {}
    if not isinstance(raw_project,dict) or not isinstance(records,dict):raise HTTPException(409,'归档结构无法核对')
    project=SimpleNamespace(id=archive.project_id,manager=raw_project.get('manager'))
    is_owner=user.id==project.manager and user.role!='external'
    def grants(row):
        ids=row.get('confidential_user_ids') or []
        if not isinstance(ids,list) or any(not isinstance(value,str) for value in ids):
            if not is_owner:raise HTTPException(403,'无法证明归档保密范围，请联系原负责人或从私有加密备份恢复')
            return []
        return ids
    documents={}
    definitions={}
    for key,model,target,flag in (('project_documents',ProjectDocument,documents,'confidential'),
                                ('project_document_definitions',ProjectDocumentDefinition,definitions,'confidential_default')):
        for row in _rows(records,key):
            if not isinstance(row.get('id'),str) or not row['id'] or row['id'] in target:raise HTTPException(409,'归档资料身份记录无法核对')
            item=model(id=row.get('id'),project_id=project.id,confidential_user_ids=grants(row))
            setattr(item,flag,bool(row.get(flag)) or row.get('code') in _PRIVATE_CODES)
            item.blank_file_id=row.get('blank_file_id')
            if isinstance(item,ProjectDocument):item.definition_id=row.get('definition_id')
            target[item.id]=item
    for document in documents.values():
        if document.definition_id in definitions and definitions[document.definition_id].confidential_default:
            document.confidential=True
    versions=_rows(records,'document_versions')
    unknown_versions=any(row.get('project_document_id') not in documents for row in versions)
    assets={}
    proven_asset_ids=set()
    for row in _rows(records,'attachments'):
        if not isinstance(row.get('id'),str) or not row['id'] or row['id'] in assets:raise HTTPException(409,'归档文件身份记录无法核对')
        if isinstance(row.get('confidential'),bool):proven_asset_ids.add(row['id'])
        refs=[documents[v.get('project_document_id')] for v in versions
              if v.get('attachment_id')==row.get('id') and v.get('project_document_id') in documents]
        private=bool(row.get('confidential')) or any(item.confidential for item in refs)
        assets[row.get('id')]=Attachment(id=row.get('id'),project_id=project.id,stored_name=row.get('stored_name'),
            confidential=private,confidential_explicit=row.get('confidential_explicit',bool(row.get('confidential')) and not any(item.confidential for item in refs)),
            confidential_user_ids=grants(row))

    def allowed_file(asset):
        aliases={item.id for item in assets.values() if item.stored_name==asset.stored_name}
        refs=[documents[v.get('project_document_id')] for v in versions
              if v.get('attachment_id') in aliases and v.get('project_document_id') in documents]
        return can_read_file(user,project,asset,_references=refs)

    if stored_name is None:
        if unknown_versions and not is_owner:raise HTTPException(403,'归档资料版本缺少可证明的保密归属，请从私有加密备份恢复')
        if any(not can_read_document(user,project,row) for row in documents.values()) or any(
                not can_read_definition(user,project,row) for row in definitions.values()) or any(not allowed_file(row) for row in assets.values()):
            raise HTTPException(403,'归档包含未获授权的保密资料，完整原文不可读取；请从私有加密备份恢复')
        return any(row.confidential for row in documents.values()) or any(row.confidential_default for row in definitions.values()) or any(row.confidential for row in assets.values())

    matching=[row for row in assets.values() if row.stored_name==stored_name]
    blanks=[row for row in _rows(records,'document_template_files') if row.get('stored_name')==stored_name]
    has_private=any(row.confidential for row in documents.values()) or any(row.confidential_default for row in definitions.values()) or any(row.confidential for row in assets.values())
    complete=('project_documents' in records and 'document_versions' in records and not unknown_versions) or not has_private
    proven=bool(matching) and all(row.id in proven_asset_ids for row in matching) and complete
    if any(not allowed_file(row) for row in matching):raise HTTPException(403,'没有该归档保密文件的查看权限')
    for blank in blanks:
        references=[row for row in [*documents.values(),*definitions.values()] if row.blank_file_id==blank.get('id')]
        proven=proven or bool(references)
        if any(not (can_read_document(user,project,row) if isinstance(row,ProjectDocument) else can_read_definition(user,project,row)) for row in references):
            raise HTTPException(403,'没有该归档保密模板的查看权限')
    if not proven:
        # A retained path or actor_ids alone proves neither a public classification
        # nor a designated grant. It never grants access to an arbitrary disk path.
        if not is_owner:raise HTTPException(403,'归档缺少可证明的文件权限归属，请由原负责人核对或恢复私有加密备份')
    return any(row.confidential for row in matching) or bool(blanks and has_private) or not proven
