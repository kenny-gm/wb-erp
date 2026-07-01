"""
Migration: 修复已有 Prompt 模板的 JSON 输出指令（幂等）

如果模板内容不包含"只输出 JSON"，则追加 JSON 输出要求。
不影响已有的其他配置。
"""

from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import text
from app.database import engine


def _now():
    return datetime.now(ZoneInfo("Asia/Shanghai"))


JSON_INSTRUCTIONS = {
    "customer_reply": (
        "你必须只输出 JSON。\n"
        "不要输出 Markdown。\n"
        "不要输出解释。\n"
        "不要输出思考过程。\n"
        "不要输出 <think> 标签。\n"
        "JSON 格式：{\"reply\":\"俄语回复草稿\"}\n"
        "reply 字段必须是俄语，禁止中文。\n"
        "禁止承诺退款、赔偿、物流时效。"
    ),
    "translate_to_zh": (
        "你必须只输出 JSON。\n"
        "不要输出 Markdown。\n"
        "不要输出解释。\n"
        "不要输出思考过程。\n"
        "不要输出 <think> 标签。\n"
        "JSON 格式：{\"translated_text\":\"简体中文译文\"}\n"
        "只翻译，不总结，不生成回复。"
    ),
    "product_analysis": (
        "不要输出 <think> 标签。\n"
        "不要输出思考过程。"
    ),
}


def _append_json_instruction(system_prompt: str, required_text: str) -> str:
    """如果 system_prompt 中没有 required_text，则追加"""
    if required_text in system_prompt:
        return system_prompt
    return system_prompt + "\n\n" + required_text


def migrate_fix_ai_prompt_json_instructions():
    with engine.begin() as conn:
        for template_key, instruction in JSON_INSTRUCTIONS.items():
            row = conn.execute(
                text("SELECT id, system_prompt FROM ai_prompt_templates WHERE template_key=:key AND is_active=1"),
                {"key": template_key},
            ).fetchone()
            if not row:
                continue
            current = row.system_prompt or ""
            if "只输出 JSON" not in current:
                new_prompt = _append_json_instruction(current, instruction)
                conn.execute(
                    text("UPDATE ai_prompt_templates SET system_prompt=:prompt, updated_at=:updated_at WHERE id=:id"),
                    {"prompt": new_prompt, "updated_at": _now(), "id": row.id},
                )
                print(f"[migration] 修复模板 {template_key} 的 JSON 输出指令")
            else:
                print(f"[migration] 模板 {template_key} 已包含 JSON 输出指令，跳过")
        print("[migration] fix_ai_prompt_json_instructions 完成")
        return True


if __name__ == "__main__":
    success = migrate_fix_ai_prompt_json_instructions()
    exit(0 if success else 1)