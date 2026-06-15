"""
钉钉数据连接器 - 自定义数据源接口
供钉钉连接器调用，获取 ERP 数据库的表结构和记录数据

接口：
  GET /api/dingtalk/tables                          — 返回所有数据表清单
  GET /api/dingtalk/tables/{table_id}              — 返回某张表的字段定义
  GET /api/dingtalk/tables/{table_id}/records       — 返回记录（支持分页）
"""
import math
from datetime import datetime
from typing import Any
from fastapi import APIRouter, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db

router = APIRouter(prefix="/api/dingtalk", tags=["钉钉数据连接器"])


# ─────────────────────────────────────────
#  数据表定义
# ─────────────────────────────────────────

TABLES = {
    "shops": {
        "name": "店铺列表",
        "desc": "所有店铺信息",
        "source": "shops",
        "key_field": "id",
    },
    "products": {
        "name": "产品列表",
        "desc": "所有产品信息",
        "source": "products",
        "key_field": "id",
    },
    "daily_stats": {
        "name": "每日销售统计",
        "desc": "每日各店铺销售数据（按店铺+日期聚合）",
        "source": "orders",
        "key_field": "id",
        "aggregated": True,
    },
    "ad_daily": {
        "name": "每日广告数据",
        "desc": "每日各产品广告数据（按产品+店铺+日期聚合）",
        "source": "ad_records",
        "key_field": "id",
        "aggregated": True,
    },
}


# ─────────────────────────────────────────
#  字段定义
# ─────────────────────────────────────────

def get_shops_fields() -> list[dict]:
    return [
        {"fieldId": "id",           "fieldName": "店铺ID",        "type": "number"},
        {"fieldId": "name",         "fieldName": "店铺名称",      "type": "text"},
        {"fieldId": "platform",     "fieldName": "平台",          "type": "singleSelect", "config": {"options": [{"name": "wildberries"}, {"name": "yandex"}]}},
        {"fieldId": "currency",     "fieldName": "货币",          "type": "singleSelect", "config": {"options": [{"name": "RUB"}, {"name": "CNY"}]}},
        {"fieldId": "exchange_rate","fieldName": "汇率",          "type": "number"},
        {"fieldId": "is_active",    "fieldName": "是否启用",      "type": "checkbox"},
        {"fieldId": "last_sync_at", "fieldName": "最后同步时间",  "type": "date"},
    ]


def get_products_fields() -> list[dict]:
    return [
        {"fieldId": "id",            "fieldName": "产品ID(nm_id)", "type": "number"},
        {"fieldId": "nm_id",         "fieldName": "nm_id",        "type": "text"},
        {"fieldId": "sku",           "fieldName": "SKU",          "type": "text"},
        {"fieldId": "shop_id",       "fieldName": "店铺ID",        "type": "number"},
        {"fieldId": "shop_name",     "fieldName": "店铺名称",      "type": "text"},
        {"fieldId": "name",          "fieldName": "产品名称",      "type": "text"},
        {"fieldId": "owner",         "fieldName": "负责人",        "type": "text"},
        {"fieldId": "weight",        "fieldName": "重量(kg)",      "type": "number"},
        {"fieldId": "length",        "fieldName": "长度(cm)",      "type": "number"},
        {"fieldId": "width",         "fieldName": "宽度(cm)",      "type": "number"},
        {"fieldId": "height",        "fieldName": "高度(cm)",      "type": "number"},
        {"fieldId": "purchase_price","fieldName": "采购价(CNY)",   "type": "number"},
        {"fieldId": "commission_rate","fieldName": "佣金率",      "type": "number"},
    ]


def get_daily_stats_fields() -> list[dict]:
    return [
        {"fieldId": "id",             "fieldName": "ID",           "type": "number"},
        {"fieldId": "date",           "fieldName": "日期",         "type": "date"},
        {"fieldId": "shop_id",        "fieldName": "店铺ID",       "type": "number"},
        {"fieldId": "shop_name",      "fieldName": "店铺名称",     "type": "text"},
        {"fieldId": "order_count",    "fieldName": "订单数",       "type": "number"},
        {"fieldId": "total_amount",   "fieldName": "销售额(RUB)",  "type": "number"},
        {"fieldId": "commission",     "fieldName": "佣金(RUB)",    "type": "number"},
        {"fieldId": "logistics_fee",  "fieldName": "物流费(RUB)",  "type": "number"},
        {"fieldId": "profit",         "fieldName": "利润(RUB)",     "type": "number"},
        {"fieldId": "profit_rate",    "fieldName": "利润率",       "type": "number"},
    ]


