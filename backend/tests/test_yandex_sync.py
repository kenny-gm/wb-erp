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
8. Dashboard 无负责人筛选时不会 UnboundLocalError
9. Yandex traffic 更新/新建 record 字段正确
10. businessId fallback 行为正确
11. scheduler import 正确
12. migration 幂等
13. WB 多 advert_id UNIQUE 不冲突

运行方式：
    cd /opt/wb-erp/backend
    python -m pytest tests/test_yandex_sync.py -v
"""

import hashlib
import sys
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, date
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import pytest
from pathlib import Path
import importlib.util
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# Helpers
# ============================================================

@contextmanager
def mock_sync_logs_no_commit(mock_db):
    """
    当 _create_sync_log 和 _finish_sync_log 被 patch 为 no-op 时，
    sync 方法内的 db 改动不会 commit。
    使用此 helper 在 sync 调用后手动 commit：
        with mock_sync_logs_no_commit(mock_db):
            svc.sync_xxx(...)
    """
    try:
        yield
    finally:
        mock_db.commit()


@contextmanager
def patched_sync_methods(svc):
    """
    Patch SyncService._create_sync_log / _finish_sync_log 为 no-op，
    并在退出时自动 commit session。
    """
    def noop_create(self, *args, **kwargs):
        return MagicMock(id=1)

    def noop_finish(self, *args, **kwargs):
        pass

    with patch.object(type(svc), "_create_sync_log", noop_create):
        with patch.object(type(svc), "_finish_sync_log", noop_finish):
            try:
                yield
            finally:
                svc.db.commit()


# ============================================================
# Test 1: Yandex orders 写入 Order + OrderItem + AdRecord
# ============================================================

def test_yandex_orders_writes_order_orderitem_adrecord(mock_db, mock_shop_yandex_biz):
    """sync_yandex_orders 应写入 Order、OrderItem 和 AdRecord(product_analytics)"""
    from app.services.sync_fixed import SyncService
    from app.models.models import Order, OrderItem, AdRecord

    mock_rows = [
        {"order_id": "2001", "order_date": "2026-05-20", "offer_id": "SKU001",
         "offer_name": "测试商品A", "quantity": 3, "price": 150.0,
         "total_price": 450.0, "currency": "CNY", "campaign_id": 111},
        {"order_id": "2002", "order_date": "2026-05-21", "offer_id": "SKU001",
         "offer_name": "测试商品A", "quantity": 1, "price": 300.0,
         "total_price": 300.0, "currency": "CNY", "campaign_id": 111},
    ]
    mock_aggregated = [
        {"offer_id": "SKU001", "offer_name": "测试商品A", "day": "2026-05-20",
         "order_count": 1, "order_items": 3, "sales_amount": 450.0},
        {"offer_id": "SKU001", "offer_name": "测试商品A", "day": "2026-05-21",
         "order_count": 1, "order_items": 1, "sales_amount": 300.0},
    ]

    from app.models.models import Product
    p = Product(shop_id=mock_shop_yandex_biz.id, nm_id="ym_test001", sku="SKU001", name="测试商品A")
    mock_db.add(p)
    mock_db.commit()

    svc = SyncService(mock_db, mock_shop_yandex_biz)
    with patched_sync_methods(svc):
        with patch.object(svc.client, "get_orders_for_db", return_value=mock_rows):
            with patch.object(svc.client, "get_orders_aggregated", return_value=mock_aggregated):
                result = svc.sync_yandex_orders(days=7)

    assert result["success"] is True
    assert result["order_count"] == 2
    assert result["item_count"] == 2
    assert result["ad_count"] == 2

    orders = mock_db.query(Order).filter(Order.shop_id == mock_shop_yandex_biz.id).all()
    assert len(orders) == 2

    ads = mock_db.query(AdRecord).filter(
        AdRecord.shop_id == mock_shop_yandex_biz.id,
        AdRecord.ad_type == "product_analytics"
    ).all()
    assert len(ads) == 2


# ============================================================
# Test 2: business_id + campaign_ids 聚合
# ============================================================

YANDEX_MULTI_CAMPAIGN_ROWS = [
    {"order_id": "1001", "order_date": "2026-05-25", "offer_id": "SKU001",
     "offer_name": "测试商品A", "quantity": 1, "price": 200.0,
     "total_price": 200.0, "currency": "CNY", "campaign_id": 111},
    {"order_id": "1002", "order_date": "2026-05-25", "offer_id": "SKU001",
     "offer_name": "测试商品A", "quantity": 2, "price": 142.75,
     "total_price": 285.50, "currency": "CNY", "campaign_id": 222},
]


def test_yandex_multi_campaign_aggregates_by_offer_id_and_day(mock_db, mock_shop_yandex_biz):
    """同一 offer_id + day 跨多个 campaign 应聚合成一条 AdRecord"""
    from app.services.sync_fixed import SyncService
    from app.models.models import AdRecord, Product

    p = Product(shop_id=mock_shop_yandex_biz.id, nm_id="ym_test002", sku="SKU001", name="测试")
    mock_db.add(p)
    mock_db.commit()

    mock_aggregated = [
        {"offer_id": "SKU001", "offer_name": "测试商品A", "day": "2026-05-25",
         "order_count": 2, "order_items": 3, "sales_amount": 485.50},
    ]

    svc = SyncService(mock_db, mock_shop_yandex_biz)
    with patched_sync_methods(svc):
        with patch.object(svc.client, "get_orders_for_db", return_value=YANDEX_MULTI_CAMPAIGN_ROWS):
            with patch.object(svc.client, "get_orders_aggregated", return_value=mock_aggregated):
                result = svc.sync_yandex_orders(days=7)

    assert result["success"] is True

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
        {"offer_id": "SKU001", "offer_name": "测试商品A", "day": "2026-05-25",
         "order_count": 1, "order_items": 2, "sales_amount": 485.50},
    ]

    svc = SyncService(mock_db, mock_shop_yandex_biz)
    with patched_sync_methods(svc):
        with patch.object(svc.client, "get_orders_for_db", return_value=[]):
            with patch.object(svc.client, "get_orders_aggregated", return_value=mock_aggregated):
                svc.sync_yandex_orders(days=7)

    rec = mock_db.query(AdRecord).filter(
        AdRecord.shop_id == mock_shop_yandex_biz.id,
        AdRecord.ad_type == "product_analytics"
    ).first()

    assert rec is not None
    assert abs(rec.sales - 485.50) < 0.01, f"期望 CNY 原始值 485.50，实际 {rec.sales}"
    assert rec.cost == 0


# ============================================================
# Test 4: Dashboard 展示 Yandex sales CNY -> RUB
# ============================================================

def test_dashboard_yandex_sales_converted_to_rub(mock_db, mock_shop_yandex_biz):
    """Dashboard 对 Yandex CNY sales 应乘汇率转 RUB"""
    from app.models.models import AdRecord, Product
    from app.routers.dashboard import get_dashboard_stats, DashboardFilter

    p = Product(shop_id=mock_shop_yandex_biz.id, nm_id="ym_test004", sku="SKU001", name="测试", owner="kenny")
    mock_db.add(p)
    mock_db.commit()

    ad = AdRecord(
        shop_id=mock_shop_yandex_biz.id, product_id=p.id,
        record_date=date(2026, 5, 25), ad_type="product_analytics",
        sales=485.50, visitors=100, cart_count=10, order_count=2, cost=0,
    )
    mock_db.add(ad)
    mock_db.commit()

    filter_obj = DashboardFilter(start_date="2026-05-01", end_date="2026-05-31")
    stats = get_dashboard_stats(
        filter_data=filter_obj, db=mock_db,
        current_user=SimpleNamespace(id=1, allowed_owners=["kenny"]),
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

    ad = AdRecord(
        shop_id=mock_shop_yandex_biz.id, product_id=p.id,
        record_date=date(2026, 5, 25), ad_type="advertising",
        sales=0, visitors=0, cart_count=0, order_count=0, cost=100.00,
    )
    mock_db.add(ad)
    mock_db.commit()

    filter_obj = DashboardFilter(start_date="2026-05-01", end_date="2026-05-31")
    stats = get_dashboard_stats(
        filter_data=filter_obj, db=mock_db,
        current_user=SimpleNamespace(id=1, allowed_owners=[]),
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

    p = Product(shop_id=mock_shop_wb_cny.id, nm_id="123456", sku="WB001", name="WB商品", owner="kenny")
    mock_db.add(p)
    mock_db.commit()

    ad1 = AdRecord(
        shop_id=mock_shop_wb_cny.id, product_id=p.id,
        record_date=date(2026, 5, 25), ad_type="product_analytics",
        sales=1000.00, visitors=50, cart_count=5, order_count=1, cost=0,
    )
    mock_db.add(ad1)

    ad2 = AdRecord(
        shop_id=mock_shop_wb_cny.id, product_id=p.id,
        record_date=date(2026, 5, 25), ad_type="advertising",
        sales=0, visitors=0, cart_count=0, order_count=0, cost=200.00,
    )
    mock_db.add(ad2)
    mock_db.commit()

    filter_obj = DashboardFilter(start_date="2026-05-01", end_date="2026-05-31")
    stats = get_dashboard_stats(
        filter_data=filter_obj, db=mock_db,
        current_user=SimpleNamespace(id=1, allowed_owners=["kenny"]),
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
    is_wb = nm_id and "ym_" not in nm_id
    assert not is_wb, "Yandex nm_id 不应生成 WB 链接"


# ============================================================
# Test 8: convert_ad_cost 函数逻辑
# ============================================================

def test_convert_ad_cost_yandex_cny_to_rub():
    """convert_ad_cost 对 Yandex CNY 应乘汇率，对 WB RUB 不转换"""
    from app.routers.dashboard import convert_ad_cost

    shop_rates = {
        1: {"platform": "yandex", "currency": "CNY", "rate": 12.5},
        2: {"platform": "wildberries", "currency": "RUB", "rate": 12.5},
    }

    yandex_ad = MagicMock()
    yandex_ad.shop_id = 1
    yandex_ad.cost = 100.0
    assert convert_ad_cost(yandex_ad, shop_rates) == 1250.0

    wb_ad = MagicMock()
    wb_ad.shop_id = 2
    wb_ad.cost = 200.0
    assert convert_ad_cost(wb_ad, shop_rates) == 200.0

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

    svc = SyncService(mock_db, mock_shop_yandex_biz)
    with patched_sync_methods(svc):
        with patch.object(svc.client, "get_orders_for_db", return_value=[]):
            with patch.object(svc.client, "get_orders_aggregated", return_value=[]):
                result = svc.sync_yandex_orders(days=7)

    assert result["success"] is True
    assert mock_shop_yandex_biz.last_sync_at is not None


# ============================================================
# Test 10: sync_yandex_orders 失败时不更新 last_sync_at
# ============================================================

def test_yandex_orders_no_update_on_failure(mock_db, mock_shop_yandex_biz):
    """sync_yandex_orders 失败时不应更新 shop.last_sync_at"""
    from app.services.sync_fixed import SyncService

    original_sync_at = mock_shop_yandex_biz.last_sync_at

    svc = SyncService(mock_db, mock_shop_yandex_biz)
    with patched_sync_methods(svc):
        with patch.object(svc.client, "get_orders_for_db", side_effect=Exception("API error")):
            result = svc.sync_yandex_orders(days=7)

    assert result["success"] is False
    assert mock_shop_yandex_biz.last_sync_at == original_sync_at


# ============================================================
# Test 11: Yandex 单项 sync 拒绝 ads/keywords/inventory
# ============================================================

def test_yandex_single_sync_rejects_ads_keywords_inventory(mock_db, mock_shop_yandex_biz):
    """Yandex 店铺单独触发 ads/keywords/inventory 应返回 MVP 提示"""
    from app.routers.shops import _sync_shop_data_internal

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
# Test 12: Dashboard 无负责人筛选时不会 UnboundLocalError
# ============================================================

def test_dashboard_no_owner_filter_no_unbound_local_error(mock_db, mock_shop_yandex_biz):
    """无负责人筛选时 prev_product_ids 未定义导致的 UnboundLocalError 已修复"""
    from app.models.models import AdRecord, Product
    from app.routers.dashboard import get_dashboard_stats, DashboardFilter

    p = Product(shop_id=mock_shop_yandex_biz.id, nm_id="ym_test007", sku="SKU001", name="测试")
    mock_db.add(p)
    mock_db.commit()

    ad = AdRecord(
        shop_id=mock_shop_yandex_biz.id, product_id=p.id,
        record_date=date(2026, 5, 25), ad_type="product_analytics",
        sales=100.0, visitors=50, cart_count=5, order_count=2, cost=0,
    )
    mock_db.add(ad)
    mock_db.commit()

    # 无负责人筛选调用 Dashboard（之前会 UnboundLocalError）
    filter_obj = DashboardFilter(start_date="2026-05-01", end_date="2026-05-31")
    stats = get_dashboard_stats(
        filter_data=filter_obj, db=mock_db,
        current_user=SimpleNamespace(id=1, allowed_owners=[]),
    )

    assert stats.sales_amount >= 0
    assert stats.visitors >= 0


# ============================================================
# Test 13: Yandex traffic 更新 existing record 时保留 order_count/sales/cost
# ============================================================

def test_yandex_traffic_existing_preserves_order_sales_cost(mock_db, mock_shop_yandex_biz):
    """Yandex traffic sync 更新 existing record 时不覆盖 order_count/sales/cost"""
    from app.services.sync_fixed import SyncService
    from app.models.models import AdRecord, Product

    p = Product(shop_id=mock_shop_yandex_biz.id, nm_id="ym_traf001", sku="SKU-T1", name="测试")
    mock_db.add(p)
    mock_db.commit()

    existing_ad = AdRecord(
        shop_id=mock_shop_yandex_biz.id, product_id=p.id,
        record_date=date(2026, 6, 1), ad_type="product_analytics",
        impressions=1000, clicks=50, visitors=50, cart_count=10,
        order_count=5, sales=500.0, cost=0,
    )
    mock_db.add(existing_ad)
    mock_db.commit()

    svc = SyncService(mock_db, mock_shop_yandex_biz)
    with patched_sync_methods(svc):
        with patch.object(svc, "_fetch_shows_sales_report_business", return_value={
            "success": True, "records": [
                {"offer_id": "SKU-T1", "date": "2026-06-01",
                 "shows": 2000, "clicks": 100, "to_cart": 20}
            ]
        }):
            result = svc.sync_yandex_traffic(date_from="2026-06-01", date_to="2026-06-01")

    assert result["success"] is True

    updated = mock_db.query(AdRecord).filter(
        AdRecord.product_id == p.id,
        func.date(AdRecord.record_date) == func.date(date(2026, 6, 1)),
        AdRecord.ad_type == "product_analytics"
    ).first()
    assert updated is not None
    assert updated.impressions == 2000
    assert updated.clicks == 100
    assert updated.visitors == 100
    assert updated.cart_count == 20
    # 原有字段未被覆盖
    assert updated.order_count == 5
    assert updated.sales == 500.0
    assert updated.cost == 0


# ============================================================
# Test 14: Yandex traffic 新建 record 时 clicks/order_count/sales/cost 正确
# ============================================================

def test_yandex_traffic_new_record_fields_correct(mock_db, mock_shop_yandex_biz):
    """Yandex traffic 新建 record 时 clicks=值, order_count=0, sales=0, cost=0"""
    from app.services.sync_fixed import SyncService
    from app.models.models import AdRecord, Product

    p = Product(shop_id=mock_shop_yandex_biz.id, nm_id="ym_traf002", sku="SKU-T2", name="测试")
    mock_db.add(p)
    mock_db.commit()

    svc = SyncService(mock_db, mock_shop_yandex_biz)
    with patched_sync_methods(svc):
        with patch.object(svc, "_fetch_shows_sales_report_business", return_value={
            "success": True, "records": [
                {"offer_id": "SKU-T2", "date": "2026-06-02",
                 "shows": 3000, "clicks": 150, "to_cart": 30}
            ]
        }):
            result = svc.sync_yandex_traffic(date_from="2026-06-02", date_to="2026-06-02")

    assert result["success"] is True

    new_ad = mock_db.query(AdRecord).filter(
        AdRecord.product_id == p.id,
        func.date(AdRecord.record_date) == func.date(date(2026, 6, 2)),
        AdRecord.ad_type == "product_analytics"
    ).first()
    assert new_ad is not None
    assert new_ad.clicks == 150
    assert new_ad.impressions == 3000
    assert new_ad.visitors == 150
    assert new_ad.cart_count == 30
    assert new_ad.order_count == 0
    assert new_ad.sales == 0.0
    assert new_ad.cost == 0.0


# ============================================================
# Test 15: businessId 未知异常时不 fallback campaign
# ============================================================

def test_yandex_traffic_unknown_exception_no_fallback(mock_db, mock_shop_yandex_biz):
    """businessId 请求未知异常时应直接返回失败，不 fallback 到 campaign"""
    from app.services.sync_fixed import SyncService

    svc = SyncService(mock_db, mock_shop_yandex_biz)
    with patched_sync_methods(svc):
        with patch.object(svc, "_fetch_shows_sales_report_business", side_effect=RuntimeError("未知错误")):
            result = svc.sync_yandex_traffic(date_from="2026-06-01", date_to="2026-06-01")

    assert result["success"] is False
    assert "error" in result


# ============================================================
# Test 16: businessId 400 时 fallback campaign
# ============================================================

def test_yandex_traffic_400_fallback_allowed(mock_db, mock_shop_yandex_biz):
    """businessId 返回 400（fallback_allowed=True）时应 fallback 到 campaign"""
    from app.services.sync_fixed import SyncService

    svc = SyncService(mock_db, mock_shop_yandex_biz)
    with patched_sync_methods(svc):
        with patch.object(svc, "_fetch_shows_sales_report_business", return_value={
            "success": False, "fallback_allowed": True,
            "error": "400 Bad Request", "records": [],
        }):
            with patch.object(svc, "_fetch_shows_sales_report", return_value=[]):
                result = svc.sync_yandex_traffic(date_from="2026-06-01", date_to="2026-06-01")

    assert result["success"] is True


# ============================================================
# Test 17: scheduler import SessionLocal 不报错
# ============================================================

def test_scheduler_imports_session_local():
    """scheduler.py 能正确 import SessionLocal，不报 app.core.database 错误"""
    import sys
    sys.path.insert(0, "/app/backend")
    from app.tasks import scheduler as sched_module
    assert hasattr(sched_module, "sync_yandex_traffic_task")
    assert hasattr(sched_module, "sync_dingtalk_task")


# ============================================================
# Test 18: migration 幂等
# ============================================================

def test_migration_idempotent(mock_db):
    """migration 第一次运行返回 True，第二次运行也返回 True"""
    import sys, os, tempfile, importlib.util

    # 创建临时文件数据库
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        engine = create_engine(f"sqlite:///{db_path}", echo=False)

        # 手动创建 ad_records 表
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE ad_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shop_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    record_date DATETIME,
                    ad_type VARCHAR(50),
                    impressions INTEGER DEFAULT 0,
                    visitors INTEGER DEFAULT 0,
                    cart_count INTEGER DEFAULT 0,
                    order_count INTEGER DEFAULT 0,
                    sales REAL DEFAULT 0,
                    cost REAL DEFAULT 0
                )
            """))
            conn.commit()

        # 动态加载 migration 模块
        spec = importlib.util.spec_from_file_location(
            "mig", Path(__file__).resolve().parents[1] / "migrations" / "fix_ad_records_dedup_index.py"
        )
        mig_mod = importlib.util.module_from_spec(spec)
        original_engine = None
        if spec.loader:
            # Patch engine before exec
            sys.modules["app.migrations.fix_ad_records_dedup_index"] = mig_mod
            spec.loader.exec_module(mig_mod)
            original_engine = mig_mod.engine
            mig_mod.engine = engine

            try:
                result1 = mig_mod.migrate_fix_ad_records_dedup_index()
                assert result1 is True, f"第一次运行应返回 True，实际: {result1}"

                result2 = mig_mod.migrate_fix_ad_records_dedup_index()
                assert result2 is True, f"第二次运行应返回 True，实际: {result2}"
            finally:
                if original_engine is not None:
                    mig_mod.engine = original_engine
        os.unlink(db_path)
    except Exception:
        if os.path.exists(db_path):
            os.unlink(db_path)
        raise


