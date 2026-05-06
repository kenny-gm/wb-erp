from datetime import datetime, timedelta
from app.database import SessionLocal
from app.models.models import MetricHistory, OperationLog, Alert
from zoneinfo import ZoneInfo

def track_operation_effects():
    db = SessionLocal()
    try:
        target_date = (datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=7)).strftime("%Y-%m-%d")
        print(f"开始追踪运营效果，跟踪日期: {target_date}...")
        
        logs = db.query(OperationLog).filter(
            OperationLog.effect == "pending",
            OperationLog.log_date <= target_date
        ).all()
        
        for log in logs:
            tracking_end = (datetime.strptime(log.log_date, "%Y-%m-%d") + timedelta(days=log.effect_tracking_days)).strftime("%Y-%m-%d")
            
            metrics = db.query(MetricHistory).filter(
                MetricHistory.product_id == log.product_id,
                MetricHistory.date > log.log_date,
                MetricHistory.date <= tracking_end
            ).all()
            
            if not metrics:
                continue
            
            avg_conversion = sum(m.conversion_rate for m in metrics) / len(metrics)
            avg_roas = sum(m.roas for m in metrics) / len(metrics) if any(m.roas for m in metrics) else 0
            avg_sales = sum(m.sales for m in metrics) / len(metrics)
            avg_ad_cost = sum(m.ad_cost for m in metrics) / len(metrics)
            
            before = log.metrics_before or {}
            after = {
                "conversion_rate": avg_conversion,
                "roas": avg_roas,
                "sales": avg_sales,
                "ad_cost": avg_ad_cost
            }
            
            effect = "neutral"
            analysis = []
            
            if after["conversion_rate"] > before.get("conversion_rate", 0):
                effect = "positive"
            elif after["roas"] > before.get("roas", 0):
                effect = "positive"
            elif after["sales"] < before.get("sales", 0) and after["ad_cost"] > before.get("ad_cost", 0):
                effect = "negative"
            
            if effect == "positive":
                analysis.append("操作后指标有所改善")
                if after["conversion_rate"] > before.get("conversion_rate", 0):
                    analysis.append(f"转化率提升 {(after[conversion_rate] - before[conversion_rate]):.2f}%")
                if after["roas"] > before.get("roas", 0):
                    analysis.append(f"ROAS提升 {(after[roas] - before[roas]):.2f}")
            elif effect == "negative":
                analysis.append("操作后指标下降")
                if after["sales"] < before.get("sales", 0):
                    if before.get("sales", 0) > 0:
                        analysis.append(f"销售额下降 {((before[sales] - after[sales]) / before[sales] * 100):.1f}%")
            else:
                analysis.append("操作前后无明显变化")
            
            log.metrics_after = after
            log.effect = effect
            log.effect_analysis = "；".join(analysis)
            
            if log.alert_id:
                alert = db.query(Alert).filter(Alert.id == log.alert_id).first()
                if alert and effect == "positive":
                    alert.is_resolved = True
                    alert.resolved_note = f"操作效果积极，问题已解决。{log.effect_analysis}"
                    alert.resolved_at = datetime.now()
        
        db.commit()
        print(f"效果追踪完成，共处理 {len(logs)} 条运营记录")
    except Exception as e:
        print(f"效果追踪失败: {e}")
        db.rollback()
    finally:
        db.close()
