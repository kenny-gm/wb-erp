"""
Migration: 新增问答回复可见范围字段（幂等）

customer_service_items: answer_visibility
  - "all"       = 所有人可见（默认）
  - "questioner" = 仅提问者可见
"""
from sqlalchemy import text
from app.database import engine


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column_name for row in rows)


def _add_column(conn, table_name: str, column_name: str, ddl: str):
    if not _column_exists(conn, table_name, column_name):
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))


def migrate_add_question_answer_visibility():
    with engine.begin() as conn:
        _add_column(conn, "customer_service_items", "answer_visibility", "VARCHAR(20) DEFAULT 'all'")
        return True


if __name__ == "__main__":
    success = migrate_add_question_answer_visibility()
    exit(0 if success else 1)
