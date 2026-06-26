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

# ============================================================
# 迁移：确保 sync_jobs 表存在
# ============================================================
def migrate_add_sync_jobs(db_url: str = None):
    """检测并创建 sync_jobs 表（如果不存在）
    支持 SQLite 和 PostgreSQL 双引擎"""
    if db_url is None:
        db_url = str(engine.url)

    from sqlalchemy import text, inspect as sqla_inspect
    inspector = sqla_inspect(engine)

    try:
        existing_tables = inspector.get_table_names()
    except Exception as e:
        print(f"检测表列表失败: {e}")
        return False

    if "sync_jobs" in existing_tables:
        print("sync_jobs 表已存在，跳过")
        return True

    print("sync_jobs 表不存在，开始创建...")
    try:
        if "postgres" in db_url.lower():
            # PostgreSQL
            engine.execute(text("""
                CREATE TABLE sync_jobs (
                    id SERIAL PRIMARY KEY,
                    shop_id INTEGER NOT NULL REFERENCES shops(id),
                    sync_type VARCHAR(50) NOT NULL,
                    status VARCHAR(20) DEFAULT 'pending',
                    progress INTEGER DEFAULT 0,
                    message TEXT DEFAULT '',
                    result_json TEXT,
                    error TEXT,
                    created_by INTEGER,
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
        else:
            # SQLite
            engine.execute(text("""
                CREATE TABLE sync_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shop_id INTEGER NOT NULL,
                    sync_type VARCHAR(50) NOT NULL,
                    status VARCHAR(20) DEFAULT 'pending',
                    progress INTEGER DEFAULT 0,
                    message TEXT DEFAULT '',
                    result_json TEXT,
                    error TEXT,
                    created_by INTEGER,
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
        print("sync_jobs 表创建成功")
        return True
    except Exception as e:
        print(f"创建 sync_jobs 表失败: {e}")
        return False


migrate_add_sync_jobs()


# ============================================================
# 迁移：确保客服工作台菜单存在
# ============================================================
def migrate_add_customer_service_menu():
    """幂等补充客服工作台菜单。已有菜单表的生产库也需要补这一项。"""
    from app.database import SessionLocal
    from app.models.models import MenuItem

    db = SessionLocal()
    try:
        existing = db.query(MenuItem).filter(MenuItem.key == "customer-service").first()
        if existing:
            print("customer-service 菜单已存在，跳过")
            return True
        menu = MenuItem(
            key="customer-service",
            name="客服工作台",
            icon="ChatDotRound",
            path="/customer-service",
            sort_order=6,
            is_visible=True,
        )
        db.add(menu)
        db.commit()
        print("customer-service 菜单添加成功")
        return True
    except Exception as e:
        db.rollback()
        print(f"添加 customer-service 菜单失败: {e}")
        return False
    finally:
        db.close()


migrate_add_customer_service_menu()
