"""
Migration: 新增 ai_prompt_templates 表和默认 AI 设置

幂等：可重复执行。
"""

from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import text
from app.database import engine
import json


def _now():
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name},
    ).fetchone()
    return row is not None


def _ensure_setting(conn, key: str, value: str, description: str = ""):
    exists = conn.execute(
        text("SELECT id FROM system_settings WHERE key=:key"),
        {"key": key},
    ).fetchone()
    if not exists:
        conn.execute(
            text("INSERT INTO system_settings (key, value, description, updated_at) VALUES (:key, :value, :description, :updated_at)"),
            {"key": key, "value": value, "description": description, "updated_at": _now()},
        )


def _insert_prompt_if_missing(conn, template_key, name, description, system_prompt, user_prompt_template, output_schema_json, temperature=0.2, max_tokens=1200):
    exists = conn.execute(
        text("SELECT id FROM ai_prompt_templates WHERE template_key=:template_key AND version=1"),
        {"template_key": template_key},
    ).fetchone()
    if exists:
        return
    conn.execute(
        text("""
            INSERT INTO ai_prompt_templates
            (template_key, name, description, system_prompt, user_prompt_template, output_schema_json,
             temperature, max_tokens, is_active, version, created_at, updated_at)
            VALUES
            (:template_key, :name, :description, :system_prompt, :user_prompt_template, :output_schema_json,
             :temperature, :max_tokens, 1, 1, :created_at, :updated_at)
        """),
        {
            "template_key": template_key,
            "name": name,
            "description": description,
            "system_prompt": system_prompt,
            "user_prompt_template": user_prompt_template,
            "output_schema_json": json.dumps(output_schema_json, ensure_ascii=False),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "created_at": _now(),
            "updated_at": _now(),
        },
    )


def migrate_add_ai_prompt_templates():
    with engine.begin() as conn:
        # 创建表
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_prompt_templates (
                id INTEGER PRIMARY KEY,
                template_key VARCHAR(80) NOT NULL,
                name VARCHAR(200) NOT NULL,
                description TEXT DEFAULT '',
                system_prompt TEXT NOT NULL,
                user_prompt_template TEXT NOT NULL,
                output_schema_json TEXT DEFAULT '{}',
                temperature FLOAT DEFAULT 0.2,
                max_tokens INTEGER DEFAULT 1200,
                is_active BOOLEAN DEFAULT 1,
                version INTEGER DEFAULT 1,
                created_by INTEGER NULL,
                updated_by INTEGER NULL,
                created_at DATETIME,
                updated_at DATETIME,
                FOREIGN KEY(created_by) REFERENCES users(id),
                FOREIGN KEY(updated_by) REFERENCES users(id)
            )
        """))

        # 创建索引
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_ai_prompt_template_key_version ON ai_prompt_templates(template_key, version)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ai_prompt_template_active ON ai_prompt_templates(template_key, is_active)"))

        # 插入默认 AI 设置
        _ensure_setting(conn, "ai.enabled", "false", "AI 是否启用")
        _ensure_setting(conn, "ai.provider", "openai", "AI 服务商")
        _ensure_setting(conn, "ai.base_url", "https://api.openai.com/v1", "OpenAI 兼容 Base URL")
        _ensure_setting(conn, "ai.model", "gpt-4.1-mini", "AI 模型")
        _ensure_setting(conn, "ai.timeout", "60", "AI 请求超时秒数")
        _ensure_setting(conn, "ai.max_tokens", "1200", "AI 默认最大输出 token")

        # 插入默认 Prompt 模板
        _insert_prompt_if_missing(
            conn,
            "translate_to_zh",
            "俄语内容翻译成中文",
            "客服手动点击翻译时使用",
            "你必须只输出 JSON。\n不要输出 Markdown。\n不要输出解释。\n不要输出思考过程。\n不要输出 <think> 标签。\nJSON 格式：{\"translated_text\":\"简体中文译文\"}\n只翻译，不总结，不生成回复。\n\n请将俄语买家内容翻译成简体中文。保留商品型号、数字、单位、订单编号。不要添加原文没有的信息。",
            "原文：\n{{text}}",
            {"type": "object", "properties": {"translated_text": {"type": "string"}}},
            0.1,
            1200,
        )
        _insert_prompt_if_missing(
            conn,
            "customer_reply",
            "客服俄语回复草稿",
            "生成客服回复草稿，必须人工确认后发送",
            "你必须只输出 JSON。\n不要输出 Markdown。\n不要输出解释。\n不要输出思考过程。\n不要输出 <think> 标签。\nJSON 格式：{\"reply\":\"俄语回复草稿\"}\nreply 字段必须是俄语，禁止中文。\n禁止承诺退款、赔偿、物流时效。\n\n你是 Wildberries 店铺客服助手。只生成回复草稿，最终由人工确认。",
            "渠道：{{channel}}\n商品：{{product_name}}\n买家内容：{{content}}\n中文参考：{{content_zh}}\n请生成一条俄语回复草稿。",
            {"type": "object", "properties": {"reply": {"type": "string"}}},
            0.3,
            1200,
        )
        _insert_prompt_if_missing(
            conn,
            "product_analysis",
            "产品运营分析",
            "仅基于系统内数据分析产品问题",
            "你必须只输出 JSON。不要输出 Markdown。不要输出 <think> 标签。不要输出思考过程。\n\n你是 Wildberries 店铺产品运营分析助手。你只能基于系统提供的数据进行分析。不能编造竞品、关键词、大盘、外部市场信息。如果系统未提供相关数据，必须明确写入 offline_checks，提示负责人线下验证。",
            "产品：{{product}}\n系统事实数据：{{facts}}\n客服与退货证据：{{evidence}}\n请输出诊断和建议。",
            {"type": "object", "properties": {"diagnosis": {"type": "array"}, "offline_checks": {"type": "array"}}},
            0.2,
            1600,
        )
        _insert_prompt_if_missing(
            conn,
            "task_suggestion",
            "负责人任务建议",
            "根据产品风险信号生成可派发任务建议",
            "你是运营任务拆解助手。只能基于系统证据提出任务。不要编造外部数据。",
            "风险信号：{{signals}}\n证据：{{evidence}}\n请输出任务标题、说明、验收标准和建议截止时间。",
            {"type": "object", "properties": {"tasks": {"type": "array"}}},
            0.2,
            1200,
        )

        # 验证
        count = conn.execute(text("SELECT COUNT(*) FROM ai_prompt_templates")).fetchone()[0]
        print(f"[migration] ai_prompt_templates 表创建完成，当前模板数: {count}")
        return True


if __name__ == "__main__":
    success = migrate_add_ai_prompt_templates()
    exit(0 if success else 1)
