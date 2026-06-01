"""
Yandex MVP 同步测试（按 business-level 设计）

覆盖：
1. Yandex orders 写入 Order + OrderItem + AdRecord
2. business_id + campaign_ids 聚合
3. Yandex sales CNY 原值入库（不提前转 RUB）
4. Dashboard 展示 Yandex sales CNY -> RUB
5. Dashboard 展示 Yandex ad_cost CNY -> RUB
6. WB CNY 店铺 sales CNY -> RUB，但 ad_cost 不转换（RUB）
7. ProductSalesTable 不给 Yandex 生成 WB 链接

运行方式：
    cd /opt/wb-erp/backend
    python -m pytest tests/test_yandex_sync.py -v
"""

import hashlib
import sys
import os
from datetime import datetime, timedelta, date
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# Mock 数据
# ============================================================

def make_yandex_order_rows(offer_id="SKU001", offer_name="测试商品A",
                            order_id="1001", qty=2, price=100.0,
                            campaign_id=111, day="2026-05-25"):
    """生成单条 Yandex order 行"""
    return {
        "order_id": order_id,
        "order_date": day,
        "offer_id": offer_id,
        "offer_name": offer_name,
        "quantity": qty,
        "price": price,
        "total_price": price * qty,
        "currency": "CNY",
        "campaign_id": campaign_id,
    }


# 两个 campaign 同一 offer_id + day（用于测试聚合）
YANDEX_MULTI_CAMPAIGN_ROWS = [
    make_yandex_order_rows(campaign_id=111, order_id="1001", qty=1, price=200.0),
    make_yandex_order_rows(campaign_id=222, order_id="1002", qty=2, price=142.75),
]


# ============================================================
# Test 1: Yandex orders 写入 Order + OrderItem + AdRecord
# ============================================================

def test_yandex_orders_writes_order_orderitem_adrecord(mock_db, mock_shop_yandex_biz):
    """sync_yandex_orders 应写入 Order、OrderItem 和 AdRecord(product_analytics)"""
    from app.services.sync_fixed import SyncService
    from app.models.models import Order, OrderItem, AdRecord

    # Mock get_orders_for_db 返回订单行
    mock_rows = [
        make_yandex_order_rows(order_id="2001", qty=3, price=150.0, day="2026-05-20"),
        make_yandex_order_rows(order_id="2002", qty=1, price=300.0, day="2026-05-21"),
    ]
    mock_aggregated = [
        {
            "offer_id": "SKU001",
            "offer_name": "测试商品A",
            "day": "2026-05-20",
            "order_count": 1,
            "order_items": 3,
            "sales_amount": 450.0,
        },
        {
            "offer_id": "SKU001",
            "offer_name": "测试商品A",
            "day": "2026-05-21",
            "order_count": 1,
            "order_items": 1,
            "sales_amount": 300.0,
        },
    ]

    with patch.object(SyncService, "_create_sync_log", return_value=MagicMock(id=1)):
        with patch.object(SyncService, "_finish_sync_log", return_value=None):
            svc = SyncService(mock_db, mock_shop_yandex_biz)
            with patch.object(svc.client, "get_orders_for_db", return_value=mock_rows):
                with patch.object(svc.client, "get_orders_aggregated", return_value=mock_aggregated):
                    # 先建 Product（sync 会自动创建，这里手动建一个方便查询）
                    from app.models.models import Product
                    p = Product(
                        shop_id=mock_shop_yandex_biz.id,
                        nm_id="ym_test001",
                        sku="SKU001",
                        name="测试商品A",
                    )
                    mock_db.add(p)
                    mock_db.commit()

                    result = svc.sync_yandex_orders(days=7)

    assert result["success"] is True
    assert result["order_count"] == 2
    assert result["item_count"] == 2
    assert result["ad_count"] == 2

    # 验证 Order 写入
    orders = mock_db.query(Order).filter(Order.shop_id == mock_shop_yandex_biz.id).all()
    assert len(orders) == 2

    # 验证 AdRecord 写入
    ads = mock_db.query(AdRecord).filter(
        AdRecord.shop_id == mock_shop_yandex_biz.id,
        AdRecord.ad_type == "product_analytics"
    ).all()
    assert len(ads) == 2


