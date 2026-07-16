#!/usr/bin/env python3
"""Validate SQLite -> MySQL shadow migration results.

The script is read-only. It compares legacy SQLite source data with the MySQL
v2 shadow schema that has already been seeded by the migration scripts.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import pymysql
from pymysql.cursors import DictCursor


AD_CNY_RUB_CUTOFF = date(2026, 7, 15)
MONEY_TOLERANCE = Decimal("0.02")
COUNT_TOLERANCE = 0


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def sqlite_rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params))


def mysql_connect(args: argparse.Namespace):
    return pymysql.connect(
        host=args.mysql_host,
        port=args.mysql_port,
        user=args.mysql_user,
        password=args.mysql_password,
        database=args.mysql_db,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
    )


def mysql_rows(conn, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def scalar_sqlite(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return row[0]


def scalar_mysql(conn, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = mysql_rows(conn, sql, params)[0]
    return next(iter(row.values()))


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


def latest_data_window(conn: sqlite3.Connection, days: int) -> tuple[str, str]:
    row = conn.execute(
        """
        SELECT MAX(max_date) AS max_date
        FROM (
          SELECT MAX(date(record_date)) AS max_date FROM ad_records
          UNION ALL
          SELECT MAX(date(date)) AS max_date FROM ad_keyword_stats
          UNION ALL
          SELECT MAX(date(COALESCE(external_created_at, created_at))) AS max_date
          FROM customer_service_items
          UNION ALL
          SELECT MAX(date(COALESCE(finished_at, started_at))) AS max_date
          FROM sync_logs
        )
        """
    ).fetchone()
    max_date = date_value(row["max_date"])
    if not max_date:
        raise RuntimeError("No source data found for validation")
    start_date = max_date - timedelta(days=days - 1)
    return start_date.isoformat(), max_date.isoformat()


def fetch_cny_rate(conn: sqlite3.Connection) -> Decimal:
    value = scalar_sqlite(conn, "SELECT value FROM system_settings WHERE key = 'cny_to_rub' LIMIT 1")
    return decimal_value(value, "1")


def add_check(results: list[CheckResult], name: str, ok: bool, detail: str) -> None:
    results.append(CheckResult(name=name, ok=ok, detail=detail))


def compare_int(results: list[CheckResult], name: str, expected: int, actual: int) -> None:
    add_check(
        results,
        name,
        abs(expected - actual) <= COUNT_TOLERANCE,
        f"expected={expected}, actual={actual}",
    )


def compare_money(results: list[CheckResult], name: str, expected: Any, actual: Any) -> None:
    expected_money = money(expected)
    actual_money = money(actual)
    add_check(
        results,
        name,
        abs(expected_money - actual_money) <= MONEY_TOLERANCE,
        f"expected={expected_money}, actual={actual_money}",
    )


def sqlite_dim_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "dim_shop": int(scalar_sqlite(conn, "SELECT COUNT(*) FROM shops") or 0),
        "dim_owner": int(
            scalar_sqlite(
                conn,
                "SELECT COUNT(DISTINCT TRIM(owner)) FROM products WHERE owner IS NOT NULL AND TRIM(owner) != ''",
            )
            or 0
        ),
        "dim_product": int(scalar_sqlite(conn, "SELECT COUNT(*) FROM products") or 0),
        "dim_product_group": int(
            scalar_sqlite(
                conn,
                """
                SELECT COUNT(*) FROM (
                  SELECT DISTINCT TRIM(COALESCE(NULLIF(custom_name, ''), NULLIF(name, ''), nm_id)) AS group_name
                  FROM products
                  WHERE TRIM(COALESCE(NULLIF(custom_name, ''), NULLIF(name, ''), nm_id)) != ''
                )
                """,
            )
            or 0
        ),
        "dim_product_group_member": int(scalar_sqlite(conn, "SELECT COUNT(*) FROM products") or 0),
    }


def mysql_table_counts(conn, tables: list[str], start_date: str | None = None, end_date: str | None = None) -> dict[str, int]:
    result = {}
    date_columns = {
        "fact_product_daily": "biz_date",
        "fact_product_funnel_daily": "biz_date",
        "fact_ad_daily": "biz_date",
        "fact_ad_keyword_daily": "biz_date",
        "fact_customer_signal_daily": "biz_date",
        "fact_sync_health": "date(COALESCE(finished_at, started_at, created_at))",
        "view_ops_overview": "biz_date",
        "view_ops_customer_signals": "biz_date",
    }
    for table in tables:
        if start_date and end_date and table in date_columns:
            result[table] = int(
                scalar_mysql(
                    conn,
                    f"SELECT COUNT(*) AS count FROM {table} WHERE {date_columns[table]} BETWEEN %s AND %s",
                    (start_date, end_date),
                )
                or 0
            )
        else:
            result[table] = int(scalar_mysql(conn, f"SELECT COUNT(*) AS count FROM {table}") or 0)
    return result


def sqlite_fact_counts(conn: sqlite3.Connection, start_date: str, end_date: str) -> dict[str, int]:
    return {
        "fact_product_daily": int(
            scalar_sqlite(
                conn,
                """
                SELECT COUNT(*) FROM (
                  SELECT ar.shop_id, p.nm_id, date(ar.record_date)
                  FROM ad_records ar
                  JOIN products p ON p.id = ar.product_id
                  WHERE ar.ad_type = 'product_analytics'
                    AND date(ar.record_date) BETWEEN ? AND ?
                  GROUP BY ar.shop_id, p.nm_id, date(ar.record_date)
                )
                """,
                (start_date, end_date),
            )
            or 0
        ),
        "fact_product_funnel_daily": int(
            scalar_sqlite(
                conn,
                """
                SELECT COUNT(*) FROM (
                  SELECT ar.shop_id, p.nm_id, date(ar.record_date)
                  FROM ad_records ar
                  JOIN products p ON p.id = ar.product_id
                  WHERE ar.ad_type = 'product_analytics'
                    AND date(ar.record_date) BETWEEN ? AND ?
                  GROUP BY ar.shop_id, p.nm_id, date(ar.record_date)
                )
                """,
                (start_date, end_date),
            )
            or 0
        ),
        "fact_ad_daily": int(
            scalar_sqlite(
                conn,
                """
                SELECT COUNT(*) FROM (
                  SELECT ar.shop_id, p.nm_id, COALESCE(ar.advert_id, 0), date(ar.record_date),
                         COALESCE(ar.payment_type, ''), COALESCE(ar.placements, '')
                  FROM ad_records ar
                  JOIN products p ON p.id = ar.product_id
                  WHERE ar.ad_type = 'advertising'
                    AND date(ar.record_date) BETWEEN ? AND ?
                  GROUP BY ar.shop_id, p.nm_id, COALESCE(ar.advert_id, 0), date(ar.record_date),
                           COALESCE(ar.payment_type, ''), COALESCE(ar.placements, '')
                )
                """,
                (start_date, end_date),
            )
            or 0
        ),
        "fact_ad_keyword_daily": int(
            scalar_sqlite(
                conn,
                """
                SELECT COUNT(*) FROM (
                  SELECT aks.shop_id, p.nm_id, COALESCE(aks.advert_id, 0), COALESCE(aks.keyword, ''),
                         COALESCE(aks.platform, 'search'), date(aks.date)
                  FROM ad_keyword_stats aks
                  JOIN products p
                    ON p.id = aks.product_id
                    OR (p.shop_id = aks.shop_id AND CAST(p.nm_id AS TEXT) = CAST(aks.nm_id AS TEXT))
                  WHERE date(aks.date) BETWEEN ? AND ?
                  GROUP BY aks.shop_id, p.nm_id, COALESCE(aks.advert_id, 0), COALESCE(aks.keyword, ''),
                           COALESCE(aks.platform, 'search'), date(aks.date)
                )
                """,
                (start_date, end_date),
            )
            or 0
        ),
        "fact_customer_signal_daily": int(
            scalar_sqlite(
                conn,
                """
                SELECT COUNT(*) FROM (
                  SELECT c.shop_id, COALESCE(p.nm_id, c.nm_id, ''), date(COALESCE(c.external_created_at, c.created_at))
                  FROM customer_service_items c
                  JOIN shops s ON s.id = c.shop_id
                  LEFT JOIN products p ON p.id = c.product_id
                  WHERE date(COALESCE(c.external_created_at, c.created_at)) BETWEEN ? AND ?
                  GROUP BY c.shop_id, COALESCE(p.nm_id, c.nm_id, ''), date(COALESCE(c.external_created_at, c.created_at))
                )
                """,
                (start_date, end_date),
            )
            or 0
        ),
        "fact_sync_health": int(
            scalar_sqlite(
                conn,
                """
                SELECT COUNT(*)
                FROM sync_logs l
                JOIN shops s ON s.id = l.shop_id
                WHERE date(COALESCE(l.finished_at, l.started_at)) BETWEEN ? AND ?
                """,
                (start_date, end_date),
            )
            or 0
        ),
    }


def sqlite_product_aggregates(conn: sqlite3.Connection, start_date: str, end_date: str, rate: Decimal) -> dict[str, Decimal | int]:
    row = conn.execute(
        """
        SELECT
          SUM(ar.sales) AS sales_native,
          SUM(CASE WHEN UPPER(COALESCE(s.currency, 'RUB')) = 'CNY'
                   THEN ar.sales * ?
                   ELSE ar.sales END) AS sales_rub,
          SUM(ar.order_count) AS order_count
        FROM ad_records ar
        JOIN products p ON p.id = ar.product_id
        JOIN shops s ON s.id = ar.shop_id
        WHERE ar.ad_type = 'product_analytics'
          AND date(ar.record_date) BETWEEN ? AND ?
        """,
        (str(rate), start_date, end_date),
    ).fetchone()
    funnel = conn.execute(
        """
        SELECT
          SUM(visitors) AS visitors,
          SUM(CASE WHEN COALESCE(cart_count, 0) != 0 THEN cart_count ELSE COALESCE(atbs, 0) END) AS cart_count
        FROM ad_records ar
        JOIN products p ON p.id = ar.product_id
        WHERE ar.ad_type = 'product_analytics'
          AND date(ar.record_date) BETWEEN ? AND ?
        """,
        (start_date, end_date),
    ).fetchone()
    return {
        "sales_native": money(row["sales_native"]),
        "sales_rub": money(row["sales_rub"]),
        "order_count": int(row["order_count"] or 0),
        "visitors": int(funnel["visitors"] or 0),
        "cart_count": int(funnel["cart_count"] or 0),
    }


def mysql_product_aggregates(conn, start_date: str, end_date: str) -> dict[str, Decimal | int]:
    product = mysql_rows(
        conn,
        """
        SELECT
          SUM(sales_amount) AS sales_native,
          SUM(sales_amount_rub) AS sales_rub,
          SUM(order_count) AS order_count
        FROM fact_product_daily
        WHERE biz_date BETWEEN %s AND %s
        """,
        (start_date, end_date),
    )[0]
    funnel = mysql_rows(
        conn,
        """
        SELECT SUM(visitors) AS visitors, SUM(cart_count) AS cart_count
        FROM fact_product_funnel_daily
        WHERE biz_date BETWEEN %s AND %s
        """,
        (start_date, end_date),
    )[0]
    return {
        "sales_native": money(product["sales_native"]),
        "sales_rub": money(product["sales_rub"]),
        "order_count": int(product["order_count"] or 0),
        "visitors": int(funnel["visitors"] or 0),
        "cart_count": int(funnel["cart_count"] or 0),
    }


def sqlite_ad_aggregates(conn: sqlite3.Connection, start_date: str, end_date: str, rate: Decimal) -> dict[str, Decimal | int]:
    row = conn.execute(
        """
        SELECT
          SUM(ar.cost) AS ad_cost_native,
          SUM(
            CASE
              WHEN UPPER(COALESCE(s.currency, 'RUB')) = 'CNY'
               AND (LOWER(COALESCE(s.platform, '')) = 'yandex' OR date(ar.record_date) >= ?)
              THEN ar.cost * ?
              ELSE ar.cost
            END
          ) AS ad_cost_rub,
          SUM(ar.order_count) AS ad_order_count
        FROM ad_records ar
        JOIN products p ON p.id = ar.product_id
        JOIN shops s ON s.id = ar.shop_id
        WHERE ar.ad_type = 'advertising'
          AND date(ar.record_date) BETWEEN ? AND ?
        """,
        (AD_CNY_RUB_CUTOFF.isoformat(), str(rate), start_date, end_date),
    ).fetchone()
    return {
        "ad_cost_native": money(row["ad_cost_native"]),
        "ad_cost_rub": money(row["ad_cost_rub"]),
        "ad_order_count": int(row["ad_order_count"] or 0),
    }


def mysql_ad_aggregates(conn, start_date: str, end_date: str) -> dict[str, Decimal | int]:
    row = mysql_rows(
        conn,
        """
        SELECT
          SUM(ad_cost) AS ad_cost_native,
          SUM(ad_cost_rub) AS ad_cost_rub,
          SUM(order_count) AS ad_order_count
        FROM fact_ad_daily
        WHERE biz_date BETWEEN %s AND %s
        """,
        (start_date, end_date),
    )[0]
    return {
        "ad_cost_native": money(row["ad_cost_native"]),
        "ad_cost_rub": money(row["ad_cost_rub"]),
        "ad_order_count": int(row["ad_order_count"] or 0),
    }


def sqlite_customer_aggregates(conn: sqlite3.Connection, start_date: str, end_date: str) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
          SUM(CASE WHEN channel = 'question' THEN 1 ELSE 0 END) AS question_count,
          SUM(CASE WHEN channel = 'feedback' THEN 1 ELSE 0 END) AS feedback_count,
          SUM(CASE WHEN channel = 'chat' THEN 1 ELSE 0 END) AS chat_count,
          SUM(CASE WHEN channel = 'return_claim' THEN 1 ELSE 0 END) AS return_claim_count,
          SUM(CASE WHEN COALESCE(reply_status, '') = 'unanswered' THEN 1 ELSE 0 END) AS unanswered_count,
          SUM(CASE WHEN COALESCE(is_overdue, 0) = 1 THEN 1 ELSE 0 END) AS overdue_count
        FROM customer_service_items
        WHERE date(COALESCE(external_created_at, created_at)) BETWEEN ? AND ?
        """,
        (start_date, end_date),
    ).fetchone()
    sync_row = conn.execute(
        """
        SELECT COUNT(*) AS sync_log_count, SUM(records_count) AS sync_records_count
        FROM sync_logs
        WHERE date(COALESCE(finished_at, started_at)) BETWEEN ? AND ?
        """,
        (start_date, end_date),
    ).fetchone()
    return {
        "question_count": int(row["question_count"] or 0),
        "feedback_count": int(row["feedback_count"] or 0),
        "chat_count": int(row["chat_count"] or 0),
        "return_claim_count": int(row["return_claim_count"] or 0),
        "unanswered_count": int(row["unanswered_count"] or 0),
        "overdue_count": int(row["overdue_count"] or 0),
        "sync_log_count": int(sync_row["sync_log_count"] or 0),
        "sync_records_count": int(sync_row["sync_records_count"] or 0),
    }


