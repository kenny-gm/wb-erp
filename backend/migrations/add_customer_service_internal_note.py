"""
Migration: 新增客服内部备注字段（幂等）

customer_service_items: internal_note, internal_note_updated_by, internal_note_updated_at
"""
from sqlalchemy import text
from app.database import engine


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column_name for row in rows)


def _add_column(conn, table_name: str, column_name: str, ddl: str):
    if not _column_exists(conn, table_name, column_name):
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))


def migrate_add_customer_service_internal_note():
    with engine.begin() as conn:
        _add_column(conn, "customer_service_items", "internal_note", "TEXT DEFAULT ''")
        _add_column(conn, "customer_service_items", "internal_note_updated_by", "VARCHAR(100)")
        _add_column(conn, "customer_service_items", "internal_note_updated_at", "DATETIME")
        print("[migration] add_customer_service_internal_note 完成")
        return True


if __name__ == "__main__":
    success = migrate_add_customer_service_internal_note()
    exit(0 if success else 1)
