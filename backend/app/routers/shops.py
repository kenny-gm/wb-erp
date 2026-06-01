"""
店铺管理路由
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_serializer

from app.database import get_db
from app.models.models import Shop, SyncLog, SyncJob
from fastapi import BackgroundTasks
from app.routers.auth import get_current_user, get_current_admin
from app.services.sync_fixed import SyncService
from app.utils.timezone import format_shanghai_time

router = APIRouter(prefix="/api/shops", tags=["店铺管理"])

# ========== 异步同步任务模型 ==========

class SyncJobCreate(BaseModel):
    sync_type: str = "all"
    history: bool = False


class SyncJobResponse(BaseModel):
    id: int
    shop_id: int
    sync_type: str
    status: str
    progress: int
    message: str
    result_json: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SyncJobCreateResponse(BaseModel):
    success: bool
    job_id: int
    status: str
    message: str




# ========== 请求/响应模型 ==========

class ShopCreate(BaseModel):
    name: str
    api_token: Optional[str] = None
    platform: str = "wildberries"
    platform_config: Optional[dict] = None
    currency: str = "RUB"
    sync_interval_hours: int = 24


class ShopUpdate(BaseModel):
    name: Optional[str] = None
    api_token: Optional[str] = None
    platform: Optional[str] = None
    platform_config: Optional[dict] = None
    currency: Optional[str] = None
    sync_enabled: Optional[bool] = None
    sync_interval_hours: Optional[int] = None
    vat_rate: Optional[float] = None
    withdrawal_fee: Optional[float] = None
    warehouse_factor: Optional[float] = None
    localization_index: Optional[float] = None
    delivery_first_liter: Optional[float] = None
    delivery_first_liter_currency: Optional[str] = None
    delivery_per_liter: Optional[float] = None
    delivery_per_liter_currency: Optional[str] = None
    warehouse_fee_tiers: Optional[list] = None
    warehouse_fee_currency: Optional[str] = None


class ShopResponse(BaseModel):
    id: int
    name: str
    platform: str = "wildberries"
    platform_config: dict = {}
    currency: str
    exchange_rate: float
    sync_enabled: bool
    sync_interval_hours: int
    last_sync_at: Optional[str] = None
    is_active: bool
    created_at: str
    vat_rate: float = 0.0
    withdrawal_fee: float = 0.0
    warehouse_factor: float = 1.0
    localization_index: float = 1.0
    delivery_first_liter: float = 0.0
    delivery_first_liter_currency: str = "RUB"
    delivery_per_liter: float = 0.0
    delivery_per_liter_currency: str = "RUB"
    warehouse_fee_tiers: list = []
    warehouse_fee_currency: str = "RUB"
    has_token: bool = False

    class Config:
        from_attributes = True


def _shop_to_dict(shop: Shop, include_token: bool = False) -> dict:
    """将 Shop 模型转换为响应字典"""
    return {
        "id": shop.id,
        "name": shop.name,
        "platform": shop.platform,
        "platform_config": shop.platform_config or {},
        "currency": shop.currency,
        "api_token": "***" + shop.api_token[-5:] if shop.api_token and include_token else ("***" if shop.api_token else ""),
        "has_token": bool(shop.api_token),
        "sync_enabled": shop.sync_enabled,
        "sync_interval_hours": shop.sync_interval_hours,
        "last_sync_at": shop.last_sync_at.strftime("%Y-%m-%d %H:%M:%S") if shop.last_sync_at else None,
        "is_active": shop.is_active,
        "created_at": shop.created_at.strftime("%Y-%m-%d %H:%M:%S") if shop.created_at else None,
        "vat_rate": shop.vat_rate,
        "withdrawal_fee": shop.withdrawal_fee,
        "warehouse_factor": shop.warehouse_factor,
        "localization_index": shop.localization_index,
        "delivery_first_liter": shop.delivery_first_liter,
        "delivery_first_liter_currency": shop.delivery_first_liter_currency,
        "delivery_per_liter": shop.delivery_per_liter,
        "delivery_per_liter_currency": shop.delivery_per_liter_currency,
        "warehouse_fee_tiers": shop.warehouse_fee_tiers or [],
        "warehouse_fee_currency": shop.warehouse_fee_currency or "RUB",
    }


# ========== 路由 ==========

@router.get("/")
def list_shops(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取店铺列表"""
    shops = db.query(Shop).filter(Shop.is_active == True).all()
    return [_shop_to_dict(shop) for shop in shops]