def mysql_customer_aggregates(conn, start_date: str, end_date: str) -> dict[str, int]:
    row = mysql_rows(
        conn,
        """
        SELECT
          SUM(question_count) AS question_count,
          SUM(feedback_count) AS feedback_count,
          SUM(chat_count) AS chat_count,
          SUM(return_claim_count) AS return_claim_count,
          SUM(unanswered_count) AS unanswered_count,
          SUM(overdue_count) AS overdue_count
        FROM fact_customer_signal_daily
        WHERE biz_date BETWEEN %s AND %s
        """,
        (start_date, end_date),
    )[0]
    sync_row = mysql_rows(
        conn,
        """
        SELECT COUNT(*) AS sync_log_count, SUM(records_count) AS sync_records_count
        FROM fact_sync_health
        WHERE date(COALESCE(finished_at, started_at, created_at)) BETWEEN %s AND %s
        """,
        (start_date, end_date),
    )[0]
    return {
        "question_count": int(row["question_count"] or 0),
        "feedback_count": int(row["feedback_count"] or 0),
        "chat_count": int(row["chat_count"] or 0),
        "return_claim_count": int(row["return_claim_count"] or 0),
        "unanswered_count": int(row["unanswered_count"] or 0),
        "overdue_count": int(row["overdue_count"] or 0),
        "sync_log_count": int(sync_row["sync_log_count"] or 0),
        "sync_records_count": int(sync_row["sync_records_count"] or 0),
    }


