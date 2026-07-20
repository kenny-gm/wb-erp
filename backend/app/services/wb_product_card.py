"""
WB product card parsing helpers.

Only text/structured fields are persisted. Image/media fields are stripped to
avoid storing large payloads in the database.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from app.models.models import Product


MEDIA_KEYS = {
    "mediaFiles",
    "mediafiles",
    "media",
    "photos",
    "photo",
    "pictures",
    "images",
    "image",
    "video",
    "videos",
}


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _first_text(card: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = card.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _characteristics(card: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = card.get("characteristics")
    if raw is None:
        raw = card.get("characterstics")
    return raw if isinstance(raw, list) else []


def _char_value(card: Dict[str, Any], *names: str) -> str:
    wanted = {name.lower() for name in names}
    for char in _characteristics(card):
        name = str(char.get("name") or "").strip().lower()
        if name not in wanted and str(char.get("id")) != "0":
            continue
        value = char.get("value")
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value if str(v).strip())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def product_name_from_card(card: Dict[str, Any], fallback: str = "") -> str:
    return (
        _char_value(card, "Наименование")
        or _first_text(card, "imtName", "title", "name", "subjectName")
        or fallback
    )


def strip_media_fields(value: Any) -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if key in MEDIA_KEYS or key.lower() in MEDIA_KEYS:
                continue
            clean[key] = strip_media_fields(item)
        return clean
    if isinstance(value, list):
        return [strip_media_fields(item) for item in value]
    return value


def extract_wb_card_fields(card: Dict[str, Any]) -> Dict[str, Any]:
    clean_card = strip_media_fields(copy.deepcopy(card))
    characteristics = _characteristics(clean_card)
    return {
        "wb_title": _first_text(card, "imtName", "title", "name") or product_name_from_card(card),
        "wb_brand": _first_text(card, "brand", "brandName"),
        "wb_subject_name": _first_text(card, "subjectName", "object", "objectName"),
        "wb_description": _first_text(card, "description"),
        "wb_characteristics_json": _json_dumps(characteristics or []),
        "wb_card_raw_json": _json_dumps(clean_card or {}),
        "wb_card_updated_at": datetime.now(ZoneInfo("Asia/Shanghai")),
    }


def apply_wb_card_fields(product: Product, card: Dict[str, Any]) -> None:
    for field, value in extract_wb_card_fields(card).items():
        setattr(product, field, value)
