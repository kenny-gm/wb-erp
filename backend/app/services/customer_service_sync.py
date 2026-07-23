"""
WB 客服数据同步服务

v1 只写客服模块自己的表，不写 OperationLog。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session
from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError

from app.models.models import (
    CustomerServiceAction,
    CustomerServiceItem,
    CustomerServiceMessage,
    Product,
    Shop,
    SyncLog,
    SystemSetting,
)
from app.services.wb_customer_client import WBCustomerClient, WBCustomerRateLimit


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
CUSTOMER_SERVICE_HISTORY_DAYS = 30


class CustomerServiceSyncService:
    """把 WB 客服接口数据归一到客服工作台表。"""

    def __init__(self, db: Session, shop: Shop):
        self.db = db
        self.shop = shop
        self.client = WBCustomerClient(shop.api_token)
        self._chat_items: Dict[str, CustomerServiceItem] = {}  # 本次同步批次内缓存: external_id -> item

    def _integrity_snapshot(self) -> Dict[str, int]:
        """Capture customer-service table health before/after sync."""
        queries = {
            "items": "SELECT COUNT(*) FROM customer_service_items",
            "shop_items": "SELECT COUNT(*) FROM customer_service_items WHERE shop_id = :shop_id",
            "orphan_messages": """
                SELECT COUNT(*)
                FROM customer_service_messages m
                LEFT JOIN customer_service_items i ON i.id = m.item_id
                WHERE i.id IS NULL
            """,
            "orphan_actions": """
                SELECT COUNT(*)
                FROM customer_service_actions a
                LEFT JOIN customer_service_items i ON i.id = a.item_id
                WHERE i.id IS NULL
            """,
            "item_dup_keys": """
                SELECT COUNT(*) FROM (
                    SELECT shop_id, platform, channel, external_id, COUNT(*) c
                    FROM customer_service_items
                    GROUP BY shop_id, platform, channel, external_id
                    HAVING c > 1
                ) AS duplicate_items
            """,
            "msg_dup_dedup": """
                SELECT COUNT(*) FROM (
                    SELECT message_dedup_key, COUNT(*) c
                    FROM customer_service_messages
                    WHERE message_dedup_key IS NOT NULL AND message_dedup_key != ''
                    GROUP BY message_dedup_key
                    HAVING c > 1
                ) AS duplicate_messages
            """,
            "cross_channel_chat_messages": """
                SELECT COUNT(*)
                FROM customer_service_messages m
                JOIN customer_service_items i ON i.id = m.item_id
                WHERE i.channel != 'chat'
                  AND (
                    m.raw_json LIKE '%"chatID"%'
                    OR m.raw_json LIKE '%"chatId"%'
                    OR m.raw_json LIKE '%"dialogId"%'
                    OR m.raw_json LIKE '%"replySign"%'
                    OR m.raw_json LIKE '%"reply_sign"%'
                    OR (
                        m.raw_json LIKE '%"eventType"%message%'
                        AND m.raw_json LIKE '%"message"%'
                    )
                  )
            """,
        }
        return {
            key: int(self.db.execute(text(query), {"shop_id": self.shop.id}).scalar() or 0)
            for key, query in queries.items()
        }

    def _validate_integrity_snapshot(self, before: Dict[str, int], context: str) -> None:
        after = self._integrity_snapshot()
        failures = []
        if after["items"] < before["items"]:
            failures.append(f"items {before['items']} -> {after['items']}")
        if after["shop_items"] < before["shop_items"]:
            failures.append(f"shop_items {before['shop_items']} -> {after['shop_items']}")
        for key in ("orphan_messages", "orphan_actions", "item_dup_keys", "msg_dup_dedup"):
            if after[key]:
                failures.append(f"{key}={after[key]}")
        before_cross_channel = before.get("cross_channel_chat_messages", 0)
        if after["cross_channel_chat_messages"] > before_cross_channel:
            failures.append(
                "cross_channel_chat_messages "
                f"{before_cross_channel} -> {after['cross_channel_chat_messages']}"
            )
        if failures:
            raise RuntimeError(f"{context} 后客服数据完整性异常: " + "; ".join(failures))

    def sync_all(self, days: int = CUSTOMER_SERVICE_HISTORY_DAYS) -> Dict[str, Any]:
        results = {
            "questions": self.sync_questions(days=days),
            "feedbacks": self.sync_feedbacks(days=days),
            "chats": self.sync_chats(),
            "return_claims": self.sync_return_claims(),
        }
        total = sum(v.get("count", 0) for v in results.values() if isinstance(v, dict))
        failed_channels = []
        errors = []
        rate_limited_channels = []
        for channel, result in results.items():
            if isinstance(result, dict) and not result.get("success", True):
                failed_channels.append(channel)
                if result.get("rate_limited"):
                    rate_limited_channels.append(channel)
                errors.append(f"{channel}: {result.get('error', 'unknown')}")
        overall_success = not failed_channels
        return {
            "success": overall_success,
            "count": total,
            "results": results,
            "failed_channels": failed_channels,
            "rate_limited_channels": rate_limited_channels,
            "errors": errors,
        }

    def sync_questions(self, days: int = CUSTOMER_SERVICE_HISTORY_DAYS) -> Dict[str, Any]:
        sync_log = self._create_sync_log("customer_service_questions")
        try:
            integrity_before = self._integrity_snapshot()
            since = int((self._now() - timedelta(days=days)).timestamp())
            seen_ids: set = set()
            total = 0
            for answered in (False, True):
                for rec in self._paged_feedbacks_api(
                    lambda take, skip: self.client.get_questions(
                        is_answered=answered, take=take, skip=skip, date_from=since
                    )
                ):
                    ext_id = str(rec.get("id") or rec.get("questionId"))
                    if ext_id in seen_ids:
                        continue
                    seen_ids.add(ext_id)
                    self._upsert_question(rec)
                    total += 1
            self.db.commit()
            self._validate_integrity_snapshot(integrity_before, "WB 问答同步")
            self._finish_sync_log(sync_log, True, total, f"WB 问答同步完成：{total} 条")
            return {"success": True, "count": total}
        except WBCustomerRateLimit as exc:
            self.db.rollback()
            self._finish_sync_log(sync_log, False, 0, f"WB 问答限流: {exc}")
            return {"success": False, "rate_limited": True, "error": str(exc)}
        except Exception as exc:
            self.db.rollback()
            self._finish_sync_log(sync_log, False, 0, str(exc))
            return {"success": False, "error": str(exc)}

    def sync_feedbacks(self, days: int = CUSTOMER_SERVICE_HISTORY_DAYS) -> Dict[str, Any]:
        sync_log = self._create_sync_log("customer_service_feedbacks")
        try:
            integrity_before = self._integrity_snapshot()
            since = int((self._now() - timedelta(days=days)).timestamp())
            seen_ids: set = set()
            count = 0
            for answered in (False, True):
                for rec in self._paged_feedbacks_api(
                    lambda take, skip: self.client.get_feedbacks(
                        is_answered=answered, take=take, skip=skip, date_from=since
                    )
                ):
                    ext_id = str(rec.get("id") or rec.get("feedbackId"))
                    if ext_id in seen_ids:
                        continue
                    seen_ids.add(ext_id)
                    self._upsert_feedback(rec)
                    count += 1
            self.db.commit()
            self._validate_integrity_snapshot(integrity_before, "WB 评价同步")
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

    def sync_chats(self, force_full_sync: bool = False) -> Dict[str, Any]:
        sync_log = self._create_sync_log("customer_service_chats")
        try:
            integrity_before = self._integrity_snapshot()
            cursor_key = f"customer_service_chat_cursor:{self.shop.id}"
            cursor = None if force_full_sync else self._get_setting(cursor_key)

            total_count = 0
            seen_ids: set = set()
            page_count = 0
            next_cursor = cursor
            last_valid_cursor: Optional[str] = None  # 只在有 events 时才更新
            empty_pages = 0
            self._chat_items.clear()  # 清空上批次缓存，防止残留

            # 第一步：用 get_chats 拿到所有聊天的 goodCard 信息（移动端发的消息不带 goodCard，需要从这里补充）
            good_card_by_chat_id: Dict[str, Dict[str, Any]] = {}
            try:
                chats_result = self.client.get_chats(limit=1000)
                chats_list = []
                if isinstance(chats_result, dict):
                    chats_list = chats_result.get("result") or []
                for chat in chats_list:
                    chat_id = str(chat.get("chatID") or "")
                    good_card = chat.get("goodCard") or {}
                    if chat_id:
                        good_card_by_chat_id[chat_id] = good_card
                logger.info(f"[WB Chat Sync][shop {self.shop.id}] get_chats 拿到 {len(good_card_by_chat_id)} 个聊天的 goodCard")
            except Exception as e:
                logger.warning(f"[WB Chat Sync][shop {self.shop.id}] get_chats 失败: {e}")

            while True:
                page_count += 1
                raw = self.client.get_chat_events(next_cursor=next_cursor)

                result_block = raw.get("result") if isinstance(raw, dict) else {}
                events = result_block.get("events", []) if isinstance(result_block, dict) else []
                page_next_cursor = result_block.get("next") if isinstance(result_block, dict) else None

                logger.info(
                    f"[WB Chat Sync][shop {self.shop.id}] 第 {page_count} 页: "
                    f"events数量={len(events)}, next={page_next_cursor}"
                )

                for rec in events:
                    chat_id = rec.get("chatID") or rec.get("chatId") or rec.get("dialogId") or rec.get("rid")
                    ext_id = str(chat_id or rec.get("eventID") or rec.get("eventId") or rec.get("id") or f"{hash(str(rec))}")
                    if ext_id not in seen_ids:
                        seen_ids.add(ext_id)
                    self._upsert_chat_event(rec, good_card_by_chat_id)
                    total_count += 1

                # 有事件时，记录 last_valid_cursor（用 page_next_cursor，不是 next_cursor）
                if events and page_next_cursor:
                    last_valid_cursor = page_next_cursor
                    empty_pages = 0
                elif events and not page_next_cursor:
                    # 有事件但 WB 说没有下一页，记录当前页最后事件的 cursor（用 next_cursor 传入值）
                    last_valid_cursor = next_cursor

                # 没有事件时的处理
                if not events:
                    empty_pages += 1
                    if empty_pages >= 2 or not page_next_cursor:
                        # 连续两页空 or WB 说没有下一页，停止
                        break
                    # 第一页空：保存游标并退出（下次从此处继续）
                    if page_next_cursor:
                        self._set_setting(cursor_key, str(page_next_cursor), "WB 买家聊天同步游标")
                    self.db.commit()
                    self._validate_integrity_snapshot(integrity_before, "WB 买家聊天同步")
                    self._finish_sync_log(sync_log, True, total_count, f"WB 买家聊天同步完成（空页中断）：{len(seen_ids)} 会话 {total_count} 事件，共 {page_count} 页")
                    return {"success": True, "count": total_count, "sessions": len(seen_ids), "pages": page_count, "next_cursor": page_next_cursor}

                if not page_next_cursor:
                    break

                next_cursor = page_next_cursor
                # 限流保护：页间暂停
                time.sleep(1.1)

            # 保存 last_valid_cursor（只有真正有下一页才保存，否则用已有游标继续）
            if last_valid_cursor:
                self._set_setting(cursor_key, str(last_valid_cursor), "WB 买家聊天同步游标")
            self.db.commit()
            self._validate_integrity_snapshot(integrity_before, "WB 买家聊天同步")
            self._finish_sync_log(sync_log, True, total_count, f"WB 买家聊天同步完成：{len(seen_ids)} 会话 {total_count} 事件，共 {page_count} 页")
            return {"success": True, "count": total_count, "sessions": len(seen_ids), "pages": page_count, "next_cursor": last_valid_cursor or next_cursor}
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
            integrity_before = self._integrity_snapshot()
            stats = {
                "active": {"new": 0, "updated": 0, "count": 0},
                "archived": {"new": 0, "updated": 0, "count": 0, "closed_transitions": 0},
                "reconciled": {"closed": 0},
            }
            active_ids: set[str] = set()
            archived_ids: set[str] = set()
            for is_archive in (False, True):
                offset = 0
                while True:
                    result = self.client.get_return_claims(limit=100, offset=offset, is_archive=is_archive)
                    records = self._extract_records(result, ("claims", "data", "result"))
                    if not records:
                        break
                    for rec in records:
                        claim_id = rec.get("id") or rec.get("claimId")
                        if claim_id:
                            if is_archive:
                                archived_ids.add(str(claim_id))
                            else:
                                active_ids.add(str(claim_id))
                        was_open = self._upsert_return_claim(rec, is_archive=is_archive)
                        key = "archived" if is_archive else "active"
                        stats[key]["count"] += 1
                        if was_open:
                            stats[key]["new"] += 1
                        else:
                            stats[key]["updated"] += 1
                        if is_archive and was_open:
                            stats["archived"]["closed_transitions"] += 1
                    if len(records) < 100:
                        break
                    offset += 100
                    time.sleep(0.5)
            stats["reconciled"]["closed"] = self._reconcile_missing_return_claims(active_ids, archived_ids)
            self.db.commit()
            self._validate_integrity_snapshot(integrity_before, "WB 退货申请同步")
            total = stats["active"]["count"] + stats["archived"]["count"] + stats["reconciled"]["closed"]
            message = (
                f"WB 退货申请同步完成：{stats['active']['count']} 活跃 + "
                f"{stats['archived']['count']} 已归档"
            )
            if stats["reconciled"]["closed"]:
                message += f" + {stats['reconciled']['closed']} 本地超时对账关闭"
            self._finish_sync_log(sync_log, True, total, message)
            return {"success": True, **stats}
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
        answer = rec.get("answer") or {}
        answer_text = answer.get("text") if isinstance(answer, dict) else answer
        answer_visibility = "all"
        question_status = rec.get("status") or rec.get("state") or ""
        is_answered = bool(rec.get("isAnswered") or answer_text)
        # 状态映射：已拒绝/已关闭 -> closed；已回答 -> replied；未处理 -> open
        if question_status in ("rejected", "closed"):
            override_status = "closed"
            override_reply_status = "answered"
        elif is_answered:
            override_status = "replied"
            override_reply_status = "answered"
        else:
            override_status = "open"
            override_reply_status = "unanswered"
        external_updated = self._parse_dt(rec.get("updatedDate"))
        item = self._upsert_item(
            channel="question",
            external_id=str(rec.get("id") or rec.get("questionId")),
            nm_id=nm_id,
            title=rec.get("productName") or product.get("productName") or product.get("name") or "",
            content=rec.get("text") or rec.get("question") or "",
            customer_name=rec.get("userName") or rec.get("username") or "",
            external_status=question_status,
            is_answered=is_answered,
            external_created_at=self._parse_dt(rec.get("createdDate") or rec.get("date")),
            external_updated_at=external_updated,
            raw=rec,
            override_status=override_status,
            override_reply_status=override_reply_status,
            override_closed_at=external_updated if override_status == "closed" else None,
            override_answer_visibility=answer_visibility,
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

    def _upsert_chat_event(
        self,
        rec: Dict[str, Any],
        good_card_by_chat_id: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> CustomerServiceItem:
        chat_id = rec.get("chatID") or rec.get("chatId") or rec.get("dialogId") or rec.get("rid")
        event_id = rec.get("eventID") or rec.get("eventId") or rec.get("messageId") or rec.get("id")
        message_obj = rec.get("message") or {}
        # WB 聊天接口 message 是 object：{"text": "...", "attachments": {"goodCard": {...}}}
        # 优先用 event 自带的 goodCard（web端），没有则用 get_chats 补充（移动端）
        event_good_card = message_obj.get("attachments", {}).get("goodCard") or rec.get("goodCard") or rec.get("product") or {}
        lookup_good_card = (good_card_by_chat_id or {}).get(str(chat_id), {}) if chat_id else {}
        good_card = event_good_card if event_good_card.get("nmID") or event_good_card.get("nmId") else lookup_good_card
        nm_id = rec.get("nmId") or rec.get("nmID") or good_card.get("nmId") or good_card.get("nmID")
        # 用 nm_id 匹配系统产品，获取 custom_name
        product = self._find_product(nm_id) if nm_id else None
        text = message_obj.get("text") or rec.get("text") or rec.get("body") or ""
        # WB 聊天接口用 addTimestamp（Unix ms），addTime 是 ISO 字符串
        created_at = self._parse_dt(rec.get("addTimestamp")) or self._parse_dt(rec.get("addTime")) or self._parse_dt(rec.get("createdAt")) or self._parse_dt(rec.get("date"))
        direction = "seller" if rec.get("isSeller") or rec.get("sender") == "seller" else "buyer"
        external_id_str = str(chat_id or event_id)
        # 同 channel 去重：先查本次批次内缓存（解决同事务内 SQL query 看不到未 flush 新item 的问题），再查 DB
        existing = self._chat_items.get(external_id_str)
        if not existing:
            existing = self.db.query(CustomerServiceItem).filter(
                CustomerServiceItem.shop_id == self.shop.id,
                CustomerServiceItem.platform == "wildberries",
                CustomerServiceItem.channel == "chat",
                CustomerServiceItem.external_id == external_id_str,
            ).first()
        if existing:
            self._chat_items[external_id_str] = existing  # 缓存更新
            # 先保存旧值，用于判断状态
            old_external_updated_at = existing.external_updated_at
            old_closed_at = existing.closed_at
            # 已有记录，追加消息
            self._add_message(
                item=existing,
                external_message_id=str(event_id or f"{external_id_str}:{created_at or self._now()}"),
                direction=direction,
                text=text,
                attachments=self._extract_attachments(message_obj),
                created_at_external=created_at,
                raw=rec,
            )
            # 刷新 replySign
            existing.reply_sign = rec.get("replySign") or rec.get("reply_sign") or existing.reply_sign
            # 刷新 raw_json
            existing.raw_json = self._json(rec)
            # 如果已有聊天但缺 nm_id 或 product_matched=0，用 goodCard 数据补充并重新匹配产品
            lookup_nm = good_card.get("nmID") or good_card.get("nmId")
            if (not existing.nm_id or not existing.product_matched) and lookup_nm:
                existing.nm_id = lookup_nm
                # 尝试匹配产品
                existing_product = self._find_product(lookup_nm)
                existing.product_matched = bool(existing_product)
                if existing_product:
                    existing.product_name = existing_product.custom_name or existing_product.name
                    existing.product_name_ru = existing_product.name
                    existing.sku = existing_product.sku
                    existing.owner = existing_product.owner
            # 刷新外部更新时间
            if created_at and created_at > (existing.external_updated_at or existing.external_created_at or self._now()):
                existing.external_updated_at = created_at
            # 聊天状态映射规则（不覆盖已完结状态）：
            # - 买家消息：只有在 closed_at 之后的新消息才重开
            # - 卖家消息：用 old_external_updated_at 判断，不把已完结聊天改回 replied
            is_after_closed = not old_closed_at or (created_at and created_at > old_closed_at)
            is_newer_event = not old_external_updated_at or (created_at and created_at > old_external_updated_at)
            if direction == "buyer":
                if existing.status != "closed" or is_after_closed:
                    existing.status = "open"
                    existing.reply_status = "unanswered"
                    existing.is_archived = False
                    existing.closed_by = None
                    existing.closed_at = None
            elif direction in ("seller", "operator"):
                if existing.status != "closed" and is_newer_event:
                    existing.status = "replied"
                    existing.reply_status = "answered"
            existing.updated_at = self._now()
            return existing
        item = self._upsert_item(
            channel="chat",
            external_id=external_id_str,
            nm_id=nm_id,
            title=(product.custom_name or product.name) if product else (good_card.get("name") or good_card.get("title") or "买家聊天"),
            content=text,
            customer_name=rec.get("clientName") or rec.get("buyerName") or "",
            external_status=rec.get("status") or "",
            is_answered=direction == "seller",
            external_created_at=created_at,
            external_updated_at=created_at,
            raw=rec,
        )
        item.product_matched = bool(product)
        if product:
            item.product_name_ru = good_card.get("name") or good_card.get("title") or item.product_name_ru
        self._chat_items[external_id_str] = item  # 缓存，防止同批次内重复创建
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

    def _upsert_return_claim(self, rec: Dict[str, Any], is_archive: bool = False) -> bool:
        """Upsert 退货申请。返回 was_open: 记录是否在此次同步前为新创建（即此次从 open→closed 的过渡）"""
        claim_id = rec.get("id") or rec.get("claimId")
        nm_id = rec.get("nm_id") or rec.get("nmId") or rec.get("nmID")
        created_at = self._parse_dt(rec.get("dt") or rec.get("created_at") or rec.get("createdAt"))
        sla_deadline = created_at + timedelta(hours=120) if created_at else None
        content = rec.get("user_comment") or rec.get("comment") or rec.get("text") or ""
        actions = rec.get("actions") or rec.get("availableActions") or []
        external_updated = self._parse_dt(rec.get("dt_update") or rec.get("updated_at") or rec.get("updatedAt"))

        # 查旧状态，用于判断 open→closed 过渡
        existing = self.db.query(CustomerServiceItem).filter(
            CustomerServiceItem.shop_id == self.shop.id,
            CustomerServiceItem.platform == "wildberries",
            CustomerServiceItem.channel == "return_claim",
            CustomerServiceItem.external_id == str(claim_id),
        ).first()
        was_open = (existing is None)  # 新创建=此次同步首次见到

        # 状态映射
        if is_archive:
            status = "closed"
            reply_status = "answered"
        else:
            # is_archive=False：待处理退货
            if actions:
                status = "open"
                reply_status = "unanswered"
            else:
                # 无 actions = 不可处理，不显示按钮
                status = "closed"
                reply_status = "answered"

        item = self._upsert_item(
            channel="return_claim",
            external_id=str(claim_id),
            nm_id=nm_id,
            title=rec.get("subject") or rec.get("claim_type") or "退货申请",
            content=content,
            customer_name=rec.get("user_name") or rec.get("userName") or "",
            external_status=rec.get("status") or rec.get("status_ex") or "",
            is_answered=(reply_status == "answered"),
            external_created_at=created_at,
            external_updated_at=external_updated,
            sla_deadline_at=sla_deadline,
            raw=rec,
            # 覆盖默认状态映射
            override_status=status,
            override_reply_status=reply_status,
            # 归档退货：WB dt_update 才是真正的卖家处理时间
            override_closed_at=external_updated if status == "closed" else None,
        )
        # 保存 actions 数组到 raw_json（已在 raw 中）
        self._add_message(
            item=item,
            external_message_id=f"{item.external_id}:return_claim",
            direction="buyer",
            text=content,
            attachments=self._extract_attachments(rec),
            created_at_external=created_at,
            raw=rec,
        )
        return was_open

    def _reconcile_missing_return_claims(self, active_ids: set[str], archived_ids: set[str]) -> int:
        """Close stale local return claims no longer present in WB active claims."""
        now = self._now()
        open_items = self.db.query(CustomerServiceItem).filter(
            CustomerServiceItem.shop_id == self.shop.id,
            CustomerServiceItem.platform == "wildberries",
            CustomerServiceItem.channel == "return_claim",
            CustomerServiceItem.status == "open",
            CustomerServiceItem.reply_status == "unanswered",
            CustomerServiceItem.external_created_at.isnot(None),
        ).all()

        reconciled = 0
        for item in open_items:
            external_id = str(item.external_id)
            if external_id in active_ids or external_id in archived_ids:
                continue

            deadline_hours = item.return_deadline_hours or 120
            deadline = item.sla_deadline_at or (item.external_created_at + timedelta(hours=deadline_hours))
            if deadline > now:
                continue

            try:
                raw = json.loads(item.raw_json or "{}")
                if not isinstance(raw, dict):
                    raw = {"value": raw}
            except (TypeError, ValueError):
                raw = {"value": item.raw_json}

            raw["reconciled_missing_from_wb_active"] = True
            raw["reconciled_at"] = now.isoformat()
            raw["previous_status"] = item.status
            raw["previous_reply_status"] = item.reply_status
            raw["reason"] = "not_returned_by_wb_active_after_successful_sync"
            raw["last_active_ids_count"] = len(active_ids)
            raw["last_archived_ids_count"] = len(archived_ids)

            item.status = "closed"
            item.reply_status = "answered"
            item.closed_at = item.closed_at or item.external_updated_at or now
            item.external_updated_at = item.external_updated_at or now
            item.external_status = item.external_status or "missing_from_wb_active"
            item.is_overdue = False
            item.risk_level = "normal"
            item.priority = "normal"
            item.raw_json = self._json(raw)
            reconciled += 1

        return reconciled

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
        override_status: Optional[str] = None,
        override_reply_status: Optional[str] = None,
        override_closed_at: Optional[datetime] = None,
        override_answer_visibility: Optional[str] = None,
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

        was_created = False
        if not item:
            item = CustomerServiceItem(
                shop_id=self.shop.id,
                platform="wildberries",
                channel=channel,
                external_id=external_id,
            )
            self.db.add(item)
            self.db.flush()  # 确保 item.id 立即可用，避免后续 _add_message 的 item_id 为 None
            was_created = True

        item.external_status = external_status or ""
        if nm_id is not None:
            item.nm_id = str(nm_id)
        # nm_id 已有值不覆盖为 None（保留首次设置的产品）
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
        has_existing_seller_reply = False
        has_successful_reply_action = False
        if channel in ("feedback", "question") and item.id and not is_answered:
            has_existing_seller_reply = self.db.query(CustomerServiceMessage.id).filter(
                CustomerServiceMessage.item_id == item.id,
                CustomerServiceMessage.direction.in_(("seller", "operator")),
                or_(
                    CustomerServiceMessage.external_message_id == f"{external_id}:answer",
                    CustomerServiceMessage.external_message_id.like(f"local:{item.id}:%"),
                ),
            ).first() is not None
            has_successful_reply_action = self.db.query(CustomerServiceAction.id).filter(
                CustomerServiceAction.item_id == item.id,
                CustomerServiceAction.action_type == "reply",
                CustomerServiceAction.success == True,  # noqa: E712
            ).first() is not None
        effective_answered = is_answered or has_existing_seller_reply or has_successful_reply_action
        # 支持调用方强制覆盖状态（用于退货等特殊映射）
        if override_reply_status is not None:
            item.reply_status = override_reply_status
        else:
            item.reply_status = "answered" if effective_answered else "unanswered"
        if override_status is not None:
            item.status = override_status
            if override_status == "closed":
                item.closed_at = override_closed_at or item.closed_at or self._now()
        else:
            # 始终更新状态，不受旧状态限制
            item.status = "replied" if effective_answered else "open"
        item.issue_type = self._issue_type(channel, item.content, raw)
        item.risk_level = self._risk_level(channel, item.rating, item.sla_deadline_at)
        item.priority = item.risk_level
        item.raw_json = self._json(raw)
        # buyer_key 已废弃：WB 无稳定跨渠道买家ID，不再写入
        # if channel in ("feedback", "question"):
        #     item.buyer_key = raw.get("userName") or customer_name or item.buyer_key
        # elif channel == "chat":
        #     item.buyer_key = raw.get("clientName") or customer_name or item.buyer_key
        # elif channel == "return_claim":
        #     item.buyer_key = raw.get("srid") or customer_name or item.buyer_key
        # else:
        #     item.buyer_key = customer_name or item.buyer_key
        # reply_sign：聊天回复凭证，支持后续刷新
        if channel == "chat":
            item.reply_sign = raw.get("replySign") or raw.get("reply_sign") or item.reply_sign
        if override_answer_visibility is not None:
            item.answer_visibility = override_answer_visibility
        item.updated_at = self._now()
        # 新创建的 item 已在 session 中，跳过独立 UPDATE（同一事务内 INSERT 对后续 UPDATE 不可见）
        if was_created:
            return item
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
        if item.channel != "chat" and self._raw_is_chat_event(raw):
            logger.warning(
                "skip cross-channel WB chat message: shop_id=%s item_id=%s item_channel=%s item_external_id=%s event_id=%s",
                item.shop_id,
                item.id,
                item.channel,
                item.external_id,
                raw.get("eventID") or raw.get("eventId") or raw.get("messageId") or raw.get("id"),
            )
            return
        if not external_message_id:
            external_message_id = f"{item.external_id}:{direction}:{created_at_external or self._now()}"
        # 生成去重键：shop_id:channel:external_message_id
        dedup_key = f"{item.shop_id}:{item.channel}:{external_message_id}"
        existing = self.db.query(CustomerServiceMessage).filter(
            CustomerServiceMessage.message_dedup_key == dedup_key,
        ).first() if item.id else None
        if existing:
            existing.message_text = text or existing.message_text
            existing.attachments_json = self._json(attachments)
            existing.raw_json = self._json(raw)
            return
        local_echo = self._find_local_chat_echo(item, direction, text)
        if local_echo:
            local_echo.external_message_id = external_message_id
            local_echo.message_dedup_key = dedup_key
            local_echo.message_text = text or local_echo.message_text
            local_echo.attachments_json = self._json(attachments)
            local_echo.created_at_external = created_at_external or local_echo.created_at_external
            local_echo.raw_json = self._json(raw)
            return
        msg = CustomerServiceMessage(
            item=item,
            external_message_id=external_message_id,
            message_dedup_key=dedup_key,
            direction=direction,
            sender_type=direction,
            message_text=text or "",
            attachments_json=self._json(attachments),
            created_at_external=created_at_external,
            raw_json=self._json(raw),
        )
        try:
            self.db.add(msg)
            # 不单独 flush：item 已在 _upsert_item 中持久化，flush 会触发 item 的重复 UPDATE
        except IntegrityError:
            self.db.rollback()
            # 并发写入冲突，重新查询并更新
            existing = self.db.query(CustomerServiceMessage).filter(
                CustomerServiceMessage.message_dedup_key == dedup_key,
            ).first()
            if existing:
                existing.message_text = text or existing.message_text
                existing.attachments_json = self._json(attachments)
                existing.raw_json = self._json(raw)
                return

    def _find_local_chat_echo(
        self,
        item: CustomerServiceItem,
        direction: str,
        text: str,
    ) -> Optional[CustomerServiceMessage]:
        if item.channel != "chat" or direction != "seller" or not item.id:
            return None
        normalized_text = (text or "").strip()
        if not normalized_text:
            return None
        return (
            self.db.query(CustomerServiceMessage)
            .filter(
                CustomerServiceMessage.item_id == item.id,
                CustomerServiceMessage.direction == "seller",
                CustomerServiceMessage.message_dedup_key.is_(None),
                CustomerServiceMessage.external_message_id.like(f"local:{item.id}:%"),
                CustomerServiceMessage.message_text == normalized_text,
            )
            .order_by(CustomerServiceMessage.created_at.desc(), CustomerServiceMessage.id.desc())
            .first()
        )

    @staticmethod
    def _raw_is_chat_event(raw: Dict[str, Any]) -> bool:
        if not isinstance(raw, dict):
            return False
        if raw.get("chatID") or raw.get("chatId") or raw.get("dialogId") or raw.get("replySign") or raw.get("reply_sign"):
            return True
        if raw.get("eventType") == "message" and isinstance(raw.get("message"), dict):
            return True
        return False

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
            # 统一返回 naive datetime（DB 存储格式），避免 aware vs naive 比较错误
            return datetime.fromtimestamp(value, SHANGHAI_TZ).replace(tzinfo=None)
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
