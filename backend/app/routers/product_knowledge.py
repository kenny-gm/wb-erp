from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import CustomerServiceItem, Product, ProductKnowledge, User, UserRole
from app.routers.auth import get_current_user
from app.services.ai_client import AIClient, AIClientDisabled, AIClientError


router = APIRouter(prefix="/api/product-knowledge", tags=["产品知识库"])
logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def _json_loads(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _json_dumps(value) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def _format_characteristic(row: Dict[str, Any]) -> str:
    name = str(row.get("name") or row.get("charcName") or "").strip()
    value = row.get("value")
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value if str(v).strip())
    value = str(value or "").strip()
    if name and value:
        return f"- {name}: {value}"
    if name:
        return f"- {name}"
    if value:
        return f"- {value}"
    return ""


def _wb_basic_info_from_products(products: List[Product]) -> str:
    """Format WB card facts as the product basic-info block."""
    rows = [product for product in products if product]
    if not rows:
        return ""

    lines: List[str] = []
    for title, attr in [
        ("WB标题", "wb_title"),
        ("品牌", "wb_brand"),
        ("类目", "wb_subject_name"),
        ("WB描述", "wb_description"),
    ]:
        value = next((str(getattr(product, attr, "")).strip() for product in rows if getattr(product, attr, None)), "")
        if value:
            lines.append(f"{title}: {value}")

    characteristic_lines: List[str] = []
    for product in rows:
        characteristics = _json_loads(getattr(product, "wb_characteristics_json", None), [])
        for row in characteristics:
            if len(characteristic_lines) >= 20:
                break
            if isinstance(row, dict):
                line = _format_characteristic(row)
                if line and line not in characteristic_lines:
                    characteristic_lines.append(line)
        if len(characteristic_lines) >= 20:
            break
    if characteristic_lines:
        lines.append("参数/属性:")
        lines.extend(characteristic_lines)

    if not lines:
        return ""
    return "WB产品卡字段（来自WB Content API，不含图片）:\n" + "\n".join(lines)


def _translate_basic_info_to_zh(db: Session, basic_info: str) -> str:
    source = (basic_info or "").strip()
    if not source:
        raise HTTPException(status_code=400, detail="没有可翻译的 WB 基础信息")
    system_prompt = (
        "你是跨境电商产品资料翻译助手。只做事实翻译和结构化整理，"
        "不要添加原文没有的信息，不要写营销夸张语，不要写客服回复话术。"
        "不要输出思考过程，不要输出<think>标签，只输出中文整理结果。"
    )
    source_variants = [source[:2500]]
    if len(source) > 1400:
        source_variants.append(source[:1400])
    try:
        client = AIClient(db)
        for index, text in enumerate(source_variants):
            user_prompt = (
                "请把下面 WB 商品卡基础信息翻译并整理成中文，保留标题、品牌、类目、描述、参数/属性结构。"
                "输出纯中文文本，不要输出 JSON，不要解释，控制在 1000 字以内。\n\n"
                f"{text}"
            )
            result = client.chat_text(
                system_prompt,
                user_prompt,
                temperature=0.1,
                max_tokens=1600 if index == 0 else 1000,
            ).strip()
            if result:
                return result
        raise AIClientError("AI 返回空中文整理")
    except AIClientDisabled as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except AIClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _try_translate_basic_info_to_zh(db: Session, profile: ProductKnowledge) -> bool:
    """Auto-generate Chinese basics without breaking normal page loads."""
    if not (profile.basic_info or "").strip():
        profile.basic_info_zh = ""
        return False
    try:
        translated = _translate_basic_info_to_zh(db, profile.basic_info or "").strip()
        if not translated:
            return False
        profile.basic_info_zh = translated
        return True
    except HTTPException as exc:
        logger.warning(
            "product knowledge basic info auto-translation skipped: profile_id=%s detail=%s",
            profile.id,
            exc.detail,
        )
        return False