@router.get("/{shop_id}/")
def get_shop(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取单个店铺详情"""
    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.is_active == True).first()
    if not shop:
        raise HTTPException(status_code=404, detail="店铺不存在")
    return _shop_to_dict(shop)


@router.post("/")
def create_shop(
    data: ShopCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """创建店铺

    Yandex：自动调用 get_campaigns() 按 businessId 分组，
    为每个 businessId 创建或更新一个 business-level Yandex Shop。
    不按 campaignId 拆分为多个店铺。
    """
    if data.platform == "yandex":
        from app.services.yandex_client import YandexClient
        if not data.api_token:
            raise HTTPException(status_code=400, detail="Yandex 店铺需要 API Token")

        try:
            client = YandexClient(data.api_token)
            businesses = client.get_campaigns()
        except Exception as e:
            err_msg = str(e)
            if "401" in err_msg or "Unauthorized" in err_msg:
                raise HTTPException(status_code=401, detail="Token 无效或已过期，请重新获取")
            if "403" in err_msg or "Forbidden" in err_msg:
                raise HTTPException(status_code=403, detail="Token 无权限访问 Yandex API，请确认已在 Yandex Partner Market 授权")
            raise HTTPException(status_code=502, detail=f"Yandex API 调用失败: {e}")

        if not businesses:
            raise HTTPException(status_code=400, detail="未找到任何 Yandex Business，请确认 Token 正确且已开通接口权限")

        results = []
        for biz_id, biz_info in businesses.items():
            # 查找是否已存在同一 businessId 的 Yandex shop
            existing_shops = db.query(Shop).filter(
                Shop.platform == "yandex",
                Shop.is_active == True
            ).all()
            existing = next(
                (s for s in existing_shops
                 if (s.platform_config or {}).get("business_id") == biz_id),
                None
            )

            campaign_ids = [c["campaign_id"] for c in biz_info["campaigns"] if c["campaign_id"]]
            platform_config = {
                "business_id": biz_id,
                "business_name": biz_info["business_name"],
                "campaign_ids": campaign_ids,
                "campaigns": biz_info["campaigns"],
            }

            if existing:
                # 更新已有 business-level shop
                existing.name = data.name or biz_info["business_name"] or f"Yandex Business {biz_id}"
                existing.currency = data.currency or "CNY"
                existing.platform_config = platform_config
                if data.api_token:
                    existing.api_token = data.api_token
                db.commit()
                db.refresh(existing)
                results.append(_shop_to_dict(existing))
            else:
                shop = Shop(
                    name=data.name or biz_info["business_name"] or f"Yandex Business {biz_id}",
                    api_token=data.api_token or "",
                    platform="yandex",
                    platform_config=platform_config,
                    currency=data.currency or "CNY",
                    sync_interval_hours=data.sync_interval_hours,
                )
                db.add(shop)
                results.append(shop)

        db.commit()
        for r in results:
            if hasattr(r, "id"):
                db.refresh(r)
        return [(_shop_to_dict(r) if hasattr(r, "__dict__") else r) for r in results]

    # Wildberries / 其他平台
    shop = Shop(
        name=data.name,
        api_token=data.api_token or "",
        platform=data.platform,
        platform_config=data.platform_config or {},
        currency=data.currency,
        sync_interval_hours=data.sync_interval_hours
    )

    db.add(shop)
    db.commit()
    db.refresh(shop)
    return _shop_to_dict(shop)


@router.put("/{shop_id}/")
def update_shop(
    shop_id: int,
    data: ShopUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """更新店铺"""
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="店铺不存在")

    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(shop, key, value)

    db.commit()
    db.refresh(shop)
    return _shop_to_dict(shop)


@router.delete("/{shop_id}/")
def delete_shop(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """删除店铺（软删除）"""
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="店铺不存在")

    shop.is_active = False
    db.commit()
    return {"message": "店铺已删除"}


@router.post("/{shop_id}/test-connection/")
def test_connection(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """测试 API 连接"""
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="店铺不存在")

    if shop.platform == "yandex":
        from app.services.yandex_client import YandexClient
        client = YandexClient(shop.api_token)
        if client.test_connection():
            return {"success": True, "message": "Yandex API 连接成功"}
        else:
            return {"success": False, "message": "Yandex API 连接失败，请检查 Token"}
    else:
        from app.services.wb_api import WBAPIClient
        client = WBAPIClient(shop.api_token)
        if client.ping():
            return {"success": True, "message": "Wildberries API 连接成功"}
        else:
            return {"success": False, "message": "Wildberries API 连接失败，请检查 API Token"}


@router.post("/{shop_id}/sync/")
def sync_shop_data(
    shop_id: int,
    sync_type: str = "all",
    history: bool = False,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """手动同步数据（需要管理员认证）"""
    return _sync_shop_data_internal(shop_id, sync_type, history, db)


def _sync_shop_data_internal(
    shop_id: int,
    sync_type: str = "all",
    history: bool = False,
    db: Session = Depends(get_db)
):
    """内部同步数据"""
    import logging
    logger = logging.getLogger(__name__)

    logger.info(f"========== 开始同步店铺 {shop_id} ==========")

    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        logger.error(f"店铺 {shop_id} 不存在")
        raise HTTPException(status_code=404, detail="店铺不存在")

    logger.info(f"店铺信息: {shop.name}, platform={shop.platform}")

    sync_service = SyncService(db, shop)

    is_new = shop.last_sync_at is None
    if is_new:
        logger.info("检测到新店铺，将同步历史数据")
        history = True

    logger.info(f"同步类型: {sync_type}, 历史数据: {history}")

    results = {}

    try:
        if sync_type == "products":
            results["products"] = sync_service.sync_products(overwrite=True)
        elif sync_type == "orders":
            results["orders"] = sync_service.sync_orders()
        elif sync_type == "inventory":
            results["inventory"] = sync_service.sync_inventory()
        elif sync_type == "ads":
            if shop.platform == "yandex":
                results["ads"] = {"success": True, "message": "Yandex MVP 暂不支持广告"}
            else:
                results["ads"] = sync_service.sync_ads(days=7)
        elif sync_type == "keywords":
            if shop.platform == "yandex":
                results["keywords"] = {"success": True, "message": "Yandex MVP 暂不支持关键词"}
            else:
                results["keywords"] = sync_service.sync_keywords(days=30)
        elif sync_type == "product_sales":
            results["product_sales"] = sync_service.sync_product_sales(days=30 if history else 7)
        elif sync_type == "all":
            results = sync_service.sync_all(history=history)
    except Exception as e:
        logger.error(f"同步失败: {str(e)}", exc_info=True)
        return {
            "is_new_shop": is_new,
            "success": False,
            "error": str(e),
            "results": results
        }

    logger.info(f"========== 同步店铺 {shop_id} 完成 ==========")
    return {
        "is_new_shop": is_new,
        "success": True,
        "results": results
    }


@router.get("/{shop_id}/sync-logs/")
def get_sync_logs(
    shop_id: int,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取同步日志"""
    logs = db.query(SyncLog).filter(
        SyncLog.shop_id == shop_id
    ).order_by(SyncLog.started_at.desc()).limit(limit).all()
    return logs


@router.get("/{shop_id}/products/")
def get_shop_products(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取店铺的产品列表"""
    from app.models.models import Product

    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.is_active == True).first()
    if not shop:
        raise HTTPException(status_code=404, detail="店铺不存在")

    query = db.query(Product).filter(Product.shop_id == shop_id)

    user_allowed_owners = getattr(current_user, 'allowed_owners', None) or []
    if user_allowed_owners:
        query = query.filter(Product.owner.in_(user_allowed_owners))

    products = query.all()
    return [
        {
            "id": p.id,
            "nm_id": p.nm_id,
            "sku": p.sku,
            "name": p.custom_name or p.name or p.sku,
            "shop_id": p.shop_id
        }
        for p in products
    ]


@router.get("/{shop_id}/traffic-source/")
def get_traffic_source(
    shop_id: int,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取流量来源分析"""
    from app.models.models import Product, Order, AdRecord
    from app.services.wb_api import WBAPIClient
    from datetime import timedelta

    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.is_active == True).first()
    if not shop:
        raise HTTPException(status_code=404, detail="店铺不存在")

    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    if not date_from:
        date_from = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    ad_clicks = 0
    ad_impressions = 0
    ad_spend = 0

    if shop.api_token and shop.platform == "wildberries":
        try:
            client = WBAPIClient(shop.api_token)
            adverts = client.get_adverts()
            ad_ids = [ad.get("id") for ad in adverts if ad.get("id")]
            if ad_ids:
                try:
                    stats = client.get_ad_stats(ids=ad_ids, date_from=date_from, date_to=date_to)
                    for stat in stats:
                        for day in stat.get("days", []):
                            ad_impressions += day.get("views", 0)
                            ad_clicks += day.get("clicks", 0)
                            ad_spend += day.get("sum", 0)
                except Exception as e:
                    print(f"获取广告统计失败: {e}")
        except Exception as e:
            print(f"获取广告列表失败: {e}")

    try:
        orders = db.query(Order).filter(
            Order.shop_id == shop_id,
            Order.created_at >= datetime.strptime(date_from, "%Y-%m-%d"),
            Order.created_at <= datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
        ).all()
        total_orders = len(orders)
    except:
        total_orders = 0

    ad_orders = int(ad_clicks * 0.01) if ad_clicks > 0 else int(total_orders * 0.3)
    natural_orders = max(0, total_orders - ad_orders)
    ad_visitors = ad_clicks
    natural_visitors = natural_orders * 100
    total_visitors = ad_visitors + natural_visitors

    if total_visitors > 0:
        ad_ratio = round(ad_visitors / total_visitors * 100, 1)
        natural_ratio = round(natural_visitors / total_visitors * 100, 1)
        other_ratio = round(100 - ad_ratio - natural_ratio, 1)
    else:
        ad_ratio = 25.0
        natural_ratio = 73.0
        other_ratio = 2.0

    return {
        "date_from": date_from,
        "date_to": date_to,
        "total_visitors": total_visitors,
        "ad_visitors": ad_visitors,
        "natural_visitors": natural_visitors,
        "other_visitors": 0,
        "ad_ratio": ad_ratio,
        "natural_ratio": natural_ratio,
        "other_ratio": other_ratio,
        "ad_clicks": ad_clicks,
        "ad_impressions": ad_impressions,
        "ad_spend": ad_spend,
        "total_orders": total_orders,
        "ad_orders": ad_orders,
        "natural_orders": natural_orders
    }


# ========== 内部同步端点（使用API密钥）==========
INTERNAL_API_KEY = "wb-erp-internal-sync-key-2026"


@router.post("/internal-sync/{shop_id}/")
def internal_sync_shop_data(
    shop_id: int,
    sync_type: str = "all",
    history: bool = False,
    api_key: str = None,
    db: Session = Depends(get_db)
):
    """内部同步数据（服务器端定时任务使用）"""
    import logging
    logger = logging.getLogger(__name__)

    if api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="无效的API密钥")

    return _sync_shop_data_internal(shop_id, sync_type, history, db)

