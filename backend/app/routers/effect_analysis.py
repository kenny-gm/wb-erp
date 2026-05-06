from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from app.models.models import MetricHistory, OperationLog, User
from app.routers.auth import get_current_user

router = APIRouter(prefix="/api/effect-analysis", tags=["效果分析"])

@router.get("/product/{product_id}")
def get_effect_analysis(
    product_id: int,
    days: int = Query(30),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    metrics = db.query(MetricHistory).filter(
        MetricHistory.product_id == product_id,
        MetricHistory.date >= start_date
    ).order_by(MetricHistory.date).all()
    
    events = db.query(OperationLog).filter(
        OperationLog.product_id == product_id,
        OperationLog.log_date >= start_date
    ).order_by(OperationLog.log_date).all()
    
    return {
        "metrics": [
            {
                "date": m.date,
                "sales": m.sales,
                "ad_cost": m.ad_cost,
                "roas": m.roas,
                "conversion_rate": m.conversion_rate
            }
            for m in metrics
        ],
        "events": [
            {
                "date": e.log_date,
                "title": e.title,
                "detail": e.content,
                "effect": e.effect,
                "action_type": e.action_type
            }
            for e in events
        ]
    }