def _sync_profile_basic_info(
    db: Session,
    profile: ProductKnowledge,
    products: Optional[List[Product]] = None,
    auto_translate: bool = True,
) -> bool:
    linked_ids = _json_loads(profile.linked_product_ids_json, [])
    rows = products
    if rows is None:
        rows = db.query(Product).filter(Product.id.in_(linked_ids)).all() if linked_ids else []

    changed = False
    wb_basic_info = _wb_basic_info_from_products(rows or [])
    if wb_basic_info:
        current_basic = (profile.basic_info or "").strip()
        if current_basic != wb_basic_info:
            profile.basic_info = wb_basic_info
            profile.basic_info_zh = ""
            changed = True

    if auto_translate and (profile.basic_info or "").strip() and not (profile.basic_info_zh or "").strip():
        if _try_translate_basic_info_to_zh(db, profile):
            changed = True

    return changed


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


def _allowed_owners(user: User) -> List[str]:
    raw = getattr(user, "allowed_owners", None)
    if isinstance(raw, list):
        return [str(owner).strip() for owner in raw if str(owner).strip()]
    if isinstance(raw, str):
        return [owner.strip() for owner in raw.split(",") if owner.strip()]
    return []


def _base_product_query(db: Session, user: User):
    query = db.query(Product)
    owners = _allowed_owners(user)
    if owners:
        query = query.filter(Product.owner.in_(owners))
    return query


def _can_edit(profile: ProductKnowledge, user: User) -> bool:
    if user.role in (UserRole.ADMIN, UserRole.MANAGER):
        return True
    if user.role != UserRole.PRODUCT_OWNER:
        return False
    owners = set(_allowed_owners(user))
    if not owners:
        return False
    profile_owners = set(_json_loads(profile.owners_json, []))
    return bool(owners & profile_owners)


def _profile_to_dict(profile: ProductKnowledge) -> Dict[str, Any]:
    fields = [
        profile.basic_info,
        profile.basic_info_zh,
        profile.features,
        profile.usage_guide,
        profile.troubleshooting,
        profile.after_sales_policy,
    ]
    faq = _json_loads(profile.faq_json, [])
    completed = sum(1 for value in fields if (value or "").strip())
    if faq:
        completed += 1
    completeness = round(completed / 7 * 100)
    return {
        "id": profile.id,
        "product_key": profile.product_key,
        "product_name": profile.product_name,
        "aliases": _json_loads(profile.aliases_json, []),
        "linked_product_ids": _json_loads(profile.linked_product_ids_json, []),
        "linked_nm_ids": _json_loads(profile.linked_nm_ids_json, []),
        "linked_skus": _json_loads(profile.linked_skus_json, []),
        "owners": _json_loads(profile.owners_json, []),
        "shop_names": _json_loads(profile.shop_names_json, []),
        "basic_info": profile.basic_info or "",
        "basic_info_zh": profile.basic_info_zh or "",
        "features": profile.features or "",
        "usage_guide": profile.usage_guide or "",
        "troubleshooting": profile.troubleshooting or "",
        "faq": faq,
        "after_sales_policy": profile.after_sales_policy or "",
        "internal_notes_zh": profile.internal_notes_zh or "",
        "ai_enabled": bool(profile.ai_enabled),
        "status": profile.status or "active",
        "completeness": completeness,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        "reviewed_at": profile.reviewed_at.isoformat() if profile.reviewed_at else None,
    }


