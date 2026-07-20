"""
Migration: 新增产品知识库表和菜单（幂等）

产品知识库以中文产品名称为主线，一个产品一条知识档案，
不同店铺同一产品通过 linked_* 字段关联。
"""
from sqlalchemy import text
from app.database import engine


def _table_exists(conn, table_name: str) -> bool:
    dialect = engine.dialect.name
    if dialect == "sqlite":
        return bool(conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
            {"name": table_name},
        ).fetchone())
    if dialect == "mysql":
        return bool(conn.execute(text(f"SHOW TABLES LIKE '{table_name}'")).fetchone())
    raise RuntimeError(f"Unsupported dialect: {dialect}")


def migrate_add_product_knowledge() -> bool:
    with engine.begin() as conn:
        if not _table_exists(conn, "product_knowledge"):
            if engine.dialect.name == "mysql":
                conn.execute(text("""
                    CREATE TABLE product_knowledge (
                        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                        product_key VARCHAR(64) NOT NULL UNIQUE,
                        product_name VARCHAR(500) NOT NULL,
                        aliases_json TEXT,
                        linked_product_ids_json TEXT,
                        linked_nm_ids_json TEXT,
                        linked_skus_json TEXT,
                        owners_json TEXT,
                        shop_names_json TEXT,
                        basic_info TEXT,
                        features TEXT,
                        usage_guide TEXT,
                        troubleshooting TEXT,
                        faq_json TEXT,
                        after_sales_policy TEXT,
                        reply_rules TEXT,
                        answer_examples_ru TEXT,
                        internal_notes_zh TEXT,
                        ai_enabled BOOL DEFAULT TRUE,
                        status VARCHAR(20) DEFAULT 'active',
                        updated_by INT NULL,
                        reviewed_by INT NULL,
                        reviewed_at DATETIME NULL,
                        created_at DATETIME NULL,
                        updated_at DATETIME NULL,
                        INDEX ix_product_knowledge_product_key (product_key),
                        INDEX ix_product_knowledge_product_name (product_name),
                        INDEX ix_product_knowledge_name_status (product_name, status)
                    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                """))
            elif engine.dialect.name == "sqlite":
                conn.execute(text("""
                    CREATE TABLE product_knowledge (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_key VARCHAR(64) NOT NULL UNIQUE,
                        product_name VARCHAR(500) NOT NULL,
                        aliases_json TEXT DEFAULT '[]',
                        linked_product_ids_json TEXT DEFAULT '[]',
                        linked_nm_ids_json TEXT DEFAULT '[]',
                        linked_skus_json TEXT DEFAULT '[]',
                        owners_json TEXT DEFAULT '[]',
                        shop_names_json TEXT DEFAULT '[]',
                        basic_info TEXT DEFAULT '',
                        features TEXT DEFAULT '',
                        usage_guide TEXT DEFAULT '',
                        troubleshooting TEXT DEFAULT '',
                        faq_json TEXT DEFAULT '[]',
                        after_sales_policy TEXT DEFAULT '',
                        reply_rules TEXT DEFAULT '',
                        answer_examples_ru TEXT DEFAULT '',
                        internal_notes_zh TEXT DEFAULT '',
                        ai_enabled BOOLEAN DEFAULT 1,
                        status VARCHAR(20) DEFAULT 'active',
                        updated_by INTEGER NULL,
                        reviewed_by INTEGER NULL,
                        reviewed_at DATETIME NULL,
                        created_at DATETIME NULL,
                        updated_at DATETIME NULL
                    )
                """))
                conn.execute(text("CREATE INDEX ix_product_knowledge_product_key ON product_knowledge(product_key)"))
                conn.execute(text("CREATE INDEX ix_product_knowledge_product_name ON product_knowledge(product_name)"))
                conn.execute(text("CREATE INDEX ix_product_knowledge_name_status ON product_knowledge(product_name, status)"))
            print("[migration] product_knowledge 表已创建")
        else:
            print("[migration] product_knowledge 表已存在，跳过")

        menu_exists = conn.execute(
            text("SELECT id FROM menu_items WHERE `key`=:key") if engine.dialect.name == "mysql"
            else text("SELECT id FROM menu_items WHERE key=:key"),
            {"key": "product-knowledge"},
        ).fetchone()
        if not menu_exists:
            conn.execute(
                text("""
                    INSERT INTO menu_items (`key`, name, icon, path, sort_order, is_visible)
                    VALUES (:key, :name, :icon, :path, :sort_order, :is_visible)
                """) if engine.dialect.name == "mysql" else text("""
                    INSERT INTO menu_items (key, name, icon, path, sort_order, is_visible)
                    VALUES (:key, :name, :icon, :path, :sort_order, :is_visible)
                """),
                {
                    "key": "product-knowledge",
                    "name": "产品知识库",
                    "icon": "Document",
                    "path": "/product-knowledge",
                    "sort_order": 7,
                    "is_visible": True,
                },
            )
            print("[migration] 产品知识库菜单已添加")
        else:
            print("[migration] 产品知识库菜单已存在，跳过")
    return True


if __name__ == "__main__":
    success = migrate_add_product_knowledge()
    exit(0 if success else 1)
