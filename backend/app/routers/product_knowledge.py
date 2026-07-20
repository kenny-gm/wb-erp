from __future__ import annotations

import hashlib
import json
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


router = APIRouter(prefix="/api/product-knowledge", tags=["产品知识库"])


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


def _product_name(product: Product) -> str:
    return (product.custom_name or product.name or product.sku or "").strip()


def _product_key(product_name: str) -> str:
    normalized = " ".join((product_name or "").strip().lower().split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


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
        profile.features,
        profile.usage_guide,
        profile.troubleshooting,
        profile.after_sales_policy,
    ]
    faq = _json_loads(profile.faq_json, [])
    completed = sum(1 for value in fields if (value or "").strip())
    if faq:
        completed += 1
    completeness = round(completed / 6 * 100)
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


def sync_profiles_from_products(db: Session, user: User) -> int:
    products = _base_product_query(db, user).filter(Product.nm_id != "0").all()
    grouped: Dict[str, List[Product]] = {}
    for product in products:
        name = _product_name(product)
        if not name:
            continue
        grouped.setdefault(name, []).append(product)

    changed = 0
    for name, rows in grouped.items():
        key = _product_key(name)
        profile = db.query(ProductKnowledge).filter(ProductKnowledge.product_key == key).first()
        if not profile:
            profile = ProductKnowledge(product_key=key, product_name=name)
            db.add(profile)
            changed += 1
        aliases = sorted({p.name for p in rows if p.name and p.name != name})
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
        if touched:
            profile.updated_at = _now()
            changed += 1
    if changed:
        db.commit()
    else:
        db.flush()
    return changed


class KnowledgePayload(BaseModel):
    basic_info: Optional[str] = None
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
    sync_profiles_from_products(db, current_user)
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
    changed = sync_profiles_from_products(db, current_user)
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


def find_product_knowledge_for_item(db: Session, item: CustomerServiceItem) -> Optional[ProductKnowledge]:
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
    return None


def build_product_knowledge_context(db: Session, item: CustomerServiceItem) -> Dict[str, Any]:
    profile = find_product_knowledge_for_item(db, item)
    if not profile:
        return {"context": "未命中产品知识库。禁止编造具体产品功能、尺寸、材质、故障处理或售后承诺。", "sources": []}

    faq = _json_loads(profile.faq_json, [])
    sections = [
        ("基础信息", profile.basic_info),
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