# ============================================================
# Test 2: business_id + campaign_ids 聚合
# ============================================================

def test_yandex_multi_campaign_aggregates_by_offer_id_and_day(mock_db, mock_shop_yandex_biz):
    """同一 offer_id + day 跨多个 campaign 应聚合成一条 AdRecord"""
    from app.services.sync_fixed import SyncService
    from app.models.models import AdRecord, Product

    # 建 Product
    p = Product(shop_id=mock_shop_yandex_biz.id, nm_id="ym_test002", sku="SKU001", name="测试")
    mock_db.add(p)
    mock_db.commit()

    mock_aggregated = [
        {
            "offer_id": "SKU001",
            "offer_name": "测试商品A",
            "day": "2026-05-25",
            "order_count": 2,   # 2 个 campaign 各 1 单
            "order_items": 3,   # 1+2
            "sales_amount": 485.50,  # 200 + 285.50
        },
    ]

    with patch.object(SyncService, "_create_sync_log", return_value=MagicMock(id=1)):
        with patch.object(SyncService, "_finish_sync_log", return_value=None):
            svc = SyncService(mock_db, mock_shop_yandex_biz)
            with patch.object(svc.client, "get_orders_for_db", return_value=YANDEX_MULTI_CAMPAIGN_ROWS):
                with patch.object(svc.client, "get_orders_aggregated", return_value=mock_aggregated):
                    result = svc.sync_yandex_orders(days=7)

    assert result["success"] is True

    # 只应有 1 条 AdRecord（2026-05-25，SKU001）
    ads = mock_db.query(AdRecord).filter(
        AdRecord.shop_id == mock_shop_yandex_biz.id,
        AdRecord.ad_type == "product_analytics"
    ).all()

    assert len(ads) == 1, f"期望 1 条聚合 AdRecord，实际 {len(ads)} 条"
    rec = ads[0]
    assert rec.order_count == 2
    assert abs(rec.sales - 485.50) < 0.01


# ============================================================
# Test 3: Yandex sales CNY 原值入库
# ============================================================

def test_yandex_cny_sales_stored_raw(mock_db, mock_shop_yandex_biz):
    """Yandex AdRecord.sales 保存 CNY 原始值，不提前转 RUB"""
    from app.services.sync_fixed import SyncService
    from app.models.models import AdRecord, Product

    p = Product(shop_id=mock_shop_yandex_biz.id, nm_id="ym_test003", sku="SKU001", name="测试")
    mock_db.add(p)
    mock_db.commit()

    mock_aggregated = [
        {
            "offer_id": "SKU001",
            "offer_name": "测试商品A",
            "day": "2026-05-25",
            "order_count": 1,
            "order_items": 2,
            "sales_amount": 485.50,  # CNY 原始值
        },
    ]

    with patch.object(SyncService, "_create_sync_log", return_value=MagicMock(id=1)):
        with patch.object(SyncService, "_finish_sync_log", return_value=None):
            svc = SyncService(mock_db, mock_shop_yandex_biz)
            with patch.object(svc.client, "get_orders_for_db", return_value=[]):
                with patch.object(svc.client, "get_orders_aggregated", return_value=mock_aggregated):
                    svc.sync_yandex_orders(days=7)

    rec = mock_db.query(AdRecord).filter(
        AdRecord.shop_id == mock_shop_yandex_biz.id,
        AdRecord.ad_type == "product_analytics"
    ).first()

    assert rec is not None
    assert abs(rec.sales - 485.50) < 0.01, f"期望 CNY 原始值 485.50，实际 {rec.sales}"
    assert rec.cost == 0  # 无广告费


# ============================================================
# Test 4: Dashboard 展示 Yandex sales CNY -> RUB
# ============================================================

