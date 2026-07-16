#!/usr/bin/env python3
"""Seed customer-signal and sync-health facts into the MySQL shadow database.

The script only writes aggregated facts. It does not migrate customer-service
message bodies or raw payloads.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pymysql
from pymysql.cursors import DictCursor


def date_value(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)[:10]).date()


def decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


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
        autocommit=False,
    )


def latest_data_window(conn: sqlite3.Connection, days: int) -> tuple[str, str]:
    row = conn.execute(
        """
        SELECT MAX(max_date) AS max_date
        FROM (
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
        raise RuntimeError("No customer/sync source data found")
    return (max_date - timedelta(days=days - 1)).isoformat(), max_date.isoformat()


def load_dimension_maps(mysql_conn) -> dict[str, Any]:
    with mysql_conn.cursor() as cur:
        cur.execute("SELECT id, legacy_shop_id, platform FROM dim_shop WHERE legacy_shop_id IS NOT NULL")
        shops = {int(row["legacy_shop_id"]): row for row in cur.fetchall()}
        cur.execute(
            """
            SELECT
              p.id AS product_id,
              p.legacy_product_id,
              p.shop_id,
              p.nm_id,
              s.legacy_shop_id,
              g.product_group_id
            FROM dim_product p
            JOIN dim_shop s ON s.id = p.shop_id
            LEFT JOIN dim_product_group_member g ON g.product_id = p.id
            """
        )
        product_rows = cur.fetchall()

    by_legacy_product: dict[int, dict[str, Any]] = {}
    by_shop_nm: dict[tuple[int, str], dict[str, Any]] = {}
    for row in product_rows:
        if row["legacy_product_id"] is not None:
            by_legacy_product[int(row["legacy_product_id"])] = row
        by_shop_nm[(int(row["legacy_shop_id"]), str(row["nm_id"]))] = row
    return {
        "shops": shops,
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


def source_api_for_sync_type(sync_type: str) -> str:
    value = (sync_type or "").lower()
    if value.startswith("customer_service"):
        return "user_communication"
    if "keyword" in value or "ad" in value:
        return "promotion"
    if "product" in value:
        return "content"
    if "order" in value or "sales" in value:
        return "statistics"
    if "yandex" in value:
        return "yandex"
    return "legacy"


def build_customer_signal(sqlite_conn: sqlite3.Connection, maps: dict[str, Any], start_date: str, end_date: str) -> list[dict[str, Any]]:
    rows = sqlite_rows(
        sqlite_conn,
        """
        SELECT
          shop_id AS legacy_shop_id,
          product_id AS legacy_product_id,
          COALESCE(nm_id, '') AS nm_id,
          date(COALESCE(external_created_at, created_at)) AS biz_date,
          SUM(CASE WHEN channel = 'question' THEN 1 ELSE 0 END) AS question_count,
          SUM(CASE WHEN channel = 'feedback' THEN 1 ELSE 0 END) AS feedback_count,
          SUM(CASE WHEN channel = 'chat' THEN 1 ELSE 0 END) AS chat_count,
          SUM(CASE WHEN channel = 'return_claim' THEN 1 ELSE 0 END) AS return_claim_count,
          SUM(CASE WHEN channel = 'feedback' AND COALESCE(rating, 5) <= 3 THEN 1 ELSE 0 END) AS negative_feedback_count,
          AVG(CASE WHEN channel = 'feedback' AND rating IS NOT NULL THEN rating ELSE NULL END) AS avg_rating,
          SUM(CASE WHEN COALESCE(reply_status, '') = 'unanswered' THEN 1 ELSE 0 END) AS unanswered_count,
          SUM(CASE WHEN COALESCE(is_overdue, 0) = 1 THEN 1 ELSE 0 END) AS overdue_count
        FROM customer_service_items
        WHERE date(COALESCE(external_created_at, created_at)) BETWEEN ? AND ?
        GROUP BY shop_id, product_id, COALESCE(nm_id, ''), date(COALESCE(external_created_at, created_at))
        """,
        (start_date, end_date),
    )
    result = []
    for row in rows:
        shop = maps["shops"].get(int(row["legacy_shop_id"] or 0))
        if not shop:
            continue
        product = resolve_product(maps, row["legacy_product_id"], row["legacy_shop_id"], row["nm_id"])
        result.append(
            {
                "shop_id": shop["id"],
                "product_id": product["product_id"] if product else None,
                "product_group_id": product["product_group_id"] if product else None,
                "nm_id": str(product["nm_id"] if product else (row["nm_id"] or "")),
                "biz_date": row["biz_date"],
                "question_count": int(row["question_count"] or 0),
                "feedback_count": int(row["feedback_count"] or 0),
                "chat_count": int(row["chat_count"] or 0),
                "return_claim_count": int(row["return_claim_count"] or 0),
                "negative_feedback_count": int(row["negative_feedback_count"] or 0),
                "avg_rating": decimal_or_none(row["avg_rating"]),
                "unanswered_count": int(row["unanswered_count"] or 0),
                "overdue_count": int(row["overdue_count"] or 0),
            }
        )
    return result


def build_sync_health(sqlite_conn: sqlite3.Connection, maps: dict[str, Any], start_date: str, end_date: str) -> list[dict[str, Any]]:
    rows = sqlite_rows(
        sqlite_conn,
        """
        SELECT
          id,
          shop_id AS legacy_shop_id,
          sync_type,
          status,
          records_count,
          started_at,
          finished_at,
          message
        FROM sync_logs
        WHERE date(COALESCE(finished_at, started_at)) BETWEEN ? AND ?
        ORDER BY id
        """,
        (start_date, end_date),
    )
    result = []
    for row in rows:
        shop = maps["shops"].get(int(row["legacy_shop_id"] or 0))
        if not shop:
            continue
        result.append(
            {
                "shop_id": shop["id"],
                "source_api": source_api_for_sync_type(row["sync_type"]),
                "sync_type": row["sync_type"] or "unknown",
                "status": row["status"] or "unknown",
                "records_count": int(row["records_count"] or 0),
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "error_message": None if (row["status"] or "") == "success" else row["message"],
                "sync_batch_id": f"legacy:{row['id']}",
            }
        )
    return result


def upsert_customer_signal(mysql_conn, rows: list[dict[str, Any]]) -> None:
    with mysql_conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO fact_customer_signal_daily
              (shop_id, product_id, product_group_id, nm_id, biz_date, question_count,
               feedback_count, chat_count, return_claim_count, negative_feedback_count,
               avg_rating, unanswered_count, overdue_count)
            VALUES
              (%(shop_id)s, %(product_id)s, %(product_group_id)s, %(nm_id)s, %(biz_date)s,
               %(question_count)s, %(feedback_count)s, %(chat_count)s, %(return_claim_count)s,
               %(negative_feedback_count)s, %(avg_rating)s, %(unanswered_count)s, %(overdue_count)s)
            ON DUPLICATE KEY UPDATE
              product_id=VALUES(product_id), product_group_id=VALUES(product_group_id),
              question_count=VALUES(question_count), feedback_count=VALUES(feedback_count),
              chat_count=VALUES(chat_count), return_claim_count=VALUES(return_claim_count),
              negative_feedback_count=VALUES(negative_feedback_count), avg_rating=VALUES(avg_rating),
              unanswered_count=VALUES(unanswered_count), overdue_count=VALUES(overdue_count)
            """,
            rows,
        )


def replace_sync_health(mysql_conn, rows: list[dict[str, Any]], start_date: str, end_date: str) -> None:
    with mysql_conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM fact_sync_health
            WHERE date(COALESCE(finished_at, started_at, created_at)) BETWEEN %s AND %s
            """,
            (start_date, end_date),
        )
        cur.executemany(
            """
            INSERT INTO fact_sync_health
              (shop_id, source_api, sync_type, status, records_count, started_at,
               finished_at, error_message, sync_batch_id)
            VALUES
              (%(shop_id)s, %(source_api)s, %(sync_type)s, %(status)s, %(records_count)s,
               %(started_at)s, %(finished_at)s, %(error_message)s, %(sync_batch_id)s)
            """,
            rows,
        )


def count_mysql(mysql_conn) -> dict[str, int]:
    with mysql_conn.cursor() as cur:
        result = {}
        for table in ["fact_customer_signal_daily", "fact_sync_health"]:
            cur.execute(f"SELECT COUNT(*) AS count FROM {table}")
            result[table] = int(cur.fetchone()["count"])
        return result


def print_summary(payload: dict[str, list[dict[str, Any]]], start_date: str, end_date: str) -> None:
    print(f"Prepared customer/sync payload for {start_date} to {end_date}:")
    print(f"  fact_customer_signal_daily: {len(payload['fact_customer_signal_daily'])}")
    print(f"  fact_sync_health: {len(payload['fact_sync_health'])}")
    print("  customer totals:")
    print(f"    questions: {sum(r['question_count'] for r in payload['fact_customer_signal_daily'])}")
    print(f"    feedbacks: {sum(r['feedback_count'] for r in payload['fact_customer_signal_daily'])}")
    print(f"    chats: {sum(r['chat_count'] for r in payload['fact_customer_signal_daily'])}")
    print(f"    return_claims: {sum(r['return_claim_count'] for r in payload['fact_customer_signal_daily'])}")
    print(f"    unanswered: {sum(r['unanswered_count'] for r in payload['fact_customer_signal_daily'])}")
    print(f"    overdue: {sum(r['overdue_count'] for r in payload['fact_customer_signal_daily'])}")
    print(f"    sync_records_count: {sum(r['records_count'] for r in payload['fact_sync_health'])}")


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

    mysql_conn = mysql_connect(args)
    try:
        maps = load_dimension_maps(mysql_conn)
        payload = {
            "fact_customer_signal_daily": build_customer_signal(sqlite_conn, maps, start_date, end_date),
            "fact_sync_health": build_sync_health(sqlite_conn, maps, start_date, end_date),
        }
        print_summary(payload, start_date, end_date)
        if not args.apply:
            print("DRY RUN: no rows written.")
            return

        upsert_customer_signal(mysql_conn, payload["fact_customer_signal_daily"])
        replace_sync_health(mysql_conn, payload["fact_sync_health"], start_date, end_date)
        mysql_conn.commit()
        print("MySQL customer/sync fact counts:")
        for table, count in count_mysql(mysql_conn).items():
            print(f"  {table}: {count}")
    finally:
        mysql_conn.close()


if __name__ == "__main__":
    main()
