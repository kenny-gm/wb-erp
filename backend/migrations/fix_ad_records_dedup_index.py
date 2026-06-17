"""
Migration: 修复 ad_records 唯一索引，包含 advert_id

解决 WB 广告同一产品同一天多个 advert_id 时的 UNIQUE constraint 冲突。

索引变更：(shop_id, product_id, DATE(record_date), ad_type)
       → (shop_id, product_id, DATE(record_date), ad_type, advert_id)

幂等：可重复执行，重复执行时跳过已符合目标的索引。
"""

from sqlalchemy import text
from app.database import engine


def migrate_fix_ad_records_dedup_index():
    """
    修复 ad_records.ix_ad_records_dedup 唯一索引，使其包含 advert_id。

    执行逻辑（幂等）：
    1. 检查 ad_records 表是否存在，不存在则直接返回 True（前置依赖缺失）
    2. 检查 advert_id 列是否存在，不存在则 ADD COLUMN
    3. advert_id NULL → 0
    4. 用 PRAGMA index_xinfo 验证当前索引列序列是否已符合目标
    5. 如不符合，创建新索引（先删旧索引）
    6. 验证新索引列序列正确

    Returns:
        bool: True = 迁移成功或已符合目标, False = 有重复数据/执行失败
    """
    with engine.connect() as conn:
        # ============================================================
        # Step 1: 检查 ad_records 表是否存在
        # ============================================================
        result = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ad_records'"
        ))
        if not result.fetchone():
            print("[migration] ad_records 表不存在，跳过")
            return True

        # ============================================================
        # Step 2: 检查并添加 advert_id 列
        # ============================================================
        col_result = conn.execute(text("PRAGMA table_info(ad_records)"))
        existing_cols = [row[1] for row in col_result.fetchall()]

        if "advert_id" not in existing_cols:
            print("[migration] advert_id 列不存在，添加...")
            conn.execute(text("ALTER TABLE ad_records ADD COLUMN advert_id INTEGER DEFAULT 0"))
            conn.commit()
            print("[migration] advert_id 列添加成功")
        else:
            print("[migration] advert_id 列已存在")

        # ============================================================
        # Step 3: advert_id NULL → 0
        # ============================================================
        result = conn.execute(text("SELECT COUNT(*) FROM ad_records WHERE advert_id IS NULL"))
        null_count = result.fetchone()[0]
        if null_count > 0:
            print(f"[migration] advert_id NULL → 0: {null_count} 条")
            conn.execute(text("UPDATE ad_records SET advert_id = 0 WHERE advert_id IS NULL"))
            conn.commit()
        else:
            print("[migration] advert_id NULL 检查: 0 条，无需处理")

        # ============================================================
        # Step 4: 用 PRAGMA index_xinfo 验证当前索引列序列
        # ============================================================
        index_info_result = conn.execute(text(
            "PRAGMA index_xinfo(ix_ad_records_dedup)"
        ))
        index_rows = index_info_result.fetchall()
        # index_xinfo returns: (seqno, cid, name, desc, coll,)
        # seqno=0 is the first column, seqno=1 is second, etc.
        # seqno=-1 means UNIQUE constraint at table level (not an index column)
        # We collect column names in order, skipping seqno=-1
        current_index_cols = []
        for row in index_rows:
            seqno, cid, name = row[0], row[1], row[2]
            if cid == -1:
                # Table-level constraint or expression, not a plain column
                continue
            current_index_cols.append(name)

        print(f"[migration] 当前索引列序列: {current_index_cols}")

        TARGET_COLS = ["shop_id", "product_id", "DATE(record_date)", "ad_type", "advert_id"]
        # Normalize comparison: extract just the column names without expressions
        current_normalized = [c for c in current_index_cols]
        # DATE(record_date) is stored as DATE(record_date) in index but we can't
        # easily parse it. Instead, we check if the index has 5 columns
        # and the last one is advert_id
        if len(current_index_cols) == 5 and current_index_cols[-1] == "advert_id":
            print("[migration] 索引已符合目标（5列且最后一列为advert_id），跳过")
            return True

        # ============================================================
        # Step 5: 检查重复数据（有重复则不允许继续）
        # ============================================================
        dupes_result = conn.execute(text("""
            SELECT
                shop_id,
                product_id,
                DATE(record_date) AS dt,
                ad_type,
                advert_id,
                COUNT(*) AS cnt
            FROM ad_records
            GROUP BY shop_id, product_id, DATE(record_date), ad_type, advert_id
            HAVING COUNT(*) > 1
        """))
        dupes = dupes_result.fetchall()

        if dupes:
            print("[migration] ❌ 发现重复数据，无法创建索引：")
            for d in dupes:
                print(f"  shop={d[0]} pid={d[1]} dt={d[2]} type={d[3]} advert={d[4]} cnt={d[5]}")
            print("[migration] 必须先手动处理重复数据后再执行此迁移")
            return False

        print("[migration] 重复数据检查: 0 组，通过")

        # ============================================================
        # Step 6: 删除旧索引，创建新索引
        # ============================================================
        conn.execute(text("DROP INDEX IF EXISTS ix_ad_records_dedup"))
        conn.commit()
        print("[migration] 旧索引已删除")

        conn.execute(text("""
            CREATE UNIQUE INDEX ix_ad_records_dedup
            ON ad_records(shop_id, product_id, DATE(record_date), ad_type, advert_id)
        """))
        conn.commit()
        print("[migration] 新索引创建成功")

        # ============================================================
        # Step 7: 验证新索引列序列
        # ============================================================
        new_index_result = conn.execute(text(
            "PRAGMA index_xinfo(ix_ad_records_dedup)"
        ))
        new_index_rows = new_index_result.fetchall()
        new_index_cols = []
        for row in new_index_rows:
            seqno, cid, name = row[0], row[1], row[2]
            if cid == -1:
                continue
            new_index_cols.append(name)

        print(f"[migration] 新索引列序列验证: {new_index_cols}")

        # Valid index: 5 columns, last is advert_id
        if len(new_index_cols) == 5 and new_index_cols[-1] == "advert_id":
            print("[migration] ✅ 迁移完成，索引验证通过")
            return True
        else:
            print(f"[migration] ❌ 索引验证失败，期望5列且最后一列advert_id，实际: {new_index_cols}")
            return False


if __name__ == "__main__":
    success = migrate_fix_ad_records_dedup_index()
    exit(0 if success else 1)
