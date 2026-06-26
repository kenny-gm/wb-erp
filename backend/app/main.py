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

# 迁移：确保 platform_config 列存在
from app.init_db import migrate_add_platform_config
migrate_add_platform_config()

# 迁移：修复 ad_records 唯一索引（包含 advert_id，解决 WB 同产品同天多广告冲突）
from migrations.fix_ad_records_dedup_index import migrate_fix_ad_records_dedup_index
migrate_fix_ad_records_dedup_index()  # 幂等，重复执行无影响

# 导入路由
from app.routers import auth, dashboard, products, shops, admin, users, inventory, orders, ads, customer_service
from app.routers import metric_thresholds
from app.routers import alerts, operation_logs, effect_analysis


# 导入所有模型（确保create_all能创建所有表）
from app.models.models import (
    User, Shop, Product, ProductPermission, InventoryRecord, InventorySnapshot,
    Order, OrderItem, AdRecord, SystemSetting, UISetting, MenuItem, SyncLog,
    MetricHistory, OperationLog, Alert, AlertRule,
    CustomerServiceItem, CustomerServiceMessage, CustomerServiceAction
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
app.include_router(metric_thresholds.router)
app.include_router(alerts.router)
app.include_router(operation_logs.router)
app.include_router(effect_analysis.router)


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
        start_scheduler()
        print("定时任务调度器已启动")
    except Exception as e:
        print(f"启动定时任务失败: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
