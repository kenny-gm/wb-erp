"""
客服翻译服务 - 手动触发，不自动翻译

使用 translate_to_zh Prompt 模板将俄语文本翻译成中文。
缓存机制：source hash 不变时不重复调用 AI。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.models import CustomerServiceItem, CustomerServiceMessage
from app.services.ai_client import AIClient, AIClientError
from app.services.ai_prompt_service import get_active_template, render_template


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def source_hash(text: str) -> str:
    """对文本内容计算 SHA256，用于判断内容是否变化"""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _extract_translated_text(raw: str) -> str:
    """从 AI 输出中提取中文翻译，兼容 JSON、fenced JSON 和纯文本。"""
    text = (raw or "").strip()
    if not text:
        return ""

    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())

    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.insert(0, text[start:i + 1])
                    break

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            translated = parsed.get("translated_text") or parsed.get("translation") or parsed.get("text")
            if isinstance(translated, str) and translated.strip():
                return translated.strip()

    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*```$", "", text).strip()
    text = re.sub(r"^(translated_text|translation|翻译|中文翻译)\s*[:：]\s*", "", text, flags=re.IGNORECASE).strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1].strip()
    return text


class CustomerTranslationService:
    def __init__(self, db: Session):
        self.db = db
        self.ai = AIClient(db)

    def translate_text(self, text: str) -> str:
        """调用 AI 将俄语文本翻译成中文，返回翻译后文本"""
        if not text or not text.strip():
            return ""
        if len(text) > 6000:
            text = text[:6000]
        template = get_active_template(self.db, "translate_to_zh")
        system_prompt = template.system_prompt
        user_prompt = render_template(template.user_prompt_template, {"text": text})
        if hasattr(self.ai, "chat_text"):
            raw = self.ai.chat_text(
                system_prompt,
                user_prompt,
                template.temperature,
                template.max_tokens,
            )
            translated = _extract_translated_text(raw)
        else:
            output = self.ai.chat_json(
                system_prompt,
                user_prompt,
                template.temperature,
                template.max_tokens,
            )
            translated = output.get("translated_text") or output.get("translation") or ""
        if not translated:
            raise AIClientError("AI 未返回 translated_text")
        return translated.strip()

    def translate_item(self, item: CustomerServiceItem) -> dict:
        """翻译客服事项 title + content，返回结果 dict"""
        source = "\n".join([x for x in [item.title or "", item.content or ""] if x]).strip()
        h = source_hash(source)
        # 缓存命中：hash 未变且已有翻译
        if (
            item.translation_status == "translated"
            and item.translation_source_hash == h
            and item.content_zh
        ):
            return {"success": True, "status": "translated", "content_zh": item.content_zh, "cached": True}
        try:
            translated = self.translate_text(source)
            item.content_zh = translated
            item.title_zh = None
            item.translation_status = "translated"
            item.translation_error = ""
            item.translation_source_hash = h
            item.translated_at = datetime.now(SHANGHAI_TZ).replace(tzinfo=None)
            return {"success": True, "status": "translated", "content_zh": translated, "cached": False}
        except Exception as exc:
            item.translation_status = "failed"
            item.translation_error = str(exc)[:1000]
            item.translation_source_hash = h
            return {"success": False, "status": "failed", "error": str(exc)}

    def translate_message(self, message: CustomerServiceMessage) -> dict:
        """翻译客服消息，返回结果 dict"""
        source = (message.message_text or "").strip()
        h = source_hash(source)
        # 缓存命中
        if (
            message.translation_status == "translated"
            and message.translation_source_hash == h
            and message.message_text_zh
        ):
            return {"success": True, "status": "translated", "message_text_zh": message.message_text_zh, "cached": True}
        try:
            translated = self.translate_text(source)
            message.message_text_zh = translated
            message.translation_status = "translated"
            message.translation_error = ""
            message.translation_source_hash = h
            message.translated_at = datetime.now(SHANGHAI_TZ).replace(tzinfo=None)
            return {"success": True, "status": "translated", "message_text_zh": translated, "cached": False}
        except Exception as exc:
            message.translation_status = "failed"
            message.translation_error = str(exc)[:1000]
            message.translation_source_hash = h
            return {"success": False, "status": "failed", "error": str(exc)}
