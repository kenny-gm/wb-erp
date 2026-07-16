#!/usr/bin/env python3
"""Seed MySQL v2 dimension tables from the legacy SQLite database.

The script is dry-run by default. Use --apply only for the shadow MySQL
database, never for production cutover without a fresh backup and validation.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from collections import defaultdict
from decimal import Decimal
from typing import Any

import pymysql
from pymysql.cursors import DictCursor


def sqlite_rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params))


def decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def bool_int(value: Any, default: int = 1) -> int:
    if value is None:
        return default
    return 1 if bool(value) else 0


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


def fetch_cny_rate(conn: sqlite3.Connection) -> Decimal | None:
    row = conn.execute(
        "SELECT value FROM system_settings WHERE key = 'cny_to_rub' LIMIT 1"
    ).fetchone()
    if not row:
        return None
    return decimal_or_none(row["value"])


def build_payload(sqlite_conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    cny_rate = fetch_cny_rate(sqlite_conn)

    shops = []
    for row in sqlite_rows(sqlite_conn, "SELECT * FROM shops ORDER BY id"):
        shops.append(
            {
                "legacy_shop_id": row["id"],
                "platform": row["platform"] or "wildberries",
                "name": row["name"],
                "currency": row["currency"] or "RUB",
                "cny_to_rub_rate": cny_rate if (row["currency"] or "").upper() == "CNY" else None,
                "sync_enabled": bool_int(row["sync_enabled"]),
                "is_active": bool_int(row["is_active"]),
            }
        )

    users_by_name = {
        row["username"]: row
        for row in sqlite_rows(sqlite_conn, "SELECT * FROM users ORDER BY id")
        if row["username"]
    }
    owner_names = {
        row["owner"].strip()
        for row in sqlite_rows(
            sqlite_conn,
            "SELECT DISTINCT owner FROM products WHERE owner IS NOT NULL AND TRIM(owner) != ''",
        )
    }
    owners = []
    for owner_name in sorted(owner_names):
        user = users_by_name.get(owner_name)
        owners.append(
            {
                "owner_name": owner_name,
                "user_id": user["id"] if user else None,
                "role": user["role"] if user else None,
                "allowed_shops_json": user["allowed_shops"] if user else None,
                "is_active": bool_int(user["is_active"], default=1) if user else 1,
            }
        )

    products = []
    group_owner_candidates: dict[str, list[str]] = defaultdict(list)
    for row in sqlite_rows(sqlite_conn, "SELECT * FROM products ORDER BY id"):
        group_name = (row["custom_name"] or row["name"] or row["nm_id"] or "").strip()
        if row["owner"] and group_name:
            group_owner_candidates[group_name].append(row["owner"])
        products.append(
            {
                "legacy_product_id": row["id"],
                "legacy_shop_id": row["shop_id"],
                "nm_id": str(row["nm_id"]),
                "sku": row["sku"],
                "name": row["name"],
                "custom_name": row["custom_name"],
                "owner": row["owner"],
                "length_cm": decimal_or_none(row["length"]),
                "width_cm": decimal_or_none(row["width"]),
                "height_cm": decimal_or_none(row["height"]),
                "weight_kg": decimal_or_none(row["weight"]),
                "purchase_price_cny": decimal_or_none(row["purchase_price"]),
                "shipping_price_cny": decimal_or_none(row["shipping_price"]),
                "group_name": group_name,
            }
        )

    groups = []
    for group_name in sorted({p["group_name"] for p in products if p["group_name"]}):
        owners_for_group = [owner for owner in group_owner_candidates[group_name] if owner]
        owner = sorted(set(owners_for_group))[0] if owners_for_group else None
        groups.append({"group_name": group_name, "owner": owner})

    return {
        "shops": shops,
        "owners": owners,
        "products": products,
        "groups": groups,
    }


def upsert_dimensions(mysql_conn, payload: dict[str, list[dict[str, Any]]]) -> None:
    with mysql_conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO dim_shop
              (legacy_shop_id, platform, name, currency, cny_to_rub_rate, sync_enabled, is_active)
            VALUES
              (%(legacy_shop_id)s, %(platform)s, %(name)s, %(currency)s, %(cny_to_rub_rate)s,
               %(sync_enabled)s, %(is_active)s)
            ON DUPLICATE KEY UPDATE
              platform=VALUES(platform), name=VALUES(name), currency=VALUES(currency),
              cny_to_rub_rate=VALUES(cny_to_rub_rate), sync_enabled=VALUES(sync_enabled),
              is_active=VALUES(is_active)
            """,
            payload["shops"],
        )

        cur.executemany(
            """
            INSERT INTO dim_owner
              (owner_name, user_id, role, allowed_shops_json, is_active)
            VALUES
              (%(owner_name)s, %(user_id)s, %(role)s, %(allowed_shops_json)s, %(is_active)s)
            ON DUPLICATE KEY UPDATE
              user_id=VALUES(user_id), role=VALUES(role),
              allowed_shops_json=VALUES(allowed_shops_json), is_active=VALUES(is_active)
            """,
            payload["owners"],
        )

        cur.executemany(
            """
            INSERT INTO dim_product_group (group_name, owner)
            VALUES (%(group_name)s, %(owner)s)
            ON DUPLICATE KEY UPDATE owner=VALUES(owner), status='active'
            """,
            payload["groups"],
        )

        shop_map = {}
        cur.execute("SELECT id, legacy_shop_id FROM dim_shop WHERE legacy_shop_id IS NOT NULL")
        for row in cur.fetchall():
            shop_map[row["legacy_shop_id"]] = row["id"]

        products = []
        for item in payload["products"]:
            shop_id = shop_map.get(item["legacy_shop_id"])
            if not shop_id:
                raise RuntimeError(f"Missing dim_shop for legacy shop {item['legacy_shop_id']}")
            products.append({**item, "shop_id": shop_id})

        cur.executemany(
            """
            INSERT INTO dim_product
              (legacy_product_id, shop_id, nm_id, sku, name, custom_name, owner,
               length_cm, width_cm, height_cm, weight_kg, purchase_price_cny, shipping_price_cny)
            VALUES
              (%(legacy_product_id)s, %(shop_id)s, %(nm_id)s, %(sku)s, %(name)s, %(custom_name)s,
               %(owner)s, %(length_cm)s, %(width_cm)s, %(height_cm)s, %(weight_kg)s,
               %(purchase_price_cny)s, %(shipping_price_cny)s)
            ON DUPLICATE KEY UPDATE
              shop_id=VALUES(shop_id), nm_id=VALUES(nm_id), sku=VALUES(sku), name=VALUES(name),
              custom_name=VALUES(custom_name), owner=VALUES(owner), length_cm=VALUES(length_cm),
              width_cm=VALUES(width_cm), height_cm=VALUES(height_cm), weight_kg=VALUES(weight_kg),
              purchase_price_cny=VALUES(purchase_price_cny), shipping_price_cny=VALUES(shipping_price_cny)
            """,
            products,
        )

        cur.execute("SELECT id, group_name FROM dim_product_group")
        group_map = {row["group_name"]: row["id"] for row in cur.fetchall()}
        cur.execute("SELECT id, legacy_product_id, shop_id, nm_id FROM dim_product")
        product_map = {row["legacy_product_id"]: row for row in cur.fetchall()}

        first_product_by_group: dict[int, int] = {}
        members = []
        for item in products:
            group_id = group_map.get(item["group_name"])
            product = product_map.get(item["legacy_product_id"])
            if not group_id or not product:
                continue
            first_product_by_group.setdefault(group_id, product["id"])
            members.append(
                {
                    "product_group_id": group_id,
                    "product_id": product["id"],
                    "shop_id": product["shop_id"],
                    "nm_id": product["nm_id"],
                    "is_primary": 1 if first_product_by_group[group_id] == product["id"] else 0,
                }
            )

        cur.executemany(
            """
            INSERT INTO dim_product_group_member
              (product_group_id, product_id, shop_id, nm_id, is_primary)
            VALUES
              (%(product_group_id)s, %(product_id)s, %(shop_id)s, %(nm_id)s, %(is_primary)s)
            ON DUPLICATE KEY UPDATE
              shop_id=VALUES(shop_id), nm_id=VALUES(nm_id), is_primary=VALUES(is_primary)
            """,
            members,
        )
    mysql_conn.commit()


