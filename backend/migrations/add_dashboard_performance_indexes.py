"""
Dashboard 性能优化索引 migration
幂等：使用 CREATE INDEX IF NOT EXISTS
"""

from sqlalchemy import text
from app.database import engine


def migrate_add_dashboard_performance_indexes():
    indexes = [
        (
            "ix_ad_records_dashboard_main",
            """
            CREATE INDEX IF NOT EXISTS ix_ad_records_dashboard_main
            ON ad_records(ad_type, record_date, product_id, shop_id)
            """,
        ),
        (
            "ix_ad_records_dashboard_ad_cost",
            """
            CREATE INDEX IF NOT EXISTS ix_ad_records_dashboard_ad_cost
            ON ad_records(ad_type, record_date, shop_id, product_id)
            """,
        ),
        (
            "ix_products_dashboard_filters",
            """
            CREATE INDEX IF NOT EXISTS ix_products_dashboard_filters
            ON products(shop_id, owner, nm_id)
            """,
        ),
        (
            "ix_sync_logs_type_status_finished",
            """
            CREATE INDEX IF NOT EXISTS ix_sync_logs_type_status_finished
            ON sync_logs(sync_type, status, finished_at)
            """,
        ),
    ]

    try:
        with engine.begin() as conn:
            for name, ddl in indexes:
                conn.execute(text(ddl))
                print(f"[migration] ensured index {name}")
        print("[migration] add_dashboard_performance_indexes: done")
    except Exception as exc:
        print(f"[migration] add_dashboard_performance_indexes failed: {exc}")
        raise


if __name__ == "__main__":
    migrate_add_dashboard_performance_indexes()
