"""
客服工作台路由

v1 范围：
- WB 问答、评价、买家聊天、退货申请统一收件箱
- 负责人权限基于 User.allowed_owners
- 每次处理写 CustomerServiceAction，不写 OperationLog
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, case, or_
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.database import SessionLocal, get_db
from app.models.models import (
    CustomerServiceAction,
    CustomerServiceItem,
    CustomerServiceMessage,
    Shop,
    SyncLog,
    User,
)
from app.routers.auth import get_current_user
from app.services.ai_client import AIClient, AIClientError
from app.services.ai_prompt_service import get_active_template, render_template
from app.services.customer_service_sync import CustomerServiceSyncService
from app.services.customer_translation_service import CustomerTranslationService
from app.services.sync_lock import SyncLockService
from app.services.wb_customer_client import WBCustomerAPIError, WBCustomerClient, WBCustomerRateLimit
from app.utils.permissions import (
    filter_customer_query,
    can_access_customer_item,
    require_cs_permission,
    has_permission,
)
from app.utils.permissions import _role as _cs_role, _user_allowed_owners, _user_allowed_shops  # noqa: F401


router = APIRouter(prefix="/api/customer-service", tags=["客服工作台"])
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class ReplyRequest(BaseModel):
    message: str


class AssignOwnerRequest(BaseModel):
    assigned_owner: str
    assigned_user_id: Optional[int] = None
    handover_note: Optional[str] = None


class StatusUpdateRequest(BaseModel):
    status: str
    reply_status: Optional[str] = None


class InternalNoteUpdateRequest(BaseModel):
    internal_note: str = ""


class ReturnAnswerRequest(BaseModel):
    action: str
    comment: Optional[str] = None


class SyncRequest(BaseModel):
    shop_id: Optional[int] = None
    channel: str = "all"  # all/questions/feedbacks/chats/return_claims
    days: int = 30
    force_full_sync: bool = False  # 强制从头同步（清除聊天 cursor）


@router.get("/stats")
def get_customer_service_stats(
    shop_id: Optional[int] = Query(None),
    owner: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_cs_permission(current_user, "customer_service:read")
    query = _visible_query(db.query(CustomerServiceItem), current_user)
    if shop_id:
        query = query.filter(CustomerServiceItem.shop_id == shop_id)
    if owner:
        query = query.filter(or_(
            CustomerServiceItem.owner == owner,
            CustomerServiceItem.assigned_owner == owner,
        ))

    # 过滤未归档
    open_query = query.filter(CustomerServiceItem.is_archived == False)
    # 活跃：open / pending_internal / replied（已回复仍计入统计）
    active_query = open_query.filter(
        CustomerServiceItem.status.in_(["open", "pending_internal", "replied"])
    )

    # ---- 评论卡片：差评(1-3星) / 好评(4-5星)，各分待回复/已回复 ----
    # 待回复：status=open/pending_internal + reply_status=unanswered
    # 已回复：任意活跃status + reply_status=answered
    feedback_query = active_query.filter(CustomerServiceItem.channel == "feedback")
    feedback_low_bad = feedback_query.filter(
        CustomerServiceItem.rating.in_([1, 2, 3]),
        CustomerServiceItem.reply_status == "unanswered"
    ).count()
    feedback_low_bad_replied = feedback_query.filter(
        CustomerServiceItem.rating.in_([1, 2, 3]),
        CustomerServiceItem.reply_status == "answered"
    ).count()
    feedback_high_bad = feedback_query.filter(
        CustomerServiceItem.rating.in_([4, 5]),
        CustomerServiceItem.reply_status == "unanswered"
    ).count()
    feedback_high_bad_replied = feedback_query.filter(
        CustomerServiceItem.rating.in_([4, 5]),
        CustomerServiceItem.reply_status == "answered"
    ).count()

    # ---- 问答卡片：待回复 / 已回复 ----
    question_query = active_query.filter(CustomerServiceItem.channel == "question")
    question_unanswered = question_query.filter(
        CustomerServiceItem.reply_status == "unanswered"
    ).count()
    question_answered = question_query.filter(
        CustomerServiceItem.reply_status == "answered"
    ).count()

    # ---- 退货卡片：待处理 / 已拒绝 / 已同意 ----
    # 退货申请 status=open 且 reply_status=unanswered = 待处理
    # status=closed = 已处理（拒绝/同意均 closed）
    return_query = open_query.filter(CustomerServiceItem.channel == "return_claim")
    return_pending = return_query.filter(
        CustomerServiceItem.status == "open",
        CustomerServiceItem.reply_status == "unanswered"
    ).count()
    return_closed = return_query.filter(
        CustomerServiceItem.status == "closed"
    ).count()

    # ---- 聊天卡片：待卖家回复 / 待买家回复 / 已完结 ----
    chat_open_query = open_query.filter(
        CustomerServiceItem.channel == "chat",
        CustomerServiceItem.status.notin_(["closed", "archived"]),
    )
    chat_waiting_seller = chat_open_query.filter(
        CustomerServiceItem.reply_status == "unanswered",
        CustomerServiceItem.status.notin_(["pending_internal"]),
    ).count()
    chat_pending_internal = open_query.filter(
        CustomerServiceItem.channel == "chat",
        CustomerServiceItem.status == "pending_internal",
    ).count()
    chat_waiting_buyer = chat_open_query.filter(
        CustomerServiceItem.status == "replied"
    ).count()
    chat_finished = open_query.filter(
        CustomerServiceItem.channel == "chat",
        CustomerServiceItem.status == "closed",
    ).count()

    # ---- 全局 ----
    overdue = open_query.filter(CustomerServiceItem.is_overdue == True).count()

    return {
        # 评论
        "feedback_low_bad_unanswered": feedback_low_bad,
        "feedback_low_bad_replied": feedback_low_bad_replied,
        "feedback_high_bad_unanswered": feedback_high_bad,
        "feedback_high_bad_replied": feedback_high_bad_replied,
        # 问答
        "question_unanswered": question_unanswered,
        "question_answered": question_answered,
        # 退货
        "return_pending": return_pending,
        "return_closed": return_closed,
        # 聊天
        "chat_unanswered": chat_waiting_seller,
        "chat_answered": chat_waiting_buyer,
        "chat_waiting_seller": chat_waiting_seller,
        "chat_waiting_buyer": chat_waiting_buyer,
        "chat_pending_internal": chat_pending_internal,
        "chat_finished": chat_finished,
        # 全局
        "overdue": overdue,
    }


@router.get("/inbox")
def list_customer_service_items(
    shop_id: Optional[int] = Query(None),
    owner: Optional[str] = Query(None),
    channel: str = Query("all"),
    status: str = Query("open"),
    search: str = Query(""),
    quick_key: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_cs_permission(current_user, "customer_service:read")
    query = _visible_query(db.query(CustomerServiceItem), current_user)
    query = query.filter(CustomerServiceItem.is_archived == False)

    if shop_id:
        query = query.filter(CustomerServiceItem.shop_id == shop_id)
    if owner:
        query = query.filter(or_(
            CustomerServiceItem.owner == owner,
            CustomerServiceItem.assigned_owner == owner,
        ))

    # ── quick_key 精确过滤 ──────────────────────────────────

    if quick_key:
        if quick_key == "feedback_low_bad_unanswered":
            query = query.filter(
                CustomerServiceItem.channel == "feedback",
                CustomerServiceItem.rating.in_([1, 2, 3]),
                CustomerServiceItem.reply_status == "unanswered",
                CustomerServiceItem.status.notin_(["closed", "archived"]),
            )
        elif quick_key == "feedback_low_bad_replied":
            query = query.filter(
                CustomerServiceItem.channel == "feedback",
                CustomerServiceItem.rating.in_([1, 2, 3]),
                CustomerServiceItem.reply_status == "answered",
            )
        elif quick_key == "feedback_high_bad_unanswered":
            query = query.filter(
                CustomerServiceItem.channel == "feedback",
                CustomerServiceItem.rating.in_([4, 5]),
                CustomerServiceItem.reply_status == "unanswered",
                CustomerServiceItem.status.notin_(["closed", "archived"]),
            )
        elif quick_key == "feedback_high_bad_replied":
            query = query.filter(
                CustomerServiceItem.channel == "feedback",
                CustomerServiceItem.rating.in_([4, 5]),
                CustomerServiceItem.reply_status == "answered",
            )
        elif quick_key == "question_unanswered":
            query = query.filter(
                CustomerServiceItem.channel == "question",
                CustomerServiceItem.reply_status == "unanswered",
                CustomerServiceItem.status.notin_(["closed", "archived"]),
            )
        elif quick_key == "question_answered":
            query = query.filter(
                CustomerServiceItem.channel == "question",
                CustomerServiceItem.reply_status == "answered",
            )
        elif quick_key == "return_pending":
            query = query.filter(
                CustomerServiceItem.channel == "return_claim",
                CustomerServiceItem.status == "open",
                CustomerServiceItem.reply_status == "unanswered",
            )
        elif quick_key == "return_closed":
            query = query.filter(
                CustomerServiceItem.channel == "return_claim",
                CustomerServiceItem.status == "closed",
            )
        elif quick_key == "chat_unanswered":
            query = query.filter(
                CustomerServiceItem.channel == "chat",
                CustomerServiceItem.reply_status == "unanswered",
                CustomerServiceItem.status.notin_(["closed", "archived"]),
            )
        elif quick_key == "chat_answered":
            query = query.filter(
                CustomerServiceItem.channel == "chat",
                CustomerServiceItem.status == "replied",
            )
        elif quick_key == "chat_waiting_seller":
            query = query.filter(
                CustomerServiceItem.channel == "chat",
                CustomerServiceItem.reply_status == "unanswered",
                CustomerServiceItem.status.notin_(["closed", "archived"]),
            )
        elif quick_key == "chat_waiting_buyer":
            query = query.filter(
                CustomerServiceItem.channel == "chat",
                CustomerServiceItem.status == "replied",
            )
        elif quick_key == "chat_finished":
            query = query.filter(
                CustomerServiceItem.channel == "chat",
                CustomerServiceItem.status == "closed",
            )
        elif quick_key == "chat_pending_internal":
            query = query.filter(
                CustomerServiceItem.channel == "chat",
                CustomerServiceItem.status == "pending_internal",
            )
    else:
        # ── 普通 channel / status 过滤 ───────────────────
        if channel != "all":
            query = query.filter(CustomerServiceItem.channel == channel)
        if status != "all":
            if status == "unanswered":
                query = query.filter(
                    CustomerServiceItem.reply_status == "unanswered",
                    CustomerServiceItem.status.notin_(["closed", "archived"]),
                )
            elif status == "replied":
                query = query.filter(CustomerServiceItem.status == "replied")
            elif status == "pending_internal":
                query = query.filter(CustomerServiceItem.status == "pending_internal")
            elif status == "closed":
                query = query.filter(CustomerServiceItem.status == "closed")
            else:
                query = query.filter(CustomerServiceItem.status == status)

    if search:
        like = f"%{search.strip()}%"
        query = query.filter(or_(
            CustomerServiceItem.nm_id.like(like),
            CustomerServiceItem.sku.like(like),
            CustomerServiceItem.product_name.like(like),
            CustomerServiceItem.product_name_ru.like(like),
            CustomerServiceItem.customer_name.like(like),
            CustomerServiceItem.content.like(like),
            CustomerServiceItem.external_id.like(like),
        ))

    total = query.count()
    risk_order = case(
        (CustomerServiceItem.risk_level == "urgent", 0),
        (CustomerServiceItem.risk_level == "high", 1),
        (CustomerServiceItem.risk_level == "normal", 2),
        else_=3,
    )
    items = query.order_by(
        risk_order,
        CustomerServiceItem.sla_deadline_at.is_(None),
        CustomerServiceItem.sla_deadline_at.asc(),
        CustomerServiceItem.external_created_at.desc(),
        CustomerServiceItem.id.desc(),
    ).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [_serialize_item(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/items/{item_id}")
def get_customer_service_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_cs_permission(current_user, "customer_service:read")
    item = _get_visible_item(db, item_id, current_user)
    return _serialize_item(item, include_messages=True, include_actions=True)


@router.get("/items/{item_id}/related")
def get_related_items(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """跨渠道聚合已禁用，WB 无稳定跨渠道买家ID，始终返回空列表（保留权限检查和404行为）"""
    require_cs_permission(current_user, "customer_service:read")
    _get_visible_item(db, item_id, current_user)  # 权限验证，item不存在或无权访问时抛404
    return {"items": []}


@router.post("/sync")
def sync_customer_service(
    data: SyncRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_cs_permission(current_user, "customer_service:sync")
    shops_query = db.query(Shop).filter(
        Shop.is_active == True,
        Shop.platform == "wildberries",
    )
    if data.shop_id:
        shops_query = shops_query.filter(Shop.id == data.shop_id)
    shops = shops_query.all()
    if not shops:
        raise HTTPException(status_code=404, detail="未找到可同步的 WB 店铺")

    log_ids = []
    skipped_shops = []
    for shop in shops:
        # 并发保护：检查是否有活跃锁
        lock = SyncLockService(db)
        if lock.is_locked(shop.id, "customer_service"):
            skipped_shops.append(shop.name)
            continue
        sync_log = SyncLog(
            shop_id=shop.id,
            sync_type="customer_service",
            status="running",
            message=f"客服同步进行中（{shop.name}）",
            records_count=0,
        )
        db.add(sync_log)
        db.commit()
        db.refresh(sync_log)
        log_ids.append(sync_log.id)
        background_tasks.add_task(_run_customer_service_sync_task, shop.id, data.channel, data.days, sync_log.id, data.force_full_sync)
    msg = f"客服数据同步已开始，稍后刷新收件箱查看结果"
    if skipped_shops:
        msg = f"以下店铺已有同步进行中，跳过: {', '.join(skipped_shops)}"
    return {
        "success": True,
        "status": "queued" if not skipped_shops else "partial",
        "log_ids": log_ids,
        "count": len(shops) - len(skipped_shops),
        "skipped": skipped_shops,
        "message": msg,
    }
    return {
        "success": True,
        "status": "queued",
        "log_ids": log_ids,
        "count": len(shops),
        "message": "客服数据同步已开始，稍后刷新收件箱查看结果",
    }


@router.get("/sync-status/{log_id}")
def get_sync_status(
    log_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询客服同步任务状态，前端轮询使用"""
    require_cs_permission(current_user, "customer_service:sync")
    sync_log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
    if not sync_log:
        raise HTTPException(status_code=404, detail="同步记录不存在")
    return {
        "id": sync_log.id,
        "shop_id": sync_log.shop_id,
        "status": sync_log.status,
        "message": sync_log.message,
        "records_count": sync_log.records_count,
        "started_at": sync_log.started_at.isoformat() if sync_log.started_at else None,
        "finished_at": sync_log.finished_at.isoformat() if sync_log.finished_at else None,
    }


