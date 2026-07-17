"""
同步频率设置路由
"""
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Shop, SyncJob, SyncSchedule
from app.routers.auth import get_current_admin
from app.routers.shops import run_sync_job_background

router = APIRouter(prefix="/api/sync-schedules", tags=["同步频率设置"])

SYNC_TYPE_LABELS = {
    "products": "商品",
    "orders": "订单/销售",
    "inventory": "库存",
    "ads": "广告",
    "keywords": "关键词",
    "product_sales": "产品销售/漏斗",
    "customer_service": "客服",
}

SYNC_TYPE_ORDER = [
    "customer_service",
    "orders",
    "product_sales",
    "products",
    "inventory",
    "ads",
    "keywords",
]


class SyncScheduleUpdate(BaseModel):
    enabled: Optional[bool] = None
    interval_minutes: Optional[int] = Field(default=None, ge=1, le=10080)
    next_run_at: Optional[datetime] = None


def format_dt(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S")


def schedule_to_dict(schedule: SyncSchedule) -> dict:
    shop = schedule.shop
    return {
        "id": schedule.id,
        "shop_id": schedule.shop_id,
        "shop_name": shop.name if shop else "",
        "platform": shop.platform if shop else "",
        "sync_type": schedule.sync_type,
        "sync_type_label": SYNC_TYPE_LABELS.get(schedule.sync_type, schedule.sync_type),
        "enabled": bool(schedule.enabled),
        "interval_minutes": schedule.interval_minutes,
        "last_run_at": format_dt(schedule.last_run_at),
        "next_run_at": format_dt(schedule.next_run_at),
        "last_status": schedule.last_status,
        "last_message": schedule.last_message,
        "updated_at": format_dt(schedule.updated_at),
    }


def default_sync_types_for_shop(shop: Shop) -> list[str]:
    if shop.platform == "wildberries":
        return SYNC_TYPE_ORDER
    return ["orders", "product_sales", "products", "inventory"]


def ensure_default_schedules(db: Session) -> int:
    """为现有启用店铺补默认计划；默认按原店铺间隔，不立刻提高同步频率。"""
    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    created = 0
    shops = db.query(Shop).filter(Shop.is_active == True).all()
    for shop in shops:
        interval = max(1, int(shop.sync_interval_hours or 24)) * 60
        for sync_type in default_sync_types_for_shop(shop):
            exists = db.query(SyncSchedule).filter(
                SyncSchedule.shop_id == shop.id,
                SyncSchedule.sync_type == sync_type,
            ).first()
            if exists:
                continue
            db.add(SyncSchedule(
                shop_id=shop.id,
                sync_type=sync_type,
                enabled=bool(shop.sync_enabled),
                interval_minutes=interval,
                next_run_at=now + timedelta(minutes=interval),
                last_message="按店铺原同步间隔自动初始化",
            ))
            created += 1
    if created:
        db.commit()
    return created


@router.get("/")
def list_sync_schedules(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    ensure_default_schedules(db)
    schedules = db.query(SyncSchedule).join(Shop).filter(
        Shop.is_active == True
    ).order_by(Shop.id.asc(), SyncSchedule.sync_type.asc()).all()
    return [schedule_to_dict(s) for s in schedules]


@router.post("/initialize/")
def initialize_sync_schedules(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    created = ensure_default_schedules(db)
    return {"success": True, "created": created}


@router.put("/{schedule_id}/")
def update_sync_schedule(
    schedule_id: int,
    data: SyncScheduleUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    schedule = db.query(SyncSchedule).filter(SyncSchedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="同步计划不存在")

    if data.enabled is not None:
        schedule.enabled = data.enabled
    if data.interval_minutes is not None:
        schedule.interval_minutes = data.interval_minutes
    if data.next_run_at is not None:
        schedule.next_run_at = data.next_run_at.replace(tzinfo=None)

    schedule.updated_at = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    db.commit()
    db.refresh(schedule)
    return schedule_to_dict(schedule)


@router.post("/{schedule_id}/run-now/")
def run_schedule_now(
    schedule_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    schedule = db.query(SyncSchedule).filter(SyncSchedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="同步计划不存在")

    shop = db.query(Shop).filter(Shop.id == schedule.shop_id, Shop.is_active == True).first()
    if not shop:
        raise HTTPException(status_code=404, detail="店铺不存在")

    existing = db.query(SyncJob).filter(
        SyncJob.shop_id == schedule.shop_id,
        SyncJob.sync_type == schedule.sync_type,
        SyncJob.status.in_(["pending", "running"]),
    ).first()
    if existing:
        return {
            "success": True,
            "job_id": existing.id,
            "status": existing.status,
            "message": "同步任务已在运行中",
        }

    job = SyncJob(
        shop_id=schedule.shop_id,
        sync_type=schedule.sync_type,
        status="pending",
        progress=0,
        message="等待同步...",
        created_by=current_user.id if current_user else None,
    )
    db.add(job)
    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    schedule.next_run_at = now + timedelta(minutes=schedule.interval_minutes)
    schedule.updated_at = now
    db.commit()
    db.refresh(job)

    background_tasks.add_task(run_sync_job_background, job.id, schedule.shop_id, schedule.sync_type, False)
    return {
        "success": True,
        "job_id": job.id,
        "status": "pending",
        "message": "同步任务已启动",
    }