def sync_profiles_from_products(db: Session, user: User, auto_translate_limit: int = 3) -> int:
    products = _base_product_query(db, user).filter(Product.nm_id != "0").all()
    grouped: Dict[str, List[Product]] = {}
    for product in products:
        name = _product_name(product)
        if not name:
            continue
        grouped.setdefault(name, []).append(product)

    changed = 0
    translations_remaining = max(auto_translate_limit, 0)
    for name, rows in grouped.items():
        key = _product_key(name)
        profile = db.query(ProductKnowledge).filter(ProductKnowledge.product_key == key).first()
        if not profile:
            profile = ProductKnowledge(product_key=key, product_name=name)
            db.add(profile)
            changed += 1
        aliases = sorted({
            value
            for p in rows
            for value in (p.name, getattr(p, "wb_title", None), getattr(p, "wb_subject_name", None))
            if value and value != name
        })
        product_ids = sorted({p.id for p in rows})
        nm_ids = sorted({p.nm_id for p in rows if p.nm_id})
        skus = sorted({p.sku for p in rows if p.sku})
        owners = sorted({p.owner for p in rows if p.owner})
        shop_names = sorted({p.shop.name for p in rows if p.shop and p.shop.name})
        updates = {
            "product_name": name,
            "aliases_json": _json_dumps(aliases),
            "linked_product_ids_json": _json_dumps(product_ids),
            "linked_nm_ids_json": _json_dumps(nm_ids),
            "linked_skus_json": _json_dumps(skus),
            "owners_json": _json_dumps(owners),
            "shop_names_json": _json_dumps(shop_names),
        }
        touched = False
        for field, value in updates.items():
            if getattr(profile, field) != value:
                setattr(profile, field, value)
                touched = True
        before_zh = (profile.basic_info_zh or "").strip()
        if _sync_profile_basic_info(db, profile, rows, auto_translate=translations_remaining > 0):
            touched = True
        after_zh = (profile.basic_info_zh or "").strip()
        if not before_zh and after_zh and translations_remaining > 0:
            translations_remaining -= 1
        if touched:
            profile.updated_at = _now()
            changed += 1
    if changed:
        db.commit()
    else:
        db.flush()
    return changed


class KnowledgePayload(BaseModel):
    features: Optional[str] = None
    usage_guide: Optional[str] = None
    troubleshooting: Optional[str] = None
    faq: Optional[List[Dict[str, Any]]] = None
    after_sales_policy: Optional[str] = None
    internal_notes_zh: Optional[str] = None
    ai_enabled: Optional[bool] = None
    status: Optional[str] = None

    class Config:
        extra = "forbid"


@router.get("/")
def list_product_knowledge(
    search: str = "",
    owner: str = "",
    status: str = "active",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sync_profiles_from_products(db, current_user, auto_translate_limit=0)
    query = db.query(ProductKnowledge)
    if status and status != "all":
        query = query.filter(ProductKnowledge.status == status)
    owners = _allowed_owners(current_user)
    if owners and current_user.role != UserRole.ADMIN:
        owner_filters = [ProductKnowledge.owners_json.contains(owner_name) for owner_name in owners]
        query = query.filter(or_(*owner_filters))
    if owner:
        query = query.filter(ProductKnowledge.owners_json.contains(owner))
    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            ProductKnowledge.product_name.like(like),
            ProductKnowledge.aliases_json.like(like),
            ProductKnowledge.linked_skus_json.like(like),
            ProductKnowledge.linked_nm_ids_json.like(like),
        ))
    rows = query.order_by(ProductKnowledge.updated_at.desc(), ProductKnowledge.product_name.asc()).all()
    return {"items": [_profile_to_dict(row) for row in rows], "total": len(rows)}


