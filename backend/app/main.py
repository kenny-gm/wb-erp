"""
主应用入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp
from starlette.datastructures import URL
from starlette.requests import Request
from app.config import settings
from app.database import engine, Base

# 迁移：确保 platform_config 列存在。app.init_db 在导入时也会创建表和补菜单。
from app.init_db import migrate_add_platform_config
migrate_add_platform_config()


def run_sqlite_legacy_migrations():
    """Run legacy startup migrations that still contain SQLite-only DDL/introspection."""
    if engine.dialect.name != "sqlite":
        print(f"跳过 SQLite legacy migrations: 当前数据库 dialect={engine.dialect.name}")
        return

    # 迁移：修复 ad_records 唯一索引（包含 advert_id，解决 WB 同产品同天多广告冲突）
    from migrations.fix_ad_records_dedup_index import migrate_fix_ad_records_dedup_index
    migrate_fix_ad_records_dedup_index()  # 幂等，重复执行无影响

    # 迁移：增加 buyer_key 和 reply_sign 字段（支持跨 channel 同买家聚合、聊天凭证刷新）
    from migrations.add_buyer_key_column import migrate_add_buyer_key_and_reply_sign
    migrate_add_buyer_key_and_reply_sign()  # 幂等，重复执行无影响

    # 迁移：补全 customer_service_items 缺失列（初始化表结构不完整 bug）
    from migrations.fix_customer_service_items_columns import migrate_fix_customer_service_items_columns
    migrate_fix_customer_service_items_columns()  # 幂等，重复执行无影响

    # 迁移：新增 ai_prompt_templates 表和默认 AI 设置
    from migrations.add_ai_prompt_templates import migrate_add_ai_prompt_templates
    migrate_add_ai_prompt_templates()  # 幂等，重复执行无影响

    # 迁移：新增客服翻译字段
    from migrations.add_customer_translation_fields import migrate_add_customer_translation_fields
    migrate_add_customer_translation_fields()  # 幂等，重复执行无影响

    # 迁移：优化 customer_reply Prompt
    from migrations.optimize_customer_reply_prompt import migrate_optimize_customer_reply_prompt
    migrate_optimize_customer_reply_prompt()  # 幂等，重复执行无影响

    from migrations.add_dashboard_performance_indexes import migrate_add_dashboard_performance_indexes
    migrate_add_dashboard_performance_indexes()  # 幂等，重复执行无影响

    # 迁移：新增客服内部备注字段
    from migrations.add_customer_service_internal_note import migrate_add_customer_service_internal_note
    migrate_add_customer_service_internal_note()  # 幂等，重复执行无影响

    # 迁移：customer_service_messages 唯一约束（item_id + external_message_id）
    from migrations.fix_customer_service_message_unique import migrate_fix_customer_service_message_unique
    migrate_fix_customer_service_message_unique()  # 幂等，重复执行无影响

    # 迁移：message_dedup_key 去重键（修复跨-item消息重复）
    from migrations.msg_dedup_migration import upgrade as msg_dedup_upgrade
    msg_dedup_upgrade()  # 幂等，重复执行无影响

    from migrations.add_question_answer_visibility import migrate_add_question_answer_visibility
    migrate_add_question_answer_visibility()  # 幂等，重复执行无影响

    # 迁移：客服表删除保护（正常同步只 upsert，维护删除需显式开关）
    from migrations.add_customer_service_delete_guard import migrate_add_customer_service_delete_guard
    migrate_add_customer_service_delete_guard()  # 幂等，重复执行无影响


run_sqlite_legacy_migrations()

# 迁移：新增 sync_locks 表（客服同步分布式锁），支持 SQLite/MySQL。
from migrations.add_sync_lock import migrate_add_sync_locks
migrate_add_sync_locks()  # 幂等，重复执行无影响

# 迁移：扩大客服聊天 reply_sign 字段，支持 MySQL 存储 WB 超长回复凭证。
from migrations.expand_customer_service_reply_sign import migrate_expand_customer_service_reply_sign
migrate_expand_customer_service_reply_sign()  # 幂等，重复执行无影响

# 迁移：产品知识库，支持客服 AI 草稿引用产品档案。
from migrations.add_product_knowledge import migrate_add_product_knowledge
migrate_add_product_knowledge()  # 幂等，重复执行无影响

# 导入路由
from app.routers import auth, dashboard, products, shops, admin, users, inventory, orders, ads, customer_service, sync_schedules, product_knowledge
from app.routers import metric_thresholds
from app.routers import operation_logs, effect_analysis
from app.routers import ai_settings, ai_prompts


# 导入所有模型（确保create_all能创建所有表）
from app.models.models import (
    User, Shop, Product, ProductPermission, InventoryRecord, InventorySnapshot,
    Order, OrderItem, AdRecord, SystemSetting, UISetting, MenuItem, SyncLog,
    SyncSchedule, MetricHistory, OperationLog,
    CustomerServiceItem, CustomerServiceMessage, CustomerServiceAction, ProductKnowledge,
    AIPromptTemplate
)

# 创建数据库表
Base.metadata.create_all(bind=engine)


# ─── 自定义 ASGI 中间件 ────────────────────────────────────────────

class ProxyAwareSchemeMiddleware:
    """将 X-Forwarded-Proto 注入 scope，确保 FastAPI 生成 https:// URL（用于重定向）"""
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            headers = dict(scope.get("headers", []))
            forwarded_proto = headers.get(b"x-forwarded-proto", b"").decode()
            forwarded_host = headers.get(b"x-forwarded-host", b"").decode()
            if forwarded_proto == "https":
                scope["scheme"] = "https"
                if forwarded_host:
                    scope["host"] = forwarded_host
        await self.app(scope, receive, send)


# ─── 创建应用 ──────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Wildberries 跨境电商 ERP 系统"
)

# 顺序很重要：ProxyAware → TrustedHost → CORSMiddleware
app.add_middleware(ProxyAwareSchemeMiddleware)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(products.router)
app.include_router(shops.router)
app.include_router(admin.router)
app.include_router(users.router)
app.include_router(inventory.router)
app.include_router(orders.router)
app.include_router(ads.router)
app.include_router(customer_service.router)
app.include_router(sync_schedules.router)
app.include_router(product_knowledge.router)
app.include_router(metric_thresholds.router)
app.include_router(operation_logs.router)
app.include_router(effect_analysis.router)
app.include_router(ai_settings.router)
app.include_router(ai_prompts.router)


@app.get("/")
def root():
    """根路径"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health")
def health_check():
    """健康检查"""
    return {"status": "healthy"}


@app.on_event("startup")
async def startup_event():
    """启动时初始化"""
    try:
        from app.tasks.scheduler import start_scheduler
        started = start_scheduler()
        if started:
            print("定时任务调度器已启动")
        else:
            print("定时任务调度器未启动")
    except Exception as e:
        print(f"启动定时任务失败: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
