"""
WB 客服数据同步服务

v1 只写客服模块自己的表，不写 OperationLog。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.models import (
    CustomerServiceItem,
    CustomerServiceMessage,
    Product,
    Shop,
    SyncLog,
    SystemSetting,
)
from app.services.wb_customer_client import WBCustomerClient, WBCustomerRateLimit


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class CustomerServiceSyncService:
    """把 WB 客服接口数据归一到客服工作台表。"""

    def __init__(self, db: Session, shop: Shop):
        self.db = db
        self.shop = shop
        self.client = WBCustomerClient(shop.api_token)

    def sync_all(self, days: int = 30) -> Dict[str, Any]:
        results = {
            "questions": self.sync_questions(days=days),
            "feedbacks": self.sync_feedbacks(days=days),
            "chats": self.sync_chats(),
            "return_claims": self.sync_return_claims(),
        }
        total = sum(v.get("count", 0) for v in results.values() if isinstance(v, dict))
        return {"success": True, "count": total, "results": results}

    def sync_questions(self, days: int = 30) -> Dict[str, Any]:
        sync_log = self._create_sync_log("customer_service_questions")
        try:
            since = int((self._now() - timedelta(days=days)).timestamp())
            count = 0
            for answered in (False, True):
                for rec in self._paged_feedbacks_api(
                    lambda take, skip: self.client.get_questions(
                        is_answered=answered, take=take, skip=skip, date_from=since
                    )
                ):
                    self._upsert_question(rec)
                    count += 1
            self.db.commit()
            self._finish_sync_log(sync_log, True, count, "WB 问答同步完成")
            return {"success": True, "count": count}
        except WBCustomerRateLimit as exc:
            self.db.rollback()
            self._finish_sync_log(sync_log, False, 0, f"WB 问答限流: {exc}")
            return {"success": False, "rate_limited": True, "error": str(exc)}
        except Exception as exc:
            self.db.rollback()
            self._finish_sync_log(sync_log, False, 0, str(exc))
            return {"success": False, "error": str(exc)}

    def sync_feedbacks(self, days: int = 30) -> Dict[str, Any]:
        sync_log = self._create_sync_log("customer_service_feedbacks")
        try:
            since = int((self._now() - timedelta(days=days)).timestamp())
            count = 0
            for answered in (False, True):
                for rec in self._paged_feedbacks_api(
                    lambda take, skip: self.client.get_feedbacks(
                        is_answered=answered, take=take, skip=skip, date_from=since
                    )
                ):
                    self._upsert_feedback(rec)
                    count += 1
            self.db.commit()
            self._finish_sync_log(sync_log, True, count, "WB 评价同步完成")
            return {"success": True, "count": count}
        except WBCustomerRateLimit as exc:
            self.db.rollback()
            self._finish_sync_log(sync_log, False, 0, f"WB 评价限流: {exc}")
            return {"success": False, "rate_limited": True, "error": str(exc)}
        except Exception as exc:
            self.db.rollback()
            self._finish_sync_log(sync_log, False, 0, str(exc))
            return {"success": False, "error": str(exc)}

    def sync_chats(self) -> Dict[str, Any]:
        sync_log = self._create_sync_log("customer_service_chats")
        try:
            cursor_key = f"customer_service_chat_cursor:{self.shop.id}"
            cursor = self._get_setting(cursor_key)
            result = self.client.get_chat_events(next_cursor=cursor or None, limit=100)
            events = self._extract_records(result, ("events", "data", "result"))
            data_block = result.get("data") if isinstance(result, dict) else {}
            next_cursor = result.get("next") or result.get("nextCursor") or result.get("cursor")
            if not next_cursor and isinstance(data_block, dict):
                next_cursor = data_block.get("next") or data_block.get("nextCursor") or data_block.get("cursor")

            count = 0
            for rec in events:
                self._upsert_chat_event(rec)
                count += 1
            if next_cursor:
                self._set_setting(cursor_key, str(next_cursor), "WB 买家聊天同步游标")
            self.db.commit()
            self._finish_sync_log(sync_log, True, count, "WB 买家聊天同步完成")
            return {"success": True, "count": count, "next_cursor": next_cursor}
        except WBCustomerRateLimit as exc:
            self.db.rollback()
            self._finish_sync_log(sync_log, False, 0, f"WB 聊天限流: {exc}")
            return {"success": False, "rate_limited": True, "error": str(exc)}
        except Exception as exc:
            self.db.rollback()
            self._finish_sync_log(sync_log, False, 0, str(exc))
            return {"success": False, "error": str(exc)}

    def sync_return_claims(self) -> Dict[str, Any]:
        sync_log = self._create_sync_log("customer_service_return_claims")
        try:
            count = 0
            offset = 0
            while True:
                result = self.client.get_return_claims(limit=100, offset=offset, is_archive=False)
                records = self._extract_records(result, ("claims", "data", "result"))
                if not records:
                    break
                for rec in records:
                    self._upsert_return_claim(rec)
                    count += 1
                if len(records) < 100:
                    break
                offset += 100
            self.db.commit()
            self._finish_sync_log(sync_log, True, count, "WB 退货申请同步完成")
            return {"success": True, "count": count}
        except WBCustomerRateLimit as exc:
            self.db.rollback()
            self._finish_sync_log(sync_log, False, 0, f"WB 退货限流: {exc}")
            return {"success": False, "rate_limited": True, "error": str(exc)}
        except Exception as exc:
            self.db.rollback()
            self._finish_sync_log(sync_log, False, 0, str(exc))
            return {"success": False, "error": str(exc)}

    def _upsert_question(self, rec: Dict[str, Any]) -> CustomerServiceItem:
        product = rec.get("productDetails") or rec.get("product") or {}
        nm_id = rec.get("nmId") or rec.get("nmID") or product.get("nmId")
        item = self._upsert_item(
            channel="question",
            external_id=str(rec.get("id") or rec.get("questionId")),
            nm_id=nm_id,
            title=rec.get("productName") or product.get("productName") or product.get("name") or "",
            content=rec.get("text") or rec.get("question") or "",
            customer_name=rec.get("userName") or rec.get("username") or "",
            external_status=rec.get("state") or rec.get("status") or "",
            is_answered=bool(rec.get("isAnswered") or rec.get("answer")),
            external_created_at=self._parse_dt(rec.get("createdDate") or rec.get("date")),
            external_updated_at=self._parse_dt(rec.get("updatedDate")),
            raw=rec,
        )
        self._add_message(
            item=item,
            external_message_id=f"{item.external_id}:question",
            direction="buyer",
            text=item.content,
            attachments=[],
            created_at_external=item.external_created_at,
            raw=rec,
        )
        answer = rec.get("answer") or {}
        answer_text = answer.get("text") if isinstance(answer, dict) else answer
        if answer_text:
            self._add_message(
                item=item,
                external_message_id=f"{item.external_id}:answer",
                direction="seller",
                text=str(answer_text),
                attachments=[],
                created_at_external=self._parse_dt(answer.get("date")) if isinstance(answer, dict) else None,
                raw=answer if isinstance(answer, dict) else {"text": answer_text},
            )
        return item

    def _upsert_feedback(self, rec: Dict[str, Any]) -> CustomerServiceItem:
        product = rec.get("productDetails") or rec.get("product") or {}
        nm_id = rec.get("nmId") or rec.get("nmID") or product.get("nmId")
        rating = rec.get("productValuation") or rec.get("valuation") or rec.get("rating")
        item = self._upsert_item(
            channel="feedback",
            external_id=str(rec.get("id") or rec.get("feedbackId")),
            nm_id=nm_id,
            title=rec.get("productName") or product.get("productName") or product.get("name") or "",
            content=rec.get("text") or rec.get("pros") or rec.get("cons") or "",
            customer_name=rec.get("userName") or rec.get("username") or "",
            rating=int(rating) if rating is not None else None,
            external_status=rec.get("state") or rec.get("status") or "",
            is_answered=bool(rec.get("answer") or rec.get("isAnswered")),
            external_created_at=self._parse_dt(rec.get("createdDate") or rec.get("date")),
            external_updated_at=self._parse_dt(rec.get("updatedDate")),
            raw=rec,
        )
        self._add_message(
            item=item,
            external_message_id=f"{item.external_id}:feedback",
            direction="buyer",
            text=item.content,
            attachments=self._extract_attachments(rec),
            created_at_external=item.external_created_at,
            raw=rec,
        )
        answer = rec.get("answer") or {}
        answer_text = answer.get("text") if isinstance(answer, dict) else answer
        if answer_text:
            self._add_message(
                item=item,
                external_message_id=f"{item.external_id}:answer",
                direction="seller",
                text=str(answer_text),
                attachments=[],
                created_at_external=self._parse_dt(answer.get("date")) if isinstance(answer, dict) else None,
                raw=answer if isinstance(answer, dict) else {"text": answer_text},
            )
        return item

    def _upsert_chat_event(self, rec: Dict[str, Any]) -> CustomerServiceItem:
        chat_id = rec.get("chatID") or rec.get("chatId") or rec.get("dialogId") or rec.get("rid")
        event_id = rec.get("eventID") or rec.get("eventId") or rec.get("messageId") or rec.get("id")
        message_obj = rec.get("message") or {}
        # WB 聊天接口 message 是 object：{"text": "...", "attachments": {"goodCard": {...}}}
        good_card = message_obj.get("attachments", {}).get("goodCard") or rec.get("goodCard") or rec.get("product") or {}
        nm_id = rec.get("nmId") or good_card.get("nmId")
        text = message_obj.get("text") or rec.get("text") or rec.get("body") or ""
        # WB 聊天接口用 addTimestamp（Unix ms），addTime 是 ISO 字符串
        created_at = self._parse_dt(rec.get("addTimestamp")) or self._parse_dt(rec.get("addTime")) or self._parse_dt(rec.get("createdAt")) or self._parse_dt(rec.get("date"))
        direction = "seller" if rec.get("isSeller") or rec.get("sender") == "seller" else "buyer"
        external_id_str = str(chat_id or event_id)
        # 同 channel 去重：检查是否已存在同 channel 的聊天事项
        existing = self.db.query(CustomerServiceItem).filter(
            CustomerServiceItem.shop_id == self.shop.id,
            CustomerServiceItem.platform == "wildberries",
            CustomerServiceItem.channel == "chat",
            CustomerServiceItem.external_id == external_id_str,
        ).first()
        if existing:
            # 已有记录，仅追加消息，不重复插入主记录
            self._add_message(
                item=existing,
                external_message_id=str(event_id or f"{external_id_str}:{created_at or self._now()}"),
                direction=direction,
                text=text,
                attachments=self._extract_attachments(message_obj),
                created_at_external=created_at,
                raw=rec,
            )
            return existing
        item = self._upsert_item(
            channel="chat",
            external_id=external_id_str,
            nm_id=nm_id,
            title=good_card.get("title") or good_card.get("name") or "买家聊天",
            content=text,
            customer_name=rec.get("clientName") or rec.get("buyerName") or "",
            external_status=rec.get("status") or "",
            is_answered=direction == "seller",
            external_created_at=created_at,
            external_updated_at=created_at,
            raw=rec,
        )
        self._add_message(
            item=item,
            external_message_id=str(event_id or f"{item.external_id}:{created_at or self._now()}"),
            direction=direction,
            text=text,
            attachments=self._extract_attachments(message_obj),
            created_at_external=created_at,
            raw=rec,
        )
        return item

    def _upsert_return_claim(self, rec: Dict[str, Any]) -> CustomerServiceItem:
        claim_id = rec.get("id") or rec.get("claimId")
        nm_id = rec.get("nm_id") or rec.get("nmId") or rec.get("nmID")
        created_at = self._parse_dt(rec.get("dt") or rec.get("created_at") or rec.get("createdAt"))
        sla_deadline = created_at + timedelta(hours=120) if created_at else None
        content = rec.get("user_comment") or rec.get("comment") or rec.get("text") or ""
        item = self._upsert_item(
            channel="return_claim",
            external_id=str(claim_id),
            nm_id=nm_id,
            title=rec.get("subject") or rec.get("claim_type") or "退货申请",
            content=content,
            customer_name=rec.get("user_name") or rec.get("userName") or "",
            external_status=rec.get("status") or rec.get("status_ex") or "",
            is_answered=False,
            external_created_at=created_at,
            external_updated_at=self._parse_dt(rec.get("dt_update") or rec.get("updated_at") or rec.get("updatedAt")),
            sla_deadline_at=sla_deadline,
            raw=rec,
        )
        self._add_message(
            item=item,
            external_message_id=f"{item.external_id}:return_claim",
            direction="buyer",
            text=content,
            attachments=self._extract_attachments(rec),
            created_at_external=created_at,
            raw=rec,
        )
        return item

    def _upsert_item(
        self,
        channel: str,
        external_id: str,
        nm_id: Optional[Any],
        title: str,
        content: str,
        customer_name: str,
        external_status: str,
        is_answered: bool,
        external_created_at: Optional[datetime],
        external_updated_at: Optional[datetime],
        raw: Dict[str, Any],
        rating: Optional[int] = None,
        sla_deadline_at: Optional[datetime] = None,
    ) -> CustomerServiceItem:
        if not external_id or external_id == "None":
            external_id = f"{channel}:{nm_id}:{external_created_at or self._now()}:{hash(content)}"

        product = self._find_product(nm_id)
        item = self.db.query(CustomerServiceItem).filter(
            CustomerServiceItem.shop_id == self.shop.id,
            CustomerServiceItem.platform == "wildberries",
            CustomerServiceItem.channel == channel,
            CustomerServiceItem.external_id == external_id,
        ).first()

        if not item:
            item = CustomerServiceItem(
                shop_id=self.shop.id,
                platform="wildberries",
                channel=channel,
                external_id=external_id,
            )
            self.db.add(item)

        item.external_status = external_status or ""
        item.nm_id = str(nm_id) if nm_id is not None else item.nm_id
        item.product_id = product.id if product else None
        item.sku = product.sku if product else item.sku
        item.product_name = product.custom_name or product.name if product else (title or item.product_name)
        item.product_name_ru = title or item.product_name_ru
        item.owner = product.owner if product else None
        item.product_matched = bool(product)
        if product and not item.assigned_owner:
            item.assigned_owner = product.owner
            item.assignment_status = "assigned" if product.owner else "unassigned"

        item.customer_name = customer_name or item.customer_name
        item.title = title or item.title or ""
        item.content = content or item.content or ""
        item.rating = rating if rating is not None else item.rating
        item.external_created_at = external_created_at or item.external_created_at
        item.external_updated_at = external_updated_at or item.external_updated_at
        item.sla_deadline_at = sla_deadline_at or item.sla_deadline_at
        item.is_overdue = bool(item.sla_deadline_at and item.sla_deadline_at < self._now())
        item.reply_status = "answered" if is_answered else "unanswered"
        if item.status not in ("pending_internal", "closed", "archived"):
            item.status = "replied" if is_answered else "open"
        item.issue_type = self._issue_type(channel, item.content, raw)
        item.risk_level = self._risk_level(channel, item.rating, item.sla_deadline_at)
        item.priority = item.risk_level
        item.raw_json = self._json(raw)
        # buyer_key：跨 channel 聚合同一买家
        if channel in ("feedback", "question"):
            item.buyer_key = raw.get("userName") or customer_name or item.buyer_key
        elif channel == "chat":
            item.buyer_key = raw.get("clientName") or customer_name or item.buyer_key
        elif channel == "return_claim":
            item.buyer_key = raw.get("srid") or customer_name or item.buyer_key
        else:
            item.buyer_key = customer_name or item.buyer_key
        item.updated_at = self._now()
        return item

    def _add_message(
        self,
        item: CustomerServiceItem,
        external_message_id: str,
        direction: str,
        text: str,
        attachments: List[Dict[str, Any]],
        created_at_external: Optional[datetime],
        raw: Dict[str, Any],
    ) -> None:
        if not external_message_id:
            external_message_id = f"{item.external_id}:{direction}:{created_at_external or self._now()}"
        existing = self.db.query(CustomerServiceMessage).filter(
            CustomerServiceMessage.item_id == item.id,
            CustomerServiceMessage.external_message_id == external_message_id,
        ).first() if item.id else None
        if existing:
            existing.message_text = text or existing.message_text
            existing.attachments_json = self._json(attachments)
            existing.raw_json = self._json(raw)
            return
        self.db.add(CustomerServiceMessage(
            item=item,
            external_message_id=external_message_id,
            direction=direction,
            sender_type=direction,
            message_text=text or "",
            attachments_json=self._json(attachments),
            created_at_external=created_at_external,
            raw_json=self._json(raw),
        ))

    def _paged_feedbacks_api(self, fetcher) -> Iterable[Dict[str, Any]]:
        take = 100
        skip = 0
        while True:
            result = fetcher(take, skip)
            records = self._extract_records(result, ("questions", "feedbacks", "data", "result"))
            if not records:
                break
            for rec in records:
                yield rec
            if len(records) < take:
                break
            skip += take

    def _extract_records(self, data: Any, candidate_keys: Tuple[str, ...]) -> List[Dict[str, Any]]:
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if not isinstance(data, dict):
            return []
        for key in candidate_keys:
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
            if isinstance(value, dict):
                nested = self._extract_records(value, candidate_keys)
                if nested:
                    return nested
        return []

    def _find_product(self, nm_id: Optional[Any]) -> Optional[Product]:
        if nm_id is None:
            return None
        nm = str(nm_id)
        return self.db.query(Product).filter(
            Product.shop_id == self.shop.id,
            Product.nm_id == nm,
        ).first()

    def _extract_attachments(self, rec: Dict[str, Any]) -> List[Dict[str, Any]]:
        attachments: List[Dict[str, Any]] = []
        for key in ("photos", "photoLinks", "video", "videos", "videoLinks", "files", "attachments"):
            value = rec.get(key)
            if not value:
                continue
            if isinstance(value, str):
                attachments.append({"type": key, "url": value})
            elif isinstance(value, list):
                for row in value:
                    if isinstance(row, str):
                        attachments.append({"type": key, "url": row})
                    elif isinstance(row, dict):
                        attachments.append({
                            "type": row.get("type") or key,
                            "url": row.get("url") or row.get("link"),
                            "download_id": row.get("downloadId") or row.get("download_id") or row.get("id"),
                            "name": row.get("name") or row.get("fileName") or "",
                        })
            elif isinstance(value, dict):
                attachments.append({
                    "type": value.get("type") or key,
                    "url": value.get("url") or value.get("link"),
                    "download_id": value.get("downloadId") or value.get("download_id") or value.get("id"),
                    "name": value.get("name") or value.get("fileName") or "",
                })
        return [a for a in attachments if a.get("url") or a.get("download_id")]

    def _issue_type(self, channel: str, text: str, raw: Dict[str, Any]) -> str:
        source = f"{text} {raw.get('subject', '')} {raw.get('claim_type', '')}".lower()
        if channel == "return_claim":
            return "return"
        if any(key in source for key in ("слом", "брак", "дефект", "повреж", "не работает")):
            return "quality"
        if any(key in source for key in ("доставка", "получ", "курьер", "срок")):
            return "delivery"
        if any(key in source for key in ("размер", "объем", "литр", "подходит")):
            return "product_info"
        return "other"

    def _risk_level(self, channel: str, rating: Optional[int], sla_deadline_at: Optional[datetime]) -> str:
        now = self._now()
        if channel == "return_claim" and sla_deadline_at:
            hours_left = (sla_deadline_at - now).total_seconds() / 3600
            if hours_left <= 6:
                return "urgent"
            if hours_left <= 24:
                return "high"
        if rating is not None:
            if rating <= 2:
                return "urgent"
            if rating <= 3:
                return "high"
        return "normal"

    def _get_setting(self, key: str) -> str:
        row = self.db.query(SystemSetting).filter(SystemSetting.key == key).first()
        return row.value if row else ""

    def _set_setting(self, key: str, value: str, description: str) -> None:
        row = self.db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if not row:
            row = SystemSetting(key=key, value=value, description=description)
            self.db.add(row)
        else:
            row.value = value
            row.description = description

    def _create_sync_log(self, sync_type: str) -> SyncLog:
        sync_log = SyncLog(shop_id=self.shop.id, sync_type=sync_type, status="running")
        self.db.add(sync_log)
        self.db.commit()
        return sync_log

    def _finish_sync_log(self, sync_log: SyncLog, success: bool, count: int, message: str) -> None:
        sync_log.status = "success" if success else "failed"
        sync_log.records_count = count
        sync_log.message = message
        sync_log.finished_at = self._now()
        self.db.commit()

    def _parse_dt(self, value: Any) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            # WB addTimestamp 是 13 位毫秒（> 1e11），除以 1000 转秒
            if value > 1e11:
                value = value / 1000
            return datetime.fromtimestamp(value, SHANGHAI_TZ)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                if text.endswith("Z"):
                    text = text[:-1] + "+00:00"
                parsed = datetime.fromisoformat(text)
                if parsed.tzinfo:
                    return parsed.astimezone(SHANGHAI_TZ).replace(tzinfo=None)
                return parsed
            except ValueError:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(text, fmt)
                    except ValueError:
                        continue
        return None

    def _now(self) -> datetime:
        return datetime.now(SHANGHAI_TZ).replace(tzinfo=None)

    def _json(self, value: Any) -> str:
        return json.dumps({} if value is None else value, ensure_ascii=False, default=str)
