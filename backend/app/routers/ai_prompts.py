"""
AI 提示词模板路由

GET /api/ai-prompts                    - 列出所有模板（active 版本）
GET /api/ai-prompts/{template_key}     - 获取某 key 所有版本
PATCH /api/ai-prompts/{template_key}   - 保存新版本（不覆盖旧版本）
POST /api/ai-prompts/{template_key}/test - 渲染 / 调用 AI 测试
POST /api/ai-prompts/{template_key}/activate-version - 激活指定版本
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import AIPromptTemplate
from app.routers.auth import get_current_user, get_current_admin
from app.services.ai_client import AIClient, AIClientDisabled, AIClientError
from app.services.ai_prompt_service import (
    activate_version as svc_activate_version,
    create_new_version,
    get_active_template,
    list_all_versions,
    list_templates,
    render_template,
)


router = APIRouter(prefix="/api/ai-prompts", tags=["AI提示词"])


# ========== Schema ==========

class PromptPayload(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    user_prompt_template: Optional[str] = None
    output_schema_json: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

    class Config:
        extra = "forbid"


class TestRequest(BaseModel):
    variables: Dict[str, Any] = {}
    run_ai: bool = False

    class Config:
        extra = "forbid"


class ActivateRequest(BaseModel):
    version: int

    class Config:
        extra = "forbid"


# ========== 接口 ==========

@router.get("")
def get_all_prompts(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin),
):
    """列出所有模板的 active 版本（admin/manager）"""
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足")
    return list_templates(db)


@router.get("/{template_key}")
def get_prompt_versions(
    template_key: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin),
):
    """获取某 key 所有版本（admin/manager）"""
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足")
    return list_all_versions(db, template_key)


@router.patch("/{template_key}")
def patch_prompt(
    template_key: str,
    data: PromptPayload,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin),
):
    """保存新版本（仅 admin）"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="权限不足")
    payload = data.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=400, detail="没有提供任何修改字段")
    if data.output_schema_json is not None:
        try:
            json.loads(data.output_schema_json)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"output_schema_json 不是合法 JSON: {e}")

    tpl = create_new_version(db, template_key, payload, current_user.id)
    return {"success": True, "version": tpl.version, "id": tpl.id}


@router.post("/{template_key}/test")
def test_prompt(
    template_key: str,
    data: TestRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin),
):
    """渲染 Prompt（可选是否调用 AI，admin/manager）"""
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足")
    tpl = get_active_template(db, template_key)
    if not tpl:
        raise HTTPException(status_code=404, detail=f"模板 {template_key} 不存在或未激活")

    rendered_system = render_template(tpl.system_prompt, data.variables)
    rendered_user = render_template(tpl.user_prompt_template, data.variables)

    result = {
        "success": True,
        "rendered_system_prompt": rendered_system,
        "rendered_user_prompt": rendered_user,
        "ai_output": None,
    }

    if data.run_ai:
        client = AIClient(db)
        try:
            if tpl.output_schema_json and tpl.output_schema_json != "{}":
                out = client.chat_json(
                    rendered_system,
                    rendered_user,
                    tpl.temperature,
                    tpl.max_tokens,
                )
                result["ai_output"] = out
            else:
                out = client.chat_text(
                    rendered_system,
                    rendered_user,
                    tpl.temperature,
                    tpl.max_tokens,
                )
                result["ai_output"] = out
        except AIClientDisabled as e:
            result["success"] = False
            result["error"] = str(e)
        except AIClientError as e:
            result["success"] = False
            result["error"] = str(e)
            # 从错误信息中提取原始文本片段（不含 <think>）
            raw = str(e)
            if "原始文本片段:" in raw:
                result["raw_output_preview"] = raw.split("原始文本片段:", 1)[1].strip()

    return result


@router.post("/{template_key}/activate-version")
def activate_prompt_version(
    template_key: str,
    data: ActivateRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin),
):
    """激活指定版本（仅 admin）"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="权限不足")
    try:
        tpl = svc_activate_version(db, template_key, data.version, current_user.id)
        return {"success": True, "version": tpl.version}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
