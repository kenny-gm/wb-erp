#!/usr/bin/env python3
"""Sync WB API responses into the MySQL raw layer.

The script is conservative by default. Without --apply it only prints the plan.
The first executable batch is permission_probe: it calls a small set of
low-risk read-only endpoints and writes both success and permission failures to
the MySQL shadow raw tables.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any

import httpx
import pymysql
from pymysql.cursors import DictCursor


@dataclass(frozen=True)
class RawBatch:
    phase: str
    source_api: str
    endpoint: str
    target_table: str
    risk: str
    note: str


API_DOMAINS = {
    "common": "https://common-api.wildberries.ru",
    "content": "https://content-api.wildberries.ru",
    "marketplace": "https://marketplace-api.wildberries.ru",
    "analytics": "https://seller-analytics-api.wildberries.ru",
    "statistics": "https://statistics-api.wildberries.ru",
    "promotion": "https://advert-api.wildberries.ru",
    "finance": "https://finance-api.wildberries.ru",
    "feedbacks": "https://feedbacks-api.wildberries.ru",
    "buyer_chat": "https://buyer-chat-api.wildberries.ru",
    "returns": "https://returns-api.wildberries.ru",
}


BATCHES: list[RawBatch] = [
    RawBatch("permission_probe", "common", "/api/v1/seller-info", "wb_raw_api_responses", "low", "seller/token identity probe"),
    RawBatch("permission_probe", "content", "/content/v2/get/cards/list", "wb_raw_content_cards", "low", "first page only"),
    RawBatch("permission_probe", "promotion", "/api/advert/v2/adverts", "wb_raw_promotion_campaigns", "low", "campaign list probe"),
    RawBatch("permission_probe", "marketplace", "/api/v3/orders/new", "wb_raw_statistics_orders", "low", "new orders probe only"),
    RawBatch("permission_probe", "feedbacks", "/api/v1/questions", "wb_raw_customer_questions", "low", "take=1"),
    RawBatch("permission_probe", "feedbacks", "/api/v1/feedbacks", "wb_raw_customer_feedbacks", "low", "take=1"),
    RawBatch("permission_probe", "buyer_chat", "/api/v1/seller/chats", "wb_raw_customer_chats", "low", "limit=1"),
    RawBatch("permission_probe", "returns", "/api/v1/claims", "wb_raw_customer_returns", "low", "limit=1"),
    RawBatch("content", "content", "/content/v2/get/cards/list", "wb_raw_content_cards", "medium", "full cursor pagination"),
    RawBatch("inventory", "statistics", "/api/v1/supplier/stocks", "wb_raw_inventory_stocks", "medium", "product/barcode fallback"),
    RawBatch("inventory", "marketplace", "/api/v3/warehouses", "wb_raw_inventory_stocks", "low", "warehouse dictionary"),
    RawBatch("sales", "statistics", "/api/v1/supplier/orders", "wb_raw_statistics_orders", "medium", "official history window"),
    RawBatch("sales", "statistics", "/api/v1/supplier/sales", "wb_raw_statistics_sales", "medium", "sales/returns raw"),
    RawBatch("sales", "analytics", "/api/analytics/v3/sales-funnel/products/history", "wb_raw_analytics_product_funnel", "high", "low rate limit, nm/date windows"),
    RawBatch("ads", "promotion", "/api/advert/v2/adverts", "wb_raw_promotion_campaigns", "medium", "campaigns"),
    RawBatch("ads", "promotion", "/adv/v3/fullstats", "wb_raw_promotion_stats", "high", "50 advert ids per request"),
    RawBatch("ads", "promotion", "/adv/v1/normquery/stats", "wb_raw_promotion_keywords", "high", "keyword/search cluster stats"),
    RawBatch("customer", "feedbacks", "/api/v1/questions", "wb_raw_customer_questions", "medium", "paged"),
    RawBatch("customer", "feedbacks", "/api/v1/feedbacks", "wb_raw_customer_feedbacks", "medium", "paged"),
    RawBatch("customer", "buyer_chat", "/api/v1/seller/events", "wb_raw_customer_chats", "high", "cursor based, never reuse old cursor blindly"),
    RawBatch("customer", "returns", "/api/v1/claims", "wb_raw_customer_returns", "medium", "active/archive pages"),
    RawBatch("finance", "finance", "realization reports", "wb_raw_finance_realization_reports", "high", "financial source of truth"),
    RawBatch("finance", "finance", "documents", "wb_raw_finance_documents", "high", "documents/accounting"),
]


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


def load_wb_shops(sqlite_path: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, name, platform, currency, is_active, api_token,
                   CASE WHEN api_token IS NULL OR api_token = '' THEN 0 ELSE length(api_token) END AS token_len
            FROM shops
            WHERE platform = 'wildberries' AND is_active = 1
            ORDER BY id
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def selected_batches(phase: str) -> list[RawBatch]:
    if phase == "all":
        return BATCHES
    return [batch for batch in BATCHES if batch.phase == phase]


def permission_probe_request(batch: RawBatch) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    if batch.source_api == "content":
        return (
            "POST",
            None,
            {
                "settings": {
                    "sort": {"ascending": False},
                    "filter": {"withPhoto": -1},
                    "cursor": {"limit": 1},
                }
            },
        )
    if batch.source_api == "feedbacks" and batch.endpoint in {"/api/v1/questions", "/api/v1/feedbacks"}:
        return "GET", {"take": 1, "skip": 0, "order": "dateDesc", "isAnswered": "false"}, None
    if batch.source_api == "buyer_chat":
        return "GET", {"limit": 1, "offset": 0}, None
    if batch.source_api == "returns":
        return "GET", {"limit": 1, "offset": 0, "is_archive": "false"}, None
    return "GET", None, None


def content_cards_request(
    limit: int,
    updated_at: str | None = None,
    nm_id: int | None = None,
) -> dict[str, Any]:
    cursor: dict[str, Any] = {"limit": limit}
    if updated_at:
        cursor["updatedAt"] = updated_at
    if nm_id:
        cursor["nmID"] = nm_id

    return {
        "settings": {
            "sort": {"ascending": False},
            "filter": {"withPhoto": -1},
            "cursor": cursor,
        }
    }


def response_body(response: httpx.Response) -> Any:
    if not response.content:
        return {}
    try:
        return response.json()
    except json.JSONDecodeError:
        return {"text": response.text[:2000]}


def probe_endpoint(shop: dict[str, Any], batch: RawBatch, timeout: float) -> dict[str, Any]:
    method, params, json_data = permission_probe_request(batch)
    base_url = API_DOMAINS[batch.source_api]
    url = f"{base_url}{batch.endpoint}"
    headers = {"Authorization": shop["api_token"], "Content-Type": "application/json"}
    started_at = datetime.now(timezone.utc)

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(method, url, headers=headers, params=params, json=json_data)
        body = response_body(response)
        ok = 200 <= response.status_code < 300
        raw = {
            "ok": ok,
            "method": method,
            "url": url,
            "status_code": response.status_code,
            "request": {"params": params or {}, "json": json_data or {}},
            "response": body,
            "fetched_at": started_at.isoformat(),
        }
    except Exception as exc:
        raw = {
            "ok": False,
            "method": method,
            "url": url,
            "status_code": None,
            "request": {"params": params or {}, "json": json_data or {}},
            "error": type(exc).__name__,
            "message": str(exc)[:1000],
            "fetched_at": started_at.isoformat(),
        }

    return {
        "shop_id": shop["id"],
        "platform": "wildberries",
        "source_api": batch.source_api,
        "source_endpoint": batch.endpoint,
        "external_id": f"permission_probe:{batch.source_api}:{batch.endpoint}",
        "request_params_json": raw["request"],
        "raw_json": raw,
        "target_table": batch.target_table,
    }


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def insert_raw_rows(mysql_conn, rows: list[dict[str, Any]], sync_batch_id: str) -> None:
    sql = """
        INSERT INTO {table}
          (shop_id, platform, source_api, source_endpoint, external_id, sync_batch_id,
           request_params_json, raw_json, raw_hash)
        VALUES
          (%(shop_id)s, %(platform)s, %(source_api)s, %(source_endpoint)s, %(external_id)s,
           %(sync_batch_id)s, CAST(%(request_params_json)s AS JSON), CAST(%(raw_json)s AS JSON),
           %(raw_hash)s)
    """
    with mysql_conn.cursor() as cur:
        for row in rows:
            raw_json = json_dump(row["raw_json"])
            params_json = json_dump(row["request_params_json"])
            cur.execute(
                sql.format(table=row["target_table"]),
                {
                    "shop_id": row["shop_id"],
                    "platform": row["platform"],
                    "source_api": row["source_api"],
                    "source_endpoint": row["source_endpoint"],
                    "external_id": row["external_id"],
                    "sync_batch_id": sync_batch_id,
                    "request_params_json": params_json,
                    "raw_json": raw_json,
                    "raw_hash": hashlib.sha256(raw_json.encode("utf-8")).hexdigest(),
                },
            )
    mysql_conn.commit()


def insert_raw_rows_replace_batch(mysql_conn, rows: list[dict[str, Any]], sync_batch_id: str, table: str) -> None:
    with mysql_conn.cursor() as cur:
        cur.execute(f"DELETE FROM {table} WHERE sync_batch_id = %s", (sync_batch_id,))
    mysql_conn.commit()
    if rows:
        insert_raw_rows(mysql_conn, rows, sync_batch_id)


def count_rows_for_batch(mysql_conn, sync_batch_id: str) -> dict[str, int]:
    tables = sorted({batch.target_table for batch in BATCHES if batch.phase == "permission_probe"})
    counts: dict[str, int] = {}
    with mysql_conn.cursor() as cur:
        for table in tables:
            cur.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE sync_batch_id = %s", (sync_batch_id,))
            counts[table] = int(cur.fetchone()["count"])
    return counts


def count_table_for_batch(mysql_conn, table: str, sync_batch_id: str) -> int:
    with mysql_conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE sync_batch_id = %s", (sync_batch_id,))
        return int(cur.fetchone()["count"])


def run_permission_probe(args: argparse.Namespace, shops: list[dict[str, Any]], batches: list[RawBatch]) -> None:
    if not args.mysql_user or not args.mysql_password:
        raise SystemExit("MYSQL_USER and MYSQL_PASSWORD are required with --apply")

    sync_batch_id = args.sync_batch_id or f"permission_probe_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    rows: list[dict[str, Any]] = []
    print(f"Running WB permission probe: batch={sync_batch_id}")
    for shop in shops:
        if not shop.get("api_token"):
            print(f"  shop {shop['id']} {shop['name']}: skipped, missing token")
            continue
        for batch in batches:
            row = probe_endpoint(shop, batch, args.timeout)
            rows.append(row)
            raw = row["raw_json"]
            status = raw.get("status_code")
            ok = "OK" if raw.get("ok") else "FAIL"
            print(f"  shop {shop['id']} {batch.source_api} {batch.endpoint}: {ok} status={status}")

    mysql_conn = mysql_connect(args)
    try:
        insert_raw_rows(mysql_conn, rows, sync_batch_id)
        print("MySQL raw rows written:")
        for table, count in count_rows_for_batch(mysql_conn, sync_batch_id).items():
            print(f"  {table}: {count}")
    finally:
        mysql_conn.close()


def fetch_content_cards_page(
    shop: dict[str, Any],
    limit: int,
    timeout: float,
    updated_at: str | None = None,
    nm_id: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    endpoint = "/content/v2/get/cards/list"
    url = f"{API_DOMAINS['content']}{endpoint}"
    request_json = content_cards_request(limit=limit, updated_at=updated_at, nm_id=nm_id)
    headers = {"Authorization": shop["api_token"], "Content-Type": "application/json"}
    fetched_at = datetime.now(timezone.utc)

    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, headers=headers, params={"locale": "ru"}, json=request_json)

    body = response_body(response)
    if not (200 <= response.status_code < 300):
        raise RuntimeError(
            f"content cards failed: shop_id={shop['id']} status={response.status_code} body={json_dump(body)[:1000]}"
        )
    if not isinstance(body, dict):
        raise RuntimeError(f"content cards invalid body: shop_id={shop['id']} type={type(body).__name__}")

    cards = body.get("cards") or []
    cursor = body.get("cursor") or {}
    if not isinstance(cards, list):
        raise RuntimeError(f"content cards invalid cards: shop_id={shop['id']} type={type(cards).__name__}")
    if not isinstance(cursor, dict):
        cursor = {}

    page_meta = {
        "method": "POST",
        "url": url,
        "status_code": response.status_code,
        "request": {"params": {"locale": "ru"}, "json": request_json},
        "cursor": cursor,
        "cards_count": len(cards),
        "fetched_at": fetched_at.isoformat(),
    }
    return page_meta, cards, cursor


def run_content_cards(args: argparse.Namespace, shops: list[dict[str, Any]]) -> None:
    if not args.mysql_user or not args.mysql_password:
        raise SystemExit("MYSQL_USER and MYSQL_PASSWORD are required with --apply")

    sync_batch_id = args.sync_batch_id or f"content_cards_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    limit = max(1, min(args.page_limit, 100))
    target_table = "wb_raw_content_cards"
    rows: list[dict[str, Any]] = []
    total_pages = 0
    print(f"Running WB content cards sync: batch={sync_batch_id} limit={limit} max_pages={args.max_pages}")

    for shop in shops:
        if not shop.get("api_token"):
            print(f"  shop {shop['id']} {shop['name']}: skipped, missing token")
            continue

        updated_at: str | None = None
        nm_id: int | None = None
        seen_page_keys: set[tuple[str | None, int | None]] = set()

        for page in range(1, args.max_pages + 1):
            page_key = (updated_at, nm_id)
            if page_key in seen_page_keys:
                print(f"  shop {shop['id']} page {page}: stopped, repeated cursor")
                break
            seen_page_keys.add(page_key)

            page_meta, cards, cursor = fetch_content_cards_page(
                shop=shop,
                limit=limit,
                timeout=args.timeout,
                updated_at=updated_at,
                nm_id=nm_id,
            )
            total_pages += 1
            print(
                f"  shop {shop['id']} {shop['name']} page {page}: "
                f"cards={len(cards)} cursor_total={cursor.get('total')}"
            )

            for card in cards:
                card_nm_id = card.get("nmID") or card.get("nmId") or card.get("nm_id")
                external_id = str(card_nm_id) if card_nm_id is not None else hashlib.sha256(
                    json_dump(card).encode("utf-8")
                ).hexdigest()
                request_context = {
                    **page_meta["request"],
                    "page": page,
                    "cursor_response": cursor,
                }
                rows.append(
                    {
                        "shop_id": shop["id"],
                        "platform": "wildberries",
                        "source_api": "content",
                        "source_endpoint": "/content/v2/get/cards/list",
                        "external_id": external_id,
                        "request_params_json": request_context,
                        "raw_json": {
                            "card": card,
                            "page": page,
                            "page_meta": page_meta,
                        },
                        "target_table": target_table,
                    }
                )

            if len(cards) < limit:
                break
            next_updated_at = cursor.get("updatedAt")
            next_nm_id = cursor.get("nmID") or cursor.get("nmId")
            if not next_updated_at or not next_nm_id:
                break
            updated_at = str(next_updated_at)
            nm_id = int(next_nm_id)

    mysql_conn = mysql_connect(args)
    try:
        insert_raw_rows_replace_batch(mysql_conn, rows, sync_batch_id, target_table)
        count = count_table_for_batch(mysql_conn, target_table, sync_batch_id)
        print("MySQL content card rows written:")
        print(f"  {target_table}: {count}")
        print(f"  pages_fetched: {total_pages}")
    finally:
        mysql_conn.close()


def fetch_inventory_endpoint(
    shop: dict[str, Any],
    source_api: str,
    endpoint: str,
    timeout: float,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{API_DOMAINS[source_api]}{endpoint}"
    headers = {"Authorization": shop["api_token"], "Content-Type": "application/json"}
    fetched_at = datetime.now(timezone.utc)

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url, headers=headers, params=params)
        body = response_body(response)
        ok = 200 <= response.status_code < 300
        return {
            "ok": ok,
            "method": "GET",
            "url": url,
            "status_code": response.status_code,
            "request": {"params": params or {}, "json": {}},
            "response": body,
            "fetched_at": fetched_at.isoformat(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "method": "GET",
            "url": url,
            "status_code": None,
            "request": {"params": params or {}, "json": {}},
            "error": type(exc).__name__,
            "message": str(exc)[:1000],
            "fetched_at": fetched_at.isoformat(),
        }


def inventory_payload_items(raw: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
    if not raw.get("ok"):
        return []
    response = raw.get("response")
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        for key in keys:
            value = response.get(key)
            if isinstance(value, list):
                return value
    return []


def inventory_external_id(prefix: str, item: Any) -> str:
    if not isinstance(item, dict):
        return f"{prefix}:{hashlib.sha256(json_dump(item).encode('utf-8')).hexdigest()}"

    parts = [
        item.get("warehouseId") or item.get("warehouseID") or item.get("id"),
        item.get("nmId") or item.get("nmID"),
        item.get("barcode"),
        item.get("supplierArticle"),
        item.get("techSize"),
    ]
    key = ":".join(str(part) for part in parts if part not in (None, ""))
    if key:
        return f"{prefix}:{key}"
    return f"{prefix}:{hashlib.sha256(json_dump(item).encode('utf-8')).hexdigest()}"


def build_inventory_rows(
    shop: dict[str, Any],
    source_api: str,
    endpoint: str,
    raw: dict[str, Any],
    item_keys: tuple[str, ...],
    external_prefix: str,
) -> list[dict[str, Any]]:
    target_table = "wb_raw_inventory_stocks"
    items = inventory_payload_items(raw, item_keys)

    if not raw.get("ok") or not items:
        return [
            {
                "shop_id": shop["id"],
                "platform": "wildberries",
                "source_api": source_api,
                "source_endpoint": endpoint,
                "external_id": f"{external_prefix}:response",
                "request_params_json": raw["request"],
                "raw_json": raw,
                "target_table": target_table,
            }
        ]

    rows: list[dict[str, Any]] = []
    for item in items:
        rows.append(
            {
                "shop_id": shop["id"],
                "platform": "wildberries",
                "source_api": source_api,
                "source_endpoint": endpoint,
                "external_id": inventory_external_id(external_prefix, item),
                "request_params_json": raw["request"],
                "raw_json": {
                    "item": item,
                    "response_meta": {
                        "method": raw["method"],
                        "url": raw["url"],
                        "status_code": raw["status_code"],
                        "fetched_at": raw["fetched_at"],
                    },
                },
                "target_table": target_table,
            }
        )
    return rows


def run_inventory(args: argparse.Namespace, shops: list[dict[str, Any]]) -> None:
    if not args.mysql_user or not args.mysql_password:
        raise SystemExit("MYSQL_USER and MYSQL_PASSWORD are required with --apply")

    sync_batch_id = args.sync_batch_id or f"inventory_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    target_table = "wb_raw_inventory_stocks"
    rows: list[dict[str, Any]] = []
    print(f"Running WB inventory raw sync: batch={sync_batch_id}")

    for shop in shops:
        if not shop.get("api_token"):
            print(f"  shop {shop['id']} {shop['name']}: skipped, missing token")
            continue

        stocks_raw = fetch_inventory_endpoint(
            shop=shop,
            source_api="statistics",
            endpoint="/api/v1/supplier/stocks",
            timeout=args.timeout,
            params={"dateFrom": "2020-01-01"},
        )
        stock_items = inventory_payload_items(stocks_raw, ("stocks", "data"))
        rows.extend(
            build_inventory_rows(
                shop=shop,
                source_api="statistics",
                endpoint="/api/v1/supplier/stocks",
                raw=stocks_raw,
                item_keys=("stocks", "data"),
                external_prefix="statistics_stocks",
            )
        )
        stock_status = stocks_raw.get("status_code")
        stock_ok = "OK" if stocks_raw.get("ok") else "FAIL"
        print(f"  shop {shop['id']} statistics stocks: {stock_ok} status={stock_status} rows={len(stock_items)}")

        warehouses_raw = fetch_inventory_endpoint(
            shop=shop,
            source_api="marketplace",
            endpoint="/api/v3/warehouses",
            timeout=args.timeout,
        )
        warehouse_items = inventory_payload_items(warehouses_raw, ("warehouses", "data"))
        rows.extend(
            build_inventory_rows(
                shop=shop,
                source_api="marketplace",
                endpoint="/api/v3/warehouses",
                raw=warehouses_raw,
                item_keys=("warehouses", "data"),
                external_prefix="marketplace_warehouses",
            )
        )
        warehouse_status = warehouses_raw.get("status_code")
        warehouse_ok = "OK" if warehouses_raw.get("ok") else "FAIL"
        print(
            f"  shop {shop['id']} marketplace warehouses: "
            f"{warehouse_ok} status={warehouse_status} rows={len(warehouse_items)}"
        )

    mysql_conn = mysql_connect(args)
    try:
        insert_raw_rows_replace_batch(mysql_conn, rows, sync_batch_id, target_table)
        count = count_table_for_batch(mysql_conn, target_table, sync_batch_id)
        print("MySQL inventory raw rows written:")
        print(f"  {target_table}: {count}")
    finally:
        mysql_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan WB raw API sync batches")
    parser.add_argument("--sqlite-path", default="/app/db/wb_erp.db")
    parser.add_argument(
        "--phase",
        choices=["permission_probe", "content", "inventory", "sales", "ads", "customer", "finance", "all"],
        default="permission_probe",
    )
    parser.add_argument("--shop-id", type=int)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--page-limit", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--sync-batch-id", default="")
    parser.add_argument("--mysql-host", default=os.getenv("MYSQL_HOST", "wb-erp-mysql"))
    parser.add_argument("--mysql-port", default=int(os.getenv("MYSQL_PORT", "3306")), type=int)
    parser.add_argument("--mysql-db", default=os.getenv("MYSQL_DATABASE", "wb_erp_shadow"))
    parser.add_argument("--mysql-user", default=os.getenv("MYSQL_USER", ""))
    parser.add_argument("--mysql-password", default=os.getenv("MYSQL_PASSWORD", ""))
    parser.add_argument("--apply", action="store_true", help="Call WB read-only endpoints and write MySQL shadow raw rows")
    args = parser.parse_args()

    shops = load_wb_shops(args.sqlite_path)
    if args.shop_id:
        shops = [shop for shop in shops if int(shop["id"]) == args.shop_id]

    batches = selected_batches(args.phase)
    print("WB raw API sync plan")
    print(f"  phase: {args.phase}")
    print(f"  shops: {len(shops)}")
    for shop in shops:
        print(f"    - {shop['id']} {shop['name']} currency={shop['currency']} token_len={shop['token_len']}")
    print(f"  days: {args.days}")
    print(f"  max_pages: {args.max_pages}")
    print(f"  planned endpoints: {len(batches)}")
    for batch in batches:
        print(f"    - [{batch.risk}] {batch.source_api} {batch.endpoint} -> {batch.target_table} ({batch.note})")

    if args.apply:
        if args.phase == "permission_probe":
            run_permission_probe(args, shops, batches)
            return
        if args.phase == "content":
            run_content_cards(args, shops)
            return
        if args.phase == "inventory":
            run_inventory(args, shops)
            return
        raise SystemExit("--apply is currently allowed only for --phase permission_probe, content, or inventory")
        return
    print("dry-run only: no WB API calls, no MySQL writes")


if __name__ == "__main__":
    main()