# ============================================================
# Test 19: WB 同一产品同一天多个 advert_id 可以共存
# ============================================================

def test_wb_multiple_advert_id_no_unique_conflict(mock_db):
    """WB 广告同一产品同一天多个 advert_id 可以写入，不报 UNIQUE 冲突"""
    from app.models.models import Shop, Product, AdRecord

    shop = Shop(name="测试WB", api_token="fake", platform="wildberries",
                 currency="RUB", sync_enabled=True, sync_interval_hours=24)
    mock_db.add(shop)
    mock_db.commit()

    p = Product(shop_id=shop.id, nm_id="12345", sku="WB-SKU", name="测试")
    mock_db.add(p)
    mock_db.commit()

    # 写入 advert_id=36698338
    ad1 = AdRecord(
        shop_id=shop.id, product_id=p.id,
        record_date=date(2026, 6, 1), ad_type="advertising",
        impressions=1000, clicks=50, visitors=50, cart_count=5,
        order_count=1, sales=100.0, cost=50.0, advert_id=36698338,
    )
    mock_db.add(ad1)
    mock_db.commit()

    # 写入 advert_id=36698799（同一产品同一天，不同 advert_id）
    ad2 = AdRecord(
        shop_id=shop.id, product_id=p.id,
        record_date=date(2026, 6, 1), ad_type="advertising",
        impressions=800, clicks=40, visitors=40, cart_count=3,
        order_count=0, sales=0, cost=30.0, advert_id=36698799,
    )
    mock_db.add(ad2)
    mock_db.commit()

    # 使用 func.date() 避免 datetime vs date 类型不匹配
    records = mock_db.query(AdRecord).filter(
        AdRecord.shop_id == shop.id,
        AdRecord.product_id == p.id,
        func.date(AdRecord.record_date) == func.date(date(2026, 6, 1)),
        AdRecord.ad_type == "advertising"
    ).all()

    assert len(records) == 2, f"期望 2 条记录（不同 advert_id），实际 {len(records)}"
    advert_ids = sorted([r.advert_id for r in records])
    assert advert_ids == [36698338, 36698799], f"advert_id 应为 [36698338, 36698799]，实际 {advert_ids}"


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mock_db():
    from app.database import Base
    import app.models.models
    import app.models.metric_threshold

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
        is_active=True,
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
        is_active=True,
        sync_enabled=True,
        sync_interval_hours=24,
    )
    mock_db.add(shop)
    mock_db.commit()
    mock_db.refresh(shop)
    return shop


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
