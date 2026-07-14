"""
Migration: 添加 message_dedup_key 列并建立唯一索引（幂等版本）
修复跨-item消息重复 bug
重要：此脚本只处理 question/feedback/return_claim 渠道，不处理 chat 渠道
（chat 消息的 external_message_id 是纯 UUID，无冒号，不能用同样的 WB ID 提取逻辑）
"""
import sqlite3
from collections import defaultdict
from app.database import engine


def upgrade():
    conn = engine.raw_connection()
    cursor = conn.cursor()
    
    try:
        # Step 0: 检查列是否存在
        cursor.execute("PRAGMA table_info(customer_service_messages)")
        cols = [r[1] for r in cursor.fetchall()]

        cursor.execute("PRAGMA index_list(customer_service_messages)")
        indexes = [r[1] for r in cursor.fetchall()]
        if 'message_dedup_key' in cols and 'ix_msg_dedup_key' in indexes:
            print("message_dedup_key 列和唯一索引已存在，跳过历史清理")
            return
        
        if 'message_dedup_key' not in cols:
            cursor.execute("ALTER TABLE customer_service_messages ADD COLUMN message_dedup_key VARCHAR(200)")
            conn.commit()
            print("新增 message_dedup_key 列")
        else:
            print("message_dedup_key 列已存在，跳过")

        # Step 1: 回填 message_dedup_key
        cursor.execute("DROP TABLE IF EXISTS tmp_dedup_map")
        cursor.execute("""
            CREATE TEMPORARY TABLE tmp_dedup_map AS
            SELECT m.id as msg_id,
                   i.shop_id || ':' || i.channel || ':' || m.external_message_id as dedup_key
            FROM customer_service_messages m
            JOIN customer_service_items i ON i.id = m.item_id
            WHERE m.external_message_id IS NOT NULL
              AND m.external_message_id != ''
              AND (m.message_dedup_key IS NULL OR m.message_dedup_key = '')
        """)
        conn.commit()

        cursor.execute("""
            UPDATE customer_service_messages
            SET message_dedup_key = (
                SELECT dedup_key FROM tmp_dedup_map WHERE msg_id = customer_service_messages.id
            )
            WHERE EXISTS (
                SELECT 1 FROM tmp_dedup_map WHERE msg_id = customer_service_messages.id
            )
        """)
        conn.commit()
        cursor.execute("DROP TABLE tmp_dedup_map")
        conn.commit()
        
        cursor.execute("SELECT COUNT(*) FROM customer_service_messages WHERE message_dedup_key IS NULL OR message_dedup_key = ''")
        null_count = cursor.fetchone()[0]
        print(f"回填后 NULL/空 dedup_key: {null_count}")

        # Step 2: 删除孤儿消息
        cursor.execute("""
            DELETE FROM customer_service_messages 
            WHERE (message_dedup_key IS NULL OR message_dedup_key = '')
              AND item_id NOT IN (SELECT id FROM customer_service_items)
        """)
        conn.commit()
        print(f"清理孤儿消息: {cursor.rowcount} 条")

        # Step 3: 清理串频道消息（只针对 question/feedback/return_claim）
        # chat 渠道不参与此清理
        for channel, suffixes in [
            ('question', ['%:question', '%:answer']),
            ('feedback', ['%:feedback', '%:answer']),
            ('return_claim', ['%:return_claim', '%:answer']),
        ]:
            keep_patterns = ' OR '.join([f"m.external_message_id LIKE '{s}'" for s in suffixes])
            cursor.execute(f"""
                DELETE FROM customer_service_messages
                WHERE message_dedup_key IS NOT NULL
                  AND message_dedup_key != ''
                  AND item_id IN (
                      SELECT m.id FROM customer_service_messages m
                      JOIN customer_service_items i ON i.id = m.item_id
                      WHERE i.channel = '{channel}'
                        AND ({keep_patterns}) = 0
                  )
            """)
            conn.commit()
            print(f"清理 {channel} 串频道: {cursor.rowcount} 条")

        # Step 4: 清理 WB ID 不匹配的跨-item重复（只针对 question/feedback/return_claim）
        # chat 渠道的 external_message_id 是纯 UUID，无冒号，不能用 WB ID 提取逻辑
        # .chat 渠道通过 message_dedup_key 唯一索引本身就能防止重复，不需要额外清理
        cursor.execute("""
            SELECT m.external_message_id, m.item_id, i.external_id, i.channel
            FROM customer_service_messages m
            JOIN customer_service_items i ON i.id = m.item_id
            WHERE m.external_message_id IS NOT NULL
              AND m.external_message_id != ''
              AND m.message_dedup_key IS NOT NULL
              AND m.message_dedup_key != ''
              AND i.channel IN ('question', 'feedback', 'return_claim')
            ORDER BY m.external_message_id, m.item_id
        """)
        all_rows = cursor.fetchall()

        ext_to_msgs = defaultdict(list)
        for ext_id, item_id, item_ext, item_channel in all_rows:
            ext_to_msgs[ext_id].append({'item_id': item_id, 'item_ext': item_ext, 'item_channel': item_channel})

        cross_exts = {k: v for k, v in ext_to_msgs.items() if len(set(m['item_id'] for m in v)) > 1}
        print(f"跨 item external_message_id（question/feedback/return_claim）: {len(cross_exts)}")

        to_delete = []
        for ext_id, msgs in cross_exts.items():
            # 提取 WB ID（最后一个冒号后面的类型后缀）
            last_colon = ext_id.rfind(':')
            if last_colon == -1:
                continue  # 没有冒号，跳过（不处理 chat 类型的 UUID）
            wb_id = ext_id[:last_colon]
            
            correct_item_id = None
            for msg in msgs:
                if msg['item_ext'] == wb_id:
                    correct_item_id = msg['item_id']
                    break
            
            if correct_item_id is None:
                continue
            
            for msg in msgs:
                if msg['item_id'] != correct_item_id:
                    to_delete.append((ext_id, msg['item_id']))

        if to_delete:
            batch_size = 500
            total_deleted = 0
            for i in range(0, len(to_delete), batch_size):
                batch = to_delete[i:i+batch_size]
                ext_ids = [x[0] for x in batch]
                item_ids = [x[1] for x in batch]
                placeholders = ','.join(['?' for _ in batch])
                cursor.execute(f"DELETE FROM customer_service_messages WHERE external_message_id IN ({placeholders}) AND item_id IN ({placeholders})", ext_ids + item_ids)
                total_deleted += cursor.rowcount
                conn.commit()
            print(f"清理 WB ID 不匹配: {total_deleted} 条")
        else:
            print("清理 WB ID 不匹配: 0 条")

        # Step 5: 清理 dedup_key 重复（保留 id 最小）
        cursor.execute("""
            DELETE FROM customer_service_messages
            WHERE message_dedup_key IS NOT NULL
              AND message_dedup_key != ''
              AND id NOT IN (
                  SELECT MIN(id)
                  FROM customer_service_messages
                  WHERE message_dedup_key IS NOT NULL
                    AND message_dedup_key != ''
                  GROUP BY message_dedup_key
              )
        """)
        conn.commit()
        print(f"清理 dedup_key 重复: {cursor.rowcount} 条")

        # Step 6: 清理 NULL 消息
        cursor.execute("DELETE FROM customer_service_messages WHERE message_dedup_key IS NULL OR message_dedup_key = ''")
        conn.commit()
        print(f"清理 NULL 消息: {cursor.rowcount} 条")

        # Step 7: 重建唯一索引
        cursor.execute("DROP INDEX IF EXISTS ix_msg_dedup_key")
        cursor.execute("CREATE UNIQUE INDEX ix_msg_dedup_key ON customer_service_messages(message_dedup_key)")
        conn.commit()
        print("唯一索引创建完成")

        # 验证
        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT message_dedup_key
                FROM customer_service_messages
                WHERE message_dedup_key IS NOT NULL AND message_dedup_key != ''
                GROUP BY message_dedup_key
                HAVING COUNT(*) > 1
            )
        """)
        dup_count = cursor.fetchone()[0]
        print(f"重复 dedup_key: {dup_count}")

        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT m.external_message_id
                FROM customer_service_messages m
                JOIN customer_service_items i ON i.id = m.item_id
                WHERE m.external_message_id IS NOT NULL AND m.external_message_id != ''
                  AND i.channel IN ('question', 'feedback', 'return_claim')
                GROUP BY m.external_message_id
                HAVING COUNT(DISTINCT m.item_id) > 1
            )
        """)
        cross_item = cursor.fetchone()[0]
        print(f"跨 item 重复（question/feedback/return_claim）: {cross_item}")

        cursor.execute("SELECT COUNT(*) FROM customer_service_messages")
        total = cursor.fetchone()[0]
        print(f"总消息数: {total}")

    finally:
        conn.close()


if __name__ == "__main__":
    upgrade()