@router.get("/permission-check/{shop_id}")
def check_customer_service_permission(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_cs_permission(current_user, "customer_service:sync")
    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.is_active == True).first()
    if not shop:
        raise HTTPException(status_code=404, detail="店铺不存在")
    if shop.platform != "wildberries":
        raise HTTPException(status_code=400, detail="当前仅支持 WB 客服权限检测")
    return WBCustomerClient(shop.api_token).check_permissions()


@router.post("/items/{item_id}/ai-draft")
def generate_ai_reply_draft(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_cs_permission(current_user, "customer_service:ai_draft")
    item = _get_visible_item(db, item_id, current_user)
    try:
        template = get_active_template(db, "customer_reply")

        # 补齐所有 Prompt 变量
        messages = sorted(item.messages or [], key=lambda m: m.created_at_external or m.created_at)
        messages_text = "\n".join([
            f"{'客服' if m.direction == 'seller' else '买家'}: {m.message_text}"
            for m in messages[-10:]
            if m.message_text
        ])

        raw = _json_loads(item.raw_json, {})
        is_return_related = item.channel == "return_claim" or "return" in raw

        variables = {
            "channel": str(item.channel) if item.channel is not None else "",
            "shop_name": item.shop.name if item.shop else "",
            "product_name": item.product_name or item.title or "",
            "rating": str(item.rating) if item.rating is not None else "",
            "status": str(item.status) if item.status is not None else "",
            "reply_status": str(item.reply_status) if item.reply_status is not None else "",
            "is_archived": str(bool(getattr(item, "is_archived", False))),
            "is_return_related": str(is_return_related),
            "content": item.content or item.title or "",
            "content_zh": item.content_zh or item.title_zh or "",
            "messages": messages_text,
            "return_context": "",
            "existing_answer": "",
            "internal_note": getattr(item, "internal_note", "") or "",
        }
        system_prompt = template.system_prompt
        user_prompt = render_template(template.user_prompt_template, variables)
        output = AIClient(db).chat_json(
            system_prompt,
            user_prompt,
            template.temperature,
            template.max_tokens,
        )
        # MiniMax 等模型可能返回 reply_ru / draft_ru，兼容处理
        draft = (output.get("reply") or output.get("reply_ru") or output.get("draft") or output.get("draft_ru") or "").strip()
        if not draft:
            raise AIClientError("AI 未返回回复内容")
        if _contains_cjk(draft):
            raise HTTPException(status_code=400, detail="AI 草稿含中文，已拦截，请调整 Prompt 后重试")
        if not draft.lower().startswith("здравствуйте"):
            raise HTTPException(status_code=400, detail="AI 草稿未以 Здравствуйте 开头，已拦截")
        # 拦截内部商品编码
        blocked_tokens = [
            str(item.nm_id) if item.nm_id else "",
            str(item.sku) if item.sku else "",
        ]
        for token in blocked_tokens:
            if token and len(token) >= 4 and token.lower() in draft.lower():
                raise HTTPException(status_code=400, detail="AI 草稿包含内部商品编码，已拦截")
    except AIClientError as exc:
        _record_action(
            db,
            item,
            current_user,
            "ai_draft_generated",
            request={"channel": item.channel, "template": "customer_reply"},
            success=False,
            error=str(exc),
        )
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc))

    _record_action(
        db,
        item,
        current_user,
        "ai_draft_generated",
        request={"channel": item.channel, "template": "customer_reply"},
        response={"draft": draft},
    )
    _touch_handled(item, current_user)
    db.commit()
    return {"success": True, "draft": draft}


