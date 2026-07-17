from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

scheduler = BackgroundScheduler()

def start_scheduler():
    try:
        from app.config import settings
        if not getattr(settings, "SYNC_ENABLED", True):
            print("SYNC_ENABLED=false，定时任务调度器不启动")
            return False

        from app.tasks.effect_tracking import track_operation_effects
        
        # Daily at 6:10 AM Beijing time - track operation effects
        scheduler.add_job(track_operation_effects, CronTrigger(hour=6, minute=10, timezone="Asia/Shanghai"))
        # Daily at 6:15 AM Beijing time - Yandex traffic sync (shows-sales)
        scheduler.add_job(sync_yandex_traffic_task, CronTrigger(hour=6, minute=15, timezone="Asia/Shanghai"))
        # Every minute - scan due sync_schedules by shop and data type.
        scheduler.add_job(sync_due_schedules_task, IntervalTrigger(minutes=1, timezone="Asia/Shanghai"))
        
        scheduler.start()
        print("定时任务调度器已启动")
        return True
    except Exception as e:
        print(f"启动定时任务失败: {e}")
        return False


def sync_yandex_traffic_task():
    """每天 6:15 北京时间同步 Yandex 流量数据（shows-sales 报告）"""
    from app.database import SessionLocal
    from app.services.sync_fixed import SyncService
    from app.models.models import Shop
    import logging

    logger = logging.getLogger("sync")
    db = SessionLocal()
    try:
        # 只同步 Yandex 店铺
        shops = db.query(Shop).filter(Shop.platform == "yandex", Shop.is_active == 1).all()
        for shop in shops:
            try:
                svc = SyncService(db, shop)
                result = svc.sync_yandex_traffic()
                logger.info(f"Yandex traffic sync [{shop.name}]: {result}")
            except Exception as e:
                logger.error(f"Yandex traffic sync [{shop.name}] 失败: {e}")
    finally:
        db.close()

def sync_due_schedules_task():
    """每分钟检查并触发到期的同步计划（按店铺 + 数据类型）"""
    import logging
    from datetime import datetime, timedelta, timezone
    from app.database import SessionLocal
    from app.models.models import Shop, SyncJob, SyncSchedule
    from app.routers.sync_schedules import ensure_default_schedules
    import httpx

    logger = logging.getLogger("sync")

    # 全局同步开关检查
    from app.config import settings
    if not getattr(settings, 'SYNC_ENABLED', True):
        logger.info("[店铺定时同步] SYNC_ENABLED=false，已跳过")
        return

    db = SessionLocal()
    try:
        ensure_default_schedules(db)
        now_cst = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
        due_schedules = db.query(SyncSchedule).join(Shop).filter(
            Shop.is_active == True,
            Shop.sync_enabled == True,
            SyncSchedule.enabled == True,
            SyncSchedule.next_run_at <= now_cst,
        ).order_by(SyncSchedule.next_run_at.asc()).all()

        if not due_schedules:
            logger.info("[同步计划] 没有到期计划")
            return

        logger.info(f"[同步计划] 开始执行 {len(due_schedules)} 个到期计划")
        api_key = settings.INTERNAL_API_KEY
        base_url = "http://localhost:8000"

        for schedule in due_schedules:
            shop = schedule.shop
            if not shop:
                continue
            existing_job = db.query(SyncJob).filter(
                SyncJob.shop_id == shop.id,
                SyncJob.sync_type == schedule.sync_type,
                SyncJob.status.in_(["pending", "running"])
            ).first()
            if existing_job:
                logger.info(f"[同步计划] {shop.name}/{schedule.sync_type} 已有任务，跳过")
                continue
            try:
                resp = httpx.post(
                    f"{base_url}/api/shops/internal-sync/{shop.id}/?sync_type={schedule.sync_type}",
                    headers={"X-Internal-API-Key": api_key},
                    timeout=600
                )
                result = resp.json()
                ok = result.get("success", False)
                schedule.last_run_at = now_cst
                schedule.next_run_at = now_cst + timedelta(minutes=schedule.interval_minutes)
                schedule.last_status = "success" if ok else "failed"
                schedule.last_message = "" if ok else str(result.get("error") or result)[:1000]
                db.commit()
                logger.info(f"[同步计划] {shop.name}/{schedule.sync_type}: {'成功' if ok else '失败'}")
            except Exception as e:
                schedule.last_run_at = now_cst
                schedule.next_run_at = now_cst + timedelta(minutes=schedule.interval_minutes)
                schedule.last_status = "failed"
                schedule.last_message = str(e)[:1000]
                db.commit()
                logger.error(f"[同步计划] {shop.name}/{schedule.sync_type} 失败: {e}")
    finally:
        db.close()


def sync_due_shops_task():
    """兼容旧 job 名称，实际改为执行 sync_schedules。"""
    return sync_due_schedules_task()
