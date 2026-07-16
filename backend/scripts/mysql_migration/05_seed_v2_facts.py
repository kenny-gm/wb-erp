#!/usr/bin/env python3
"""Seed MySQL v2 fact tables from the legacy SQLite database.

This script is scoped for the shadow MySQL database. It is dry-run by default;
use --apply only after dimensions have been seeded and validated.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import pymysql
from pymysql.cursors import DictCursor


AD_CNY_RUB_CUTOFF = date(2026, 7, 15)


def decimal_value(value: Any, default: str = "0") -> Decimal:
    if value in (None, ""):
        return Decimal(default)
    return Decimal(str(value))


def money(value: Any) -> Decimal:
    return decimal_value(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def date_value(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)[:10]).date()


def mysql_connect(args: argparse.Namespace):
    return pymysql.connect(
        host=args.mysql_host,
        port=args.mysql_port,
        user=args.mysql_user,
        password=args.mysql_password,
        database=args.mysql_db,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


def sqlite_rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params))


def fetch_cny_rate(conn: sqlite3.Connection) -> Decimal:
    row = conn.execute("SELECT value FROM system_settings WHERE key = 'cny_to_rub' LIMIT 1").fetchone()
    if not row:
        return Decimal("1")
    return decimal_value(row["value"], "1")


def latest_data_window(conn: sqlite3.Connection, days: int) -> tuple[str, str]:
    rows = sqlite_rows(
        conn,
        """
        SELECT MAX(max_date) AS max_date
        FROM (
          SELECT MAX(date(order_date)) AS max_date FROM orders
          UNION ALL
          SELECT MAX(date(record_date)) AS max_date FROM ad_records
          UNION ALL
          SELECT MAX(date) AS max_date FROM ad_keyword_stats
        )
        """,
    )
    max_date = date_value(rows[0]["max_date"])
    if not max_date:
        raise RuntimeError("No source data found for fact migration")
    start_date = max_date - timedelta(days=days - 1)
    return start_date.isoformat(), max_date.isoformat()


def load_dimension_maps(mysql_conn) -> dict[str, Any]:
    with mysql_conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              p.id AS product_id,
              p.legacy_product_id,
              p.shop_id,
              p.nm_id,
              s.legacy_shop_id,
              s.platform AS shop_platform,
              s.currency AS shop_currency,
              g.product_group_id
            FROM dim_product p
            JOIN dim_shop s ON s.id = p.shop_id
            LEFT JOIN dim_product_group_member g ON g.product_id = p.id
            """
        )
        rows = cur.fetchall()

    by_legacy_product: dict[int, dict[str, Any]] = {}
    by_shop_nm: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        if row["legacy_product_id"] is not None:
            by_legacy_product[int(row["legacy_product_id"])] = row
        by_shop_nm[(int(row["legacy_shop_id"]), str(row["nm_id"]))] = row
    return {
        "by_legacy_product": by_legacy_product,
        "by_shop_nm": by_shop_nm,
    }


def resolve_product(maps: dict[str, Any], legacy_product_id: Any, legacy_shop_id: Any, nm_id: Any) -> dict[str, Any] | None:
    if legacy_product_id not in (None, ""):
        item = maps["by_legacy_product"].get(int(legacy_product_id))
        if item:
            return item
    if legacy_shop_id not in (None, "") and nm_id not in (None, ""):
        return maps["by_shop_nm"].get((int(legacy_shop_id), str(nm_id)))
    return None


def rub_amount(amount: Decimal, currency: str, rate: Decimal) -> Decimal:
    if (currency or "RUB").upper() == "CNY":
        return money(amount * rate)
    return money(amount)


def ad_rub_amount(amount: Decimal, currency: str, platform: str, biz_date: date, rate: Decimal) -> Decimal:
    if (currency or "RUB").upper() != "CNY":
        return money(amount)
    if (platform or "").lower() == "yandex" or biz_date >= AD_CNY_RUB_CUTOFF:
        return money(amount * rate)
    return money(amount)


