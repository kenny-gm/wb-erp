# MySQL Cutover Runbook - 2026-07-17

This runbook is a command checklist for a future MySQL cutover rehearsal or production cutover. It is documentation only. Do not execute the high-risk commands without Kenny's explicit confirmation.

Related document: `docs/mysql-cutover-checklist-2026-07-17.md`.

## Scope

Allowed without extra confirmation:

- Read-only checks.
- Dry-run commands.
- Git status / diff checks.
- MySQL shadow read-only SQL.

Requires explicit confirmation:

- Production backend restart.
- `SYNC_ENABLED` changes.
- `.env` / `DATABASE_URL` changes.
- SQLite backup creation if it affects production volume state.
- Any cutover or rollback command.

## Environment Setup

Run from the repository root:

```bash
cd /opt/wb-erp
set -a
source /opt/wb-erp/.env
set +a
```

Expected containers:

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}'
```

Expected:

- `wb-erp-mysql` is healthy.
- `wb-erp-backend` is running.
- `wb-erp-frontend` is running.

## Read-Only Preflight

```bash
git status --short
git log --oneline -5
docker inspect wb-erp-backend --format 'Cmd={{json .Config.Cmd}}'
docker exec wb-erp-mysql mysqladmin ping -h 127.0.0.1 -u"$MYSQL_USER" -p"$MYSQL_PASSWORD"
```

Current known runtime detail:

```text
wb-erp-backend uses uvicorn app.main:app --host 0.0.0.0 --port 8000
It does not use --reload, so code changes require a backend restart to load.
```

## Shadow Raw Count SQL

```bash
docker exec -e MYSQL_PWD="$MYSQL_PASSWORD" wb-erp-mysql \
  mysql -u"$MYSQL_USER" wb_erp_shadow -e "
SELECT 'wb_raw_analytics_product_funnel' AS table_name, COUNT(*) AS rows_count FROM wb_raw_analytics_product_funnel
UNION ALL SELECT 'wb_raw_analytics_search_terms', COUNT(*) FROM wb_raw_analytics_search_terms
UNION ALL SELECT 'wb_raw_content_cards', COUNT(*) FROM wb_raw_content_cards
UNION ALL SELECT 'wb_raw_customer_chats', COUNT(*) FROM wb_raw_customer_chats
UNION ALL SELECT 'wb_raw_customer_feedbacks', COUNT(*) FROM wb_raw_customer_feedbacks
UNION ALL SELECT 'wb_raw_customer_questions', COUNT(*) FROM wb_raw_customer_questions
UNION ALL SELECT 'wb_raw_customer_returns', COUNT(*) FROM wb_raw_customer_returns
UNION ALL SELECT 'wb_raw_discounts', COUNT(*) FROM wb_raw_discounts
UNION ALL SELECT 'wb_raw_finance_documents', COUNT(*) FROM wb_raw_finance_documents
UNION ALL SELECT 'wb_raw_finance_realization_reports', COUNT(*) FROM wb_raw_finance_realization_reports
UNION ALL SELECT 'wb_raw_inventory_stocks', COUNT(*) FROM wb_raw_inventory_stocks
UNION ALL SELECT 'wb_raw_prices', COUNT(*) FROM wb_raw_prices
UNION ALL SELECT 'wb_raw_promotion_campaigns', COUNT(*) FROM wb_raw_promotion_campaigns
UNION ALL SELECT 'wb_raw_promotion_keywords', COUNT(*) FROM wb_raw_promotion_keywords
UNION ALL SELECT 'wb_raw_promotion_stats', COUNT(*) FROM wb_raw_promotion_stats
UNION ALL SELECT 'wb_raw_statistics_orders', COUNT(*) FROM wb_raw_statistics_orders
UNION ALL SELECT 'wb_raw_statistics_sales', COUNT(*) FROM wb_raw_statistics_sales;
"
```

Known accepted exception:

```text
wb_raw_analytics_search_terms = 0
Reason: Jam permission required and intentionally skipped.
```

## Final Incremental ETL

Run only after scheduler writes are stopped for a real cutover.

```bash
docker exec \
  -e MYSQL_USER="$MYSQL_USER" \
  -e MYSQL_PASSWORD="$MYSQL_PASSWORD" \
  wb-erp-backend \
  python scripts/mysql_migration/05_seed_v2_facts.py --days 7 --apply