# ============================================================
# 后台同步任务函数
# ============================================================
def run_sync_job_background(job_id: int, shop_id: int, sync_type: str, history: bool):
    """后台执行同步任务（独立 session）"""
    import sys, traceback, json
    sys.path.insert(0, '/app/backend')

    from app.database import SessionLocal
    from app.services.sync_fixed import SyncService
    from app.models.models import Shop, SyncJob

    db = SessionLocal()
    try:
        job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
        if not job:
            print(f"[SyncJob {job_id}] 任务不存在")
            return

        shop = db.query(Shop).filter(Shop.id == shop_id).first()
        if not shop:
            job.status = "failed"
            job.error = f"店铺 {shop_id} 不存在"
            job.finished_at = datetime.now(ZoneInfo("Asia/Shanghai"))
            job.message = "店铺不存在"
            db.commit()
            return

        job.status = "running"
        job.progress = 5
        job.started_at = datetime.now(ZoneInfo("Asia/Shanghai"))
        job.message = "开始同步..."
        db.commit()

        svc = SyncService(db, shop)

        if sync_type == "all":
            job.progress = 20
            job.message = "同步商品..."
            db.commit()
            r_products = svc.sync_products(overwrite=True)
            if not r_products.get("success"):
                raise Exception(f"商品同步失败: {r_products.get('error')}")

            job.progress = 40
            job.message = "同步订单..."
            db.commit()
            r_orders = svc.sync_orders()
            if not r_orders.get("success"):
                raise Exception(f"订单同步失败: {r_orders.get('error')}")

            job.progress = 60
            job.message = "同步库存..."
            db.commit()
            r_inv = svc.sync_inventory()
            if not r_inv.get("success"):
                raise Exception(f"库存同步失败: {r_inv.get('error')}")

            job.progress = 75
            job.message = "同步广告/关键词..."
            db.commit()
            if shop.platform == "yandex":
                r_ads = {"success": True, "message": "Yandex MVP 暂不支持广告"}
            else:
                r_ads = svc.sync_ads(days=7)

            if shop.platform == "yandex":
                r_keywords = {"success": True, "message": "Yandex MVP 暂不支持关键词"}
            else:
                r_keywords = svc.sync_keywords(days=30)

            job.progress = 85
            job.message = "同步流量数据..."
            db.commit()
            if shop.platform == "yandex":
                r_traffic = svc.sync_yandex_traffic()
            else:
                r_traffic = {"success": True, "message": "WB 无流量报告"}

            job.progress = 95
            job.message = "完成..."
            db.commit()

            result = {
                "products": r_products,
                "orders": r_orders,
                "inventory": r_inv,
                "ads": r_ads,
                "keywords": r_keywords,
                "traffic": r_traffic,
            }

        elif sync_type == "products":
            r = svc.sync_products(overwrite=True)
            result = r
        elif sync_type == "orders":
            r = svc.sync_orders()
            result = r
        elif sync_type == "inventory":
            r = svc.sync_inventory()
            result = r
        elif sync_type == "ads":
            if shop.platform == "yandex":
                result = {"success": True, "message": "Yandex MVP 暂不支持广告"}
            else:
                result = svc.sync_ads(days=7)
        elif sync_type == "keywords":
            if shop.platform == "yandex":
                result = {"success": True, "message": "Yandex MVP 暂不支持关键词"}
            else:
                result = svc.sync_keywords(days=30)
        elif sync_type == "product_sales":
            days = 30 if history else 7
            if shop.platform == "yandex":
                result = svc.sync_yandex_product_sales(days=days)
            else:
                result = svc.sync_product_sales(days=days)
        else:
            raise Exception(f"未知的 sync_type: {sync_type}")

        job.status = "success"
        job.progress = 100
        job.result_json = json.dumps(result, ensure_ascii=False)
        job.message = "同步完成"
        job.finished_at = datetime.now(ZoneInfo("Asia/Shanghai"))
        db.commit()

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[SyncJob {job_id}] 失败: {e}\n{tb}")
        job.status = "failed"
        job.error = str(e)
        job.message = "同步失败"
        job.finished_at = datetime.now(ZoneInfo("Asia/Shanghai"))
        db.commit()
    finally:
        db.close()