@router.post("/refresh-from-products")
def refresh_from_products(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    changed = sync_profiles_from_products(db, current_user, auto_translate_limit=5)
    db.commit()
    return {"success": True, "created": changed}


@router.get("/{profile_id}")
def get_product_knowledge(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = db.query(ProductKnowledge).filter(ProductKnowledge.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="产品知识库不存在")
    owners = _allowed_owners(current_user)
    if owners and current_user.role != UserRole.ADMIN:
        if not (set(owners) & set(_json_loads(profile.owners_json, []))):
            raise HTTPException(status_code=403, detail="无权访问该产品知识库")
    if _sync_profile_basic_info(db, profile):
        profile.updated_at = _now()
        db.commit()
        db.refresh(profile)
    return _profile_to_dict(profile)


@router.put("/{profile_id}")
def update_product_knowledge(
    profile_id: int,
    data: KnowledgePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = db.query(ProductKnowledge).filter(ProductKnowledge.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="产品知识库不存在")
    if not _can_edit(profile, current_user):
        raise HTTPException(status_code=403, detail="无权编辑该产品知识库")

    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        if field == "faq":
            profile.faq_json = _json_dumps(value)
        elif hasattr(profile, field):
            setattr(profile, field, value)
    profile.updated_by = current_user.id
    profile.updated_at = _now()
    db.commit()
    db.refresh(profile)
    return {"success": True, "item": _profile_to_dict(profile)}


@router.post("/{profile_id}/translate-basic-info")
def translate_basic_info(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = db.query(ProductKnowledge).filter(ProductKnowledge.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="产品知识库不存在")
    if not _can_edit(profile, current_user):
        raise HTTPException(status_code=403, detail="无权更新该产品知识库")
    if not (profile.basic_info or "").strip():
        linked_ids = _json_loads(profile.linked_product_ids_json, [])
        products = db.query(Product).filter(Product.id.in_(linked_ids)).all() if linked_ids else []
        wb_basic_info = _wb_basic_info_from_products(products)
        if wb_basic_info:
            profile.basic_info = wb_basic_info
    profile.basic_info_zh = _translate_basic_info_to_zh(db, profile.basic_info or "")
    profile.updated_by = current_user.id
    profile.updated_at = _now()
    db.commit()
    db.refresh(profile)
    return {"success": True, "item": _profile_to_dict(profile)}


def find_product_knowledge_for_item(db: Session, item: CustomerServiceItem) -> Optional[ProductKnowledge]:
    probes = [str(v) for v in (item.nm_id, item.sku) if v]
    for probe in probes:
        profile = db.query(ProductKnowledge).filter(
            ProductKnowledge.status == "active",
            ProductKnowledge.ai_enabled == True,  # noqa: E712
            or_(
                ProductKnowledge.linked_nm_ids_json.like(f"%{probe}%"),
                ProductKnowledge.linked_skus_json.like(f"%{probe}%"),
                ProductKnowledge.aliases_json.like(f"%{probe}%"),
            )
        ).first()
        if profile:
            return profile

    names = []
    product = getattr(item, "product", None)
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


def build_product_knowledge_context(db: Session, item: CustomerServiceItem) -> Dict[str, Any]:
    profile = find_product_knowledge_for_item(db, item)
    if not profile:
        return {"context": "未命中产品知识库。禁止编造具体产品功能、尺寸、材质、故障处理或售后承诺。", "sources": []}

    faq = _json_loads(profile.faq_json, [])
    product = _product_for_item(db, item)
    wb_basic_info = _wb_basic_info_from_products([product] if product else [])
    basic_parts = []
    if wb_basic_info and "WB产品卡字段" not in (profile.basic_info or ""):
        basic_parts.append(wb_basic_info)
    if profile.basic_info and profile.basic_info.strip():
        basic_parts.append(profile.basic_info.strip())
    basic_info = "\n".join(basic_parts)
    sections = [
        ("基础信息", basic_info),
        ("功能卖点", profile.features),
        ("使用方法", profile.usage_guide),
        ("故障处理", profile.troubleshooting),
        ("售后边界", profile.after_sales_policy),
    ]
    lines = [f"产品知识库: {profile.product_name}"]
    for title, value in sections:
        if value and value.strip():
            lines.append(f"{title}: {value.strip()}")

    if faq:
        lines.append("FAQ:")
        for row in faq[:8]:
            question = str(row.get("question") or row.get("q") or "").strip()
            answer_zh = str(row.get("answer_zh") or row.get("note") or "").strip()
            answer_ru = str(row.get("answer_ru") or row.get("answer") or "").strip()
            if question or answer_zh or answer_ru:
                line = f"- 买家可能问: {question}\n  中文标准答案/处理说明: {answer_zh}"
                if answer_ru:
                    line += f"\n  历史俄语参考: {answer_ru}"
                lines.append(line)
    return {
        "context": "\n".join(lines),
        "sources": [{
            "id": profile.id,
            "product_name": profile.product_name,
            "completeness": _profile_to_dict(profile)["completeness"],
        }],
    }