def build_product_daily(sqlite_conn: sqlite3.Connection, maps: dict[str, Any], start_date: str, end_date: str, rate: Decimal) -> list[dict[str, Any]]:
    rows = sqlite_rows(
        sqlite_conn,
        """
        SELECT
          shop_id AS legacy_shop_id,
          product_id AS legacy_product_id,
          date(record_date) AS biz_date,
          SUM(order_count) AS order_count,
          SUM(sales) AS sales_amount
        FROM ad_records
        WHERE ad_type = 'product_analytics'
          AND date(record_date) BETWEEN ? AND ?
        GROUP BY shop_id, product_id, date(record_date)
        """,
        (start_date, end_date),
    )
    result = []
    for row in rows:
        product = resolve_product(maps, row["legacy_product_id"], row["legacy_shop_id"], None)
        if not product:
            continue
        amount = money(row["sales_amount"])
        currency = product["shop_currency"] or "RUB"
        result.append(
            {
                "shop_id": product["shop_id"],
                "product_id": product["product_id"],
                "product_group_id": product["product_group_id"],
                "nm_id": str(product["nm_id"]),
                "biz_date": row["biz_date"],
                "order_count": int(row["order_count"] or 0),
                "sales_amount": amount,
                "sales_currency": currency,
                "sales_amount_rub": rub_amount(amount, currency, rate),
                "return_count": 0,
                "cancel_count": 0,
            }
        )
    return result


def build_product_funnel(sqlite_conn: sqlite3.Connection, maps: dict[str, Any], start_date: str, end_date: str, rate: Decimal) -> list[dict[str, Any]]:
    rows = sqlite_rows(
        sqlite_conn,
        """
        SELECT
          shop_id AS legacy_shop_id,
          product_id AS legacy_product_id,
          date(record_date) AS biz_date,
          SUM(impressions) AS impressions,
          SUM(visitors) AS visitors,
          SUM(clicks) AS clicks,
          SUM(CASE WHEN COALESCE(cart_count, 0) != 0 THEN cart_count ELSE COALESCE(atbs, 0) END) AS cart_count,
          SUM(order_count) AS order_count,
          SUM(sales) AS sales_amount
        FROM ad_records
        WHERE ad_type = 'product_analytics'
          AND date(record_date) BETWEEN ? AND ?
        GROUP BY shop_id, product_id, date(record_date)
        """,
        (start_date, end_date),
    )
    result = []
    for row in rows:
        product = resolve_product(maps, row["legacy_product_id"], row["legacy_shop_id"], None)
        if not product:
            continue
        amount = money(row["sales_amount"])
        currency = product["shop_currency"] or "RUB"
        result.append(
            {
                "shop_id": product["shop_id"],
                "product_id": product["product_id"],
                "product_group_id": product["product_group_id"],
                "nm_id": str(product["nm_id"]),
                "biz_date": row["biz_date"],
                "impressions": int(row["impressions"] or 0),
                "visitors": int(row["visitors"] or 0),
                "clicks": int(row["clicks"] or 0),
                "cart_count": int(row["cart_count"] or 0),
                "order_count": int(row["order_count"] or 0),
                "sales_amount": amount,
                "sales_currency": currency,
                "sales_amount_rub": rub_amount(amount, currency, rate),
            }
        )
    return result


