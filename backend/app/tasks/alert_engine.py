from datetime import datetime, timedelta
from app.database import SessionLocal
from app.models.models import MetricHistory, Product, Alert, AlertRule, User
from zoneinfo import ZoneInfo

def run_alert_engine():
    db = SessionLocal()
    try:
        yesterday = (datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"开始执行预警引擎检查 {yesterday}...")
        
        rules = db.query(AlertRule).filter(AlertRule.is_active == True).all()
        for rule in rules:
            if rule.rule_type == "acos":
                check_acos(rule, yesterday, db)
            elif rule.rule_type == "profit":
                check_profit(rule, yesterday, db)
            elif rule.rule_type == "conversion":
                check_conversion(rule, yesterday, db)
            elif rule.rule_type == "cart_rate":
                check_cart_rate(rule, yesterday, db)
            elif rule.rule_type == "ad_ratio":
                check_ad_ratio(rule, yesterday, db)
        
        db.commit()
        print("预警引擎执行完成")
    except Exception as e:
        print(f"预警引擎执行失败: {e}")
        db.rollback()
    finally:
        db.close()

def check_acos(rule, yesterday, db):
    threshold = rule.condition.get("threshold", 8) if rule.condition else 8
    metrics = db.query(MetricHistory).filter(
        MetricHistory.date == yesterday,
        MetricHistory.acos > threshold
    ).all()
    
    for m in metrics:
        product = db.query(Product).filter(Product.id == m.product_id).first()
        if not product or not product.owner:
            continue
        user = db.query(User).filter(User.username == product.owner).first()
        if not user:
            continue
        
        existing = db.query(Alert).filter(
            Alert.product_id == m.product_id,
            Alert.alert_type == "acos",
            Alert.is_resolved == False
        ).first()
        if existing:
            continue
        
        alert = Alert(
            user_id=user.id,
            product_id=m.product_id,
            alert_type="acos",
            title=f"ACOS过高预警 - {product.name}",
            content=f"昨日ACOS为 {m.acos:.1f}%，高于目标值 {threshold}%",
            severity=rule.severity,
            metric_snapshot={
                "acos": m.acos,
                "ad_cost": m.ad_cost,
                "ad_sales": m.ad_sales,
                "date": yesterday
            }
        )
        db.add(alert)

def check_profit(rule, yesterday, db):
    metrics = db.query(MetricHistory).filter(
        MetricHistory.date == yesterday,
        MetricHistory.profit < 0
    ).all()
    
    for m in metrics:
        product = db.query(Product).filter(Product.id == m.product_id).first()
        if not product or not product.owner:
            continue
        user = db.query(User).filter(User.username == product.owner).first()
        if not user:
            continue
        
        existing = db.query(Alert).filter(
            Alert.product_id == m.product_id,
            Alert.alert_type == "profit",
            Alert.is_resolved == False
        ).first()
        if existing:
            continue
        
        alert = Alert(
            user_id=user.id,
            product_id=m.product_id,
            alert_type="profit",
            title=f"利润亏损预警 - {product.name}",
            content=f"昨日利润为 {m.profit:.2f} RUB，处于亏损状态",
            severity=rule.severity,
            metric_snapshot={
                "profit": m.profit,
                "profit_margin": m.profit_margin,
                "sales": m.sales,
                "date": yesterday
            }
        )
        db.add(alert)

def check_conversion(rule, yesterday, db):
    threshold = rule.condition.get("threshold", 1) if rule.condition else 1
    metrics = db.query(MetricHistory).filter(
        MetricHistory.date == yesterday,
        MetricHistory.conversion_rate < threshold
    ).all()
    
    for m in metrics:
        product = db.query(Product).filter(Product.id == m.product_id).first()
        if not product or not product.owner:
            continue
        user = db.query(User).filter(User.username == product.owner).first()
        if not user:
            continue
        
        existing = db.query(Alert).filter(
            Alert.product_id == m.product_id,
            Alert.alert_type == "conversion",
            Alert.is_resolved == False
        ).first()
        if existing:
            continue
        
        alert = Alert(
            user_id=user.id,
            product_id=m.product_id,
            alert_type="conversion",
            title=f"转化率过低预警 - {product.name}",
            content=f"昨日转化率为 {m.conversion_rate:.2f}%，低于目标值 {threshold}%",
            severity=rule.severity,
            metric_snapshot={
                "conversion_rate": m.conversion_rate,
                "visitors": m.visitors,
                "orders": m.order_count,
                "date": yesterday
            }
        )
        db.add(alert)

def check_cart_rate(rule, yesterday, db):
    cart_threshold = rule.condition.get("cart_rate_threshold", 10) if rule.condition else 10
    conv_threshold = rule.condition.get("conversion_threshold", 1.5) if rule.condition else 1.5
    
    metrics = db.query(MetricHistory).filter(
        MetricHistory.date == yesterday,
        MetricHistory.cart_rate > cart_threshold,
        MetricHistory.conversion_rate < conv_threshold
    ).all()
    
    for m in metrics:
        product = db.query(Product).filter(Product.id == m.product_id).first()
        if not product or not product.owner:
            continue
        user = db.query(User).filter(User.username == product.owner).first()
        if not user:
            continue
        
        existing = db.query(Alert).filter(
            Alert.product_id == m.product_id,
            Alert.alert_type == "cart_rate",
            Alert.is_resolved == False
        ).first()
        if existing:
            continue
        
        alert = Alert(
            user_id=user.id,
            product_id=m.product_id,
            alert_type="cart_rate",
            title=f"加购率高但转化低 - {product.name}",
            content=f"昨日加购率 {m.cart_rate:.1f}% 但转化率仅 {m.conversion_rate:.2f}%，建议优化购物车流程",
            severity=rule.severity,
            metric_snapshot={
                "cart_rate": m.cart_rate,
                "conversion_rate": m.conversion_rate,
                "visitors": m.visitors,
                "cart_count": m.cart_count,
                "orders": m.order_count,
                "date": yesterday
            }
        )
        db.add(alert)

def check_ad_ratio(rule, yesterday, db):
    threshold = rule.condition.get("threshold", 10) if rule.condition else 10
    metrics = db.query(MetricHistory).filter(
        MetricHistory.date == yesterday,
        MetricHistory.ad_ratio > threshold
    ).all()
    
    for m in metrics:
        product = db.query(Product).filter(Product.id == m.product_id).first()
        if not product or not product.owner:
            continue
        user = db.query(User).filter(User.username == product.owner).first()
        if not user:
            continue
        
        existing = db.query(Alert).filter(
            Alert.product_id == m.product_id,
            Alert.alert_type == "ad_ratio",
            Alert.is_resolved == False
        ).first()
        if existing:
            continue
        
        alert = Alert(
            user_id=user.id,
            product_id=m.product_id,
            alert_type="ad_ratio",
            title=f"广告费占比过高 - {product.name}",
            content=f"昨日广告费占销售额 {m.ad_ratio:.1f}%，高于目标值 {threshold}%",
            severity=rule.severity,
            metric_snapshot={
                "ad_ratio": m.ad_ratio,
                "ad_cost": m.ad_cost,
                "sales": m.sales,
                "date": yesterday
            }
        )
        db.add(alert)
