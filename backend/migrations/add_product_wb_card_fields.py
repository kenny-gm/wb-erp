"""
Migration: add WB product card text fields to products.

Stores title, brand, subject, description, characteristics and sanitized raw
card JSON. Image/media fields are intentionally not stored.
"""
from sqlalchemy import text

from app.database import engine


COLUMNS = [
    ("wb_title", "VARCHAR(500)", "TEXT"),
    ("wb_brand", "VARCHAR(200)", "TEXT"),
    ("wb_subject_name", "VARCHAR(300)", "TEXT"),
    ("wb_description", "TEXT", "TEXT"),
    ("wb_characteristics_json", "TEXT", "TEXT"),
    ("wb_card_raw_json", "TEXT", "TEXT"),
    ("wb_card_updated_at", "DATETIME", "DATETIME"),
]


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


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    if engine.dialect.name == "sqlite":
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        return any(row[1] == column_name for row in rows)
    if engine.dialect.name == "mysql":
        rows = conn.execute(text(f"SHOW COLUMNS FROM {table_name} LIKE '{column_name}'")).fetchall()
        return bool(rows)
    raise RuntimeError(f"Unsupported dialect: {engine.dialect.name}")


def migrate_add_product_wb_card_fields() -> bool:
    with engine.begin() as conn:
        if not _table_exists(conn, "products"):
            print("[migration] products 表不存在，跳过 WB 商品卡字段")
            return True

        added = []
        for column_name, mysql_type, sqlite_type in COLUMNS:
            if _column_exists(conn, "products", column_name):
                continue
            column_type = mysql_type if engine.dialect.name == "mysql" else sqlite_type
            conn.execute(text(f"ALTER TABLE products ADD COLUMN {column_name} {column_type} NULL"))
            added.append(column_name)

        if added:
            print(f"[migration] products 已新增 WB 商品卡字段: {', '.join(added)}")
        else:
            print("[migration] products WB 商品卡字段已存在，跳过")
        return True


if __name__ == "__main__":
    success = migrate_add_product_wb_card_fields()
    exit(0 if success else 1)