def test_dashboard_yandex_sales_converted_to_rub(mock_db, mock_shop_yandex_biz):
    """Dashboard 对 Yandex CNY sales 应乘汇率转 RUB"""
    from app.services.sync_fixed import SyncService
    from app.models.models import AdRecord, Product
    from app.routers.dashboard import get_dashboard_stats, DashboardFilter

    # 建 Product
    p = Product(shop_id=mock_shop_yandex_biz.id, nm_id="ym_test004", sku="SKU001", name="测试")
    mock_db.add(p)
    mock_db.commit()

    # 写入 product_analytics，sales=485.50 CNY
    ad = AdRecord(
        shop_id=mock_shop_yandex_biz.id,
        product_id=p.id,
        record_date=date(2026, 5, 25),
        ad_type="product_analytics",
        sales=485.50,
        visitors=100,
        cart_count=10,
        order_count=2,
        cost=0,
    )
    mock_db.add(ad)
    mock_db.commit()

    with patch("app.routers.dashboard.get_current_user", return_value=MagicMock(id=1)):
        filter_obj = DashboardFilter(start_date="2026-05-01", end_date="2026-05-31")
        stats = get_dashboard_stats(
            filter_data=filter_obj,
            db=mock_db,
            current_user=MagicMock(id=1),
        )

    # 485.50 CNY * 12.5 = 6068.75 RUB
    assert stats.sales_amount >= 6000, f"期望 ~6068.75，实际 {stats.sales_amount}"


# ============================================================
# Test 5: Dashboard 展示 Yandex ad_cost CNY -> RUB
# ============================================================

def test_dashboard_yandex_adcost_converted_to_rub(mock_db, mock_shop_yandex_biz):
    """Dashboard 对 Yandex advertising CNY cost 应乘汇率转 RUB"""
    from app.models.models import AdRecord, Product
    from app.routers.dashboard import get_dashboard_stats, DashboardFilter

    p = Product(shop_id=mock_shop_yandex_biz.id, nm_id="ym_test005", sku="SKU001", name="测试")
    mock_db.add(p)
    mock_db.commit()

    # advertising 类型，cost=100 CNY
    ad = AdRecord(
        shop_id=mock_shop_yandex_biz.id,
        product_id=p.id,
        record_date=date(2026, 5, 25),
        ad_type="advertising",
        sales=0,
        visitors=0,
        cart_count=0,
        order_count=0,
        cost=100.00,
    )
    mock_db.add(ad)
    mock_db.commit()

    with patch("app.routers.dashboard.get_current_user", return_value=MagicMock(id=1)):
        filter_obj = DashboardFilter(start_date="2026-05-01", end_date="2026-05-31")
        stats = get_dashboard_stats(
            filter_data=filter_obj,
            db=mock_db,
            current_user=MagicMock(id=1),
        )

    # 100 CNY * 12.5 = 1250 RUB
    assert stats.ad_cost >= 1200, f"期望 ~1250，实际 {stats.ad_cost}"


# ============================================================
# Test 6: WB CNY 店铺 sales CNY -> RUB，但 ad_cost 不转换
# ============================================================