@router.post("/items/{item_id}/translate")
def translate_customer_service_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动翻译客服事项（手动触发，不自动翻译）"""
    require_cs_permission(current_user, "customer_service:translate")
    item = _get_visible_item(db, item_id, current_user)
    service = CustomerTranslationService(db)
    result = service.translate_item(item)
    _record_action(
        db,
        item,
        current_user,
        "translate_item",
        request={"target": "item"},
        response={k: v for k, v in result.items() if k not in ("content_zh",)},
        success=result.get("success", False),
        error=result.get("error", ""),
    )
    _touch_handled(item, current_user)
    db.commit()
    return result


@router.post("/messages/{message_id}/translate")
def translate_customer_service_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动翻译单条客服消息（手动触发，不自动翻译）"""
    message = db.query(CustomerServiceMessage).filter(
        CustomerServiceMessage.id == message_id
    ).first()
    if not message:
        raise HTTPException(status_code=404, detail="消息不存在")
    # 权限校验：通过 item 访问权限
    _get_visible_item(db, message.item_id, current_user)
    require_cs_permission(current_user, "customer_service:translate")
    service = CustomerTranslationService(db)
    result = service.translate_message(message)
    _record_action(
        db,
        message.item,
        current_user,
        "translate_message",
        request={"target": "message", "message_id": message_id},
        response={k: v for k, v in result.items() if k not in ("message_text_zh",)},
        success=result.get("success", False),
        error=result.get("error", ""),
    )
    db.commit()
    return result


