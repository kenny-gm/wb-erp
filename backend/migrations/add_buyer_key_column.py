"""
Migration: 给 customer_service_items 增加 buyer_key 字段和索引

buyer_key 用于跨 channel（问答/评价/聊天/退货申请）聚合同一买家的所有事项。

回填逻辑（与 _buyer_key() 一致）：
- feedback/question → userName 或 customer_name
- chat            → clientName 或 customer_name
- return_claim    → srid 或 customer_name
- 其他            → customer_name

幂等：可重复执行。
"""

import json
from sqlalchemy import text
from app.database import engine


def migrate_add_buyer_key():
    with engine.connect() as conn:
        # Step 1: 检查表是否存在
        result = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='customer_service_items'"
        ))
        if not result.fetchone():
            print("[migration] customer_service_items 表不存在，跳过")
            return True

        # Step 2: 检查 buyer_key 列是否已存在
        col_result = conn.execute(text("PRAGMA table_info(customer_service_items)"))
        existing_cols = [row[1] for row in col_result.fetchall()]

        if "buyer_key" not in existing_cols:
            print("[migration] buyer_key 列不存在，添加...")
            conn.execute(text("ALTER TABLE customer_service_items ADD COLUMN buyer_key TEXT"))
            conn.commit()
            print("[migration] buyer_key 列添加成功")
        else:
            print("[migration] buyer_key 列已存在")

        # Step 3: 回填 buyer_key（基于 raw_json 和 customer_name，复用 _buyer_key 逻辑）
        print("[migration] 开始回填 buyer_key...")

        # 查询所有 buyer_key 为 NULL 的记录
        result = conn.execute(text(
            "SELECT id, channel, customer_name, raw_json FROM customer_service_items WHERE buyer_key IS NULL OR buyer_key = ''"
        ))
        rows = result.fetchall()

        if not rows:
            print("[migration] 无需回填，所有记录已有 buyer_key")
        else:
            print(f"[migration] 待回填记录数: {len(rows)}")
            for row in rows:
                row_id, channel, customer_name, raw_json_str = row
                raw = {}
                try:
                    raw = json.loads(raw_json_str or "{}")
                except Exception:
                    pass

                if channel in ("feedback", "question"):
                    buyer_key = raw.get("userName") or customer_name or ""
                elif channel == "chat":
                    buyer_key = raw.get("clientName") or customer_name or ""
                elif channel == "return_claim":
                    buyer_key = raw.get("srid") or customer_name or ""
                else:
                    buyer_key = customer_name or ""

                if buyer_key:
                    conn.execute(
                        text("UPDATE customer_service_items SET buyer_key = :bk WHERE id = :id"),
                        {"bk": buyer_key, "id": row_id}
                    )
            conn.commit()
            print(f"[migration] 回填完成")

        # Step 4: 检查索引是否存在
        index_result = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='ix_customer_service_items_buyer_key'"
        ))
        if not index_result.fetchone():
            conn.execute(text("CREATE INDEX ix_customer_service_items_buyer_key ON customer_service_items(buyer_key)"))
            conn.commit()
            print("[migration] 索引 ix_customer_service_items_buyer_key 创建成功")
        else:
            print("[migration] 索引 ix_customer_service_items_buyer_key 已存在")

        # Step 5: 验证
        verify = conn.execute(text("SELECT COUNT(*) FROM customer_service_items WHERE buyer_key IS NOT NULL AND buyer_key != ''"))
        count = verify.fetchone()[0]
        print(f"[migration] ✅ 完成，buyer_key 非空记录: {count} 条")
        return True


if __name__ == "__main__":
    success = migrate_add_buyer_key()
    exit(0 if success else 1)