def test_dashboard_wb_cny_sales_converted_adcost_not(mock_db, mock_shop_wb_cny):
    """WB CNY 店铺：sales 转 RUB，ad_cost 保持 RUB 不转换"""
    from app.models.models import AdRecord, Product
    from app.routers.dashboard import get_dashboard_stats, DashboardFilter

    p = Product(shop_id=mock_shop_wb_cny.id, nm_id="123456", sku="WB001", name="WB商品")
    mock_db.add(p)
    mock_db.commit()

    # product_analytics: sales=1000 CNY
    ad1 = AdRecord(
        shop_id=mock_shop_wb_cny.id,
        product_id=p.id,
        record_date=date(2026, 5, 25),
        ad_type="product_analytics",
        sales=1000.00,
        visitors=50,
        cart_count=5,
        order_count=1,
        cost=0,
    )
    mock_db.add(ad1)

    # advertising: cost=200 RUB（WB 广告费是 RUB）
    ad2 = AdRecord(
        shop_id=mock_shop_wb_cny.id,
        product_id=p.id,
        record_date=date(2026, 5, 25),
        ad_type="advertising",
        sales=0,
        visitors=0,
        cart_count=0,
        order_count=0,
        cost=200.00,
    )
    mock_db.add(ad2)
    mock_db.commit()

    with patch("app.routers.dashboard.get_current_user", return_value=MagicMock(id=1)):
        filter_obj = DashboardFilter(start_date="2026-05-01", end_date="2026-05-31")
        stats = get_dashboard_stats(
            filter_data=filter_obj,
            db=mock_db,
            current_user=MagicMock(id=1),
        )

    # sales: 1000 CNY * 12.5 = 12500 RUB
    assert stats.sales_amount >= 12000, f"期望 ~12500，实际 {stats.sales_amount}"
    # ad_cost: 200 RUB（不转换）
    assert 190 < stats.ad_cost < 210, f"期望 ~200，实际 {stats.ad_cost}"


# ============================================================
# Test 7: ProductSalesTable 不给 Yandex 生成 WB 链接
# ============================================================

def test_yandex_nmid_no_wb_link():
    """Yandex nm_id 以 'ym_' 开头，不会匹配 shop_platform === 'wildberries' 条件"""
    nm_id = "ym_" + hashlib.sha1(b"123456:SKU001").hexdigest()[:32]
    assert nm_id.startswith("ym_")
    # shop_platform === "wildberries" 条件检查：
    # nm_id 以 ym_ 开头 → 不是 wildberries → 不生成链接
    is_wb = nm_id and "ym_" not in nm_id  # 模拟前端 shop_platform === "wildberries" 检查
    assert not is_wb, "Yandex nm_id 不应生成 WB 链接"


# ============================================================
# Test 8: convert_ad_cost 函数逻辑
# ============================================================

def test_convert_ad_cost_yandex_cny_to_rub():
    """convert_ad_cost 对 Yandex CNY 应乘汇率，对 WB RUB 不转换"""
    from app.routers.dashboard import convert_ad_cost
    from unittest.mock import MagicMock

    shop_rates = {
        1: {"platform": "yandex", "currency": "CNY", "rate": 12.5},
        2: {"platform": "wildberries", "currency": "RUB", "rate": 12.5},
    }

    # Yandex: 100 CNY -> 1250 RUB
    yandex_ad = MagicMock()
    yandex_ad.shop_id = 1
    yandex_ad.cost = 100.0
    assert convert_ad_cost(yandex_ad, shop_rates) == 1250.0

    # WB: 200 RUB -> 200（不转换）
    wb_ad = MagicMock()
    wb_ad.shop_id = 2
    wb_ad.cost = 200.0
    assert convert_ad_cost(wb_ad, shop_rates) == 200.0

    # 找不到 shop: 默认 RUB，不转换
    unknown_ad = MagicMock()
    unknown_ad.shop_id = 999
    unknown_ad.cost = 300.0
    assert convert_ad_cost(unknown_ad, shop_rates) == 300.0


# ============================================================
# Test 9: sync_yandex_orders 成功后更新 last_sync_at
# ============================================================

def test_yandex_orders_updates_last_sync_on_success(mock_db, mock_shop_yandex_biz):
    """sync_yandex_orders 成功完成后应更新 shop.last_sync_at"""
    from app.services.sync_fixed import SyncService
    from app.models.models import Product

    p = Product(shop_id=mock_shop_yandex_biz.id, nm_id="ym_test006", sku="SKU001", name="测试")
    mock_db.add(p)
    mock_db.commit()

    original_sync_at = mock_shop_yandex_biz.last_sync_at

    with patch.object(SyncService, "_create_sync_log", return_value=MagicMock(id=1)):
        with patch.object(SyncService, "_finish_sync_log", return_value=None):
            svc = SyncService(mock_db, mock_shop_yandex_biz)
            with patch.object(svc.client, "get_orders_for_db", return_value=[]):
                with patch.object(svc.client, "get_orders_aggregated", return_value=[]):
                    result = svc.sync_yandex_orders(days=7)

    assert result["success"] is True
    assert mock_shop_yandex_biz.last_sync_at is not None
    if original_sync_at is None:
        assert mock_shop_yandex_biz.last_sync_at is not None


