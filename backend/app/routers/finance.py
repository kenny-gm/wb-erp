"""
财务分析路由
"""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.models import Order, OrderItem, AdRecord, Product, Shop
from app.routers.auth import get_current_user

router = APIRouter(prefix="/api/finance", tags=["财务分析"])


def to_rub(amount: float, currency: str, rate: float) -> float:
    """将金额转换为卢布"""
    if not amount:
        return 0
    if currency == "CNY":
        return amount * rate
    return amount


def get_shop_currency_and_rate(db: Session, shop_id: int = None) -> tuple:
    """获取店铺货币类型和汇率
    currency 来自 shops 表
    rate 来自 system_settings 表（cny_to_rub）
    """
    from sqlalchemy import text
    sys_setting = db.execute(text("SELECT value FROM system_settings WHERE `key` = 'cny_to_rub'")).fetchone()
    cny_to_rub = float(sys_setting[0]) if sys_setting and sys_setting[0] else 12.5
    if shop_id:
        shop = db.query(Shop).filter(Shop.id == shop_id).first()
        if shop:
            return shop.currency or "RUB", cny_to_rub
    return "RUB", cny_to_rub


@router.get("/summary/")
def finance_summary(
    shop_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """财务汇总"""
    from app.models.models import ProductPermission
    
    currency, rate = get_shop_currency_and_rate(db, shop_id)
    
    allowed_product_ids = None
    if current_user.role != "admin":
        if current_user.allowed_owners:
            products = db.query(Product.id).filter(Product.owner.in_(current_user.allowed_owners)).all()
            allowed_product_ids = [p[0] for p in products]
        else:
            perms = db.query(ProductPermission.product_id).filter(ProductPermission.user_id == current_user.id).all()
            allowed_product_ids = [p[0] for p in perms]
        if not allowed_product_ids:
            return {"total_sales": 0, "total_profit": 0, "avg_profit_rate": 0, "order_count": 0}
    
    query = db.query(Order)
    if shop_id:
        query = query.filter(Order.shop_id == shop_id)
    if start_date:
        query = query.filter(Order.order_date >= datetime.strptime(start_date, "%Y-%m-%d").strftime("%Y-%m-%d"))
    if end_date:
        query = query.filter(Order.order_date < (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"))
    
    orders = query.all()
    if allowed_product_ids is not None:
        orders = [o for o in orders if o.product_id in allowed_product_ids]
    
    total_sales = sum(to_rub(o.total_amount, currency, rate) for o in orders)
    total_product_cost = sum(to_rub(o.product_cost, currency, rate) for o in orders)
    total_commission = sum(to_rub(o.commission, currency, rate) for o in orders)
    total_logistics = sum(to_rub(o.logistics_fee, currency, rate) for o in orders)
    total_ad_cost = sum(to_rub(o.ad_cost, currency, rate) for o in orders)
    total_profit = sum(to_rub(o.profit, currency, rate) for o in orders)
    avg_profit_rate = sum(o.profit_rate for o in orders) / len(orders) if orders else 0
    total_cost = total_product_cost + total_commission + total_logistics + total_ad_cost
    
    return {
        "total_sales": round(total_sales, 2),
        "total_cost": round(total_cost, 2),
        "total_profit": round(total_profit, 2),
        "avg_profit_rate": round(avg_profit_rate * 100, 2),
        "order_count": len(orders),
        "currency": "RUB"
    }


@router.get("/product/{product_id}/")
def finance_by_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """单个产品财务分析"""
    from app.models.models import ProductPermission
    
    if current_user.role != "admin":
        if current_user.allowed_owners:
            product = db.query(Product).filter(Product.id == product_id, Product.owner.in_(current_user.allowed_owners)).first()
        else:
            perm = db.query(ProductPermission).filter(ProductPermission.product_id == product_id, ProductPermission.user_id == current_user.id).first()
            product = db.query(Product).filter(Product.id == product_id).first() if perm else None
    else:
        product = db.query(Product).filter(Product.id == product_id).first()
    
    if not product:
        return {"error": "产品不存在或无权访问"}
    
    currency, rate = get_shop_currency_and_rate(db, product.shop_id)
    order_items = db.query(OrderItem).filter(OrderItem.product_id == product_id).all()
    
    total_sales = sum(to_rub(i.total_price, currency, rate) for i in order_items)
    total_cost = sum(to_rub(i.product_cost, currency, rate) for i in order_items)
    
    return {
        "product_id": product_id,
        "product": {"nm_id": product.nm_id, "name": product.name, "custom_name": product.custom_name},
        "total_sales": round(total_sales, 2),
        "total_cost": round(total_cost, 2),
        "total_profit": round(total_sales - total_cost, 2),
        "profit_rate": round((total_sales - total_cost) / total_sales * 100, 2) if total_sales > 0 else 0,
        "order_count": len(order_items),
        "currency": "RUB"
    }