def build_ad_daily(sqlite_conn: sqlite3.Connection, maps: dict[str, Any], start_date: str, end_date: str, rate: Decimal) -> list[dict[str, Any]]:
    rows = sqlite_rows(
        sqlite_conn,
        """
        SELECT
          shop_id AS legacy_shop_id,
          product_id AS legacy_product_id,
          advert_id,
          date(record_date) AS biz_date,
          payment_type,
          placements,
          SUM(impressions) AS impressions,
          SUM(clicks) AS clicks,
          SUM(visitors) AS visitors,
          SUM(CASE WHEN COALESCE(cart_count, 0) != 0 THEN cart_count ELSE COALESCE(atbs, 0) END) AS cart_count,
          SUM(order_count) AS order_count,
          SUM(cost) AS ad_cost,
          SUM(sales) AS sales_amount
        FROM ad_records
        WHERE ad_type = 'advertising'
          AND date(record_date) BETWEEN ? AND ?
        GROUP BY shop_id, product_id, advert_id, date(record_date), payment_type, placements
        """,
        (start_date, end_date),
    )
    result = []
    for row in rows:
        product = resolve_product(maps, row["legacy_product_id"], row["legacy_shop_id"], None)
        if not product:
            continue
        biz_date = date_value(row["biz_date"])
        if not biz_date:
            continue
        ad_cost = money(row["ad_cost"])
        sales_amount = money(row["sales_amount"])
        currency = product["shop_currency"] or "RUB"
        platform = product["shop_platform"] or "wildberries"
        result.append(
            {
                "shop_id": product["shop_id"],
                "product_id": product["product_id"],
                "product_group_id": product["product_group_id"],
                "nm_id": str(product["nm_id"]),
                "advert_id": int(row["advert_id"] or 0),
                "biz_date": row["biz_date"],
                "ad_type": "advertising",
                "payment_type": row["payment_type"] or "",
                "placements": row["placements"] or "",
                "impressions": int(row["impressions"] or 0),
                "clicks": int(row["clicks"] or 0),
                "visitors": int(row["visitors"] or 0),
                "cart_count": int(row["cart_count"] or 0),
                "order_count": int(row["order_count"] or 0),
                "ad_cost": ad_cost,
                "ad_cost_currency": currency,
                "ad_cost_rub": ad_rub_amount(ad_cost, currency, platform, biz_date, rate),
                "sales_amount": sales_amount,
                "sales_amount_rub": rub_amount(sales_amount, currency, rate),
            }
        )
    return result


def build_ad_keyword_daily(sqlite_conn: sqlite3.Connection, maps: dict[str, Any], start_date: str, end_date: str, rate: Decimal) -> list[dict[str, Any]]:
    rows = sqlite_rows(
        sqlite_conn,
        """
        SELECT
          shop_id AS legacy_shop_id,
          product_id AS legacy_product_id,
          advert_id,
          nm_id,
          keyword,
          platform,
          date AS biz_date,
          SUM(views) AS impressions,
          SUM(clicks) AS clicks,
          SUM(COALESCE(order_count, orders, 0)) AS order_count,
          SUM(COALESCE(atbs, 0)) AS cart_count,
          SUM(spend) AS spend,
          AVG(avg_position) AS avg_position,
          payment_type
        FROM ad_keyword_stats
        WHERE date(date) BETWEEN ? AND ?
        GROUP BY shop_id, product_id, advert_id, nm_id, keyword, platform, date, payment_type
        """,
        (start_date, end_date),
    )
    result = []
    for row in rows:
        product = resolve_product(maps, row["legacy_product_id"], row["legacy_shop_id"], row["nm_id"])
        if not product:
            continue
        biz_date = date_value(row["biz_date"])
        if not biz_date:
            continue
        spend = money(row["spend"])
        currency = product["shop_currency"] or "RUB"
        platform_name = product["shop_platform"] or "wildberries"
        result.append(
            {
                "shop_id": product["shop_id"],
                "product_id": product["product_id"],
                "product_group_id": product["product_group_id"],
                "advert_id": int(row["advert_id"] or 0),
                "nm_id": str(product["nm_id"]),
                "keyword": row["keyword"] or "",
                "platform": row["platform"] or "search",
                "biz_date": row["biz_date"],
                "impressions": int(row["impressions"] or 0),
                "clicks": int(row["clicks"] or 0),
                "order_count": int(row["order_count"] or 0),
                "cart_count": int(row["cart_count"] or 0),
                "spend": spend,
                "spend_currency": currency,
                "spend_rub": ad_rub_amount(spend, currency, platform_name, biz_date, rate),
                "avg_position": decimal_value(row["avg_position"]) if row["avg_position"] is not None else None,
                "payment_type": row["payment_type"] or "",
            }
        )
    return result