def validate(sqlite_conn: sqlite3.Connection, mysql_conn, start_date: str, end_date: str) -> list[CheckResult]:
    results: list[CheckResult] = []
    rate = fetch_cny_rate(sqlite_conn)

    mysql_dimensions = mysql_table_counts(
        mysql_conn,
        ["dim_shop", "dim_owner", "dim_product", "dim_product_group", "dim_product_group_member"],
    )
    for table, expected in sqlite_dim_counts(sqlite_conn).items():
        compare_int(results, f"{table} row count", expected, mysql_dimensions[table])

    mysql_facts = mysql_table_counts(
        mysql_conn,
        [
            "fact_product_daily",
            "fact_product_funnel_daily",
            "fact_ad_daily",
            "fact_ad_keyword_daily",
            "fact_customer_signal_daily",
            "fact_sync_health",
        ],
        start_date,
        end_date,
    )
    for table, expected in sqlite_fact_counts(sqlite_conn, start_date, end_date).items():
        compare_int(results, f"{table} row count ({start_date}..{end_date})", expected, mysql_facts[table])

    product_expected = sqlite_product_aggregates(sqlite_conn, start_date, end_date, rate)
    product_actual = mysql_product_aggregates(mysql_conn, start_date, end_date)
    for key in ["sales_native", "sales_rub"]:
        compare_money(results, f"product aggregate {key}", product_expected[key], product_actual[key])
    for key in ["order_count", "visitors", "cart_count"]:
        compare_int(results, f"product aggregate {key}", int(product_expected[key]), int(product_actual[key]))

    ad_expected = sqlite_ad_aggregates(sqlite_conn, start_date, end_date, rate)
    ad_actual = mysql_ad_aggregates(mysql_conn, start_date, end_date)
    for key in ["ad_cost_native", "ad_cost_rub"]:
        compare_money(results, f"ad aggregate {key}", ad_expected[key], ad_actual[key])
    compare_int(results, "ad aggregate ad_order_count", int(ad_expected["ad_order_count"]), int(ad_actual["ad_order_count"]))

    customer_expected = sqlite_customer_aggregates(sqlite_conn, start_date, end_date)
    customer_actual = mysql_customer_aggregates(mysql_conn, start_date, end_date)
    for key, expected in customer_expected.items():
        compare_int(results, f"customer/sync aggregate {key}", expected, customer_actual[key])

    duplicate_checks = {
        "dim_product duplicate shop_id+nm_id": """
          SELECT COUNT(*) AS count FROM (
            SELECT shop_id, nm_id, COUNT(*) c FROM dim_product GROUP BY shop_id, nm_id HAVING c > 1
          ) d
        """,
        "fact_product_daily duplicate key": """
          SELECT COUNT(*) AS count FROM (
            SELECT shop_id, nm_id, biz_date, COUNT(*) c
            FROM fact_product_daily GROUP BY shop_id, nm_id, biz_date HAVING c > 1
          ) d
        """,
        "fact_ad_daily duplicate key": """
          SELECT COUNT(*) AS count FROM (
            SELECT shop_id, advert_id, nm_id, biz_date, COALESCE(payment_type, ''), COALESCE(placements, ''), COUNT(*) c
            FROM fact_ad_daily
            GROUP BY shop_id, advert_id, nm_id, biz_date, COALESCE(payment_type, ''), COALESCE(placements, '')
            HAVING c > 1
          ) d
        """,
        "fact_customer_signal_daily duplicate key": """
          SELECT COUNT(*) AS count FROM (
            SELECT shop_id, COALESCE(nm_id, ''), biz_date, COUNT(*) c
            FROM fact_customer_signal_daily
            GROUP BY shop_id, COALESCE(nm_id, ''), biz_date HAVING c > 1
          ) d
        """,
    }
    for name, sql in duplicate_checks.items():
        compare_int(results, name, 0, int(scalar_mysql(mysql_conn, sql) or 0))

    view_counts = mysql_table_counts(
        mysql_conn,
        ["view_ops_overview", "view_ops_customer_signals"],
        start_date,
        end_date,
    )
    expected_overview_rows = int(
        scalar_mysql(
            mysql_conn,
            """
            SELECT COUNT(*) AS count FROM (
              SELECT biz_date, shop_id
              FROM fact_product_daily
              WHERE biz_date BETWEEN %s AND %s
              GROUP BY biz_date, shop_id
            ) d
            """,
            (start_date, end_date),
        )
        or 0
    )
    compare_int(results, "view_ops_overview row count", expected_overview_rows, view_counts["view_ops_overview"])
    compare_int(
        results,
        "view_ops_customer_signals row count",
        mysql_facts["fact_customer_signal_daily"],
        view_counts["view_ops_customer_signals"],
    )

    backend_db_url = os.getenv("DATABASE_URL", "")
    if backend_db_url:
        add_check(
            results,
            "runtime DATABASE_URL remains SQLite",
            backend_db_url.startswith("sqlite"),
            f"DATABASE_URL={backend_db_url}",
        )

    return results


def print_results(results: list[CheckResult], start_date: str, end_date: str) -> None:
    print(f"MySQL shadow migration validation window: {start_date} to {end_date}")
    failed = 0
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        if not result.ok:
            failed += 1
        print(f"[{status}] {result.name}: {result.detail}")
    print(f"Summary: {len(results) - failed} passed, {failed} failed, {len(results)} total")
    if failed:
        raise SystemExit(1)


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
    args = parser.parse_args()

    if not args.mysql_user or not args.mysql_password:
        raise SystemExit("MYSQL_USER and MYSQL_PASSWORD are required for validation")

    sqlite_conn = sqlite3.connect(args.sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    start_date, end_date = (args.start_date, args.end_date)
    if not start_date or not end_date:
        start_date, end_date = latest_data_window(sqlite_conn, args.days)

    mysql_conn = mysql_connect(args)
    try:
        results = validate(sqlite_conn, mysql_conn, start_date, end_date)
        print_results(results, start_date, end_date)
    finally:
        mysql_conn.close()
        sqlite_conn.close()


if __name__ == "__main__":
    main()
