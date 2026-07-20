"""
Migration: make customer_reply prompt explicitly reference product knowledge.

The AI draft route still passes the variable from code, but the active prompt
template must visibly contain the product knowledge citation block.
"""
from sqlalchemy import text

from app.database import engine
from app.models.models import AIPromptTemplate
from app.services.ai_prompt_service import create_new_version


PRODUCT_KNOWLEDGE_BLOCK = """产品知识库引用内容（优先依据；没有出现的信息禁止编造）:
{{product_knowledge}}

如果产品知识库未命中或信息不足，请生成保守草稿，并避免具体产品功能、尺寸、材质、故障处理或售后结果承诺。"""


def _table_exists(conn, table_name: str) -> bool:
    if engine.dialect.name == "sqlite":
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        ).fetchall()
        return bool(rows)
    if engine.dialect.name == "mysql":
        rows = conn.execute(text(f"SHOW TABLES LIKE '{table_name}'")).fetchall()
        return bool(rows)
    raise RuntimeError(f"Unsupported dialect: {engine.dialect.name}")


def migrate_add_product_knowledge_to_customer_reply_prompt() -> bool:
    with engine.begin() as conn:
        if not _table_exists(conn, "ai_prompt_templates"):
            print("[migration] ai_prompt_templates 表不存在，跳过产品知识库 Prompt 显式引用")
            return True

    from app.database import SessionLocal
    db = SessionLocal()
    try:
        active = db.query(AIPromptTemplate).filter_by(
            template_key="customer_reply",
            is_active=True,
        ).first()
        if not active:
            print("[migration] customer_reply 模板不存在，跳过产品知识库 Prompt 显式引用")
            return True

        template = active.user_prompt_template or ""
        if "{{product_knowledge}}" in template and "产品知识库引用内容" in template:
            print("[migration] customer_reply 已显式引用产品知识库，跳过")
            return True

        template = template.rstrip()
        new_template = f"{template}\n\n{PRODUCT_KNOWLEDGE_BLOCK}"
        create_new_version(
            db,
            template_key="customer_reply",
            payload={
                "name": active.name,
                "system_prompt": active.system_prompt,
                "user_prompt_template": new_template,
                "temperature": active.temperature,
                "max_tokens": active.max_tokens,
                "description": "显式引用产品知识库内容，避免知识库只在代码中隐式生效",
            },
        )
        latest = db.query(AIPromptTemplate).filter_by(
            template_key="customer_reply",
            is_active=True,
        ).first()
        print(f"[migration] customer_reply 已新增产品知识库显式引用: v{latest.version}" if latest else "[migration] customer_reply 已新增产品知识库显式引用")
        return True
    finally:
        db.close()


if __name__ == "__main__":
    success = migrate_add_product_knowledge_to_customer_reply_prompt()
    exit(0 if success else 1)
