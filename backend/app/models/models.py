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
    ADMIN = "admin"            # 管理员
    FINANCE = "finance"        # 财务
    MANAGER = "manager"        # 经理
    STAFF = "staff"            # 员工
    CUSTOMER_SERVICE = "customer_service"  # 客服
    PRODUCT_OWNER = "product_owner"         # 产品负责人
    VIEWER = "viewer"          # 查看者
    CUSTOM = "custom"          # 自定义


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
    permissions = Column(JSON, default=list)  # 细粒度权限码数组
    allowed_shops = Column(JSON, default=list)  # 可访问的店铺ID列表
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    updated_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")), onupdate=lambda ctx: datetime.now(ZoneInfo("Asia/Shanghai")))
    
    # 关系
    product_permissions = relationship("ProductPermission", back_populates="user")
    operation_logs = relationship("OperationLog", back_populates="user")


class Shop(Base):
    """店铺表"""
    __tablename__ = "shops"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    api_token = Column(String(500), nullable=False)
    platform = Column(String(20), default="wildberries")  # wildberries/yandex
    platform_config = Column(JSON, default=dict)  # Yandex: {business_id, campaign_id}
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
    clicks = Column(Integer, default=0)
    cost = Column(Float, default=0)  # 花费（店铺货币）
    cost_cny = Column(Float, default=0)  # 花费（人民币）
    order_count = Column(Integer, default=0)
    sales = Column(Float, default=0)
    sales_cny = Column(Float, default=0)  # 销售额（人民币）
    
    cpm = Column(Float, default=0)
    cpc = Column(Float, default=0)
    
    ctr = Column(Float, default=0)
    conversion_rate = Column(Float, default=0)
    acos = Column(Float, default=0)
    roas = Column(Float, default=0)
    
    cart_count = Column(Integer, default=0)  # 加购数
    atbs = Column(Integer, default=0)  # 加购数（API原字段）
    shks = Column(Integer, default=0)  # 已购数（API原字段）
    
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
    order_count = Column(Integer, default=0)  # 订单数
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
    browser_logo = Column(Text, default="")
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


class AIPromptTemplate(Base):
    """AI Prompt 模板，支持版本管理"""
    __tablename__ = "ai_prompt_templates"

    id = Column(Integer, primary_key=True, index=True)
    template_key = Column(String(80), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    system_prompt = Column(Text, nullable=False)
    user_prompt_template = Column(Text, nullable=False)
    output_schema_json = Column(Text, default="{}")
    temperature = Column(Float, default=0.2)
    max_tokens = Column(Integer, default=1200)
    is_active = Column(Boolean, default=True)
    version = Column(Integer, default=1)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")),
        onupdate=lambda ctx: datetime.now(ZoneInfo("Asia/Shanghai")),
    )

    __table_args__ = (
        Index("ix_ai_prompt_template_key_version", "template_key", "version", unique=True),
        Index("ix_ai_prompt_template_active", "template_key", "is_active"),
    )