# ============================================================
# 异步同步接口
# ============================================================
@router.post("/{shop_id}/sync-async/", response_model=SyncJobCreateResponse)
def sync_shop_async(
    shop_id: int,
    sync_type: str = "all",
    history: bool = False,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
    background_tasks: BackgroundTasks = None,
):
    """创建异步同步任务，立即返回 job_id"""
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="店铺不存在")

    # 并发保护：检查是否有 pending/running 的同类型任务
    existing = db.query(SyncJob).filter(
        SyncJob.shop_id == shop_id,
        SyncJob.sync_type == sync_type,
        SyncJob.status.in_("pending", "running")
    ).first()

    if existing:
        return SyncJobCreateResponse(
            success=True,
            job_id=existing.id,
            status=existing.status,
            message="同步任务已在运行中"
        )

    # 创建新任务
    job = SyncJob(
        shop_id=shop_id,
        sync_type=sync_type,
        status="pending",
        progress=0,
        message="等待同步...",
        created_by=current_user.get("id") if current_user else None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # 启动后台任务
    if background_tasks:
        background_tasks.add_task(
            run_sync_job_background,
            job.id, shop_id, sync_type, history
        )

    return SyncJobCreateResponse(
        success=True,
        job_id=job.id,
        status="pending",
        message="同步任务已启动"
    )


@router.get("/sync-jobs/{job_id}", response_model=SyncJobResponse)
def get_sync_job(
    job_id: int,
    db: Session = Depends(get_db),
):
    """查询同步任务状态"""
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.get("/{shop_id}/sync-jobs/latest")
def get_latest_sync_job(
    shop_id: int,
    sync_type: str = "all",
    db: Session = Depends(get_db),
):
    """查询店铺最近一次同步任务"""
    job = db.query(SyncJob).filter(
        SyncJob.shop_id == shop_id,
        SyncJob.sync_type == sync_type
    ).order_by(SyncJob.id.desc()).first()
    if not job:
        raise HTTPException(status_code=404, detail="暂无同步记录")
    return job

