from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

scheduler = BackgroundScheduler()

def start_scheduler():
    try:
        from app.tasks.metric_snapshot import daily_metric_snapshot
        from app.tasks.alert_engine import run_alert_engine
        from app.tasks.effect_tracking import track_operation_effects
        
        # Daily at 6 AM Beijing time - metric snapshot
        scheduler.add_job(daily_metric_snapshot, CronTrigger(hour=6, minute=0, timezone="Asia/Shanghai"))
        # Daily at 6:05 AM Beijing time - generate alerts
        scheduler.add_job(run_alert_engine, CronTrigger(hour=6, minute=5, timezone="Asia/Shanghai"))
        # Daily at 6:10 AM Beijing time - track operation effects
        scheduler.add_job(track_operation_effects, CronTrigger(hour=6, minute=10, timezone="Asia/Shanghai"))
        # Daily at 6:15 AM Beijing time - Yandex traffic sync (shows-sales)
        scheduler.add_job(sync_yandex_traffic_task, CronTrigger(hour=6, minute=15, timezone="Asia/Shanghai"))
        # Every 2 hours - sync ERP data to DingTalk AI Table (暂时禁用，待配置 DINGTALK_MCP_URL)
        # scheduler.add_job(sync_dingtalk_task, CronTrigger(hour="*/2", minute=0, timezone="Asia/Shanghai"))
        # Every 30 mins - sync shops that are due (based on each shop's sync_interval_hours)
        scheduler.add_job(sync_due_shops_task, IntervalTrigger(minutes=30, timezone="Asia/Shanghai"))
        
        scheduler.start()
        print("定时任务调度器已启动")
    except Exception as e:
        print(f"启动定时任务失败: {e}")


def sync_dingtalk_task():
    """每2小时同步ERP数据到钉钉AI表格"""
    import logging
    logger = logging.getLogger("sync")
    try:
        import subprocess
        result = subprocess.run(
            ['python3', '/app/backend/sync_dingtalk.py'],
            capture_output=True, text=True, timeout=300,
            cwd='/app/backend'
        )
        logger.info(f"DingTalk sync: {result.stdout}")
        if result.returncode != 0:
            logger.error(f"DingTalk sync failed: {result.stderr}")
    except Exception as e:
        logger.error(f"DingTalk sync error: {e}")

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

def sync_due_shops_task():
    """每30分钟检查并同步到期的店铺（按各店铺的 sync_interval_hours）"""
    import logging
    from datetime import datetime, timedelta, timezone
    from app.database import SessionLocal
    from app.models.models import Shop
    import httpx

    logger = logging.getLogger("sync")
    db = SessionLocal()
    try:
        shops = db.query(Shop).filter(Shop.is_active == 1).all()
        now_cst = datetime.now(timezone(timedelta(hours=8)))  # 北京时间 aware

        due_shops = []
        for shop in shops:
            interval = shop.sync_interval_hours or 24
            last = shop.last_sync_at  # naive CST from DB
            if last is None:
                due_shops.append(shop)
            else:
                # last 是 naive datetime，now_cst 是 aware，直接相减
                hours_since = (now_cst.replace(tzinfo=None) - last).total_seconds() / 3600
                if hours_since >= interval:
                    due_shops.append(shop)

        if not due_shops:
            logger.info(f"[店铺定时同步] 没有店铺需要同步")
            return

        logger.info(f"[店铺定时同步] 开始同步 {len(due_shops)} 个到期店铺: {[s.name for s in due_shops]}")
        from app.config import settings
        api_key = settings.INTERNAL_API_KEY
        base_url = "http://localhost:8000"

        for shop in due_shops:
            try:
                resp = httpx.post(
                    f"{base_url}/api/shops/internal-sync/{shop.id}/?sync_type=all",
                    headers={"X-Internal-API-Key": api_key},
                    timeout=600
                )
                result = resp.json()
                ok = result.get("success", False)
                logger.info(f"[店铺定时同步] {shop.name}: {'成功' if ok else '失败'}")
            except Exception as e:
                logger.error(f"[店铺定时同步] {shop.name} 失败: {e}")
    finally:
        db.close()
