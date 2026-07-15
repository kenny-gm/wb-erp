"""
Migration: protect customer service data from accidental destructive deletes.

Normal customer-service sync only upserts records. Any intentional maintenance
delete must explicitly set system_settings.customer_service_allow_destructive_write
to "true" and should be done with a fresh DB backup.
"""
from sqlalchemy import text

from app.database import engine


GUARD_SETTING_KEY = "customer_service_allow_destructive_write"


def migrate_add_customer_service_delete_guard() -> bool:
    """Idempotently add SQLite triggers that block customer-service table deletes."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO system_settings (key, value, description)
                SELECT :key, 'false', '客服表删除保护开关；仅维护恢复时可临时设为 true'
                WHERE NOT EXISTS (
                    SELECT 1 FROM system_settings WHERE key = :key
                )
                """
            ),
            {"key": GUARD_SETTING_KEY},
        )

        guarded_tables = (
            "customer_service_items",
            "customer_service_messages",
            "customer_service_actions",
        )
        for table_name in guarded_tables:
            trigger_name = f"trg_{table_name}_block_delete"
            conn.execute(
                text(
                    f"""
                    CREATE TRIGGER IF NOT EXISTS {trigger_name}
                    BEFORE DELETE ON {table_name}
                    WHEN COALESCE(
                        (SELECT value FROM system_settings WHERE key = '{GUARD_SETTING_KEY}'),
                        'false'
                    ) != 'true'
                    BEGIN
                        SELECT RAISE(ABORT, '{table_name} delete blocked by customer service guard');
                    END
                    """
                )
            )
    print("[迁移] 客服表删除保护 trigger 已启用")
    return True


if __name__ == "__main__":
    migrate_add_customer_service_delete_guard()