def upsert_facts(mysql_conn, payload: dict[str, list[dict[str, Any]]]) -> None:
    with mysql_conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO fact_product_daily
              (shop_id, product_id, product_group_id, nm_id, biz_date, order_count,
               sales_amount, sales_currency, sales_amount_rub, return_count, cancel_count)
            VALUES
              (%(shop_id)s, %(product_id)s, %(product_group_id)s, %(nm_id)s, %(biz_date)s,
               %(order_count)s, %(sales_amount)s, %(sales_currency)s, %(sales_amount_rub)s,
               %(return_count)s, %(cancel_count)s)
            ON DUPLICATE KEY UPDATE
              product_id=VALUES(product_id), product_group_id=VALUES(product_group_id),
              order_count=VALUES(order_count), sales_amount=VALUES(sales_amount),
              sales_currency=VALUES(sales_currency), sales_amount_rub=VALUES(sales_amount_rub),
              return_count=VALUES(return_count), cancel_count=VALUES(cancel_count)
            """,
            payload["fact_product_daily"],
        )
        cur.executemany(
            """
            INSERT INTO fact_product_funnel_daily
              (shop_id, product_id, product_group_id, nm_id, biz_date, impressions, visitors,
               clicks, cart_count, order_count, sales_amount, sales_currency, sales_amount_rub)
            VALUES
              (%(shop_id)s, %(product_id)s, %(product_group_id)s, %(nm_id)s, %(biz_date)s,
               %(impressions)s, %(visitors)s, %(clicks)s, %(cart_count)s, %(order_count)s,
               %(sales_amount)s, %(sales_currency)s, %(sales_amount_rub)s)
            ON DUPLICATE KEY UPDATE
              product_id=VALUES(product_id), product_group_id=VALUES(product_group_id),
              impressions=VALUES(impressions), visitors=VALUES(visitors), clicks=VALUES(clicks),
              cart_count=VALUES(cart_count), order_count=VALUES(order_count),
              sales_amount=VALUES(sales_amount), sales_currency=VALUES(sales_currency),
              sales_amount_rub=VALUES(sales_amount_rub)
            """,
            payload["fact_product_funnel_daily"],
        )
        cur.executemany(
            """
            INSERT INTO fact_ad_daily
              (shop_id, product_id, product_group_id, nm_id, advert_id, biz_date, ad_type,
               payment_type, placements, impressions, clicks, visitors, cart_count, order_count,
               ad_cost, ad_cost_currency, ad_cost_rub, sales_amount, sales_amount_rub)
            VALUES
              (%(shop_id)s, %(product_id)s, %(product_group_id)s, %(nm_id)s, %(advert_id)s,
               %(biz_date)s, %(ad_type)s, %(payment_type)s, %(placements)s, %(impressions)s,
               %(clicks)s, %(visitors)s, %(cart_count)s, %(order_count)s, %(ad_cost)s,
               %(ad_cost_currency)s, %(ad_cost_rub)s, %(sales_amount)s, %(sales_amount_rub)s)
            ON DUPLICATE KEY UPDATE
              product_id=VALUES(product_id), product_group_id=VALUES(product_group_id),
              ad_type=VALUES(ad_type), impressions=VALUES(impressions), clicks=VALUES(clicks),
              visitors=VALUES(visitors), cart_count=VALUES(cart_count),
              order_count=VALUES(order_count), ad_cost=VALUES(ad_cost),
              ad_cost_currency=VALUES(ad_cost_currency), ad_cost_rub=VALUES(ad_cost_rub),
              sales_amount=VALUES(sales_amount), sales_amount_rub=VALUES(sales_amount_rub)
            """,
            payload["fact_ad_daily"],
        )
        cur.executemany(
            """
            INSERT INTO fact_ad_keyword_daily
              (shop_id, product_id, product_group_id, advert_id, nm_id, keyword, platform,
               biz_date, impressions, clicks, order_count, cart_count, spend, spend_currency,
               spend_rub, avg_position, payment_type)
            VALUES
              (%(shop_id)s, %(product_id)s, %(product_group_id)s, %(advert_id)s, %(nm_id)s,
               %(keyword)s, %(platform)s, %(biz_date)s, %(impressions)s, %(clicks)s,
               %(order_count)s, %(cart_count)s, %(spend)s, %(spend_currency)s, %(spend_rub)s,
               %(avg_position)s, %(payment_type)s)
            ON DUPLICATE KEY UPDATE
              product_id=VALUES(product_id), product_group_id=VALUES(product_group_id),
              impressions=VALUES(impressions), clicks=VALUES(clicks), order_count=VALUES(order_count),
              cart_count=VALUES(cart_count), spend=VALUES(spend), spend_currency=VALUES(spend_currency),
              spend_rub=VALUES(spend_rub), avg_position=VALUES(avg_position),
              payment_type=VALUES(payment_type)
            """,
            payload["fact_ad_keyword_daily"],
        )
    mysql_conn.commit()


def count_mysql(mysql_conn) -> dict[str, int]:
    tables = [
        "fact_product_daily",
        "fact_product_funnel_daily",
        "fact_ad_daily",
        "fact_ad_keyword_daily",
    ]
    with mysql_conn.cursor() as cur:
        result = {}
        for table in tables:
            cur.execute(f"SELECT COUNT(*) AS count FROM {table}")
            result[table] = int(cur.fetchone()["count"])
    return result


def print_payload_summary(payload: dict[str, list[dict[str, Any]]], start_date: str, end_date: str) -> None:
    print(f"Prepared fact payload for {start_date} to {end_date}:")
    for name, rows in payload.items():
        print(f"  {name}: {len(rows)}")
    print("  dashboard source check:")
    print(f"    product sales native: {sum((r['sales_amount'] for r in payload['fact_product_daily']), Decimal('0'))}")
    print(f"    product sales rub: {sum((r['sales_amount_rub'] for r in payload['fact_product_daily']), Decimal('0'))}")
    print(f"    funnel visitors: {sum(r['visitors'] for r in payload['fact_product_funnel_daily'])}")
    print(f"    funnel cart_count: {sum(r['cart_count'] for r in payload['fact_product_funnel_daily'])}")
    print(f"    ad cost native: {sum((r['ad_cost'] for r in payload['fact_ad_daily']), Decimal('0'))}")
    print(f"    ad cost rub: {sum((r['ad_cost_rub'] for r in payload['fact_ad_daily']), Decimal('0'))}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite-path", default="/app/db/wb_erp.db")
    parser.add_argument("--mysql-host", default=os.getenv("MYSQL_HOST", "wb-erp-mysql"))
    parser.add_argument("--mysql-port", default=int(os.getenv("MYSQL_PORT", "3306")), type=int)
    parser.add_argument("--mysql-db", default=os.getenv("MYSQL_DATABASE", "wb_erp_shadow"))
    parser.add_argument("--mysql-user", default=os.getenv("MYSQL_USER", ""))
    parser.add_argument("--mysql-password", default=os.getenv("MYSQL_PASSWORD", ""))
    parser.add_argument("--days", default=7, type=int)
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.apply and (not args.mysql_user or not args.mysql_password):
        raise SystemExit("MYSQL_USER and MYSQL_PASSWORD are required with --apply")

    sqlite_conn = sqlite3.connect(args.sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    start_date, end_date = (args.start_date, args.end_date)
    if not start_date or not end_date:
        start_date, end_date = latest_data_window(sqlite_conn, args.days)

    rate = fetch_cny_rate(sqlite_conn)
    mysql_conn = mysql_connect(args)
    try:
        maps = load_dimension_maps(mysql_conn)
        payload = {
            "fact_product_daily": build_product_daily(sqlite_conn, maps, start_date, end_date, rate),
            "fact_product_funnel_daily": build_product_funnel(sqlite_conn, maps, start_date, end_date, rate),
            "fact_ad_daily": build_ad_daily(sqlite_conn, maps, start_date, end_date, rate),
            "fact_ad_keyword_daily": build_ad_keyword_daily(sqlite_conn, maps, start_date, end_date, rate),
        }
        print_payload_summary(payload, start_date, end_date)

        if not args.apply:
            print("DRY RUN: no rows written.")
            return

        upsert_facts(mysql_conn, payload)
        print("MySQL fact counts:")
        for table, count in count_mysql(mysql_conn).items():
            print(f"  {table}: {count}")
    finally:
        mysql_conn.close()


if __name__ == "__main__":
    main()
