"""
数据库模型
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Date, Text, ForeignKey, Enum as SQLEnum, JSON, Index
from sqlalchemy.orm import relationship
from app.database import Base
import enum


class UserRole(str, enum.Enum):
    ADMIN = "admin"      # 管理员
    FINANCE = "finance"  # 财务
    MANAGER = "manager"  # 经理
    STAFF = "staff"      # 员工


class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), default=UserRole.STAFF)
    is_active = Column(Boolean, default=False)
    # 权限配置
    allowed_menus = Column(JSON, default=list)  # 可访问的菜单key列表
    allowed_owners = Column(JSON, default=list)  # 可查看的负责人列表
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    updated_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")), onupdate=lambda ctx: datetime.now(ZoneInfo("Asia/Shanghai")))
    
    # 关系
    product_permissions = relationship("ProductPermission", back_populates="user")
    operation_logs = relationship("OperationLog", back_populates="user")
    alerts = relationship("Alert", back_populates="user")


class Shop(Base):
    """店铺表"""
    __tablename__ = "shops"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    api_token = Column(String(500), nullable=False)
    currency = Column(String(10), default="RUB")  # RUB/CNY
    exchange_rate = Column(Float, default=12.5)  # 汇率 (CNY/RUB)
    sync_enabled = Column(Boolean, default=True)
    sync_interval_hours = Column(Integer, default=24)
    last_sync_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    updated_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")), onupdate=lambda ctx: datetime.now(ZoneInfo("Asia/Shanghai")))
    
    # 扩展字段
    vat_rate = Column(Float, default=0.19)  # 增值税税率
    withdrawal_fee = Column(Float, default=0.01)  # 提现手续费率
    warehouse_factor = Column(Float, default=1.0)  # 仓库系数
    localization_index = Column(Float, default=1.0)  # 本地化指数
    delivery_first_liter = Column(Float, default=0)  # 首升配送费
    delivery_first_liter_currency = Column(String(10), default="RUB")
    delivery_per_liter = Column(Float, default=0)  # 每升续费
    delivery_per_liter_currency = Column(String(10), default="RUB")
    warehouse_fee_tiers = Column(Text, default="[]")  # 仓库费层级 JSON
    warehouse_fee_currency = Column(String(10), default="RUB")
    
    # 关系
    products = relationship("Product", back_populates="shop")
    orders = relationship("Order", back_populates="shop")


class Product(Base):
    """产品表"""
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    nm_id = Column(String(50), unique=True, index=True, nullable=False)
    sku = Column(String(100), nullable=False)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    
    name = Column(String(500))
    custom_name = Column(String(500), nullable=True)
    owner = Column(String(100), nullable=True)
    weight = Column(Float, nullable=True)
    length = Column(Float, nullable=True)
    width = Column(Float, nullable=True)
    height = Column(Float, nullable=True)
    purchase_price = Column(Float, nullable=True, comment="采购价(CNY)")
    shipping_price = Column(Float, nullable=True, comment="头程单价(CNY)")
    
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    updated_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")), onupdate=lambda ctx: datetime.now(ZoneInfo("Asia/Shanghai")))
    
    # 关系
    shop = relationship("Shop", back_populates="products")
    inventory_records = relationship("InventoryRecord", back_populates="product")
    order_items = relationship("OrderItem", back_populates="product")
    permissions = relationship("ProductPermission", back_populates="product")
    operation_logs = relationship("OperationLog", back_populates="product")
    alerts = relationship("Alert", back_populates="product")


class ProductPermission(Base):
    """产品权限表"""
    __tablename__ = "product_permissions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    
    user = relationship("User", back_populates="product_permissions")
    product = relationship("Product", back_populates="permissions")


class InventoryRecord(Base):
    """库存入库记录"""
    __tablename__ = "inventory_records"
    
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    remaining_quantity = Column(Integer, nullable=False)
    product_cost = Column(Float, nullable=False)
    logistics_cost = Column(Float, default=0)
    warehouse_type = Column(String(20), default="own")
    inbound_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    
    product = relationship("Product", back_populates="inventory_records")


class InventorySnapshot(Base):
    """库存快照"""
    __tablename__ = "inventory_snapshots"
    
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    warehouse_id = Column(String(50), nullable=False)
    warehouse_name = Column(String(100))
    quantity = Column(Integer, default=0)
    snapshot_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))


class Order(Base):
    """订单表"""
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String(100), unique=True, index=True, nullable=False)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    
    status = Column(String(50), default="new")
    total_amount = Column(Float, default=0)
    commission = Column(Float, default=0)
    logistics_fee = Column(Float, default=0)
    
    product_cost = Column(Float, default=0)
    ad_cost = Column(Float, default=0)
    other_cost = Column(Float, default=0)
    profit = Column(Float, default=0)
    profit_rate = Column(Float, default=0)
    
    order_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    updated_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")), onupdate=lambda ctx: datetime.now(ZoneInfo("Asia/Shanghai")))
    
    shop = relationship("Shop", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    """订单明细"""
    __tablename__ = "order_items"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    
    nm_id = Column(String(50), nullable=False)
    sku = Column(String(100))
    quantity = Column(Integer, default=1)
    price = Column(Float, default=0)
    total_price = Column(Float, default=0)
    
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    
    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")


class AdRecord(Base):
    """广告数据记录"""
    __tablename__ = "ad_records"
    
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    product = relationship("Product")
    
    ad_type = Column(String(50), default="search")
    advert_id = Column(Integer, default=0)
    platform = Column(String(20), default="")  # web/ios/android
    payment_type = Column(String(20), default="")
    placements = Column(String(50), default="")
    
    impressions = Column(Integer, default=0)
    visitors = Column(Integer, default=0)  # 访客数 (API: clicks for advertising, visitors for product_analytics)
    cost = Column(Float, default=0)  # 花费（店铺货币）
    cost_cny = Column(Float, default=0)  # 花费（人民币）
    order_count = Column(Integer, default=0)  # 订单数 (API: order_count)
    order_sum = Column(Float, default=0)  # 销售额（店铺货币）(API: order_sum)
    sales_cny = Column(Float, default=0)  # 销售额（人民币）
    
    cpm = Column(Float, default=0)
    cpc = Column(Float, default=0)
    
    ctr = Column(Float, default=0)
    conversion_rate = Column(Float, default=0)
    acos = Column(Float, default=0)
    roas = Column(Float, default=0)
    
    cart_count = Column(Integer, default=0)  # 加购数
    
    record_date = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))


class AdKeywordStat(Base):
    """广告关键词数据"""
    __tablename__ = "ad_keyword_stats"
    
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    product = relationship("Product")
    
    advert_id = Column(Integer, nullable=False, index=True)
    nm_id = Column(Integer, nullable=False)
    platform = Column(String(20), default="web")  # web/ios/android
    
    keyword = Column(String(500), nullable=False)  # 搜索关键词
    date = Column(Date, nullable=False, index=True)  # 日期
    
    clicks = Column(Integer, default=0)  # 点击数
    views = Column(Integer, default=0)  # 展示数
    orders = Column(Integer, default=0)  # 订单数
    shks = Column(Integer, default=0)  # 退货数
    spend = Column(Float, default=0)  # 花费
    ctr = Column(Float, default=0)  # 点击率
    cpm = Column(Float, default=0)  # CPM
    cpc = Column(Float, default=0)  # CPC
    avg_position = Column(Float, default=0)  # 平均排名
    atbs = Column(Integer, default=0)  # atbs
    payment_type = Column(String(20), default="")  # 广告类型: cpm/cpc
    
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    
    __table_args__ = (
        Index('ix_ad_keyword_advert_date', 'advert_id', 'date'),
        Index('ix_ad_keyword_product_date', 'product_id', 'date'),
    )


class SystemSetting(Base):
    """系统设置"""
    __tablename__ = "system_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=False)
    description = Column(String(500))
    updated_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")), onupdate=lambda ctx: datetime.now(ZoneInfo("Asia/Shanghai")))


class UISetting(Base):
    """界面设置"""
    __tablename__ = "ui_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    login_logo = Column(String(200), default="🌿")
    system_name = Column(String(100), default="WB ERP")
    login_title = Column(String(100), default="WB ERP")
    login_subtitle = Column(String(200), default="Wildberries 跨境电商管理系统")
    sidebar_logo = Column(String(200), default="🍀 WB ERP")
    primary_color = Column(String(20), default="#8b5cf6")
    browser_logo = Column(String(500), default="")
    footer_text = Column(String(200), default="")
    updated_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")), onupdate=lambda ctx: datetime.now(ZoneInfo("Asia/Shanghai")))


class MenuItem(Base):
    """菜单项配置"""
    __tablename__ = "menu_items"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(50), unique=True, nullable=False)
    name = Column(String(50), nullable=False)
    icon = Column(String(50), nullable=True)
    path = Column(String(100), nullable=False)
    parent_key = Column(String(50), nullable=True)
    sort_order = Column(Integer, default=0)
    is_visible = Column(Boolean, default=True)
    required_role = Column(String(20), nullable=True)  # admin/finance/manager/staff
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    updated_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")), onupdate=lambda ctx: datetime.now(ZoneInfo("Asia/Shanghai")))


class SyncLog(Base):
    """同步日志"""
    __tablename__ = "sync_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    sync_type = Column(String(50), nullable=False)
    status = Column(String(20), default="running")
    message = Column(Text, nullable=True)
    records_count = Column(Integer, default=0)
    started_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    finished_at = Column(DateTime, nullable=True)





class MetricHistory(Base):
    """产品每日指标历史"""
    __tablename__ = "metric_histories"
    
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    product = relationship("Product")
    date = Column(DateTime, nullable=False)
    
    # 流量指标
    visitors = Column(Integer, default=0)
    cart_count = Column(Integer, default=0)
    order_count = Column(Integer, default=0)
    order_sum = Column(Float, default=0)
    
    # 广告指标
    ad_cost = Column(Float, default=0)
    ad_visitors = Column(Integer, default=0)
    roas = Column(Float, default=0)
    acos = Column(Float, default=0)
    
    # 转化指标
    conversion_rate = Column(Float, default=0)
    
    # 利润指标
    profit = Column(Float, default=0)
    profit_rate = Column(Float, default=0)
    
    created_at = Column(DateTime, default=datetime.now)


class OperationLog(Base):
    """运营日志"""
    __tablename__ = "operation_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="operation_logs")
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    product = relationship("Product", back_populates="operation_logs")
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=True)
    
    log_date = Column(DateTime, nullable=False)
    action_type = Column(String(50), nullable=False)
    action_detail = Column(Text, default={})
    
    metrics_before = Column(Text, default={})
    effect_tracking_days = Column(Integer, default=7)
    
    title = Column(String(200), nullable=False)
    content = Column(Text, default="{}")
    
    effect_analysis = Column(Text, default="")
    
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.now)


class Alert(Base):
    """预警"""
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="alerts")
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    product = relationship("Product", back_populates="alerts")
    
    alert_type = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, default="")
    severity = Column(String(20), default="medium")
    
    metric_snapshot = Column(Text, default={})
    
    is_read = Column(Boolean, default=False)
    is_resolved = Column(Boolean, default=False)
    resolved_note = Column(Text, default="")
    resolved_at = Column(DateTime, nullable=True)
    
    operation_log_id = Column(Integer, ForeignKey("operation_logs.id"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.now)


class AlertRule(Base):
    """预警规则"""
    __tablename__ = "alert_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    rule_type = Column(String(50), nullable=False)
    condition = Column(Text, default={})
    severity = Column(String(20), default="medium")
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
