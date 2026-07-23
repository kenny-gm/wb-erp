"""Customer service AI auto-reply orchestration."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.models import (
    AIPromptTemplate,
    CustomerAutoReplyItem,
    CustomerAutoReplyRun,
    CustomerServiceAction,
    CustomerServiceItem,
    CustomerServiceMessage,
    Product,
    ProductKnowledge,
    Shop,
    SystemSetting,
)
from app.services.ai_client import AIClient, AIClientError
from app.services.ai_prompt_service import get_active_template, render_template
from app.services.wb_customer_client import WBCustomerAPIError, WBCustomerClient, WBCustomerRateLimit


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
AUTO_REPLY_USER = "ai_auto_reply"
AUTO_REPLY_CHANNELS = {"feedback", "question", "chat"}
CUSTOMER_REPLY_TEMPLATE_KEYS = {
    "feedback": "customer_reply_feedback",
    "question": "customer_reply_question",
    "chat": "customer_reply_chat",
}
AI_DRAFT_MIN_MAX_TOKENS = 1200
AI_DRAFT_RETRY_MAX_TOKENS = 1800


DEFAULT_AUTO_REPLY_SETTINGS = {
    "enabled": False,
    "channels": ["feedback", "question", "chat"],
    "feedback_negative_enabled": True,
    "max_per_run": 20,
    "max_per_shop_per_day": 50,
    "consecutive_failures_pause": 5,
}


class CustomerAutoReplyService:
    def __init__(self, db: Session):
        self.db = db

    def get_settings(self) -> Dict[str, Any]:
        return _get_auto_reply_settings(self.db)

    def update_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        settings = self.get_settings()
        allowed_channels = [c for c in payload.get("channels", settings["channels"]) if c in AUTO_REPLY_CHANNELS]
        next_settings = {
            "enabled": bool(payload.get("enabled", settings["enabled"])),
            "channels": allowed_channels or ["feedback", "question", "chat"],
            "feedback_negative_enabled": bool(payload.get("feedback_negative_enabled", settings["feedback_negative_enabled"])),
            "max_per_run": _clamp_int(payload.get("max_per_run", settings["max_per_run"]), 1, 100),
            "max_per_shop_per_day": _clamp_int(payload.get("max_per_shop_per_day", settings["max_per_shop_per_day"]), 1, 500),
            "consecutive_failures_pause": _clamp_int(
                payload.get("consecutive_failures_pause", settings["consecutive_failures_pause"]),
                1,
                50,
            ),
        }
        _set_setting(self.db, "customer_ai_auto_reply_enabled", _bool_text(next_settings["enabled"]))
        _set_setting(self.db, "customer_ai_auto_reply_channels", json.dumps(next_settings["channels"], ensure_ascii=False))
        _set_setting(self.db, "customer_ai_auto_reply_feedback_negative_enabled", _bool_text(next_settings["feedback_negative_enabled"]))
        _set_setting(self.db, "customer_ai_auto_reply_max_per_run", str(next_settings["max_per_run"]))
        _set_setting(self.db, "customer_ai_auto_reply_max_per_shop_per_day", str(next_settings["max_per_shop_per_day"]))
        _set_setting(self.db, "customer_ai_auto_reply_consecutive_failures_pause", str(next_settings["consecutive_failures_pause"]))
        self.db.commit()
        return self.get_settings()

    def run(self, shop_id: Optional[int] = None, trigger_source: str = "sync") -> Optional[CustomerAutoReplyRun]:
        settings = self.get_settings()
        if not settings["enabled"]:
            return None

        run = CustomerAutoReplyRun(
            trigger_source=trigger_source,
            mode="send",
            status="running",
            shop_id=shop_id,
            started_at=_now(),
            created_at=_now(),
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)

        try:
            candidates = self._candidate_items(settings, shop_id)
            run.scanned_count = len(candidates)
            for item in candidates:
                if run.sent_count >= settings["max_per_run"]:
                    run.skipped_count += 1
                    continue
                if self._shop_sent_today(item.shop_id) >= settings["max_per_shop_per_day"]:
                    self._record_report_item(run, item, "skipped", "", "已达到店铺每日上限")
                    run.skipped_count += 1
                    continue
                decision = self._process_item(run, item, settings)
                if decision == "sent":
                    run.sent_count += 1
                    run.draft_count += 1
                elif decision == "blocked":
                    run.blocked_count += 1
                    run.draft_count += 1
                elif decision == "failed":
                    run.failed_count += 1
                else:
                    run.skipped_count += 1
                self.db.commit()

            run.status = "completed"
            run.finished_at = _now()
            run.message = "自动回复运行完成"
            self._pause_on_failures(settings)
            self.db.commit()
            return run
        except Exception as exc:
            run.status = "failed"
            run.failed_count += 1
            run.message = str(exc)[:1000]
            run.finished_at = _now()
            self.db.commit()
            return run

    def _candidate_items(self, settings: Dict[str, Any], shop_id: Optional[int]) -> List[CustomerServiceItem]:
        query = self.db.query(CustomerServiceItem).filter(
            CustomerServiceItem.platform == "wildberries",
            CustomerServiceItem.channel.in_(settings["channels"]),
            CustomerServiceItem.status == "open",
            CustomerServiceItem.reply_status == "unanswered",
            CustomerServiceItem.is_archived == False,
        )
        if shop_id:
            query = query.filter(CustomerServiceItem.shop_id == shop_id)
        if not settings["feedback_negative_enabled"]:
            query = query.filter(
                (CustomerServiceItem.channel != "feedback")
                | (CustomerServiceItem.rating.is_(None))
                | (CustomerServiceItem.rating >= 4)
            )
        return query.order_by(
            CustomerServiceItem.external_created_at.is_(None),
            CustomerServiceItem.external_created_at.asc(),
            CustomerServiceItem.id.asc(),
        ).limit(settings["max_per_run"] * 3).all()

    def _process_item(self, run: CustomerAutoReplyRun, item: CustomerServiceItem, settings: Dict[str, Any]) -> str:
        latest_buyer_message_id = _latest_buyer_message_id(item)
        auto_reply_key = f"{item.shop_id}:{item.channel}:{item.id}:{latest_buyer_message_id}"
        if self.db.query(CustomerAutoReplyItem).filter(CustomerAutoReplyItem.auto_reply_key == auto_reply_key).first():
            self._record_report_item(run, item, "skipped", "", "该买家消息已处理过", None, latest_buyer_message_id)
            return "skipped"

        report_row = CustomerAutoReplyItem(
            run_id=run.id,
            item_id=item.id,
            shop_id=item.shop_id,
            channel=item.channel,
            auto_reply_key=auto_reply_key,
            latest_buyer_message_id=latest_buyer_message_id,
            decision="processing",
            created_at=_now(),
            updated_at=_now(),
        )
        try:
            self.db.add(report_row)
            self.db.commit()
            draft, template_key, template, knowledge_sources = self._generate_draft(item)
            block_reason = self._validate_draft(item, draft)
            if block_reason:
                self._update_report_item(report_row, "blocked", draft, block_reason, template_key, template.version)
                self._record_action(item, "auto_reply_blocked", {"auto_reply_key": auto_reply_key}, {"draft": draft}, False, block_reason)
                return "blocked"

            response, action_type = self._send_reply(item, draft)
            self._mark_replied(item, draft, response)
            self._update_report_item(report_row, "sent", draft, "", template_key, template.version, response)
            self._record_action(
                item,
                "auto_reply_sent",
                {"auto_reply_key": auto_reply_key, "template": template_key, "knowledge_sources": knowledge_sources},
                {"draft": draft, "wb_response": response, "action_type": action_type},
                True,
                "",
                item.first_replied_at is None,
            )
            return "sent"
        except IntegrityError:
            self.db.rollback()
            self._record_report_item(run, item, "skipped", "", "幂等键已存在", None, latest_buyer_message_id)
            return "skipped"
        except Exception as exc:
            if getattr(report_row, "id", None):
                self._update_report_item(report_row, "failed", "", str(exc))
            else:
                self._record_report_item(run, item, "failed", "", str(exc), auto_reply_key, latest_buyer_message_id)
            self._record_action(item, "auto_reply_failed", {"auto_reply_key": auto_reply_key}, {}, False, str(exc))
            return "failed"

    def _generate_draft(self, item: CustomerServiceItem) -> Tuple[str, str, AIPromptTemplate, List[Dict[str, Any]]]:
        template_key = CUSTOMER_REPLY_TEMPLATE_KEYS.get(item.channel)
        if not template_key:
            raise AIClientError(f"自动回复不支持该渠道：{item.channel}")
        template = get_active_template(self.db, template_key)
        if not template:
            raise AIClientError(f"客服回复 Prompt 未配置：{template_key}")

        knowledge = _build_product_knowledge_context(self.db, item)
        variables = _build_prompt_variables(item, knowledge["context"])
        system_prompt = template.system_prompt
        user_prompt = render_template(template.user_prompt_template, variables)
        ai_client = AIClient(self.db)
        max_tokens = max(int(template.max_tokens or 0), AI_DRAFT_MIN_MAX_TOKENS)
        try:
            output = ai_client.chat_json(system_prompt, user_prompt, template.temperature, max_tokens)
            draft = _extract_ai_reply_draft(output)
            if not draft:
                draft = _extract_ai_reply_draft(ai_client.chat_text(system_prompt, user_prompt, template.temperature, max_tokens))
        except AIClientError as exc:
            if "不是合法 JSON" not in str(exc):
                raise
            draft = _extract_ai_reply_draft(ai_client.chat_text(system_prompt, user_prompt, template.temperature, max_tokens))
        if not draft and max_tokens < AI_DRAFT_RETRY_MAX_TOKENS:
            draft = _extract_ai_reply_draft(
                ai_client.chat_text(system_prompt, user_prompt, template.temperature, AI_DRAFT_RETRY_MAX_TOKENS)
            )
        if not draft:
            raise AIClientError("AI 未返回回复内容")
        return draft, template_key, template, knowledge["sources"]

    def _validate_draft(self, item: CustomerServiceItem, draft: str) -> str:
        if _contains_cjk(draft):
            return "AI 回复含中文"
        if not draft.lower().startswith("здравствуйте"):
            return "AI 回复未以 Здравствуйте 开头"
        blocked_tokens = [str(item.nm_id or ""), str(item.sku or "")]
        for token in blocked_tokens:
            if token and len(token) >= 4 and token.lower() in draft.lower():
                return "AI 回复包含内部商品编码"
        risky_patterns = [
            "обязательно вернем деньги",
            "точно вернем деньги",
            "обязательно заменим",
            "точно заменим",
            "компенсац",
            "гарантируем возврат",
            "гарантируем одобрение",
        ]
        lower = draft.lower()
        for pattern in risky_patterns:
            if pattern in lower:
                return f"AI 回复含确定承诺：{pattern}"
        if item.channel == "chat" and not (item.reply_sign or _json_loads(item.raw_json, {}).get("replySign")):
            return "聊天缺少 replySign"
        return ""

    def _send_reply(self, item: CustomerServiceItem, draft: str) -> Tuple[Dict[str, Any], str]:
        client = WBCustomerClient(item.shop.api_token)
        if item.channel == "question":
            return client.answer_question(item.external_id, draft), "reply"
        if item.channel == "feedback":
            return client.answer_feedback(item.external_id, draft), "reply"
        if item.channel == "chat":
            reply_sign = item.reply_sign or _json_loads(item.raw_json, {}).get("replySign") or _json_loads(item.raw_json, {}).get("reply_sign")
            if not reply_sign:
                raise WBCustomerAPIError("该聊天缺少 replySign，不能自动发送")
            return client.send_chat_message(reply_sign, draft), "reply"
        raise WBCustomerAPIError(f"自动回复不支持该渠道：{item.channel}")

    def _mark_replied(self, item: CustomerServiceItem, draft: str, response: Dict[str, Any]) -> None:
        now = _now()
        if item.first_replied_at is None:
            item.first_replied_by = AUTO_REPLY_USER
            item.first_replied_at = now
        item.reply_status = "answered"
        item.status = "replied"
        if item.channel == "question":
            item.answer_visibility = "all"
        item.last_handled_by = AUTO_REPLY_USER
        item.last_handled_at = now
        item.updated_at = now
        self.db.add(CustomerServiceMessage(
            item_id=item.id,
            external_message_id=f"local:auto:{item.id}:{now.isoformat()}",
            direction="seller",
            sender_type="ai_auto",
            sender_name=AUTO_REPLY_USER,
            message_text=draft,
            attachments_json="[]",
            created_at_external=now,
            raw_json=_json({"local": True, "auto_reply": True, "response": response}),
        ))

    def _record_report_item(
        self,
        run: CustomerAutoReplyRun,
        item: CustomerServiceItem,
        decision: str,
        draft: str,
        reason: str,
        auto_reply_key: Optional[str] = None,
        latest_buyer_message_id: str = "",
        prompt_template_key: str = "",
        prompt_version: Optional[int] = None,
        wb_response: Optional[Dict[str, Any]] = None,
    ) -> None:
        row = CustomerAutoReplyItem(
            run_id=run.id,
            item_id=item.id,
            shop_id=item.shop_id,
            channel=item.channel,
            auto_reply_key=auto_reply_key or f"{item.shop_id}:{item.channel}:{item.id}:skipped:{run.id}:{len(run.items or []) + 1}",
            latest_buyer_message_id=latest_buyer_message_id,
            draft_text=draft,
            decision=decision,
            block_reason=reason,
            wb_response_json=_json(wb_response or {}),
            prompt_template_key=prompt_template_key,
            prompt_version=prompt_version,
            created_at=_now(),
            updated_at=_now(),
        )
        self.db.add(row)

    def _update_report_item(
        self,
        row: CustomerAutoReplyItem,
        decision: str,
        draft: str,
        reason: str,
        prompt_template_key: str = "",
        prompt_version: Optional[int] = None,
        wb_response: Optional[Dict[str, Any]] = None,
    ) -> None:
        row.decision = decision
        row.draft_text = draft
        row.block_reason = reason
        row.prompt_template_key = prompt_template_key or row.prompt_template_key
        row.prompt_version = prompt_version if prompt_version is not None else row.prompt_version
        row.wb_response_json = _json(wb_response or {})
        row.updated_at = _now()

    def _record_action(
        self,
        item: CustomerServiceItem,
        action_type: str,
        request: Dict[str, Any],
        response: Dict[str, Any],
        success: bool,
        error: str,
        first_response: bool = False,
    ) -> None:
        response_minutes = None
        if first_response and item.external_created_at:
            response_minutes = max(0, (_now() - item.external_created_at).total_seconds() / 60)
        self.db.add(CustomerServiceAction(
            item_id=item.id,
            user_id=None,
            action_type=action_type,
            request_json=_json(_audit_sanitize(request)),
            response_json=_json(_audit_sanitize(response)),
            success=success,
            error=error,
            first_response=first_response,
            effective_response=bool(first_response and response_minutes is not None and response_minutes <= 24 * 60),
            response_minutes=response_minutes,
        ))

    def _shop_sent_today(self, shop_id: int) -> int:
        today = datetime.combine(_now().date(), time.min)
        return self.db.query(CustomerAutoReplyItem).filter(
            CustomerAutoReplyItem.shop_id == shop_id,
            CustomerAutoReplyItem.decision == "sent",
            CustomerAutoReplyItem.created_at >= today,
        ).count()

    def _pause_on_failures(self, settings: Dict[str, Any]) -> None:
        limit = settings["consecutive_failures_pause"]
        recent = self.db.query(CustomerAutoReplyItem).order_by(CustomerAutoReplyItem.created_at.desc()).limit(limit).all()
        if len(recent) == limit and all(row.decision == "failed" for row in recent):
            _set_setting(self.db, "customer_ai_auto_reply_enabled", "false")


def _get_auto_reply_settings(db: Session) -> Dict[str, Any]:
    values = {row.key: row.value for row in db.query(SystemSetting).filter(SystemSetting.key.like("customer_ai_auto_reply_%")).all()}
    channels = _json_loads(values.get("customer_ai_auto_reply_channels"), DEFAULT_AUTO_REPLY_SETTINGS["channels"])
    return {
        "enabled": _as_bool(values.get("customer_ai_auto_reply_enabled"), DEFAULT_AUTO_REPLY_SETTINGS["enabled"]),
        "channels": [c for c in channels if c in AUTO_REPLY_CHANNELS] or DEFAULT_AUTO_REPLY_SETTINGS["channels"],
        "feedback_negative_enabled": _as_bool(
            values.get("customer_ai_auto_reply_feedback_negative_enabled"),
            DEFAULT_AUTO_REPLY_SETTINGS["feedback_negative_enabled"],
        ),
        "max_per_run": _clamp_int(values.get("customer_ai_auto_reply_max_per_run"), 1, 100, DEFAULT_AUTO_REPLY_SETTINGS["max_per_run"]),
        "max_per_shop_per_day": _clamp_int(
            values.get("customer_ai_auto_reply_max_per_shop_per_day"),
            1,
            500,
            DEFAULT_AUTO_REPLY_SETTINGS["max_per_shop_per_day"],
        ),
        "consecutive_failures_pause": _clamp_int(
            values.get("customer_ai_auto_reply_consecutive_failures_pause"),
            1,
            50,
            DEFAULT_AUTO_REPLY_SETTINGS["consecutive_failures_pause"],
        ),
    }


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row:
        row.value = value
        row.updated_at = _now()
    else:
        db.add(SystemSetting(key=key, value=value, updated_at=_now()))


def _product_name(product: Product) -> str:
    return (product.custom_name or product.name or product.sku or "").strip()


def _product_key(product_name: str) -> str:
    normalized = " ".join((product_name or "").strip().lower().split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _product_for_item(db: Session, item: CustomerServiceItem) -> Optional[Product]:
    product = getattr(item, "product", None)
    if product:
        return product
    if item.product_id:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if product:
            return product
    if item.nm_id:
        product = db.query(Product).filter(Product.nm_id == str(item.nm_id)).first()
        if product:
            return product
    if item.sku:
        return db.query(Product).filter(Product.sku == str(item.sku)).first()
    return None


def _find_product_knowledge_for_item(db: Session, item: CustomerServiceItem) -> Optional[ProductKnowledge]:
    probes = [str(value) for value in (item.nm_id, item.sku) if value]
    for probe in probes:
        profile = db.query(ProductKnowledge).filter(
            ProductKnowledge.status == "active",
            ProductKnowledge.ai_enabled == True,  # noqa: E712
            or_(
                ProductKnowledge.linked_nm_ids_json.like(f"%{probe}%"),
                ProductKnowledge.linked_skus_json.like(f"%{probe}%"),
                ProductKnowledge.aliases_json.like(f"%{probe}%"),
            ),
        ).first()
        if profile:
            return profile

    names: List[str] = []
    product = _product_for_item(db, item)
    if product and _product_name(product):
        names.append(_product_name(product))
    for candidate in (item.product_name, item.title, item.product_name_ru):
        if candidate and candidate not in names:
            names.append(candidate)
    for name in names:
        profile = db.query(ProductKnowledge).filter(
            ProductKnowledge.product_key == _product_key(name),
            ProductKnowledge.status == "active",
            ProductKnowledge.ai_enabled == True,  # noqa: E712
        ).first()
        if profile:
            return profile
    return None


def _build_product_knowledge_context(db: Session, item: CustomerServiceItem) -> Dict[str, Any]:
    profile = _find_product_knowledge_for_item(db, item)
    if not profile:
        return {
            "context": "未命中产品知识库。禁止编造具体产品功能、尺寸、材质、故障处理或售后承诺。",
            "sources": [],
        }

    sections = [
        ("基础信息", profile.basic_info),
        ("功能卖点", profile.features),
        ("使用方法", profile.usage_guide),
        ("故障处理", profile.troubleshooting),
        ("售后边界", profile.after_sales_policy),
    ]
    lines = [f"产品知识库: {profile.product_name}"]
    populated = 0
    for title, value in sections:
        if value and value.strip():
            populated += 1
            lines.append(f"{title}: {value.strip()}")

    faq = _json_loads(profile.faq_json, [])
    faq_count = 0
    if faq:
        lines.append("FAQ:")
        for row in faq[:8]:
            if not isinstance(row, dict):
                continue
            question = str(row.get("question") or row.get("q") or "").strip()
            answer_zh = str(row.get("answer_zh") or row.get("note") or "").strip()
            answer_ru = str(row.get("answer_ru") or row.get("answer") or "").strip()
            if question or answer_zh or answer_ru:
                faq_count += 1
                line = f"- 买家可能问: {question}\n  中文标准答案/处理说明: {answer_zh}"
                if answer_ru:
                    line += f"\n  历史俄语参考: {answer_ru}"
                lines.append(line)

    completeness = min(100, int((populated / len(sections)) * 80) + min(20, faq_count * 4))
    return {
        "context": "\n".join(lines),
        "sources": [{
            "id": profile.id,
            "product_name": profile.product_name,
            "completeness": completeness,
        }],
    }


def _build_prompt_variables(item: CustomerServiceItem, product_knowledge: str) -> Dict[str, str]:
    messages = sorted(item.messages or [], key=lambda m: m.created_at_external or m.created_at)
    messages_text = "\n".join([
        f"{'客服' if m.direction == 'seller' else '买家'}: {m.message_text}"
        for m in messages[-10:]
        if m.message_text
    ])
    raw = _json_loads(item.raw_json, {})
    return {
        "channel": str(item.channel or ""),
        "shop_name": item.shop.name if item.shop else "",
        "product_name": item.product_name or item.title or "",
        "rating": str(item.rating) if item.rating is not None else "",
        "status": str(item.status or ""),
        "reply_status": str(item.reply_status or ""),
        "is_archived": str(bool(item.is_archived)),
        "is_return_related": str(item.channel == "return_claim" or "return" in raw),
        "content": item.content or item.title or "",
        "content_zh": item.content_zh or item.title_zh or "",
        "messages": messages_text,
        "return_context": "",
        "existing_answer": "",
        "internal_note": item.internal_note or "",
        "product_knowledge": product_knowledge,
    }


def _latest_buyer_message_id(item: CustomerServiceItem) -> str:
    messages = [
        message
        for message in (item.messages or [])
        if message.direction == "buyer"
    ]
    if messages:
        latest = max(messages, key=lambda m: m.created_at_external or m.created_at)
        return latest.external_message_id or f"message:{latest.id}"
    return item.external_id


def _extract_ai_reply_draft(output: Any) -> str:
    if isinstance(output, dict):
        for key in ("reply", "reply_ru", "draft", "draft_ru", "answer", "answer_ru", "message", "message_ru", "text", "text_ru", "content", "response", "response_ru"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            nested = _extract_ai_reply_draft(value)
            if nested:
                return nested
        for value in output.values():
            nested = _extract_ai_reply_draft(value)
            if nested:
                return nested
        return ""
    if isinstance(output, list):
        for value in output:
            nested = _extract_ai_reply_draft(value)
            if nested:
                return nested
        return ""
    if not isinstance(output, str):
        return ""
    raw = output.strip()
    if not raw:
        return ""
    candidates = [raw]
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, flags=re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    start = raw.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(raw[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.insert(0, raw[start:i + 1])
                    break
    for candidate in candidates:
        try:
            draft = _extract_ai_reply_draft(json.loads(candidate))
            if draft:
                return draft
        except Exception:
            continue
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
    raw = re.sub(r"\s*```$", "", raw).strip()
    raw = re.sub(r"^(reply|reply_ru|draft|draft_ru|ответ|черновик)\s*[:：]\s*", "", raw, flags=re.IGNORECASE).strip()
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1].strip()
    return raw


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(value: Optional[str], default: Any = None) -> Any:
    if not value:
        return default if default is not None else {}
    try:
        return json.loads(value)
    except Exception:
        return default if default is not None else {}


def _audit_sanitize(data: Any, depth: int = 0) -> Any:
    if depth > 5:
        return "<max_depth>"
    if isinstance(data, dict):
        sensitive = {"authorization", "token", "api_key", "apikey", "password", "secret", "header"}
        return {k: ("<redacted>" if k.lower() in sensitive else _audit_sanitize(v, depth + 1)) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_audit_sanitize(v, depth + 1) for v in data[:50]]
    if isinstance(data, str) and len(data) > 80:
        return data[:80] + "..."
    return data


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "开启"}


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _clamp_int(value: Any, min_value: int, max_value: int, default: Optional[int] = None) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default if default is not None else min_value
    return max(min_value, min(max_value, parsed))


def _now() -> datetime:
    return datetime.now(SHANGHAI_TZ).replace(tzinfo=None)
