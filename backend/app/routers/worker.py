"""Account-bound offline dispatch."""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, Callable
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission_contextual
from app.db import get_db, SessionLocal
from app.deps import get_current_user
from app.models import User, OfflineOpReceipt

router = APIRouter(tags=["现场工作台"])


class OfflineOp(BaseModel):
    """离线队列里的一条操作：检查项、交付物、问题或现场实际操作。

    payload: 对应端点所需字段（不含 client_uuid，它单独存放）
    """
    type: str = Field(..., pattern="^(checkitem|issue|field)$")
    client_uuid: str = Field(..., min_length=8, max_length=64)
    payload: dict


class BatchSync(BaseModel):
    ops: list[OfflineOp] = []


@router.post("/worker/sync")
@route_permission_contextual('worker.report', 'worker.issues', reason='混合离线操作逐条重新认证并校验对应动作，失败不丢弃其他操作')
def batch_sync(
    data: BatchSync,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Batch submit from offline queue. Returns accepted/rejected uuids.

    支持 checkitem / issue / field 三种离线操作；
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
        action = {"checkitem": "worker.report", "issue": "worker.issues", "field":"worker.report"}.get(op_type)
        if current is None or not current.is_active or (action and not has_permission(current, action)):
            raise HTTPException(403, "该离线操作权限已被系统管理员撤销")
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

