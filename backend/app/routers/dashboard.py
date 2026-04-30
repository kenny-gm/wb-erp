"""
销售看板路由
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.models import Shop, Product, Order, AdRecord
from app.models.metric_threshold import MetricThreshold
from app.routers.auth import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["销售看板"])


class DashboardFilter(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    shop_ids: Optional[List[int]] = None
    owners: Optional[List[str]] = None
    product_ids: Optional[List[int]] = None
    product_name: Optional[str] = None


class DashboardStats(BaseModel):
    sales_amount: float = 0
    order_count: int = 0
    visitors: int = 0
    add_to_cart: int = 0
    add_to_cart_rate: float = 0
    conversion_rate: float = 0
    ad_cost: float = 0
    ad_ratio: float = 0
    ad_ratio_alert: str = "normal"
    currency: str = "RUB"
    comparison: Optional[dict] = None
    data_updated_at: Optional[str] = None  # 数据最新更新时间
    data_source: str = "database"  # 数据来源: database=本地, api=WB API
    data_staleness: Optional[str] = None  # 数据延迟提示


def get_shop_exchange_rates(db: Session) -> dict:
    """获取所有店铺的汇率配置
    currency 来自 shops 表
    rate 来自 system_settings 表（cny_to_rub），确保汇率调整后销售额同步变化
    """
    from app.models.models import Shop
    from sqlalchemy import text
    # 从系统设置读取人民币兑卢布汇率
    sys_setting = db.execute(text("SELECT value FROM system_settings WHERE `key` = 'cny_to_rub'")).fetchone()
    cny_to_rub = float(sys_setting[0]) if sys_setting and sys_setting[0] else 12.5
    shops = db.query(Shop).filter(Shop.is_active == True).all()
    return {shop.id: {"currency": shop.currency or "RUB", "rate": cny_to_rub} for shop in shops}


def convert_currency(amount: float, to_currency: str, exchange_rate: float) -> float:
    """
    转换金额为卢布显示
    - 存储的是原始金额，根据店铺货币类型进行转换
    - 如果店铺货币是CNY，将人民币转换为卢布（乘以汇率）
    - 如果店铺货币是RUB，直接返回卢布
    """
    if not amount:
        return 0
    
    # 根据店铺货币类型进行转换
    if to_currency == "CNY":
        # 店铺是CNY，存储的是人民币，需要转换为卢布显示（乘以汇率）
        return amount * exchange_rate if exchange_rate else amount
    else:
        # 店铺是RUB，直接返回卢布
        return amount



def _add_data_info(db: Session, stats: DashboardStats) -> DashboardStats:
    """为 stats 添加数据时间信息和延迟提示（使用同步完成时间）"""
    from sqlalchemy import text
    try:
        sync_result = db.execute(text(
            "SELECT finished_at FROM sync_logs WHERE sync_type='ads' AND status='success' ORDER BY finished_at DESC LIMIT 1"
        )).fetchone()
        tz = timezone(timedelta(hours=8))
        if sync_result and sync_result[0]:
            sync_time = sync_result[0]
            if isinstance(sync_time, str):
                sync_time = datetime.strptime(sync_time, "%Y-%m-%d %H:%M:%S.%f")
            if sync_time.tzinfo is None:
                sync_time = sync_time.replace(tzinfo=tz)
            stats.data_updated_at = sync_time.strftime("%Y-%m-%d %H:%M") + " (北京时间)"
            diff_hours = (datetime.now(tz) - sync_time).total_seconds() / 3600
            if diff_hours > 48:
                stats.data_staleness = f"数据已延迟 {int(diff_hours)} 小时，最后同步于 {sync_time.strftime('%m-%d %H:%M')}，请检查同步任务"
            elif diff_hours > 24:
                stats.data_staleness = f"数据更新时间为 {sync_time.strftime('%m-%d %H:%M')}，略有延迟"
        else:
            stats.data_updated_at = "暂无同步记录"
            stats.data_staleness = "尚未从 WB API 同步广告数据"
    except Exception as e:
        stats.data_updated_at = "未知"
    return stats

@router.post("/stats/", response_model=DashboardStats)
def get_dashboard_stats(
    filter_data: DashboardFilter,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取销售看板数据"""
    # 默认显示昨天
    yesterday = datetime.now() - timedelta(days=1)
    
    if filter_data.start_date:
        start_date = datetime.strptime(filter_data.start_date, "%Y-%m-%d")
    else:
        start_date = yesterday
    
    if filter_data.end_date:
        end_date = datetime.strptime(filter_data.end_date, "%Y-%m-%d") + timedelta(days=1)
    else:
        end_date = start_date + timedelta(days=1)
    
    # 计算上一周期（同比）
    period_days = (end_date - start_date).days
    prev_start = start_date - timedelta(days=period_days)
    prev_end = start_date
    
    shop_rates = get_shop_exchange_rates(db)
    
    # 判断筛选条件
    has_shop_filter = filter_data.shop_ids and len(filter_data.shop_ids) > 0
    
    # 自动根据当前用户的allowed_owners进行过滤
    user_allowed_owners = getattr(current_user, 'allowed_owners', None) or []
    if user_allowed_owners:
        # 用户有负责人限制，强制应用
        if filter_data.owners:
            # 合并前端传入的owners和用户的allowed_owners
            filter_data.owners = list(set(filter_data.owners) & set(user_allowed_owners))
        else:
            filter_data.owners = user_allowed_owners
    
    has_owner_filter = filter_data.owners and len(filter_data.owners) > 0
    
    # 获取汇率配置 - 根据筛选条件决定
    if has_shop_filter and len(filter_data.shop_ids) == 1:
        shop_config = shop_rates.get(filter_data.shop_ids[0], {"currency": "RUB", "rate": 12.5})
    else:
        shop_config = {"currency": "RUB", "rate": 12.5}
    
    stats = DashboardStats(currency=shop_config["currency"])
    
    # ==================== 根据筛选条件处理 ====================
    if has_owner_filter:
        # 场景：有负责人筛选
        from app.models.models import Product
        
        # 查询指定负责人对应的产品ID
        products_query = db.query(Product.id).filter(
            Product.owner.in_(filter_data.owners)
        )
        if has_shop_filter:
            products_query = products_query.filter(Product.shop_id.in_(filter_data.shop_ids))
        product_ids = [p[0] for p in products_query.all()]
        
        if not product_ids:
            return stats
        stats = _add_data_info(db, stats)
        
        # 从product_analytics表汇总（销售额、访客、加购、订单）
        ads_query = db.query(AdRecord).filter(
            AdRecord.record_date >= start_date,
            AdRecord.record_date < end_date,
            AdRecord.ad_type == "product_analytics",
            AdRecord.product_id.in_(product_ids)
        )
        if has_shop_filter:
            ads_query = ads_query.filter(AdRecord.shop_id.in_(filter_data.shop_ids))
        
        ads = ads_query.all()
        
        # 从advertising表查询广告费用
        ads_cost_query = db.query(AdRecord).filter(
            AdRecord.record_date >= start_date,
            AdRecord.record_date < end_date,
            AdRecord.ad_type == "advertising",
            AdRecord.product_id.in_(product_ids),
        )
        if has_shop_filter:
            ads_cost_query = ads_cost_query.filter(AdRecord.shop_id.in_(filter_data.shop_ids))

        ads_costs = ads_cost_query.all()

        for ad in ads:
            sales_val = convert_currency(ad.sales or 0, shop_config["currency"], shop_config["rate"])
            stats.sales_amount += sales_val
            stats.visitors += ad.visitors or 0
            stats.add_to_cart += ad.cart_count or 0
            stats.order_count += ad.order_count or 0
        
        # 广告费用
        for ad in ads_costs:
            stats.ad_cost += ad.cost or 0
    else:
        # 场景：无负责人筛选
        # 从analytics表获取店铺级别汇总
        ads_query = db.query(AdRecord).filter(
            AdRecord.record_date >= start_date,
            AdRecord.record_date < end_date,
            AdRecord.ad_type == "product_analytics",
        )
        if has_shop_filter:
            ads_query = ads_query.filter(AdRecord.shop_id.in_(filter_data.shop_ids))
        
        ads = ads_query.all()
        
        # 查询广告费用数据
        ads_cost_query = db.query(AdRecord).filter(
            AdRecord.record_date >= start_date,
            AdRecord.record_date < end_date,
            AdRecord.ad_type == "advertising",
        )
        if has_shop_filter:
            ads_cost_query = ads_cost_query.filter(AdRecord.shop_id.in_(filter_data.shop_ids))

        ads_costs = ads_cost_query.all()

        # 从orders表获取销售额（只按店铺筛选）
        orders_query = db.query(Order).filter(
            Order.order_date >= start_date,
            Order.order_date < end_date
        )
        if has_shop_filter:
            orders_query = orders_query.filter(Order.shop_id.in_(filter_data.shop_ids))
        orders = orders_query.all()
        
        for order in orders:
            order_shop_config = shop_rates.get(order.shop_id, {"currency": "RUB", "rate": 12.5})
            sales_val = convert_currency(order.total_amount, order_shop_config["currency"], order_shop_config["rate"])
            stats.sales_amount += sales_val
        
        for ad in ads:
            stats.visitors += ad.visitors or 0
            stats.add_to_cart += ad.cart_count or 0
            stats.order_count += ad.order_count or 0
        
        # 从广告表获取广告费用
        for ad in ads_costs:
            stats.ad_cost += ad.cost or 0
    
    # 计算转化率等指标
    if stats.visitors > 0:
        stats.add_to_cart_rate = stats.add_to_cart / stats.visitors * 100
    
    if stats.sales_amount > 0:
        stats.ad_ratio = stats.ad_cost / stats.sales_amount
    
    # 从数据库读取预警阈值
    threshold = db.query(MetricThreshold).filter(
        MetricThreshold.metric_name == "ad_ratio",
        MetricThreshold.is_active == True
    ).first()
    
    if threshold:
        if stats.ad_ratio >= (threshold.danger_threshold or 0.05):
            stats.ad_ratio_alert = "danger"
        elif stats.ad_ratio >= (threshold.warning_threshold or 0.03):
            stats.ad_ratio_alert = "warning"
    
    # 设置货币类型
    stats.currency = shop_config["currency"]
    
    # 计算转化率
    if stats.visitors > 0:
        stats.conversion_rate = stats.order_count / stats.visitors * 100
    
    # ===== 计算上一周期数据 =====
    if has_owner_filter:
        # 上一周期也按负责人筛选
        from app.models.models import Product
        
        products_query = db.query(Product.id).filter(
            Product.owner.in_(filter_data.owners)
        )
        if has_shop_filter:
            products_query = products_query.filter(Product.shop_id.in_(filter_data.shop_ids))
        prev_product_ids = [p[0] for p in products_query.all()]
        
        if prev_product_ids:
            prev_ads_query = db.query(AdRecord).filter(
                AdRecord.record_date >= prev_start,
                AdRecord.record_date < prev_end,
                AdRecord.ad_type == "product_analytics",
                AdRecord.product_id.in_(prev_product_ids)
            )
            if has_shop_filter:
                prev_ads_query = prev_ads_query.filter(AdRecord.shop_id.in_(filter_data.shop_ids))
            
            prev_ads = prev_ads_query.all()
            prev_stats = {"sales_amount": 0, "order_count": 0, "visitors": 0, "add_to_cart": 0, "ad_cost": 0}
            for ad in prev_ads:
                prev_stats["sales_amount"] += convert_currency(ad.sales or 0, shop_config["currency"], shop_config["rate"])
                prev_stats["visitors"] += ad.visitors or 0
                prev_stats["add_to_cart"] += ad.cart_count or 0
                prev_stats["order_count"] += ad.order_count or 0
        else:
            prev_stats = {"sales_amount": 0, "order_count": 0, "visitors": 0, "add_to_cart": 0, "ad_cost": 0}
    else:
        # 上一周期无负责人筛选
        prev_ads_query = db.query(AdRecord).filter(
            AdRecord.record_date >= prev_start,
            AdRecord.record_date < prev_end,
            AdRecord.ad_type == "product_analytics",
        )
        if has_shop_filter:
            prev_ads_query = prev_ads_query.filter(AdRecord.shop_id.in_(filter_data.shop_ids))
        
        prev_ads = prev_ads_query.all()
        prev_stats = {"sales_amount": 0, "order_count": 0, "visitors": 0, "add_to_cart": 0, "ad_cost": 0}
        
        # 从orders表获取上一周期销售额
        prev_orders_query = db.query(Order).filter(
            Order.order_date >= prev_start,
            Order.order_date < prev_end
        )
        if has_shop_filter:
            prev_orders_query = prev_orders_query.filter(Order.shop_id.in_(filter_data.shop_ids))
        prev_orders = prev_orders_query.all()
        
        for order in prev_orders:
            order_shop_config = shop_rates.get(order.shop_id, {"currency": "RUB", "rate": 12.5})
            prev_stats["sales_amount"] += convert_currency(order.total_amount, order_shop_config["currency"], order_shop_config["rate"])
        
        for ad in prev_ads:
            prev_stats["visitors"] += ad.visitors or 0
            prev_stats["add_to_cart"] += ad.cart_count or 0
            prev_stats["order_count"] += ad.order_count or 0
        
        # 从advertising表获取上一周期广告费用
        prev_ads_cost_query = db.query(AdRecord).filter(
            AdRecord.record_date >= prev_start,
            AdRecord.record_date < prev_end,
            AdRecord.ad_type == "advertising",
            AdRecord.product_id.in_(prev_product_ids),
        )
        if has_shop_filter:
            prev_ads_cost_query = prev_ads_cost_query.filter(AdRecord.shop_id.in_(filter_data.shop_ids))

        prev_ads_costs = prev_ads_cost_query.all()
        for ad in prev_ads_costs:
            prev_stats["ad_cost"] += ad.cost or 0

    # 计算同比百分比
    def calc_percent(current, previous):
        if previous == 0:
            return None if current == 0 else 100.0
        return (current - previous) / previous * 100
    
    stats.comparison = {
        "sales_amount": calc_percent(stats.sales_amount, prev_stats["sales_amount"]),
        "order_count": calc_percent(stats.order_count, prev_stats["order_count"]),
        "visitors": calc_percent(stats.visitors, prev_stats["visitors"]),
        "add_to_cart": calc_percent(stats.add_to_cart, prev_stats["add_to_cart"]),
        "add_to_cart_rate": calc_percent(
            stats.add_to_cart_rate, 
            prev_stats["visitors"] > 0 and (prev_stats["add_to_cart"] / prev_stats["visitors"] * 100) or 0
        ),
        "conversion_rate": calc_percent(
            stats.conversion_rate,
            prev_stats["visitors"] > 0 and (prev_stats["order_count"] / prev_stats["visitors"] * 100) or 0
        ),
        "ad_cost": calc_percent(stats.ad_cost, prev_stats["ad_cost"]),
        "ad_ratio": calc_percent(
            stats.ad_ratio * 100,
            prev_stats["sales_amount"] > 0 and (prev_stats["ad_cost"] / prev_stats["sales_amount"] * 100) or 0
        )
    }
    
    return stats