docker exec \
  -e MYSQL_USER="$MYSQL_USER" \
  -e MYSQL_PASSWORD="$MYSQL_PASSWORD" \
  wb-erp-backend \
  python scripts/mysql_migration/07_seed_v2_customer_sync_facts.py --days 7 --apply
```

## Validation

```bash
docker exec \
  -e MYSQL_USER="$MYSQL_USER" \
  -e MYSQL_PASSWORD="$MYSQL_PASSWORD" \
  wb-erp-backend \
  python scripts/mysql_migration/06_validate_migration.py --days 7
```

Required result:

```text
Summary: 33 passed, 0 failed, 33 total
```

Important: while APScheduler is active, SQLite can change within minutes. If validation fails only because source data drifted, rerun final incremental ETL and validate again.

## View Sanity SQL

```bash
docker exec -e MYSQL_PWD="$MYSQL_PASSWORD" wb-erp-mysql \
  mysql -u"$MYSQL_USER" wb_erp_shadow -e "
SELECT 'view_ops_overview' AS view_name, COUNT(*) AS rows_count FROM view_ops_overview
UNION ALL SELECT 'view_ops_product_daily', COUNT(*) FROM view_ops_product_daily
UNION ALL SELECT 'view_ops_ad_efficiency', COUNT(*) FROM view_ops_ad_efficiency
UNION ALL SELECT 'view_ops_customer_signals', COUNT(*) FROM view_ops_customer_signals;

SELECT
  MIN(biz_date) AS min_date,
  MAX(biz_date) AS max_date,
  COUNT(DISTINCT shop_id) AS shops,
  ROUND(SUM(sales_amount_rub), 2) AS sales_rub,
  SUM(order_count) AS orders,
  ROUND(SUM(ad_cost_rub), 2) AS ad_cost_rub
FROM view_ops_overview;
"
```

## Dashboard Parity Check

Use the API/function-level comparison before cutover. Expected parity fields:

- `sales_amount`
- `order_count`
- `visitors`
- `add_to_cart`
- `ad_cost`

Known fixed issue:

```text
d8ab4a3 changed /api/dashboard/stats/ no-owner branch to use product_analytics.sales,
matching products, trend, and view_ops_overview.
```

## Production Cutover Commands

These commands are intentionally templates. Do not run without explicit confirmation.

```bash
# 1. Stop scheduler writes.
# Edit /opt/wb-erp/.env:
# SYNC_ENABLED=false

# 2. Restart backend so scheduler stop takes effect.
docker compose restart backend

# 3. Verify scheduler inactivity from logs.
docker logs --tail=200 wb-erp-backend

# 4. Back up SQLite volume.
# Record the exact backup path in the checklist before continuing.

# 5. Run final incremental ETL and validation.
# Use the commands above.

# 6. Switch DATABASE_URL.
# Edit /opt/wb-erp/.env:
# DATABASE_URL=mysql+pymysql://USER:PASSWORD@wb-erp-mysql:3306/wb_erp_shadow?charset=utf8mb4

# 7. Restart backend.
docker compose restart backend

# 8. Smoke test core pages and APIs.
```

## Smoke Test Targets

- `/docs`
- login
- Dashboard stats
- Dashboard products
- Dashboard trend
- product list/detail
- ads overview
- customer workbench read-only pages
- backend logs after first request burst

## Rollback Commands

These commands are also high-risk templates.

```bash
# 1. Stop scheduler writes.
# Edit /opt/wb-erp/.env:
# SYNC_ENABLED=false

# 2. Restore SQLite DATABASE_URL.
# Edit /opt/wb-erp/.env:
# DATABASE_URL=sqlite:////app/db/wb_erp.db

# 3. Restart backend.
docker compose restart backend

# 4. Verify old pages and API reads.
docker logs --tail=200 wb-erp-backend

# 5. Keep MySQL unchanged for delta comparison.
```

## Go / No-Go Summary

Go only if all are true:

- Git working tree is clean.
- Latest commit is pushed.
- Fresh SQLite backup exists.
- Scheduler is stopped before final ETL.
- Validation returns `33 passed, 0 failed`.
- Smoke test owner is ready.
- Rollback path is ready before changing `DATABASE_URL`.
