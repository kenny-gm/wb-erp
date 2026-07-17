# MySQL Cutover Checklist - 2026-07-17

本文档记录 2026-07-17 MySQL shadow 阶段的当前状态、切库前闸门和回滚步骤。除非 Kenny 明确确认，本文档中的高风险动作不得执行。

## 当前结论

- MySQL shadow raw / dim / fact / view 层已完成主要验收。
- 生产后端仍读写 SQLite。
- `DATABASE_URL` 未切换。
- backend/frontend 未重启。
- `wb_raw_analytics_search_terms` 因 Jam 权限要求已按确认跳过。
- `d8ab4a3 fix dashboard stats sales source` 已提交并推送，但生产 `wb-erp-backend` 不是 `--reload` 启动，运行中进程不会自动加载该修复。

## 已完成批次

| Area | Status | Evidence |
|---|---|---|
| Permission probe | Done | `wb_raw_api_responses` |
| Content cards | Done | `wb_raw_content_cards = 134` |
| Inventory | Done | `wb_raw_inventory_stocks = 602` |
| Sales / funnel | Done | `wb_raw_statistics_orders = 1749`, `wb_raw_statistics_sales = 1166`, `wb_raw_analytics_product_funnel = 126` |
| Ads | Done | `wb_raw_promotion_campaigns = 1869`, `wb_raw_promotion_stats = 567`, `wb_raw_promotion_keywords = 1585` |
| Customer service | Done | questions `465`, feedbacks `1300`, chats `608`, returns `78` |
| Finance | Done | realization reports `3230`, documents `204` |
| Prices / discounts | Done | prices `132`, discounts `132` |
| Search terms | Skipped | Jam permission required |

## Latest Shadow Validation

Last successful validation window: `2026-07-11` to `2026-07-17`.

```text
06_validate_migration.py --days 7
Summary: 33 passed, 0 failed, 33 total
```

Validated facts:

| Table | Window rows |
|---|---:|
| `fact_product_daily` | 1122 |
| `fact_product_funnel_daily` | 1122 |
| `fact_ad_daily` | 1185 |
| `fact_ad_keyword_daily` | 7285 |
| `fact_customer_signal_daily` | 236 |
| `fact_sync_health` | 2785 |
| `view_ops_overview` | 34 |
| `view_ops_customer_signals` | 236 |

Dashboard API parity after `d8ab4a3`:

| Metric | Value |
|---|---:|
| sales_amount | 6,460,162.12 RUB |
| order_count | 1200 |
| visitors | 115321 |
| add_to_cart | 11863 |
| ad_cost | 320,066.62 RUB |

## Go / No-Go Gates

All gates must pass immediately before any production switch.

- `git status --short` is empty.
- Latest code is pushed to GitHub.
- `wb-erp-mysql` is healthy.
- SQLite volume backup exists and path is recorded.
- `SYNC_ENABLED=false` is applied before final cutover ETL.
- backend is restarted once after `SYNC_ENABLED=false`, and APScheduler inactivity is verified.
- Final incremental ETL is run after scheduler is stopped.
- `06_validate_migration.py --days 7` returns `33 passed, 0 failed`.
- Dashboard smoke test is ready: `/docs`, login, Dashboard stats/products/trend.
- Product, ads, customer, and finance smoke tests are ready.
- Rollback commands are prepared before changing `DATABASE_URL`.

## High-Risk Actions Requiring Explicit Confirmation

Do not execute these from a generic "continue" instruction:

- Restart production backend.
- Set `SYNC_ENABLED=false` or `SYNC_ENABLED=true`.
- Modify `.env` or `DATABASE_URL`.
- Switch backend from SQLite to MySQL.
- Clear, truncate, drop, or migrate production data.
- Run final cutover smoke test that writes to production external systems.

## Cutover Sequence

```text
1. Confirm maintenance window.
2. Confirm rollback owner and expected maximum downtime.
3. Set SYNC_ENABLED=false.
4. Restart backend to stop APScheduler.
5. Verify APScheduler is not running sync jobs.
6. Back up SQLite volume.
7. Run final incremental ETL:
   - 05_seed_v2_facts.py --days 7 --apply
   - 07_seed_v2_customer_sync_facts.py --days 7 --apply
8. Run 06_validate_migration.py --days 7.
9. Modify DATABASE_URL to MySQL.
10. Restart backend.
11. Smoke test:
    - /docs
    - login
    - Dashboard stats/products/trend
    - product detail/list
    - ads overview
    - customer workbench read-only pages
12. If smoke passes, set SYNC_ENABLED=true.
13. Observe logs and core pages for 24-48 hours.
14. Keep SQLite as read-only backup.
```

## Rollback Sequence

```text
1. Set SYNC_ENABLED=false.
2. Modify DATABASE_URL back to SQLite.
3. Restart backend.
4. Verify old pages are restored.
5. Keep MySQL unchanged for forensic comparison.
6. Compare writes made during MySQL window.
7. Backfill SQLite only after confirming exact write delta.
8. Set SYNC_ENABLED=true after recovery is verified.
```

## Known Residual Risks

- Production backend has not loaded `d8ab4a3` until a restart occurs.
- SQLite keeps changing while APScheduler is active, so shadow validation can drift within minutes.
- Search term raw table remains empty because Jam permission was intentionally skipped.
- Formal cutover still needs explicit confirmation and a fresh SQLite backup.
