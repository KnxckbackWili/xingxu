"""Account-bound offline dispatch and read-only reconciliation of legacy UUIDs."""

import uuid
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, Callable
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission_contextual, route_permission_exempt
from app.db import get_db, SessionLocal
from app.deps import get_current_user
from app.models import User, Task, OfflineOpReceipt
from app.services.scope import ensure_project_visible

router = APIRouter(tags=["现场工作台"])


class OfflineOp(BaseModel):
    """离线队列里的一条操作：检查项、交付物、问题或现场实际操作。

    payload: 对应端点所需字段（不含 client_uuid，它单独存放）
    """
    type: str = Field(..., pattern="^(checkitem|deliverable|issue|field)$")
    client_uuid: str = Field(..., min_length=8, max_length=64)
    payload: dict


class BatchSync(BaseModel):
    ops: list[OfflineOp] = []


@router.post("/worker/sync")
@route_permission_contextual('worker.report', 'worker.deliver', 'worker.issues', reason='混合离线操作逐条重新认证并校验对应动作，失败不丢弃其他操作')
def batch_sync(
    data: BatchSync,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Batch submit from offline queue. Returns accepted/rejected uuids.

    支持 checkitem / deliverable / issue / field 四种离线操作；
    C5-6：返回每条的拒绝原因（rejected_detail: {uuid: detail}），前端被拒列表可查看。
    HYPE-99：逐项独立会话 + 幂等凭证——任一被拒项不留下可被后续成功项提交的脏状态/
    版本变更；缺字段/类型错误等单项进入 rejected_detail 而非整批 500；并发重试（多
    worker/多端）由 offline_op_receipts 唯一约束兜底，不重复写/审计/通知。receipt 唯一键
    含 project_id（HYPE-99 复审）：与 issues (project_id, client_uuid) 契约一致，同一用户
    在不同项目复用同一 client_uuid 不会被误吞。
    """
    accepted, rejected, rejected_detail = [], [], {}

    def attempt(kind,uuid_,project_id,apply):
        return _apply_offline_with_receipt(user,kind,uuid_,project_id,apply)

    def _accept(uuid_: str):
        if uuid_ not in accepted:
            accepted.append(uuid_)

    def _reject(uuid_: str, detail: str):
        if uuid_ not in rejected:
            rejected.append(uuid_)
            rejected_detail[uuid_] = detail

    for op in data.ops:
        project_id = op.payload.get("project_id") if isinstance(op.payload.get("project_id"), str) else None
        if op.type == "field":
            def _apply_field(session:Session):
                from app.routers.field_week import FieldChange
                from app.services.field_operations import apply as record_field
                body=FieldChange(**{**op.payload,'client_uuid':op.client_uuid})
                record_field(session,body.project_id,session.get(User,user.id),body.model_dump(exclude_none=True))
            apply=_apply_field
        elif op.type == "checkitem":
            apply = _apply_offline_checkitem(op, user)
        elif op.type == "deliverable":
            apply = _apply_offline_deliverable(op, user)
        elif op.type == "issue":
            apply = _apply_offline_issue(op, user)
        else:  # schema 已限定，兜底防御
            _reject(op.client_uuid, f"未知操作类型：{op.type}")
            continue
        ok, reason = attempt(op.type,op.client_uuid,project_id,apply)
        if ok:
            _accept(op.client_uuid)
        else:
            _reject(op.client_uuid, reason)
    return {"accepted": accepted, "rejected": rejected, "rejected_detail": rejected_detail,
            "message": f"同步完成：成功 {len(accepted)} 条"}


def _apply_offline_with_receipt(
    user: User,
    op_type: str,
    client_uuid: str,
    project_id: Optional[str],
    apply: Callable[[Session], None],
) -> tuple[bool, Optional[str]]:
    """在独立会话里执行一个离线操作，返回 (是否接受, 拒绝原因)。

    - 先落幂等凭证 offline_op_receipts（与业务写同事务提交）；receipt 唯一键按
      (user_id, op_type, project_id, client_uuid) 作用域去重，与问题台账/检查项/交付物
      的「项目内唯一」契约一致——同一用户在不同项目复用同一 client_uuid 不会被误吞；
    - 操作抛 HTTPException（业务拒绝）→ 回滚本会话，原因进入 rejected_detail；
    - 其余异常（缺字段/类型错误/损坏 payload/未知错误）→ 同样只拒绝本条并回滚，
      绝不把半截状态留给同一批里的后续成功项提交；
    - IntegrityError → 并发/重试重复：按同作用域查 receipt，已有则按幂等成功处理
      （不重复写）。
    """
    op_db = SessionLocal()
    try:
        from app.services.system_permissions import has_permission
        current = op_db.get(User, user.id)
        action = {"checkitem": "worker.report", "deliverable": "worker.deliver", "issue": "worker.issues", "field":"worker.report"}.get(op_type)
        if current is None or not current.is_active or (action and not has_permission(current, action, default=True)):
            raise HTTPException(403, "该离线操作权限已被系统管理员撤销")
        # Do not let an already-authorized batch retain an old policy snapshot.
        user.permission_overrides = dict(current.permission_overrides or {})
        from app.services.two_factor import required
        if (current.token_version or 0)!=(user.token_version or 0) or (required(current) and (not required(user) or not current.mfa_enabled)):
            raise HTTPException(401,'账号验证已变化，请重新登录后核对原离线操作')
        if op_type == 'field':
            apply(op_db)
            op_db.commit()
            return True,None
        if project_id is not None:
            existing = op_db.query(OfflineOpReceipt.id).filter_by(
                user_id=user.id, op_type=op_type, project_id=project_id,
                client_uuid=client_uuid).first()
            if existing is not None:
                return True, None
        op_db.add(OfflineOpReceipt(
            user_id=user.id, op_type=op_type,
            client_uuid=client_uuid, project_id=project_id,
        ))
        # apply 内部各自 commit（receive 随业务写一并落库）；命中幂等早退路径（内部不
        # commit）时这里兜底 commit，保证 receipt 持久化 → 后续重试同样被幂等吸收。
        apply(op_db)
        op_db.commit()
        return True, None
    except HTTPException as e:
        op_db.rollback()
        return False,str(e.detail)
    except IntegrityError:
        op_db.rollback()
        dup = op_db.query(OfflineOpReceipt.id).filter(
            OfflineOpReceipt.user_id == user.id,
            OfflineOpReceipt.op_type == op_type,
            OfflineOpReceipt.project_id == project_id,
            OfflineOpReceipt.client_uuid == client_uuid,
        ).first()
        if dup is not None:
            return True, None
        return False, "服务端数据冲突，请稍后重试"
    except Exception as e:  # 缺字段/类型错误/损坏 payload 等 → 单项拒绝，不 500
        op_db.rollback()
        detail = f"请求不完整或格式错误：{type(e).__name__}: {e}"
        return False, detail[:200]
    finally:
        op_db.close()


def _apply_offline_checkitem(op: OfflineOp, user: User) -> Callable[[Session], None]:
    """离线检查项操作：复用 update_check_item 的三态逻辑（通过/不通过/不适用）。"""
    def _do(db: Session):
        from app.routers.tasks import update_check_item, CheckItemUpdate
        payload = op.payload
        update_check_item(
            project_id=payload["project_id"],
            cid=payload["check_item_id"],
            data=CheckItemUpdate(**payload.get("body", {})),
            user=user,
            db=db,
        )
    return _do


def _apply_offline_deliverable(op: OfflineOp, user: User) -> Callable[[Session], None]:
    """Translate only an unambiguous pre-T22 draft; never recreate task JSON writes."""
    def apply(db: Session):
        from app.models import ProjectDocument, DocumentVersion
        from app.services import project_documents as docs
        from app.services.change_log import log_change
        payload=op.payload
        project_id,task_id=payload.get('project_id'),payload.get('task_id')
        if not isinstance(project_id,str) or not isinstance(task_id,str) or not isinstance(payload.get('deliverables'),list):
            raise HTTPException(409,'旧离线资料草稿格式待核对，请保留原UUID和完整草稿')
        actor=db.get(User,user.id)
        project=docs.writable(db,project_id,actor,'worker.deliver')
        source={}
        for document in db.query(ProjectDocument).filter_by(project_id=project_id):
            metadata=document.source_metadata or {}
            if metadata.get('kind')!='task_deliverable' or (metadata.get('task') or {}).get('id')!=task_id:continue
            original=metadata.get('original')
            name=original.get('name') if isinstance(original,dict) else str(original)
            if name in source:raise HTTPException(409,'旧资料同名来源无法安全对应，请保留草稿人工核对')
            source[name]=document
        planned=[];seen=set()
        for item in payload['deliverables']:
            if not isinstance(item,dict) or not isinstance(item.get('name'),str) or item['name'] in seen or item['name'] not in source:
                raise HTTPException(409,'旧离线资料未能对应迁移清单，请保留原UUID和完整草稿')
            seen.add(item['name']);document=source[item['name']]
            metadata=document.source_metadata or {};old=metadata.get('original') or {}
            requested_status=item.get('status')
            if requested_status in ('approved','rejected') and (not isinstance(old,dict) or old.get('status')!=requested_status):
                raise HTTPException(409,'旧离线草稿含审核变更，请保留草稿并在资料页重新核对')
            target='submitted' if item.get('done') or requested_status in ('submitted','approved') else 'pending'
            attachment=item.get('attachment_id') or (old.get('attachment_id') if isinstance(old,dict) else None)
            current=db.query(DocumentVersion).filter_by(project_document_id=document.id).order_by(DocumentVersion.uploaded_at.desc().nullslast(),DocumentVersion.id.desc()).first()
            same=target==document.status and (target!='submitted' or current and current.attachment_id==attachment)
            if document.version!=1 and not same:
                raise HTTPException(409,'资料已在新清单中更新，请保留旧草稿核对差异，未覆盖新记录')
            if payload.get('version') is not None and payload['version']!=(metadata.get('task') or {}).get('version'):
                raise HTTPException(409,'旧任务版本与迁移来源不符，请保留草稿人工核对')
            if target=='submitted' and (not isinstance(attachment,str) or not attachment):
                raise HTTPException(409,'旧草稿缺少真实附件，请保留草稿并在资料页补交')
            planned.append((document,target,attachment,same))
        for document,target,attachment,same in planned:
            if same:continue
            if target=='submitted':docs.submit(db,project,[document.id],attachment,actor,'从旧离线草稿迁移，原UUID：'+op.client_uuid)
            else:docs.update_state(db,project,document,actor,'pending','旧离线草稿请求撤回，原UUID：'+op.client_uuid)
        log_change(db,project_id,'legacy_offline_document',task_id,'translate',actor.id,'旧离线资料已明确对应新清单',None,
            {'client_uuid':op.client_uuid,'original_payload':payload,'document_ids':[row[0].id for row in planned]})
        db.commit()
    return apply


def _apply_offline_issue(op: OfflineOp, user: User) -> Callable[[Session], None]:
    """离线问题上报：复用 create_issue（client_uuid 幂等去重）。"""
    def _do(db: Session):
        from app.routers.issues import create_issue, IssueCreate
        payload = dict(op.payload)
        project_id = payload.pop("project_id")
        payload["client_uuid"] = op.client_uuid
        create_issue(
            project_id=project_id,
            data=IssueCreate(**payload),
            user=user,
            db=db,
        )
    return _do

