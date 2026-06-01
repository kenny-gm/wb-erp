"""初始化数据库表"""
from app.database import Base, engine
from app.models import models  # 导入整个模块

# 创建所有表（仅创建不存在的表，不修改现有结构）
Base.metadata.create_all(bind=engine)
print("数据库表创建完成!")

# 列出所有表
from sqlalchemy import inspect
inspector = inspect(engine)
tables = inspector.get_table_names()
print(f"创建的表: {tables}")


# ============================================================
# 迁移：确保 platform_config 列存在
# ============================================================
def migrate_add_platform_config(db_url: str = None):
    """检测并添加 platform_config 列（如果不存在）
    支持 SQLite 和 PostgreSQL 双引擎"""
    if db_url is None:
        db_url = str(engine.url)

    from sqlalchemy import text
    with engine.connect() as conn:
        is_postgres = "postgres" in db_url.lower()

        if is_postgres:
            try:
                result = conn.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'shops' AND column_name = 'platform_config'"
                ))
                columns = [row[0] for row in result.fetchall()]
            except Exception as e:
                print(f"检测 shops 表结构失败: {e}")
                return False
        else:
            # SQLite
            try:
                result = conn.execute(text("PRAGMA table_info(shops)"))
                columns = [row[1] for row in result.fetchall()]
            except Exception as e:
                print(f"检测 shops 表结构失败: {e}")
                return False

        if "platform_config" not in columns:
            print("检测到 shops 表缺少 platform_config 列，执行 ALTER ...")
            try:
                if is_postgres:
                    conn.execute(text(
                        "ALTER TABLE shops ADD COLUMN platform_config JSON DEFAULT '{}'"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE shops ADD COLUMN platform_config TEXT DEFAULT '{}'"
                    ))
                conn.commit()
                print("platform_config 列添加成功")
                return True
            except Exception as e:
                print(f"添加 platform_config 列失败: {e}")
                return False
        else:
            print("platform_config 列已存在，跳过")
            return True


# 自动执行迁移
migrate_add_platform_config()