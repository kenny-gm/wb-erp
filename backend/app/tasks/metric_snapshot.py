from datetime import datetime, timedelta
from sqlalchemy import func
from app.database import SessionLocal
from app.models.models import Product, Order, OrderItem, AdRecord, MetricHistory, Shop
from zoneinfo import ZoneInfo

def daily_metric_snapshot():
    db = SessionLocal()
    try:
        target_date = (datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"开始生成 {target_date} 的指标快照...")
        
        products = db.query(Product).all()
        for product in products:
            # 销售数据
            sales_stats = db.query(
                func.coalesce(func.sum(Order.total_amount), 0).label("sales"),
                func.coalesce(func.count(func.distinct(Order.id)), 0).label("orders")
            ).join(OrderItem).filter(
                OrderItem.product_id == product.id,
                func.date(Order.order_date) == target_date
            ).first()
            
            # 广告数据
            ad_stats = db.query(
                func.coalesce(func.sum(AdRecord.impressions), 0).label("impressions"),
                func.coalesce(func.sum(AdRecord.visitors), 0).label("clicks"),
                func.coalesce(func.sum(AdRecord.cost), 0).label("cost"),
                func.coalesce(func.sum(AdRecord.sales), 0).label("ad_sales")
            ).filter(
                AdRecord.product_id == product.id,
                func.date(AdRecord.record_date) == target_date
            ).first()
            
            # 访客、加购（从analytics类型获取）
            analytics = db.query(AdRecord).filter(
                AdRecord.product_id == product.id,
                AdRecord.ad_type == "product_analytics",
                func.date(AdRecord.record_date) == target_date
            ).first()
            
            visitors = analytics.impressions if analytics else 0
            add_to_cart = analytics.visitors if analytics else 0
            sales = float(sales_stats.sales) if sales_stats else 0
            orders = int(sales_stats.order_count) if sales_stats else 0
            ad_cost = float(ad_stats.cost) if ad_stats else 0
            ad_sales = float(ad_stats.ad_sales) if ad_stats else 0
            
            cart_rate = (add_to_cart / visitors * 100) if visitors > 0 else 0
            conversion_rate = (orders / visitors * 100) if visitors > 0 else 0
            roas = (ad_sales / ad_cost) if ad_cost > 0 else 0
            acos = (ad_cost / ad_sales * 100) if ad_sales > 0 else 0
            ad_ratio = (ad_cost / sales * 100) if sales > 0 else 0
            
            snapshot = MetricHistory(
                product_id=product.id,
                shop_id=product.shop_id,
                date=target_date,
                visitors=visitors,
                add_to_cart=add_to_cart,
                orders=orders,
                sales=sales,
                ad_impressions=int(ad_stats.impressions) if ad_stats else 0,
                ad_clicks=int(ad_stats.visitors) if ad_stats else 0,
                ad_cost=ad_cost,
                ad_sales=ad_sales,
                cart_rate=cart_rate,
                conversion_rate=conversion_rate,
                roas=roas,
                acos=acos,
                ad_ratio=ad_ratio
            )
            db.add(snapshot)
        
        db.commit()
        print(f"指标快照生成完成，共处理 {len(products)} 个产品")
    except Exception as e:
        print(f"生成指标快照失败: {e}")
        db.rollback()
    finally:
        db.close()
