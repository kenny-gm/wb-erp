import json
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session

from datetime import datetime, timedelta
from app.database import get_db
from app.models.models import OperationLog, User, Product, Shop
from app.routers.auth import get_current_user
from pydantic import BaseModel
from typing import Optional
router = APIRouter(prefix="/api/operation-logs", tags=["运营日志"])
class OperationLogCreate(BaseModel):
    product_id: Optional[int] = None
    shop_id: Optional[int] = None
    action_type: str
    action_detail: Optional[dict] = None
    tracking_days: int = 7
    title: str
    content: str
    alert_id: Optional[int] = None
class OperationLogUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    action_type: Optional[str] = None
    effect: Optional[str] = None
    effect_analysis: Optional[str] = None
@router.get("/")
def get_operation_logs(
    product_id: Optional[int] = Query(None),
    shop_id: Optional[int] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    query = db.query(OperationLog).outerjoin(Product, OperationLog.product_id == Product.id)
    
    # 根据当前用户的 allowed_owners 进行过滤
    user_allowed_owners = getattr(current_user, 'allowed_owners', None) or []
    if user_allowed_owners:
        query = query.filter(Product.owner.in_(user_allowed_owners))
    
    if product_id:
        query = query.filter(OperationLog.product_id == product_id)
    if shop_id:
        query = query.filter(Product.shop_id == shop_id)
    if start_date:
        query = query.filter(OperationLog.log_date >= start_date)
    if end_date:
        # Add time to end_date to include the full day
        end_date_with_time = end_date + ' 23:59:59' if len(end_date) == 10 else end_date
        query = query.filter(OperationLog.log_date <= end_date_with_time)
    
    logs = query.order_by(OperationLog.log_date.desc()).limit(limit).all()
    
    result = []
    product_cache = {}
    shop_cache = {}
    for log in logs:
        product_nm_id = None
        product_name = None
        shop_name = None
        if log.product_id:
            if log.product_id not in product_cache:
                product = db.query(Product).filter(Product.id == log.product_id).first()
                product_cache[log.product_id] = product
            else:
                product = product_cache[log.product_id]
            if product:
                product_nm_id = product.nm_id
                product_name = product.custom_name or product.name
                # 通过产品的shop_id获取店铺名称
                if product.shop_id:
                    if product.shop_id not in shop_cache:
                        shop = db.query(Shop).filter(Shop.id == product.shop_id).first()
                        shop_cache[product.shop_id] = shop
                    else:
                        shop = shop_cache[product.shop_id]
                    if shop:
                        shop_name = shop.name
        log_dict = {
            "id": log.id,
            "date": log.log_date.strftime("%Y-%m-%d") if log.log_date else None,
            "title": log.title,
            "detail": log.content,
            "action_type": log.action_type,
            "effect": log.effect or "pending",
            "effect_analysis": log.effect_analysis,
            "product_id": log.product_id,
            "nm_id": product_nm_id,
            "product_name": product_name,
            "shop_id": log.shop_id,
            "shop_name": shop_name,
        }
        result.append(log_dict)
    
    return result
@router.get("/counts")
def get_operation_logs_counts(
    product_ids: Optional[str] = Query(None, description="逗号分隔的产品ID"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取各产品的日志数量"""
    from sqlalchemy import func
    
    count_query = db.query(
        OperationLog.product_id,
        func.count(OperationLog.id).label('count')
    ).outerjoin(Product, OperationLog.product_id == Product.id)
    
    # 根据当前用户的 allowed_owners 进行过滤
    user_allowed_owners = getattr(current_user, 'allowed_owners', None) or []
    if user_allowed_owners:
        count_query = count_query.filter(Product.owner.in_(user_allowed_owners))
    
    if start_date:
        count_query = count_query.filter(OperationLog.log_date >= start_date)
    if end_date:
        end_date_with_time = end_date + ' 23:59:59' if len(end_date) == 10 else end_date
        count_query = count_query.filter(OperationLog.log_date <= end_date_with_time)
    
    if product_ids:
        id_list = [int(x.strip()) for x in product_ids.split(',') if x.strip().isdigit()]
        if id_list:
            count_query = count_query.filter(OperationLog.product_id.in_(id_list))
    
    results = count_query.group_by(OperationLog.product_id).all()
    
    return {str(r[0]): r[1] for r in results}
@router.post("/")
def create_operation_log(
    data: OperationLogCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    log = OperationLog(
        user_id=current_user.id,
        product_id=data.product_id,
        shop_id=data.shop_id,
        log_date=datetime.now(),
        action_type=data.action_type,
        action_detail=json.dumps(data.action_detail) if data.action_detail else '{}',
        effect_tracking_days=data.tracking_days,
        title=data.title,
        content=data.content if data.content else '',
        alert_id=data.alert_id
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
@router.patch("/{log_id}")
def update_operation_log(
    log_id: int,
    data: OperationLogUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    log = db.query(OperationLog).filter(OperationLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")
    
    if data.title is not None:
        log.title = data.title
    if data.content is not None:
        log.content = data.content
    if data.action_type is not None:
        log.action_type = data.action_type
    if data.effect is not None:
        log.effect = data.effect
    if data.effect_analysis is not None and data.effect_analysis.strip():
        from datetime import datetime, timezone, timedelta
        shanghai_tz = timezone(timedelta(hours=8))
        timestamp = datetime.now(shanghai_tz).strftime('%Y-%m-%d %H:%M')
        new_entry = "[" + timestamp + "] " + data.effect_analysis.strip()
        if log.effect_analysis:
            log.effect_analysis = log.effect_analysis + "\n" + new_entry
        else:
            log.effect_analysis = new_entry
    
    db.commit()
    db.refresh(log)
    return log
@router.delete("/{log_id}")
def delete_operation_log(
    log_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    role = getattr(current_user.role, "value", current_user.role)
    if role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可删除日志")
    log = db.query(OperationLog).filter(OperationLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")
    db.delete(log)
    db.commit()
    return {"message": "删除成功"}
@router.get("/product/{product_id}")
def get_product_logs(
    product_id: int,
    days: int = Query(30),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    # 获取产品信息用于权限检查
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return []
    
    # 检查负责人权限
    user_allowed_owners = getattr(current_user, 'allowed_owners', None) or []
    if user_allowed_owners and product.owner not in user_allowed_owners:
        return []
    
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    logs = db.query(OperationLog).filter(
        OperationLog.product_id == product_id,
        OperationLog.log_date >= start_date
    ).order_by(OperationLog.log_date.desc()).all()
    return [
        {
            "id": log.id,
            "date": log.log_date.strftime("%Y-%m-%d") if log.log_date else None,
            "title": log.title,
            "detail": log.content,
            "action_type": log.action_type,
            "effect": log.effect or "pending",
            "effect_analysis": log.effect_analysis
        }
        for log in logs
    ]
@router.get("/latest-by-products")
def get_latest_logs_by_products(
    product_ids: Optional[str] = Query(None, description="逗号分隔的产品ID"),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取各产品的最新日志信息"""
    if not product_ids:
        return {}
    
    id_list = [int(x.strip()) for x in product_ids.split(',') if x.strip().isdigit()]
    if not id_list:
        return {}
    
    # 根据当前用户的 allowed_owners 进行过滤
    user_allowed_owners = getattr(current_user, 'allowed_owners', None) or []
    base_query = db.query(OperationLog)
    if user_allowed_owners:
        base_query = base_query.join(Product, OperationLog.product_id == Product.id).filter(Product.owner.in_(user_allowed_owners))
    
    # 子查询：获取每个产品最新日志的ID
    from sqlalchemy import func as sql_func
    
    subquery = base_query.with_entities(
        OperationLog.product_id.label("product_id"),
        sql_func.max(OperationLog.id).label("max_id"),
    ).filter(
        OperationLog.product_id.in_(id_list)
    ).group_by(OperationLog.product_id).subquery()
    
    # 获取最新日志
    latest_logs = db.query(OperationLog).join(
        subquery,
        (OperationLog.product_id == subquery.c.product_id) & (OperationLog.id == subquery.c.max_id)
    ).all()
    
    result = {}
    for log in latest_logs:
        result[str(log.product_id)] = {
            "date": log.log_date.strftime("%Y-%m-%d") if log.log_date else None,
            "detail": log.content[:100] if log.content else None,
            "effect_analysis": log.effect_analysis,
            "title": log.title,
        }
    
    return result