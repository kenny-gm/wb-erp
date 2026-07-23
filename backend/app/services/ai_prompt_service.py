"""
AI Prompt 模板服务

- 查询 / 渲染模板
- 版本管理（新建版本 / 激活旧版本）
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.models import AIPromptTemplate, User


def get_active_template(db: Session, template_key: str) -> Optional[AIPromptTemplate]:
    return (
        db.query(AIPromptTemplate)
        .filter(AIPromptTemplate.template_key == template_key, AIPromptTemplate.is_active == True)
        .first()
    )


def list_templates(db: Session) -> List[Dict[str, Any]]:
    """返回每个 template_key 的当前 active 版本列表"""
    rows = (
        db.query(AIPromptTemplate)
        .filter(AIPromptTemplate.is_active == True)
        .order_by(AIPromptTemplate.template_key)
        .all()
    )
    return [_to_dict(r) for r in rows]


def render_template(template: str, variables: Dict[str, Any]) -> str:
    """
    简单 {{var_name}} 替换。
    缺失变量替换为空字符串。
    """
    def replacer(m):
        key = m.group(1).strip()
        return variables.get(key, "")
    return re.sub(r"\{\{(\w+)\}\}", replacer, template)


def create_new_version(
    db: Session,
    template_key: str,
    payload: Dict[str, Any],
    user_id: Optional[int] = None,
) -> AIPromptTemplate:
    """
    保存为新版本（不覆盖旧版本）。
    同 key 旧版本 is_active=False，新版本 is_active=True。
    """
    # 找当前最大 version
    max_ver_row = (
        db.query(AIPromptTemplate)
        .filter(AIPromptTemplate.template_key == template_key)
        .order_by(AIPromptTemplate.version.desc())
        .first()
    )
    new_version = (max_ver_row.version + 1) if max_ver_row else 1

    # 旧版本全部设为非活跃
    db.query(AIPromptTemplate).filter(
        AIPromptTemplate.template_key == template_key,
        AIPromptTemplate.is_active == True,
    ).update({"is_active": False})

    new_tpl = AIPromptTemplate(
        template_key=template_key,
        name=payload.get("name", ""),
        description=payload.get("description", ""),
        system_prompt=payload.get("system_prompt", ""),
        user_prompt_template=payload.get("user_prompt_template", ""),
        output_schema_json=payload.get("output_schema_json", "{}"),
        temperature=float(payload.get("temperature", 0.2)),
        max_tokens=int(payload.get("max_tokens", 1200)),
        is_active=True,
        version=new_version,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(new_tpl)
    db.commit()
    db.refresh(new_tpl)
    return new_tpl


def activate_version(
    db: Session,
    template_key: str,
    version: int,
    user_id: Optional[int] = None,
) -> AIPromptTemplate:
    """
    激活指定版本（只保留一个 is_active=True）。
    """
    # 全部设为非活跃
    db.query(AIPromptTemplate).filter(
        AIPromptTemplate.template_key == template_key,
    ).update({"is_active": False})

    target = (
        db.query(AIPromptTemplate)
        .filter(AIPromptTemplate.template_key == template_key, AIPromptTemplate.version == version)
        .first()
    )
    if not target:
        raise ValueError(f"template_key={template_key}, version={version} 不存在")

    target.is_active = True
    target.updated_by = user_id
    db.commit()
    db.refresh(target)
    return target


def delete_version(
    db: Session,
    template_key: str,
    version: int,
) -> AIPromptTemplate:
    """
    删除指定旧版本。
    当前激活版本不能删除，避免模板没有可用 active 版本。
    """
    target = (
        db.query(AIPromptTemplate)
        .filter(AIPromptTemplate.template_key == template_key, AIPromptTemplate.version == version)
        .first()
    )
    if not target:
        raise ValueError(f"template_key={template_key}, version={version} 不存在")
    if target.is_active:
        raise ValueError("当前激活版本不能删除")

    db.delete(target)
    db.commit()
    return target


def list_all_versions(db: Session, template_key: str) -> List[Dict[str, Any]]:
    """返回某 key 所有版本，active 排第一"""
    rows = (
        db.query(AIPromptTemplate)
        .filter(AIPromptTemplate.template_key == template_key)
        .order_by(AIPromptTemplate.is_active.desc(), AIPromptTemplate.version.desc())
        .all()
    )
    return [_to_dict(r) for r in rows]


def _to_dict(tpl: AIPromptTemplate) -> Dict[str, Any]:
    return {
        "id": tpl.id,
        "template_key": tpl.template_key,
        "name": tpl.name,
        "description": tpl.description,
        "system_prompt": tpl.system_prompt,
        "user_prompt_template": tpl.user_prompt_template,
        "output_schema_json": tpl.output_schema_json,
        "temperature": tpl.temperature,
        "max_tokens": tpl.max_tokens,
        "is_active": tpl.is_active,
        "version": tpl.version,
        "created_by": tpl.created_by,
        "updated_by": tpl.updated_by,
        "created_at": tpl.created_at.isoformat() if tpl.created_at else None,
        "updated_at": tpl.updated_at.isoformat() if tpl.updated_at else None,
    }