@router.post("/items/{item_id}/reply")
def reply_customer_service_item(
    item_id: int,
    data: ReplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    message = data.message.strip()
    if len(message) < 8:
        raise HTTPException(status_code=400, detail="回复内容过短")
    if _contains_cjk(message):
        raise HTTPException(status_code=400, detail="回复草稿含中文，请改为俄语后发送")

    item = _get_visible_item(db, item_id, current_user)
    # 按 channel 检查写权限
    if item.channel == "question":
        require_cs_permission(current_user, "customer_service:answer_question")
    elif item.channel == "feedback":
        require_cs_permission(current_user, "customer_service:reply_feedback")
    elif item.channel == "chat":
        require_cs_permission(current_user, "customer_service:send_chat")
    else:
        raise HTTPException(status_code=400, detail="该类型不支持此操作")
    client = WBCustomerClient(item.shop.api_token)
    response: Dict[str, Any] = {}
    action_type = "reply"
    is_edit = item.reply_status == "answered"  # 已回复的走编辑接口

    try:
        if item.channel == "question":
            if is_edit:
                response = client.edit_question_answer(item.external_id, message)
                action_type = "edit_answer"
            else:
                response = client.answer_question(item.external_id, message)
        elif item.channel == "feedback":
            if is_edit:
                response = client.edit_feedback_answer(item.external_id, message)
                action_type = "edit_answer"
            else:
                response = client.answer_feedback(item.external_id, message)
        elif item.channel == "chat":
            reply_sign = item.reply_sign or _raw(item).get("replySign") or _raw(item).get("reply_sign")
            if not reply_sign:
                raise HTTPException(status_code=400, detail="该聊天缺少 replySign，不能从系统直接发送")
            response = client.send_chat_message(reply_sign, message)
        else:
            raise HTTPException(status_code=400, detail="该类型不能使用普通回复，请使用退货处理")
    except WBCustomerRateLimit as exc:
        _record_action(db, item, current_user, action_type, request={"message": message}, success=False, error=str(exc))
        db.commit()
        raise HTTPException(status_code=429, detail=f"WB API 限流: {exc}")
    except WBCustomerAPIError as exc:
        _record_action(db, item, current_user, action_type, request={"message": message}, success=False, error=str(exc))
        db.commit()
        err_str = str(exc)
        if "token 无效" in err_str or "401" in err_str:
            raise HTTPException(status_code=401, detail=f"WB API 认证失败: {exc}")
        elif "权限不足" in err_str or "403" in err_str:
            raise HTTPException(status_code=403, detail=f"WB API 权限不足: {exc}")
        else:
            raise HTTPException(status_code=502, detail=f"WB API 请求失败: {exc}")

    first_response = item.first_replied_at is None
    now = _now()
    if first_response:
        item.first_replied_by = current_user.username
        item.first_replied_at = now
    item.reply_status = "answered"
    item.status = "replied"
    _touch_handled(item, current_user, now)
    db.add(CustomerServiceMessage(
        item_id=item.id,
        external_message_id=f"local:{item.id}:{now.isoformat()}",
        direction="seller",
        sender_type="seller",
        sender_name=current_user.username,
        message_text=message,
        attachments_json="[]",
        created_at_external=now,
        raw_json=_json({"local": True, "response": response}),
    ))
    _record_action(
        db,
        item,
        current_user,
        action_type,
        request={"message": message},
        response=response,
        first_response=first_response,
    )
    db.commit()
    return {"success": True, "message": "回复已发送"}


@router.post("/items/{item_id}/assign-owner")
def assign_customer_service_item(
    item_id: int,
    data: AssignOwnerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = _get_visible_item(db, item_id, current_user)
    item.assigned_owner = data.assigned_owner.strip()
    item.assigned_user_id = data.assigned_user_id
    item.handover_note = data.handover_note or ""
    item.assignment_status = "assigned"
    item.status = "pending_internal"
    _touch_handled(item, current_user)
    _record_action(db, item, current_user, "assign_owner", request=data.dict())
    db.commit()
    return {"success": True, "item": _serialize_item(item)}


@router.patch("/items/{item_id}/status")
def update_customer_service_status(
    item_id: int,
    data: StatusUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_cs_permission(current_user, "customer_service:status")
    allowed = {"open", "pending_internal", "replied", "closed", "archived"}
    allowed_reply_status = {"unanswered", "answered", "failed"}
    if data.status not in allowed:
        raise HTTPException(status_code=400, detail="无效状态")
    if data.reply_status is not None and data.reply_status not in allowed_reply_status:
        raise HTTPException(status_code=400, detail="无效回复状态")
    item = _get_visible_item(db, item_id, current_user)
    item.status = data.status
    if data.reply_status is not None:
        item.reply_status = data.reply_status
    if data.status == "archived":
        item.is_archived = True
    if data.status in ("closed", "archived"):
        item.closed_by = current_user.username
        item.closed_at = _now()
        item.assignment_status = "closed"
    else:
        item.closed_by = None
        item.closed_at = None
        if item.assignment_status == "closed":
            item.assignment_status = "assigned" if item.assigned_owner else "unassigned"
    _touch_handled(item, current_user)
    _record_action(db, item, current_user, f"status_{data.status}", request=data.dict())
    db.commit()
    return {"success": True, "item": _serialize_item(item)}


@router.patch("/items/{item_id}/note")
def update_customer_service_internal_note(
    item_id: int,
    data: InternalNoteUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_cs_permission(current_user, "customer_service:note")
    item = _get_visible_item(db, item_id, current_user)
    if item.channel not in ("chat", "return_claim"):
        raise HTTPException(status_code=400, detail="仅买家聊天和买家退货支持客服备注")
    old_note = item.internal_note or ""
    note = (data.internal_note or "").strip()
    if len(note) > 5000:
        raise HTTPException(status_code=400, detail="备注不能超过 5000 字")
    item.internal_note = note
    item.internal_note_updated_by = current_user.username
    item.internal_note_updated_at = _now()
    _touch_handled(item, current_user)
    _record_action(db, item, current_user, "note_update", request={
        "old_note_length": len(old_note),
        "new_note_length": len(note),
        "new_note_preview": note[:80] if note else "",
    })
    db.commit()
    db.refresh(item)
    return {"success": True, "item": _serialize_item(item, include_messages=True, include_actions=True)}


@router.post("/returns/{item_id}/answer")
def answer_return_claim(
    item_id: int,
    data: ReturnAnswerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_cs_permission(current_user, "customer_service:handle_return")
    item = _get_visible_item(db, item_id, current_user)
    if item.channel != "return_claim":
        raise HTTPException(status_code=400, detail="不是退货申请")
    client = WBCustomerClient(item.shop.api_token)
    try:
        response = client.answer_return_claim(item.external_id, data.action, data.comment)
    except WBCustomerRateLimit as exc:
        _record_action(db, item, current_user, f"return_{data.action}", request=data.dict(), success=False, error=str(exc))
        db.commit()
        raise HTTPException(status_code=429, detail=f"WB API 限流: {exc}")
    except WBCustomerAPIError as exc:
        _record_action(db, item, current_user, f"return_{data.action}", request=data.dict(), success=False, error=str(exc))
        db.commit()
        err_str = str(exc)
        if "token 无效" in err_str or "401" in err_str:
            raise HTTPException(status_code=401, detail=f"WB API 认证失败: {exc}")
        elif "权限不足" in err_str or "403" in err_str:
            raise HTTPException(status_code=403, detail=f"WB API 权限不足: {exc}")
        else:
            raise HTTPException(status_code=502, detail=f"WB API 请求失败: {exc}")

    item.reply_status = "answered"
    item.status = "closed"
    item.closed_by = current_user.username
    item.closed_at = _now()
    _touch_handled(item, current_user)
    _record_action(db, item, current_user, f"return_{data.action}", request=data.dict(), response=response)
    db.commit()
    return {"success": True, "message": "退货申请已处理"}


@router.get("/returns/{item_id}/actions")
def get_return_claim_actions(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回退货申请的可用操作按钮列表，对应WB卖家后台的3个选项"""
    require_cs_permission(current_user, "customer_service:read")
    item = _get_visible_item(db, item_id, current_user)
    if item.channel != "return_claim":
        raise HTTPException(status_code=400, detail="不是退货申请")
    raw = _raw(item)
    actions: list = raw.get("actions") or raw.get("availableActions") or []
    if not actions:
        return {"actions": []}
    # 映射 WB 6个技术 action -> 3个一级按钮（匹配WB卖家后台）
    # autorefund1 = 批准无需退货
    # approve2 = 批准并回收商品
    # reject1/2/3/custom = 拒绝退货（下一级再选）
    buttons = []
    if "autorefund1" in actions:
        buttons.append({"action": "autorefund1", "label": "批准无需退货"})
    if "approve2" in actions:
        buttons.append({"action": "approve2", "label": "批准并回收商品"})
    reject_actions = [a for a in actions if a in ("reject1", "reject2", "reject3", "rejectcustom", "reject")]
    if reject_actions:
        buttons.append({"action": "_reject", "label": "拒绝退货"})
    return {"actions": buttons}


@router.post("/questions/{item_id}/reject")
def reject_question(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """拒绝问题"""
    require_cs_permission(current_user, "customer_service:reject_question")
    item = _get_visible_item(db, item_id, current_user)
    if item.channel != "question":
        raise HTTPException(status_code=400, detail="不是问答")
    client = WBCustomerClient(item.shop.api_token)
    try:
        response = client.reject_question(item.external_id)
    except WBCustomerRateLimit as exc:
        _record_action(db, item, current_user, "reject_question", success=False, error=str(exc))
        db.commit()
        raise HTTPException(status_code=429, detail=f"WB API 限流: {exc}")
    except WBCustomerAPIError as exc:
        _record_action(db, item, current_user, "reject_question", success=False, error=str(exc))
        db.commit()
        raise HTTPException(status_code=502, detail=f"WB API 请求失败: {exc}")
    item.reply_status = "answered"
    item.status = "closed"
    item.closed_by = current_user.username
    item.closed_at = _now()
    _touch_handled(item, current_user)
    _record_action(db, item, current_user, "reject_question", response=response)
    db.commit()
    return {"success": True, "message": "问题已拒绝"}


@router.post("/items/{item_id}/mark-read")
def mark_customer_service_item_read(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_cs_permission(current_user, "customer_service:read")
    item = _get_visible_item(db, item_id, current_user)
    item.is_viewed = True
    _touch_handled(item, current_user)
    _record_action(db, item, current_user, "mark_read")
    db.commit()
    return {"success": True}


@router.get("/attachments/{download_id}")
def proxy_customer_service_attachment(
    download_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_cs_permission(current_user, "customer_service:read")
    message = db.query(CustomerServiceMessage).filter(
        CustomerServiceMessage.attachments_json.contains(download_id)
    ).first()
    if not message:
        raise HTTPException(status_code=404, detail="附件不存在")
    item = _get_visible_item(db, message.item_id, current_user)
    url = WBCustomerClient(item.shop.api_token).download_url(download_id)
    client = httpx.Client(timeout=60.0)
    request = client.build_request("GET", url, headers={"Authorization": item.shop.api_token})
    response = client.send(request, stream=True)
    if response.status_code != 200:
        response.close()
        client.close()
        if response.status_code in (202, 451):
            raise HTTPException(status_code=202, detail="附件仍在 WB 准备中，请稍后再试")
        raise HTTPException(status_code=response.status_code, detail=response.text[:500])

    return StreamingResponse(
        response.iter_bytes(),
        media_type=response.headers.get("content-type", "application/octet-stream"),
        background=BackgroundTask(lambda: (response.close(), client.close())),
    )


def _run_customer_service_sync_task(shop_id: int, channel: str, days: int, log_id: int, force_full_sync: bool = False) -> None:
    db = SessionLocal()
    lock = SyncLockService(db)
    lock_acquired = False
    try:
        shop = db.query(Shop).filter(Shop.id == shop_id, Shop.is_active == True).first()
        if not shop or shop.platform != "wildberries":
            return
        # 获取分布式锁
        lock_acquired = lock.acquire(shop_id, "customer_service")
        if not lock_acquired:
            sync_log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
            if sync_log:
                sync_log.status = "skipped"
                sync_log.message = f"已有同步在进行中，跳过（{shop.name}）"
                sync_log.finished_at = datetime.now(SHANGHAI_TZ)
                db.commit()
            return
        service = CustomerServiceSyncService(db, shop)
        result = {"questions": None, "feedbacks": None, "chats": None, "return_claims": None}
        try:
            if channel == "questions":
                result["questions"] = service.sync_questions(days=days)
            elif channel == "feedbacks":
                result["feedbacks"] = service.sync_feedbacks(days=days)
            elif channel == "chats":
                result["chats"] = service.sync_chats(force_full_sync=force_full_sync)
            elif channel == "return_claims":
                result["return_claims"] = service.sync_return_claims()
            else:
                result = service.sync_all(days=days)

            # 统计总条数（单 channel 用 result.count；sync_all 用 result.count）
            total = 0
            if isinstance(result, dict):
                # sync_all 返回结构：{success, count, results, ...}
                if "results" in result:
                    total = result.get("count", 0)
                else:
                    # 单 channel：result 就是 {success, count, ...}
                    total = result.get("count", 0)

            # 检查子任务实际是否成功
            overall_success = True
            rate_limited = False
            if isinstance(result, dict):
                if "results" in result:
                    # sync_all：顶层 success
                    overall_success = result.get("success", True)
                    if not overall_success:
                        rate_limited = bool(result.get("rate_limited_channels"))
                else:
                    # 单 channel：success 在 result 本身
                    overall_success = result.get("success", True)
                    if not overall_success:
                        rate_limited = result.get("rate_limited", False)

            sync_log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
            if sync_log:
                if not overall_success:
                    sync_log.status = "rate_limited" if rate_limited else "failed"
                    err_msg = result.get("errors", []) if isinstance(result, dict) else []
                    sync_log.message = f"同步失败: {err_msg}" if err_msg else ("WB 限流" if rate_limited else "同步失败")
                    sync_log.records_count = total
                else:
                    sync_log.status = "completed"
                    sync_log.records_count = total
                    sync_log.message = f"同步完成（{shop.name}）"
                sync_log.finished_at = datetime.now(SHANGHAI_TZ)
                db.commit()
        except WBCustomerRateLimit as exc:
            sync_log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
            if sync_log:
                sync_log.status = "rate_limited"
                sync_log.message = f"WB 限流: {exc}"
                sync_log.finished_at = datetime.now(SHANGHAI_TZ)
                db.commit()
        except WBCustomerAPIError as exc:
            sync_log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
            if sync_log:
                sync_log.status = "failed"
                sync_log.message = f"WB API 错误: {exc}"
                sync_log.finished_at = datetime.now(SHANGHAI_TZ)
                db.commit()
        except Exception as exc:
            sync_log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
            if sync_log:
                sync_log.status = "failed"
                sync_log.message = f"同步异常: {exc}"
                sync_log.finished_at = datetime.now(SHANGHAI_TZ)
                db.commit()
    finally:
        if lock_acquired:
            lock.release()
        db.close()
        db.close()


def _visible_query(query, current_user: User):
    """兼容旧函数，内部委托到 permissions.filter_customer_query"""
    return filter_customer_query(current_user, query)


def _get_visible_item(db: Session, item_id: int, current_user: User) -> CustomerServiceItem:
    item = _visible_query(
        db.query(CustomerServiceItem),
        current_user,
    ).filter(CustomerServiceItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="客服事项不存在或无权限")
    if not can_access_customer_item(current_user, item):
        raise HTTPException(status_code=404, detail="客服事项不存在或无权限")
    return item


def _allowed_owners(user: User) -> List[str]:
    owners = getattr(user, "allowed_owners", None)
    if isinstance(owners, (list, tuple, set)):
        return [str(o) for o in owners if o]
    return []


def _role(user: User) -> str:
    value = getattr(user, "role", "")
    return getattr(value, "value", value)


def _is_admin(user: User) -> bool:
    return _role(user) == "admin"


def _require_manager(user: User) -> None:
    if _role(user) not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="仅管理员或经理可执行该操作")


def _service_display_status(item: CustomerServiceItem) -> Dict[str, str]:
    """返回卡片/详情页展示用的业务状态，不暴露内部字段名。"""
    if item.status == "archived":
        return {"key": "archived", "label": "已归档", "type": "info"}
    if item.status == "closed":
        if item.channel == "return_claim":
            raw = _raw(item)
            wb_status = raw.get("status")
            wb_status_ex = raw.get("status_ex")
            # WB status: 0=新申请, 1=拒绝, 2=批准
            # WB status_ex: 1=拒绝理由, 5=批准不退货, 10=批准需退货
            if wb_status == 1 or wb_status_ex == 1:
                label = "退货已拒绝"
            elif wb_status == 2 and wb_status_ex == 5:
                label = "已批准（无需退货）"
            elif wb_status == 2 and wb_status_ex == 10:
                label = "已批准（待买家退货）"
            else:
                label = "退货已处理"
            if item.external_created_at and item.closed_at:
                diff = item.closed_at - item.external_created_at
                diff_h = diff.total_seconds() / 3600
                if diff_h < 1:
                    label += f"（{round(diff.total_seconds() / 60)}分钟）"
                else:
                    label += f"（{round(diff_h * 10) / 10}小时）"
            return {"key": "return_closed", "label": label, "type": "info"}
        if item.channel == "chat":
            return {"key": "chat_finished", "label": "已完结", "type": "info"}
        return {"key": "closed", "label": "已关闭", "type": "info"}
    if item.status == "pending_internal":
        return {"key": "pending_internal", "label": "内部处理中", "type": "warning"}

    if item.channel == "chat":
        if item.status == "pending_internal":
            return {"key": "pending_internal", "label": "内部处理中", "type": "warning"}
        if item.reply_status == "unanswered":
            return {"key": "waiting_seller", "label": "待卖家回复", "type": "danger"}
        if item.status == "replied" or item.reply_status == "answered":
            return {"key": "waiting_buyer", "label": "待买家回复", "type": "success"}
        return {"key": "waiting_seller", "label": "待卖家回复", "type": "danger"}

    if item.channel == "return_claim":
        if item.status == "open" and item.reply_status == "unanswered":
            return {"key": "return_pending", "label": "退货待处理", "type": "danger"}
        return {"key": "return_open", "label": "退货处理中", "type": "warning"}

    if item.reply_status == "unanswered":
        return {"key": "unanswered", "label": "待回复", "type": "danger"}
    if item.reply_status == "answered":
        return {"key": "answered", "label": "已回复", "type": "success"}

    return {"key": item.status or "open", "label": "待处理", "type": "danger"}


def _serialize_item(
    item: CustomerServiceItem,
    include_messages: bool = False,
    include_actions: bool = False,
) -> Dict[str, Any]:
    data = {
        "id": item.id,
        "shop_id": item.shop_id,
        "shop_name": item.shop.name if item.shop else "",
        "platform": item.platform,
        "channel": item.channel,
        "external_id": item.external_id,
        "external_status": item.external_status,
        "product_id": item.product_id,
        "nm_id": item.nm_id,
        "sku": item.sku,
        "product_name": item.product_name,
        "product_name_ru": item.product_name_ru,
        "owner": item.owner,
        "product_matched": item.product_matched,
        "assigned_owner": item.assigned_owner,
        "assigned_user_id": item.assigned_user_id,
        "assignment_status": item.assignment_status,
        "handover_note": item.handover_note,
        "internal_note": getattr(item, "internal_note", "") or "",
        "internal_note_updated_by": item.internal_note_updated_by,
        "internal_note_updated_at": _fmt(item.internal_note_updated_at),
        "customer_name": item.customer_name,
        "title": item.title,
        "content": item.content,
        "content_zh": item.content_zh,
        "title_zh": item.title_zh,
        "translation_status": item.translation_status,
        "translated_at": _fmt(item.translated_at),
        "translation_error": item.translation_error,
        "rating": item.rating,
        "rating_display": _rating_stars(item.rating) if item.rating else None,
        "status": item.status,
        "reply_status": item.reply_status,
        "priority": item.priority,
        "risk_level": item.risk_level,
        "issue_type": item.issue_type,
        "is_viewed": item.is_viewed,
        "first_replied_by": item.first_replied_by,
        "first_replied_at": _fmt(item.first_replied_at),
        "last_handled_by": item.last_handled_by,
        "last_handled_at": _fmt(item.last_handled_at),
        "closed_by": item.closed_by,
        "closed_at": _fmt(item.closed_at),
        "external_created_at": _fmt(item.external_created_at),
        "external_updated_at": _fmt(item.external_updated_at),
        "sla_deadline_at": _fmt(item.sla_deadline_at),
        "sla_hours_left": _hours_left(item.sla_deadline_at),
        "is_overdue": item.is_overdue,
        "display_status": _service_display_status(item),
        "return_deadline_hours": item.return_deadline_hours,
        "raw_json": _raw(item),
        "created_at": _fmt(item.created_at),
        "updated_at": _fmt(item.updated_at),
    }
    if include_messages:
        messages = sorted(item.messages or [], key=lambda m: m.created_at_external or m.created_at)
        data["messages"] = [_serialize_message(m) for m in messages]
    if include_actions:
        actions = sorted(item.actions or [], key=lambda a: a.action_time, reverse=True)
        data["actions"] = [_serialize_action(a) for a in actions[:50]]
    return data


def _serialize_message(message: CustomerServiceMessage) -> Dict[str, Any]:
    return {
        "id": message.id,
        "external_message_id": message.external_message_id,
        "direction": message.direction,
        "sender_type": message.sender_type,
        "sender_name": message.sender_name,
        "message_text": message.message_text,
        "message_text_zh": message.message_text_zh,
        "translation_status": message.translation_status,
        "translated_at": _fmt(message.translated_at),
        "translation_error": message.translation_error,
        "attachments": _json_loads(message.attachments_json, []),
        "created_at_external": _fmt(message.created_at_external),
        "created_at": _fmt(message.created_at),
    }


def _serialize_action(action: CustomerServiceAction) -> Dict[str, Any]:
    return {
        "id": action.id,
        "user_id": action.user_id,
        "username": action.user.username if action.user else "",
        "action_type": action.action_type,
        "action_time": _fmt(action.action_time),
        "success": action.success,
        "error": action.error,
        "first_response": action.first_response,
        "effective_response": action.effective_response,
        "response_minutes": action.response_minutes,
        "quality_score": action.quality_score,
        "quality_result": action.quality_result,
        "quality_reason": action.quality_reason,
    }


def _record_action(
    db: Session,
    item: CustomerServiceItem,
    user: User,
    action_type: str,
    request: Optional[Dict[str, Any]] = None,
    response: Optional[Dict[str, Any]] = None,
    success: bool = True,
    error: str = "",
    first_response: bool = False,
) -> None:
    response_minutes = None
    if first_response and item.external_created_at:
        response_minutes = max(0, (_now() - item.external_created_at).total_seconds() / 60)
    db.add(CustomerServiceAction(
        item_id=item.id,
        user_id=user.id,
        action_type=action_type,
        request_json=_json(_audit_sanitize(request or {})),
        response_json=_json(_audit_sanitize(response or {})),
        success=success,
        error=error,
        first_response=first_response,
        effective_response=bool(first_response and response_minutes is not None and response_minutes <= 24 * 60),
        response_minutes=response_minutes,
    ))


def _touch_handled(item: CustomerServiceItem, user: User, now: Optional[datetime] = None) -> None:
    item.last_handled_by = user.username
    item.last_handled_at = now or _now()
    item.updated_at = now or _now()


def _make_russian_reply_draft(item: CustomerServiceItem) -> str:
    product = item.product_name_ru or item.sku or item.nm_id or "товар"
    if item.channel == "return_claim":
        return (
            f"Здравствуйте. Спасибо за обращение по товару {product}. "
            "Мы проверим информацию по заявке на возврат и примем решение в ближайшее время."
        )
    if item.channel == "feedback" and item.rating and item.rating <= 3:
        return (
            f"Здравствуйте. Нам жаль, что товар {product} не полностью оправдал ожидания. "
            "Спасибо за подробный отзыв, мы передадим информацию ответственному специалисту и проверим качество партии."
        )
    if item.channel == "question":
        return (
            f"Здравствуйте. Спасибо за вопрос по товару {product}. "
            "Уточните, пожалуйста, какой именно параметр вас интересует, и мы поможем с выбором."
        )
    return (
        f"Здравствуйте. Спасибо за обращение по товару {product}. "
        "Мы проверим информацию и вернемся с ответом как можно скорее."
    )


# deprecated: WB 无稳定跨渠道买家ID，不再用于跨channel聚合
def _buyer_key(item: CustomerServiceItem) -> str:
    """已废弃，保留仅用于避免现有调用报错"""
    return ""


def _rating_stars(rating: Optional[int]) -> str:
    if not rating:
        return ""
    return "★" * rating + "☆" * (5 - rating)


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _raw(item: CustomerServiceItem) -> Dict[str, Any]:
    return _json_loads(item.raw_json, {})


def _audit_sanitize(data: Any, depth: int = 0) -> Any:
    """审计日志脱敏：长字符串截断至 80 字，移除 Authorization/Token 等敏感字段"""
    if depth > 5:
        return "<max_depth>"
    if isinstance(data, dict):
        SENSITIVE_KEYS = {"authorization", "token", "api_key", "apikey", "password", "secret", "header"}
        result = {}
        for k, v in data.items():
            k_lower = k.lower()
            if k_lower in SENSITIVE_KEYS:
                result[k] = "<redacted>"
            else:
                result[k] = _audit_sanitize(v, depth + 1)
        return result
    if isinstance(data, (list, tuple)):
        return [_audit_sanitize(v, depth + 1) for v in data[:50]]  # 最多 50 项
    if isinstance(data, str) and len(data) > 80:
        return data[:80] + "..."
    return data


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _fmt(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _hours_left(deadline: Optional[datetime]) -> Optional[float]:
    if not deadline:
        return None
    return round((deadline - _now()).total_seconds() / 3600, 2)


def _now() -> datetime:
    return datetime.now(SHANGHAI_TZ).replace(tzinfo=None)