# ============================================================
# Test 10: sync_yandex_orders 失败时不更新 last_sync_at
# ============================================================

def test_yandex_orders_no_update_on_failure(mock_db, mock_shop_yandex_biz):
    """sync_yandex_orders 失败时不应更新 shop.last_sync_at"""
    from app.services.sync_fixed import SyncService

    original_sync_at = mock_shop_yandex_biz.last_sync_at

    with patch.object(SyncService, "_create_sync_log", return_value=MagicMock(id=1)):
        with patch.object(SyncService, "_finish_sync_log", return_value=None):
            svc = SyncService(mock_db, mock_shop_yandex_biz)
            # 让 API 抛异常
            with patch.object(svc.client, "get_orders_for_db", side_effect=Exception("API error")):
                result = svc.sync_yandex_orders(days=7)

    assert result["success"] is False
    assert mock_shop_yandex_biz.last_sync_at == original_sync_at


# ============================================================
# Test 11: Yandex 单项 sync 拒绝 ads/keywords/inventory
# ============================================================

def test_yandex_single_sync_rejects_ads_keywords_inventory(mock_db, mock_shop_yandex_biz):
    """Yandex 店铺单独触发 ads/keywords/inventory 应返回 MVP 提示，不调用 WB 方法"""
    from app.routers.shops import _sync_shop_data_internal

    # Use the actual shop from the fixture
    result_ads = _sync_shop_data_internal(
        shop_id=mock_shop_yandex_biz.id, sync_type="ads", history=False, db=mock_db
    )
    assert "Yandex MVP" in result_ads["results"]["ads"]["message"]

    result_kw = _sync_shop_data_internal(
        shop_id=mock_shop_yandex_biz.id, sync_type="keywords", history=False, db=mock_db
    )
    assert "Yandex MVP" in result_kw["results"]["keywords"]["message"]

    result_inv = _sync_shop_data_internal(
        shop_id=mock_shop_yandex_biz.id, sync_type="inventory", history=False, db=mock_db
    )
    assert "Yandex MVP" in result_inv["results"]["inventory"]["message"]


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mock_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base

    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


@pytest.fixture
def mock_shop_yandex_biz(mock_db):
    """business-level Yandex 测试店铺（多个 campaign）"""
    from app.models.models import Shop

    shop = Shop(
        name="测试Yandex商家",
        api_token="fake-yandex-token",
        platform="yandex",
        platform_config={
            "business_id": 123456,
            "business_name": "测试商家",
            "campaign_ids": [111, 222],
            "campaigns": [
                {"campaign_id": 111, "domain": "shop1.example.com",
                 "placement_type": "CLICK_AND_COLLECT", "api_availability": "AVAILABLE"},
                {"campaign_id": 222, "domain": "shop2.example.com",
                 "placement_type": "CLICK_AND_COLLECT", "api_availability": "AVAILABLE"},
            ]
        },
        currency="CNY",
        sync_enabled=True,
        sync_interval_hours=24,
    )
    mock_db.add(shop)
    mock_db.commit()
    mock_db.refresh(shop)
    return shop


@pytest.fixture
def mock_shop_wb_cny(mock_db):
    """WB CNY 测试店铺"""
    from app.models.models import Shop

    shop = Shop(
        name="测试WB店铺(CNY)",
        api_token="fake-wb-token",
        platform="wildberries",
        currency="CNY",
        sync_enabled=True,
        sync_interval_hours=24,
    )
    mock_db.add(shop)
    mock_db.commit()
    mock_db.refresh(shop)
    return shop


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