def get_ad_daily_fields() -> list[dict]:
    return [
        {"fieldId": "id",            "fieldName": "ID",           "type": "number"},
        {"fieldId": "date",          "fieldName": "日期",         "type": "date"},
        {"fieldId": "product_id",    "fieldName": "产品ID",        "type": "number"},
        {"fieldId": "nm_id",         "fieldName": "nm_id",        "type": "text"},
        {"fieldId": "product_name",  "fieldName": "产品名称",      "type": "text"},
        {"fieldId": "shop_id",       "fieldName": "店铺ID",        "type": "number"},
        {"fieldId": "shop_name",     "fieldName": "店铺名称",      "type": "text"},
        {"fieldId": "visitors",      "fieldName": "访客数",       "type": "number"},
        {"fieldId": "cart_count",    "fieldName": "加购数",       "type": "number"},
        {"fieldId": "order_count",   "fieldName": "订单数",       "type": "number"},
        {"fieldId": "sales",         "fieldName": "销售额(RUB)",  "type": "number"},
        {"fieldId": "cost",          "fieldName": "广告花费(RUB)","type": "number"},
        {"fieldId": "impressions",   "fieldName": "曝光数",       "type": "number"},
        {"fieldId": "clicks",        "fieldName": "点击数",       "type": "number"},
        {"fieldId": "ctr",           "fieldName": "点击率",       "type": "number"},
        {"fieldId": "conversion_rate","fieldName": "转化率",      "type": "number"},
        {"fieldId": "acos",          "fieldName": "ACOS",         "type": "number"},
        {"fieldId": "roas",          "fieldName": "ROAS",         "type": "number"},
    ]


FIELD_GETTERS = {
    "shops":       get_shops_fields,
    "products":    get_products_fields,
    "daily_stats": get_daily_stats_fields,
    "ad_daily":    get_ad_daily_fields,
}


# ─────────────────────────────────────────
#  数据查询 SQL
# ─────────────────────────────────────────

def query_shops(db: Session, page: int, size: int) -> tuple[list[dict], int]:
    offset = (page - 1) * size
    total = db.execute(text("SELECT COUNT(*) FROM shops")).scalar()

    rows = db.execute(text("""
        SELECT id, name, platform, currency, exchange_rate, is_active, last_sync_at
        FROM shops
        ORDER BY id
        LIMIT :limit OFFSET :offset
    """), {"limit": size, "offset": offset}).fetchall()

    records = []
    for r in rows:
        records.append({
            "id":            r[0],
            "name":          r[1] or "",
            "platform":      r[2] or "",
            "currency":      r[3] or "",
            "exchange_rate": r[4] or 0,
            "is_active":     bool(r[5]),
            "last_sync_at":  r[6] if r[6] else None,
        })
    return records, total


def query_products(db: Session, page: int, size: int) -> tuple[list[dict], int]:
    offset = (page - 1) * size
    total = db.execute(text("SELECT COUNT(*) FROM products")).scalar()

    rows = db.execute(text("""
        SELECT p.id, p.nm_id, p.sku, p.shop_id, s.name AS shop_name,
               p.name, p.owner, p.weight, p.length, p.width, p.height,
               p.purchase_price, p.commission_rate
        FROM products p
        LEFT JOIN shops s ON p.shop_id = s.id
        ORDER BY p.id
        LIMIT :limit OFFSET :offset
    """), {"limit": size, "offset": offset}).fetchall()

    records = []
    for r in rows:
        records.append({
            "id":             r[0],
            "nm_id":          r[1] or "",
            "sku":            r[2] or "",
            "shop_id":        r[3] or 0,
            "shop_name":      r[4] or "",
            "name":           r[5] or "",
            "owner":          r[6] or "",
            "weight":         r[7] or 0,
            "length":         r[8] or 0,
            "width":          r[9] or 0,
            "height":         r[10] or 0,
            "purchase_price": r[11] or 0,
            "commission_rate": r[12] or 0,
        })
    return records, total


def query_daily_stats(db: Session, page: int, size: int) -> tuple[list[dict], int]:
    """从 orders 表按 shop_id + order_date 聚合每日数据"""
    offset = (page - 1) * size

    # 总数（独立日期×店铺组合数）
    count_sql = text("""
        SELECT COUNT(DISTINCT shop_id || '-' || DATE(order_date)) FROM orders
        WHERE order_date IS NOT NULL
    """)
    total = db.execute(count_sql).scalar() or 0

    rows = db.execute(text("""
        SELECT
            0 AS id,
            DATE(o.order_date) AS date,
            o.shop_id,
            s.name AS shop_name,
            COUNT(o.id) AS order_count,
            SUM(o.total_amount) AS total_amount,
            SUM(o.commission) AS commission,
            SUM(o.logistics_fee) AS logistics_fee,
            SUM(o.profit) AS profit,
            CASE WHEN SUM(o.total_amount) > 0
                 THEN ROUND(SUM(o.profit) / SUM(o.total_amount), 4)
                 ELSE 0 END AS profit_rate
        FROM orders o
        LEFT JOIN shops s ON o.shop_id = s.id
        WHERE o.order_date IS NOT NULL
        GROUP BY o.shop_id, DATE(o.order_date)
        ORDER BY date DESC, shop_id
        LIMIT :limit OFFSET :offset
    """), {"limit": size, "offset": offset}).fetchall()

    records = []
    for r in rows:
        records.append({
            "id":           r[0],
            "date":         r[1],
            "shop_id":      r[2] or 0,
            "shop_name":    r[3] or "",
            "order_count":  r[4] or 0,
            "total_amount": round(r[5] or 0, 2),
            "commission":   round(r[6] or 0, 2),
            "logistics_fee": round(r[7] or 0, 2),
            "profit":       round(r[8] or 0, 2),
            "profit_rate":  r[9] or 0,
        })
    return records, total