@router.post("/products/")
def get_dashboard_products(
    filter_data: DashboardFilter,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取产品销售列表（按产品分组的销售数据，含汇总和环比）"""
    from app.models.models import Product, AdRecord
    
    yesterday = datetime.now() - timedelta(days=1)
    
    if filter_data.start_date:
        start_date = datetime.strptime(filter_data.start_date, "%Y-%m-%d")
    else:
        start_date = yesterday
    
    if filter_data.end_date:
        end_date = datetime.strptime(filter_data.end_date, "%Y-%m-%d") + timedelta(days=1)
    else:
        end_date = start_date + timedelta(days=1)
    
    period_days = (end_date - start_date).days
    prev_start = start_date - timedelta(days=period_days)
    prev_end = start_date
    
    has_shop_filter = filter_data.shop_ids and len(filter_data.shop_ids) > 0
    
    # 自动根据当前用户的allowed_owners进行过滤
    user_allowed_owners = getattr(current_user, 'allowed_owners', None) or []
    if user_allowed_owners:
        if filter_data.owners:
            filter_data.owners = list(set(filter_data.owners) & set(user_allowed_owners))
        else:
            filter_data.owners = user_allowed_owners
    
    has_owner_filter = filter_data.owners and len(filter_data.owners) > 0
    
    products_query = db.query(Product).filter(Product.nm_id != "0")
    if has_shop_filter:
        products_query = products_query.filter(Product.shop_id.in_(filter_data.shop_ids))
    if filter_data.product_ids:
        products_query = products_query.filter(Product.id.in_(filter_data.product_ids))
    if filter_data.product_name:
        products_query = products_query.filter(
            (Product.custom_name == filter_data.product_name) | (Product.name == filter_data.product_name)
        )
    if has_owner_filter:
        products_query = products_query.filter(Product.owner.in_(filter_data.owners))
    products = products_query.all()
    
    product_ids = [p.id for p in products]
    
    if not product_ids:
        return {"items": [], "summary": {}, "comparison": {}}
    
    shop_rates = get_shop_exchange_rates(db)
    
    # 获取当前周期 product_analytics 数据
    current_ads = db.query(AdRecord).filter(
        AdRecord.record_date >= start_date,
        AdRecord.record_date < end_date,
        AdRecord.ad_type == "product_analytics",
        AdRecord.product_id.in_(product_ids)
    ).all()
    
    # 按产品聚合
    product_stats = {}
    for ad in current_ads:
        if ad.product_id not in product_stats:
            product_stats[ad.product_id] = {"sales": 0, "visitors": 0, "cart": 0, "orders": 0}
        product_stats[ad.product_id]["sales"] += ad.sales or 0
        product_stats[ad.product_id]["visitors"] += ad.visitors or 0
        product_stats[ad.product_id]["cart"] += ad.cart_count or 0
        product_stats[ad.product_id]["orders"] += ad.order_count or 0
    
    # 获取当前周期广告费用
    current_ads_costs = db.query(AdRecord).filter(
        AdRecord.record_date >= start_date,
        AdRecord.record_date < end_date,
        AdRecord.ad_type == "advertising",
        AdRecord.product_id.in_(product_ids),
    ).all()
    
    ad_costs = {}
    for ad in current_ads_costs:
        if ad.product_id not in ad_costs:
            ad_costs[ad.product_id] = 0
        ad_costs[ad.product_id] += ad.cost or 0
    
    # 获取上一周期 product_analytics 数据
    prev_ads = db.query(AdRecord).filter(
        AdRecord.record_date >= prev_start,
        AdRecord.record_date < prev_end,
        AdRecord.ad_type == "product_analytics",
        AdRecord.product_id.in_(product_ids)
    ).all()
    
    prev_stats = {}
    for ad in prev_ads:
        if ad.product_id not in prev_stats:
            prev_stats[ad.product_id] = {"sales": 0, "visitors": 0, "cart": 0, "orders": 0}
        prev_stats[ad.product_id]["sales"] += ad.sales or 0
        prev_stats[ad.product_id]["visitors"] += ad.visitors or 0
        prev_stats[ad.product_id]["cart"] += ad.cart_count or 0
        prev_stats[ad.product_id]["orders"] += ad.order_count or 0
    
    # 获取上一周期广告费用
    prev_ads_costs = db.query(AdRecord).filter(
        AdRecord.record_date >= prev_start,
        AdRecord.record_date < prev_end,
        AdRecord.ad_type == "advertising",
        AdRecord.product_id.in_(product_ids),
    ).all()
    
    prev_ad_costs = {}
    for ad in prev_ads_costs:
        if ad.product_id not in prev_ad_costs:
            prev_ad_costs[ad.product_id] = 0
        prev_ad_costs[ad.product_id] += ad.cost or 0
    
    # 构建返回数据
    items = []
    total_sales = 0
    total_visitors = 0
    total_cart = 0
    total_orders = 0
    total_ad_cost = 0
    total_prev_sales = 0
    total_prev_visitors = 0
    total_prev_cart = 0
    total_prev_orders = 0
    total_prev_ad_cost = 0
    
    # 获取所有相关店铺信息
    shop_ids = list(set([p.shop_id for p in products]))
    from app.models.models import Shop
    shops_map = {s.id: s for s in db.query(Shop).filter(Shop.id.in_(shop_ids)).all()}
    
    for product in products:
        pdata = product_stats.get(product.id, {"sales": 0, "visitors": 0, "cart": 0, "orders": 0})
        prev_data = prev_stats.get(product.id, {"sales": 0, "visitors": 0, "cart": 0, "orders": 0})
        
        shop_config = shop_rates.get(product.shop_id, {"currency": "RUB", "rate": 12.5})
        sales = convert_currency(pdata["sales"], shop_config["currency"], shop_config["rate"])
        prev_sales = convert_currency(prev_data["sales"], shop_config["currency"], shop_config["rate"])
        
        # 计算产品级别的比率
        cart_rate = round(pdata["cart"] / pdata["visitors"] * 100, 2) if pdata["visitors"] > 0 else 0
        conversion_rate = round(pdata["orders"] / pdata["visitors"] * 100, 2) if pdata["visitors"] > 0 else 0
        ad_ratio = round(ad_costs.get(product.id, 0) / sales * 100, 2) if sales > 0 else 0
        
        items.append({
            "product_id": product.id,
            "nm_id": product.nm_id,
            "sku": product.sku,
            "product_name": product.custom_name or product.name,
            "shop_id": product.shop_id,
            "shop_name": shops_map.get(product.shop_id, Shop()).name if shops_map.get(product.shop_id) else "",
            "owner": product.owner or "",
            "sales": sales,
            "visitors": pdata["visitors"],
            "add_to_cart": pdata["cart"],
            "cart_rate": cart_rate,
            "orders": pdata["orders"],
            "conversion_rate": conversion_rate,
            "ad_cost": ad_costs.get(product.id, 0),
            "ad_ratio": ad_ratio,
            "prev_sales": prev_sales,
            "prev_visitors": prev_data["visitors"],
            "prev_cart": prev_data["cart"],
            "prev_orders": prev_data["orders"],
            "prev_ad_cost": prev_ad_costs.get(product.id, 0),
        })
        
        total_sales += sales
        total_visitors += pdata["visitors"]
        total_cart += pdata["cart"]
        total_orders += pdata["orders"]
        total_ad_cost += ad_costs.get(product.id, 0)
        total_prev_sales += prev_sales
        total_prev_visitors += prev_data["visitors"]
        total_prev_cart += prev_data["cart"]
        total_prev_orders += prev_data["orders"]
        total_prev_ad_cost += prev_ad_costs.get(product.id, 0)
    
    # 计算比率
    def calc_cart_rate(cart, visitors):
        return round(cart / visitors * 100, 2) if visitors > 0 else 0
    
    def calc_conv_rate(orders, visitors):
        return round(orders / visitors * 100, 2) if visitors > 0 else 0
    
    def calc_ad_ratio(ad_cost, sales):
        return round(ad_cost / sales * 100, 2) if sales > 0 else 0
    
    avg_cart_rate = calc_cart_rate(total_cart, total_visitors)
    avg_conv_rate = calc_conv_rate(total_orders, total_visitors)
    avg_ad_ratio = calc_ad_ratio(total_ad_cost, total_sales)
    
    prev_cart_rate = calc_cart_rate(total_prev_cart, total_prev_visitors)
    prev_conv_rate = calc_conv_rate(total_prev_orders, total_prev_visitors)
    prev_ad_ratio = calc_ad_ratio(total_prev_ad_cost, total_prev_sales)
    
    summary = {
        "sales_amount": total_sales,
        "visitors": total_visitors,
        "add_to_cart": total_cart,
        "order_count": total_orders,
        "ad_cost": total_ad_cost,
        "add_to_cart_rate": avg_cart_rate,
        "conversion_rate": avg_conv_rate,
        "ad_ratio": avg_ad_ratio,
    }
    
    # 计算环比百分比
    def pct_change(current, prev):
        return round((current - prev) / prev * 100, 1) if prev > 0 else 0
    
    comparison = {
        "sales_amount": pct_change(total_sales, total_prev_sales),
        "visitors": pct_change(total_visitors, total_prev_visitors),
        "add_to_cart": pct_change(total_cart, total_prev_cart),
        "order_count": pct_change(total_orders, total_prev_orders),
        "ad_cost": pct_change(total_ad_cost, total_prev_ad_cost),
        "add_to_cart_rate": round(avg_cart_rate - prev_cart_rate, 2),
        "conversion_rate": round(avg_conv_rate - prev_conv_rate, 2),
        "ad_ratio": round(avg_ad_ratio - prev_ad_ratio, 2),
    }
    
    # 数据时间信息 - 使用同步完成时间（从sync_logs）
    try:
        from sqlalchemy import text
        tz = timezone(timedelta(hours=8))
        # 查找最近一次成功的广告同步
        sync_result = db.execute(text(
            "SELECT finished_at FROM sync_logs WHERE sync_type='ads' AND status='success' ORDER BY finished_at DESC LIMIT 1"
        )).fetchone()
        if sync_result and sync_result[0]:
            sync_time = sync_result[0]
            if isinstance(sync_time, str):
                sync_time = datetime.strptime(sync_time, "%Y-%m-%d %H:%M:%S.%f")
            sync_time = sync_time.replace(tzinfo=tz) if sync_time.tzinfo is None else sync_time
            diff = (datetime.now(tz) - sync_time).total_seconds() / 3600
            summary["data_updated_at"] = sync_time.strftime("%Y-%m-%d %H:%M") + " (北京时间)"
            if diff > 48:
                summary["data_staleness"] = f"数据已延迟 {int(diff)} 小时，最后同步于 {sync_time.strftime('%m-%d %H:%M')}，请检查同步任务"
            elif diff > 24:
                summary["data_staleness"] = f"数据更新时间为 {sync_time.strftime('%m-%d %H:%M')}，略有延迟"
        else:
            summary["data_updated_at"] = "暂无同步记录"
            summary["data_staleness"] = "尚未从 WB API 同步广告数据"
    except:
        pass
    
    return {"items": items, "summary": summary, "comparison": comparison}




@router.post("/trend/")
def get_sales_trend(
    filter_data: DashboardFilter,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取销售趋势 - 从product_analytics获取销售额、订单数、访客、加购"""
    if filter_data.start_date:
        start_date = datetime.strptime(filter_data.start_date, "%Y-%m-%d")
    else:
        start_date = datetime.now() - timedelta(days=30)
    
    if filter_data.end_date:
        end_date = datetime.strptime(filter_data.end_date, "%Y-%m-%d") + timedelta(days=1)
    else:
        end_date = datetime.now() + timedelta(days=1)
    
    shop_rates = get_shop_exchange_rates(db)
    
    # 查询product_analytics数据（销售额、订单、访客、加购）
    product_analytics_query = db.query(AdRecord).filter(
        AdRecord.record_date >= start_date,
        AdRecord.record_date < end_date,
        AdRecord.ad_type == "product_analytics"
    )
    if filter_data.shop_ids:
        product_analytics_query = product_analytics_query.filter(AdRecord.shop_id.in_(filter_data.shop_ids))
    if filter_data.product_ids:
        product_analytics_query = product_analytics_query.filter(AdRecord.product_id.in_(filter_data.product_ids))
    
    product_analytics = product_analytics_query.all()
    
    # 查询广告费用数据
    ads_cost_query = db.query(AdRecord).filter(
        AdRecord.record_date >= start_date,
        AdRecord.record_date < end_date,
        AdRecord.ad_type == "advertising",
    )
    if filter_data.shop_ids:
        ads_cost_query = ads_cost_query.filter(AdRecord.shop_id.in_(filter_data.shop_ids))
    if filter_data.product_ids:
        ads_cost_query = ads_cost_query.filter(AdRecord.product_id.in_(filter_data.product_ids))
    
    ads_costs = ads_cost_query.all()
    
    # 按日期汇总
    daily_data = {}
    
    # 从product_analytics获取销售、订单、访客、加购
    for ad in product_analytics:
        date_str = ad.record_date.strftime("%Y-%m-%d") if ad.record_date else "unknown"
        if date_str not in daily_data:
            daily_data[date_str] = {"sales": 0, "visitors": 0, "cart": 0, "orders": 0, "ad_cost": 0}
        
        shop_config = shop_rates.get(ad.shop_id, {"currency": "RUB", "rate": 12.5})
        sales_val = convert_currency(ad.sales or 0, shop_config["currency"], shop_config["rate"])
        daily_data[date_str]["sales"] += sales_val
        daily_data[date_str]["visitors"] += ad.visitors or 0
        daily_data[date_str]["cart"] += ad.cart_count or 0
        daily_data[date_str]["orders"] += ad.order_count or 0
    
    # 从广告数据获取广告费用
    for ad in ads_costs:
        date_str = ad.record_date.strftime("%Y-%m-%d") if ad.record_date else "unknown"
        if date_str not in daily_data:
            daily_data[date_str] = {"sales": 0, "visitors": 0, "cart": 0, "orders": 0, "ad_cost": 0}
        daily_data[date_str]["ad_cost"] += ad.cost or 0
    
    return [{"date": d, **data} for d, data in sorted(daily_data.items())]


@router.get("/owners/")
def get_owners(
    shop_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取产品负责人（根据当前用户权限过滤）"""
    query = db.query(Product.owner).filter(Product.owner != None, Product.owner != "")
    
    # 根据当前用户的 allowed_owners 进行过滤
    user_allowed_owners = getattr(current_user, 'allowed_owners', None) or []
    if user_allowed_owners:
        query = query.filter(Product.owner.in_(user_allowed_owners))
    
    if shop_id:
        query = query.filter(Product.shop_id == shop_id)
    owners = query.distinct().all()
    return [o[0] for o in owners if o[0]]


class ComparisonData(BaseModel):
    sales_amount: Optional[float] = None
    order_count: Optional[float] = None
    visitors: Optional[float] = None
    add_to_cart: Optional[float] = None
    add_to_cart_rate: Optional[float] = None
    conversion_rate: Optional[float] = None
    ad_cost: Optional[float] = None
    ad_ratio: Optional[float] = None


def get_stats_for_period(db: Session, start_date: datetime, end_date: datetime, shop_ids: List[int] = None) -> dict:
    """获取指定时间段的统计数据"""
    shop_rates = get_shop_exchange_rates(db)
    
    query = db.query(Order).filter(
        Order.order_date >= start_date,
        Order.order_date <= end_date
    )
    
    if shop_ids:
        query = query.filter(Order.shop_id.in_(shop_ids))
    
    orders = query.all()
    
    stats = {
        "sales_amount": 0,
        "order_count": 0,
        "ad_cost": 0
    }
    
    for order in orders:
        shop_config = shop_rates.get(order.shop_id, {"currency": "RUB", "rate": 12.5})
        stats["sales_amount"] += convert_currency(order.total_amount, shop_config["currency"], shop_config["rate"])
        # 销售额需要汇率转换；广告费来自 ad_records 表（卢布，无需转换）
        stats["order_count"] += 1
    
    # 广告数据 - 访客和加购（从analytics表）
    ads_query = db.query(AdRecord).filter(
        AdRecord.record_date >= start_date,
        AdRecord.record_date <= end_date,
        AdRecord.ad_type == "product_analytics",
    )
    if shop_ids:
        ads_query = ads_query.filter(AdRecord.shop_id.in_(shop_ids))
    
    ads = ads_query.all()
    stats["visitors"] = sum(ad.visitors or 0 for ad in ads)
    stats["add_to_cart"] = sum(ad.cart_count or 0 for ad in ads)
    
    # 广告费用（从advertising表）
    ads_cost_query = db.query(AdRecord).filter(
        AdRecord.record_date >= start_date,
        AdRecord.record_date <= end_date,
        AdRecord.ad_type == "advertising",
    )
    if shop_ids:
        ads_cost_query = ads_cost_query.filter(AdRecord.shop_id.in_(shop_ids))
    
    ads_costs = ads_cost_query.all()
    stats["ad_cost"] = sum(ad.cost or 0 for ad in ads_costs)
    
    if stats["visitors"] > 0:
        stats["add_to_cart_rate"] = stats["add_to_cart"] / stats["visitors"] * 100
        stats["conversion_rate"] = stats["order_count"] / stats["visitors"] * 100
    
    if stats["sales_amount"] > 0:
        stats["ad_ratio"] = stats["ad_cost"] / stats["sales_amount"]
    
    return stats


def calculate_change(current: float, previous: float) -> float:
    """计算变化百分比"""
    if not previous or previous == 0:
        return None
    return ((current - previous) / previous) * 100


@router.post("/comparison/", response_model=ComparisonData)
def get_comparison(
    filter_data: DashboardFilter,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取环比数据（与上一个时间段对比）"""
    if not filter_data.start_date or not filter_data.end_date:
        return ComparisonData()
    
    start_date = datetime.strptime(filter_data.start_date, "%Y-%m-%d")
    end_date = datetime.strptime(filter_data.end_date, "%Y-%m-%d")
    
    period_days = (end_date - start_date).days + 1
    
    # 上一周期
    prev_start = start_date - timedelta(days=period_days)
    prev_end = start_date - timedelta(days=1)
    
    current_stats = get_stats_for_period(db, start_date, end_date + timedelta(days=1), filter_data.shop_ids)
    prev_stats = get_stats_for_period(db, prev_start, prev_end + timedelta(days=1), filter_data.shop_ids)
    
    return ComparisonData(
        sales_amount=calculate_change(current_stats.get("sales_amount", 0), prev_stats.get("sales_amount", 0)),
        order_count=calculate_change(current_stats.get("order_count", 0), prev_stats.get("order_count", 0)),
        visitors=calculate_change(current_stats.get("visitors", 0), prev_stats.get("visitors", 0)),
        add_to_cart=calculate_change(current_stats.get("add_to_cart", 0), prev_stats.get("add_to_cart", 0)),
        add_to_cart_rate=calculate_change(current_stats.get("add_to_cart_rate", 0), prev_stats.get("add_to_cart_rate", 0)),
        conversion_rate=calculate_change(current_stats.get("conversion_rate", 0), prev_stats.get("conversion_rate", 0)),
        ad_cost=calculate_change(current_stats.get("ad_cost", 0), prev_stats.get("ad_cost", 0)),
        ad_ratio=calculate_change(current_stats.get("ad_ratio", 0), prev_stats.get("ad_ratio", 0))
    )


@router.post("/by-owner/")
def get_stats_by_owner(
    filter_data: DashboardFilter,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """按负责人统计销售数据"""
    if filter_data.start_date:
        start_date = datetime.strptime(filter_data.start_date, "%Y-%m-%d")
    else:
        start_date = datetime.now() - timedelta(days=7)
    
    if filter_data.end_date:
        end_date = datetime.strptime(filter_data.end_date, "%Y-%m-%d") + timedelta(days=1)
    else:
        end_date = datetime.now() + timedelta(days=1)
    
    shop_rates = get_shop_exchange_rates(db)
    
    # 获取产品-负责人映射
    products = db.query(Product).filter(Product.owner != None, Product.owner != "")
    if filter_data.shop_ids:
        products = products.filter(Product.shop_id.in_(filter_data.shop_ids))
    if filter_data.owners:
        products = products.filter(Product.owner.in_(filter_data.owners))
    
    products = products.all()
    
    # 按负责人汇总
    owner_stats = {}
    for product in products:
        owner = product.owner
        if not owner:
            continue
        
        if owner not in owner_stats:
            owner_stats[owner] = {
                "owner": owner,
                "sales": 0,
                "orders": 0,
                "visitors": 0,
                "add_to_cart": 0,
                "ad_cost": 0
            }
        
        # 从ad_records获取该产品的数据
        ad_records = db.query(AdRecord).filter(
            AdRecord.product_id == product.id,
            AdRecord.record_date >= start_date,
            AdRecord.record_date < end_date
        ).all()
        
        for ad in ad_records:
            shop_config = shop_rates.get(product.shop_id, {"currency": "RUB", "rate": 12.5})
            owner_stats[owner]["sales"] += convert_currency(ad.sales or 0, shop_config["currency"], shop_config["rate"])
            owner_stats[owner]["orders"] += ad.order_count or 0
            owner_stats[owner]["visitors"] += ad.visitors or 0
            owner_stats[owner]["add_to_cart"] += ad.cart_count or 0
            owner_stats[owner]["ad_cost"] += ad.cost or 0
    
    return list(owner_stats.values())
