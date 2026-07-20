"""
Migration: 扩大 customer_service_items.reply_sign 存储长度

WB buyer-chat replySign 可能超过 200 字符。MySQL VARCHAR(200)
会在同步聊天事件时触发 Data too long，改为 TEXT。
"""
from sqlalchemy import text
from app.database import engine


def _table_exists(conn, table_name: str) -> bool:
    dialect = engine.dialect.name
    if dialect == "sqlite":
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        ).fetchall()
        return bool(rows)
    if dialect == "mysql":
        rows = conn.execute(text(f"SHOW TABLES LIKE '{table_name}'")).fetchall()
        return bool(rows)
    raise RuntimeError(f"Unsupported dialect: {dialect}")


def _column_info(conn, table_name: str, column_name: str):
    dialect = engine.dialect.name
    if dialect == "sqlite":
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        for row in rows:
            if row[1] == column_name:
                return row
        return None
    if dialect == "mysql":
        rows = conn.execute(text(f"SHOW COLUMNS FROM {table_name} LIKE '{column_name}'")).fetchall()
        return rows[0] if rows else None
    raise RuntimeError(f"Unsupported dialect: {dialect}")


def migrate_expand_customer_service_reply_sign() -> bool:
    with engine.begin() as conn:
        if not _table_exists(conn, "customer_service_items"):
            print("[migration] customer_service_items 表不存在，跳过 reply_sign 扩容")
            return True

        column = _column_info(conn, "customer_service_items", "reply_sign")
        if not column:
            conn.execute(text("ALTER TABLE customer_service_items ADD COLUMN reply_sign TEXT"))
            print("[migration] reply_sign 列不存在，已添加 TEXT")
            return True

        if engine.dialect.name == "mysql":
            col_type = str(column[1]).lower()
            if col_type != "text":
                conn.execute(text("ALTER TABLE customer_service_items MODIFY COLUMN reply_sign TEXT NULL"))
                print(f"[migration] reply_sign 已从 {col_type} 扩容为 TEXT")
            else:
                print("[migration] reply_sign 已是 TEXT，跳过")
        else:
            print("[migration] SQLite reply_sign 无需扩容")

        return True


if __name__ == "__main__":
    success = migrate_expand_customer_service_reply_sign()
    exit(0 if success else 1)
