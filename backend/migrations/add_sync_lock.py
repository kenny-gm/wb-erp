"""
迁移：新增 sync_locks 表，用于客服同步分布式锁
"""
from sqlalchemy import inspect, text
from app.database import engine


def migrate_add_sync_locks():
    """幂等迁移：检查表是否存在，不存在则创建"""
    with engine.connect() as conn:
        if inspect(conn).has_table("sync_locks"):
            print("[迁移] sync_locks 表已存在，跳过")
            return

        if engine.dialect.name == "mysql":
            conn.execute(text("""
                CREATE TABLE sync_locks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    lock_key VARCHAR(255) NOT NULL UNIQUE,
                    locked_by VARCHAR(255) NOT NULL,
                    locked_at DATETIME NOT NULL,
                    expires_at DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_sync_locks_key (lock_key),
                    INDEX idx_sync_locks_expires (expires_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """))
        else:
            conn.execute(text("""
                CREATE TABLE sync_locks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lock_key TEXT NOT NULL UNIQUE,
                    locked_by TEXT NOT NULL,
                    locked_at TIMESTAMP NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX idx_sync_locks_key ON sync_locks(lock_key)"))
            conn.execute(text("CREATE INDEX idx_sync_locks_expires ON sync_locks(expires_at)"))

        conn.commit()
        print(f"[迁移] sync_locks 表创建成功 ({engine.dialect.name})")


if __name__ == "__main__":
    migrate_add_sync_locks()