def query_ad_daily(db: Session, page: int, size: int) -> tuple[list[dict], int]:
    """从 ad_records 按 product_id + shop_id + record_date 聚合每日数据"""
    offset = (page - 1) * size

    total = db.execute(text("""
        SELECT COUNT(DISTINCT product_id || '-' || shop_id || '-' || DATE(record_date))
        FROM ad_records
        WHERE record_date IS NOT NULL
    """)).scalar() or 0

    rows = db.execute(text("""
        SELECT
            0 AS id,
            DATE(a.record_date) AS date,
            a.product_id,
            p.nm_id,
            p.name AS product_name,
            a.shop_id,
            s.name AS shop_name,
            SUM(a.visitors) AS visitors,
            SUM(a.cart_count) AS cart_count,
            SUM(a.order_count) AS order_count,
            SUM(a.sales) AS sales,
            SUM(a.cost) AS cost,
            SUM(a.impressions) AS impressions,
            SUM(a.clicks) AS clicks,
            CASE WHEN SUM(a.clicks) > 0
                 THEN ROUND(SUM(a.clicks) * 1.0 / NULLIF(SUM(a.impressions), 0), 4)
                 ELSE 0 END AS ctr,
            CASE WHEN SUM(a.order_count) > 0 AND SUM(a.visitors) > 0
                 THEN ROUND(SUM(a.order_count) * 1.0 / SUM(a.visitors), 4)
                 ELSE 0 END AS conversion_rate,
            CASE WHEN SUM(a.sales) > 0
                 THEN ROUND(SUM(a.cost) / SUM(a.sales), 4)
                 ELSE 0 END AS acos,
            CASE WHEN SUM(a.cost) > 0
                 THEN ROUND(SUM(a.sales) / SUM(a.cost), 4)
                 ELSE 0 END AS roas
        FROM ad_records a
        LEFT JOIN products p ON a.product_id = p.id
        LEFT JOIN shops s ON a.shop_id = s.id
        WHERE a.record_date IS NOT NULL
        GROUP BY a.product_id, a.shop_id, DATE(a.record_date)
        ORDER BY date DESC, a.product_id
        LIMIT :limit OFFSET :offset
    """), {"limit": size, "offset": offset}).fetchall()

    records = []
    for r in rows:
        records.append({
            "id":              r[0],
            "date":            r[1],
            "product_id":      r[2] or 0,
            "nm_id":           r[3] or "",
            "product_name":    r[4] or "",
            "shop_id":         r[5] or 0,
            "shop_name":       r[6] or "",
            "visitors":        r[7] or 0,
            "cart_count":      r[8] or 0,
            "order_count":     r[9] or 0,
            "sales":           round(r[10] or 0, 2),
            "cost":            round(r[11] or 0, 2),
            "impressions":     r[12] or 0,
            "clicks":          r[13] or 0,
            "ctr":             r[14] or 0,
            "conversion_rate": r[15] or 0,
            "acos":            r[16] or 0,
            "roas":            r[17] or 0,
        })
    return records, total


QUERY_HANDLERS = {
    "shops":       query_shops,
    "products":    query_products,
    "daily_stats": query_daily_stats,
    "ad_daily":    query_ad_daily,
}


# ─────────────────────────────────────────
#  接口实现
# ─────────────────────────────────────────

@router.get("/tables")
def list_tables():
    """
    返回所有数据表清单
    GET /api/dingtalk/tables
    """
    tables = []
    for table_id, info in TABLES.items():
        tables.append({
            "tableId":    table_id,
            "name":       info["name"],
            "description": info["desc"],
        })
    return {"tables": tables}


@router.get("/tables/{table_id}")
def get_table_info(table_id: str):
    """
    返回某张表的字段定义
    GET /api/dingtalk/tables/{table_id}
    """
    if table_id not in TABLES:
        return {"error": f"table_id '{table_id}' not found"}, 404

    fields = FIELD_GETTERS[table_id]()
    return {
        "tableId":   table_id,
        "name":      TABLES[table_id]["name"],
        "fields":    fields,
    }


@router.get("/tables/{table_id}/records")
def get_records(
    table_id: str,
    page: int  = Query(1, ge=1, description="页码"),
    size: int  = Query(100, ge=1, le=500, description="每页条数"),
):
    """
    返回记录，支持分页
    GET /api/dingtalk/tables/{table_id}/records?page=1&size=100
    """
    if table_id not in TABLES:
        return {"error": f"table_id '{table_id}' not found"}, 404

    db: Session = next(get_db())
    try:
        records, total = QUERY_HANDLERS[table_id](db, page, size)
        return {
            "tableId": table_id,
            "page":    page,
            "size":    size,
            "total":   total,
            "records": records,
        }
    finally:
        db.close()