class SyncJob(Base):
    """异步同步任务"""
    __tablename__ = "sync_jobs"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    sync_type = Column(String(50), nullable=False)
    status = Column(String(20), default="pending")  # pending/running/success/failed
    progress = Column(Integer, default=0)  # 0-100
    message = Column(Text, default="")
    result_json = Column(Text, nullable=True)  # JSON string
    error = Column(Text, nullable=True)
    created_by = Column(Integer, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    updated_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")), onupdate=datetime.now)


class SyncSchedule(Base):
    """按店铺和数据类型拆分的自动同步计划"""
    __tablename__ = "sync_schedules"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    sync_type = Column(String(50), nullable=False)
    enabled = Column(Boolean, default=True)
    interval_minutes = Column(Integer, default=120)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    last_status = Column(String(20), nullable=True)
    last_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    updated_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")), onupdate=lambda ctx: datetime.now(ZoneInfo("Asia/Shanghai")))

    shop = relationship("Shop")

    __table_args__ = (
        Index("ix_sync_schedules_shop_type", "shop_id", "sync_type", unique=True),
        Index("ix_sync_schedules_due", "enabled", "next_run_at"),
    )

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


class CustomerServiceItem(Base):
    """客服工单：WB 问答/评价/聊天/退货申请统一入口"""
    __tablename__ = "customer_service_items"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    platform = Column(String(20), default="wildberries", nullable=False)
    channel = Column(String(30), nullable=False)  # question/feedback/chat/return_claim
    external_id = Column(String(120), nullable=False)
    external_status = Column(String(80), default="")

    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    nm_id = Column(String(50), nullable=True)
    sku = Column(String(100), nullable=True)
    product_name = Column(String(500), nullable=True)
    product_name_ru = Column(String(500), nullable=True)
    owner = Column(String(100), nullable=True)
    product_matched = Column(Boolean, default=False)

    assigned_owner = Column(String(100), nullable=True)
    assigned_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    assignment_status = Column(String(30), default="unassigned")  # unassigned/assigned/pending_internal/closed
    handover_note = Column(Text, default="")
    internal_note = Column(Text, default="")
    internal_note_updated_by = Column(String(100), nullable=True)
    internal_note_updated_at = Column(DateTime, nullable=True)

    customer_name = Column(String(200), nullable=True)
    title = Column(String(500), default="")
    content = Column(Text, default="")
    rating = Column(Integer, nullable=True)

    status = Column(String(30), default="open")  # open/pending_internal/replied/closed/archived
    reply_status = Column(String(30), default="unanswered")  # unanswered/answered/failed
    priority = Column(String(20), default="normal")  # low/normal/high/urgent
    risk_level = Column(String(20), default="normal")  # low/normal/high/urgent
    issue_type = Column(String(50), default="other")
    is_viewed = Column(Boolean, default=False)
    is_archived = Column(Boolean, default=False)

    first_replied_by = Column(String(100), nullable=True)
    first_replied_at = Column(DateTime, nullable=True)
    last_handled_by = Column(String(100), nullable=True)
    last_handled_at = Column(DateTime, nullable=True)
    closed_by = Column(String(100), nullable=True)
    closed_at = Column(DateTime, nullable=True)

    external_created_at = Column(DateTime, nullable=True)
    external_updated_at = Column(DateTime, nullable=True)
    sla_deadline_at = Column(DateTime, nullable=True)
    is_overdue = Column(Boolean, default=False)
    return_deadline_hours = Column(Integer, default=120)

    raw_json = Column(Text, default="{}")
    buyer_key = Column(String(200), nullable=True, index=True)  # deprecated: WB 无稳定跨渠道买家ID，不再用于聚合，保留字段仅避免破坏性DB迁移
    reply_sign = Column(Text, nullable=True)  # 买家聊天回复凭证（WB API 发送用）
    answer_visibility = Column(String(20), default="all")  # 历史兼容字段；WB 公开 API 当前统一公开回复

    # 翻译字段（手动触发，不自动翻译）
    content_zh = Column(Text, nullable=True)
    title_zh = Column(Text, nullable=True)
    translation_status = Column(String(30), default="pending")  # pending/translated/failed
    translated_at = Column(DateTime, nullable=True)
    translation_error = Column(Text, nullable=True)
    translation_source_hash = Column(String(64), nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    updated_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")), onupdate=lambda ctx: datetime.now(ZoneInfo("Asia/Shanghai")))

    shop = relationship("Shop")
    product = relationship("Product")
    assigned_user = relationship("User")
    messages = relationship("CustomerServiceMessage", back_populates="item")
    actions = relationship("CustomerServiceAction", back_populates="item")

    __table_args__ = (
        Index("ix_customer_service_item_dedup", "shop_id", "platform", "channel", "external_id", unique=True),
        Index("ix_customer_service_item_inbox", "shop_id", "channel", "status", "external_created_at"),
        Index("ix_customer_service_item_product", "product_id"),
        Index("ix_customer_service_item_owner", "owner"),
        Index("ix_customer_service_item_assigned_owner", "assigned_owner"),
        Index("ix_customer_service_item_assigned_user", "assigned_user_id"),
        Index("ix_customer_service_item_reply_status", "reply_status"),
        Index("ix_customer_service_item_archived", "is_archived"),
        Index("ix_customer_service_item_risk", "risk_level"),
        Index("ix_customer_service_item_sla", "sla_deadline_at"),
    )


class CustomerServiceMessage(Base):
    """客服消息明细：买家/客服/系统消息，不写入运营日志"""
    __tablename__ = "customer_service_messages"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("customer_service_items.id"), nullable=False)
    external_message_id = Column(String(120), nullable=True)
    # 去重键：shop_id:channel:external_message_id，同一 WB 消息在相同 shop+channel 下唯一
    message_dedup_key = Column(String(200), nullable=True)
    direction = Column(String(20), default="buyer")  # buyer/seller/system
    sender_type = Column(String(50), default="")
    sender_name = Column(String(200), default="")
    message_text = Column(Text, default="")
    attachments_json = Column(Text, default="[]")
    created_at_external = Column(DateTime, nullable=True)
    raw_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))

    # 翻译字段（手动触发，不自动翻译）
    message_text_zh = Column(Text, nullable=True)
    translation_status = Column(String(30), default="pending")  # pending/translated/failed
    translated_at = Column(DateTime, nullable=True)
    translation_error = Column(Text, nullable=True)
    translation_source_hash = Column(String(64), nullable=True)

    item = relationship("CustomerServiceItem", back_populates="messages")

    __table_args__ = (
        Index("ix_customer_service_message_item", "item_id"),
        Index("ix_customer_service_message_external", "external_message_id"),
        Index("ix_customer_service_message_time", "created_at_external"),
    )


class CustomerServiceAction(Base):
    """客服动作审计：每次人工/AI/系统处理都记录处理人和时间"""
    __tablename__ = "customer_service_actions"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("customer_service_items.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action_type = Column(String(50), nullable=False)  # reply/ai_draft_generated/mark_read/assign_owner/return_approve/return_reject/close/quality_check
    action_time = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    request_json = Column(Text, default="{}")
    response_json = Column(Text, default="{}")
    success = Column(Boolean, default=True)
    error = Column(Text, default="")

    first_response = Column(Boolean, default=False)
    effective_response = Column(Boolean, default=False)
    response_minutes = Column(Float, nullable=True)
    quality_score = Column(Float, nullable=True)
    quality_result = Column(String(20), nullable=True)  # pass/fail/warning
    quality_reason = Column(Text, default="")
    ai_quality_json = Column(Text, default="{}")

    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))

    item = relationship("CustomerServiceItem", back_populates="actions")
    user = relationship("User")

    __table_args__ = (
        Index("ix_customer_service_action_item", "item_id"),
        Index("ix_customer_service_action_user", "user_id"),
        Index("ix_customer_service_action_type_time", "action_type", "action_time"),
    )





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
    sales = Column(Float, default=0)
    
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
    
    metrics_before = Column(Text, default=None)
    effect_tracking_days = Column(Integer, default=7)
    
    title = Column(String(200), nullable=False)
    content = Column(Text, default="{}")
    
    effect = Column(String(50), default="pending")
    effect_analysis = Column(Text, default="")
    
    created_at = Column(DateTime, default=datetime.now)