def count_mysql(mysql_conn) -> dict[str, int]:
    tables = [
        "dim_shop",
        "dim_owner",
        "dim_product",
        "dim_product_group",
        "dim_product_group_member",
    ]
    with mysql_conn.cursor() as cur:
        result = {}
        for table in tables:
            cur.execute(f"SELECT COUNT(*) AS count FROM {table}")
            result[table] = int(cur.fetchone()["count"])
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite-path", default="/app/db/wb_erp.db")
    parser.add_argument("--mysql-host", default=os.getenv("MYSQL_HOST", "wb-erp-mysql"))
    parser.add_argument("--mysql-port", default=int(os.getenv("MYSQL_PORT", "3306")), type=int)
    parser.add_argument("--mysql-db", default=os.getenv("MYSQL_DATABASE", "wb_erp_shadow"))
    parser.add_argument("--mysql-user", default=os.getenv("MYSQL_USER", ""))
    parser.add_argument("--mysql-password", default=os.getenv("MYSQL_PASSWORD", ""))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.apply and (not args.mysql_user or not args.mysql_password):
        raise SystemExit("MYSQL_USER and MYSQL_PASSWORD are required with --apply")

    sqlite_conn = sqlite3.connect(args.sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    payload = build_payload(sqlite_conn)

    print("Prepared dimension payload:")
    print(f"  dim_shop: {len(payload['shops'])}")
    print(f"  dim_owner: {len(payload['owners'])}")
    print(f"  dim_product: {len(payload['products'])}")
    print(f"  dim_product_group: {len(payload['groups'])}")
    print(f"  dim_product_group_member: {len(payload['products'])}")

    if not args.apply:
        print("DRY RUN: no rows written.")
        return

    mysql_conn = mysql_connect(args)
    try:
        upsert_dimensions(mysql_conn, payload)
        print("MySQL dimension counts:")
        for table, count in count_mysql(mysql_conn).items():
            print(f"  {table}: {count}")
    finally:
        mysql_conn.close()


if __name__ == "__main__":
    main()
