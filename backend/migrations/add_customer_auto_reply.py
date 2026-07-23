"""Migration: add customer AI auto-reply settings and report tables."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import inspect, text

from app.database import engine, SessionLocal
from app.models.models import SystemSetting


DEFAULT_SETTINGS = {
    "customer_ai_auto_reply_enabled": ("false", "客服工作台 AI 自动回复总开关，默认关闭"),
    "customer_ai_auto_reply_channels": (
        json.dumps(["feedback", "question", "chat"], ensure_ascii=False),
        "允许自动回复的客服渠道",
    ),
    "customer_ai_auto_reply_feedback_negative_enabled": ("true", "是否允许自动回复 feedback 差评"),
    "customer_ai_auto_reply_max_per_run": ("20", "AI 自动回复单次运行最大发送数"),
    "customer_ai_auto_reply_max_per_shop_per_day": ("50", "AI 自动回复每店铺每日最大发送数"),
    "customer_ai_auto_reply_channel_daily_limits": (
        json.dumps({"feedback": 30, "question": 20, "chat": 20}, ensure_ascii=False),
        "AI 自动回复每店铺每日各渠道发送上限",
    ),
    "customer_ai_auto_reply_feedback_negative_daily_limit": ("5", "AI 自动回复每店铺每日差评发送上限"),
    "customer_ai_auto_reply_consecutive_failures_pause": ("5", "连续失败达到该数量后自动关闭总开关"),
}


def migrate_add_customer_auto_reply() -> bool:
    dialect = engine.dialect.name
    inspector = inspect(engine)
    try:
        with engine.begin() as conn:
            tables = set(inspector.get_table_names())
            if "customer_auto_reply_runs" not in tables:
                if dialect == "mysql":
                    conn.execute(text("""
                        CREATE TABLE customer_auto_reply_runs (
                            id INTEGER NOT NULL AUTO_INCREMENT,
                            trigger_source VARCHAR(50),
                            mode VARCHAR(20),
                            status VARCHAR(20),
                            shop_id INTEGER NULL,
                            scanned_count INTEGER,
                            draft_count INTEGER,
                            sent_count INTEGER,
                            blocked_count INTEGER,
                            failed_count INTEGER,
                            skipped_count INTEGER,
                            message TEXT,
                            started_at DATETIME,
                            finished_at DATETIME NULL,
                            created_at DATETIME,
                            PRIMARY KEY (id),
                            INDEX ix_customer_auto_reply_run_time (started_at),
                            INDEX ix_customer_auto_reply_run_status (status),
                            INDEX ix_customer_auto_reply_runs_shop_id (shop_id),
                            CONSTRAINT fk_customer_auto_reply_runs_shop_id FOREIGN KEY(shop_id) REFERENCES shops (id)
                        )
                    """))
                else:
                    conn.execute(text("""
                        CREATE TABLE customer_auto_reply_runs (
                            id INTEGER NOT NULL,
                            trigger_source VARCHAR(50),
                            mode VARCHAR(20),
                            status VARCHAR(20),
                            shop_id INTEGER,
                            scanned_count INTEGER,
                            draft_count INTEGER,
                            sent_count INTEGER,
                            blocked_count INTEGER,
                            failed_count INTEGER,
                            skipped_count INTEGER,
                            message TEXT,
                            started_at DATETIME,
                            finished_at DATETIME,
                            created_at DATETIME,
                            PRIMARY KEY (id),
                            FOREIGN KEY(shop_id) REFERENCES shops (id)
                        )
                    """))
                    conn.execute(text("CREATE INDEX ix_customer_auto_reply_run_time ON customer_auto_reply_runs (started_at)"))
                    conn.execute(text("CREATE INDEX ix_customer_auto_reply_run_status ON customer_auto_reply_runs (status)"))

            tables = set(inspect(engine).get_table_names())
            if "customer_auto_reply_items" not in tables:
                if dialect == "mysql":
                    conn.execute(text("""
                        CREATE TABLE customer_auto_reply_items (
                            id INTEGER NOT NULL AUTO_INCREMENT,
                            run_id INTEGER NOT NULL,
                            item_id INTEGER NOT NULL,
                            shop_id INTEGER NOT NULL,
                            channel VARCHAR(30) NOT NULL,
                            auto_reply_key VARCHAR(240) NOT NULL,
                            latest_buyer_message_id VARCHAR(120),
                            draft_text TEXT,
                            decision VARCHAR(30),
                            block_reason TEXT,
                            wb_response_json TEXT,
                            prompt_template_key VARCHAR(80),
                            prompt_version INTEGER NULL,
                            created_at DATETIME,
                            updated_at DATETIME,
                            PRIMARY KEY (id),
                            UNIQUE KEY ix_customer_auto_reply_items_auto_reply_key (auto_reply_key),
                            INDEX ix_customer_auto_reply_item_run (run_id),
                            INDEX ix_customer_auto_reply_item_item (item_id),
                            INDEX ix_customer_auto_reply_item_created (created_at),
                            INDEX ix_customer_auto_reply_item_decision (decision),
                            INDEX ix_customer_auto_reply_items_shop_id (shop_id),
                            CONSTRAINT fk_customer_auto_reply_items_run_id FOREIGN KEY(run_id) REFERENCES customer_auto_reply_runs (id),
                            CONSTRAINT fk_customer_auto_reply_items_item_id FOREIGN KEY(item_id) REFERENCES customer_service_items (id),
                            CONSTRAINT fk_customer_auto_reply_items_shop_id FOREIGN KEY(shop_id) REFERENCES shops (id)
                        )
                    """))
                else:
                    conn.execute(text("""
                        CREATE TABLE customer_auto_reply_items (
                            id INTEGER NOT NULL,
                            run_id INTEGER NOT NULL,
                            item_id INTEGER NOT NULL,
                            shop_id INTEGER NOT NULL,
                            channel VARCHAR(30) NOT NULL,
                            auto_reply_key VARCHAR(240) NOT NULL,
                            latest_buyer_message_id VARCHAR(120),
                            draft_text TEXT,
                            decision VARCHAR(30),
                            block_reason TEXT,
                            wb_response_json TEXT,
                            prompt_template_key VARCHAR(80),
                            prompt_version INTEGER,
                            created_at DATETIME,
                            updated_at DATETIME,
                            PRIMARY KEY (id),
                            FOREIGN KEY(run_id) REFERENCES customer_auto_reply_runs (id),
                            FOREIGN KEY(item_id) REFERENCES customer_service_items (id),
                            FOREIGN KEY(shop_id) REFERENCES shops (id)
                        )
                    """))
                    conn.execute(text("CREATE UNIQUE INDEX ix_customer_auto_reply_items_auto_reply_key ON customer_auto_reply_items (auto_reply_key)"))
                    conn.execute(text("CREATE INDEX ix_customer_auto_reply_item_run ON customer_auto_reply_items (run_id)"))
                    conn.execute(text("CREATE INDEX ix_customer_auto_reply_item_item ON customer_auto_reply_items (item_id)"))
                    conn.execute(text("CREATE INDEX ix_customer_auto_reply_item_created ON customer_auto_reply_items (created_at)"))
                    conn.execute(text("CREATE INDEX ix_customer_auto_reply_item_decision ON customer_auto_reply_items (decision)"))

        db = SessionLocal()
        try:
            now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
            for key, (value, description) in DEFAULT_SETTINGS.items():
                exists = db.query(SystemSetting).filter(SystemSetting.key == key).first()
                if exists:
                    continue
                db.add(SystemSetting(key=key, value=value, description=description, updated_at=now))
            db.commit()
        finally:
            db.close()
        print("[migration] customer_auto_reply 表和默认配置已确认")
        return True
    except Exception as exc:
        print(f"[migration] customer_auto_reply 迁移失败: {exc}")
        return False


if __name__ == "__main__":
    migrate_add_customer_auto_reply()
