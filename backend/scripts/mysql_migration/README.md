# MySQL Migration Scripts

这些脚本用于 MySQL v2 迁移的准备、影子库验证和最终切换前校验。

默认原则：

- 默认只读或 dry-run。
- 不删除数据。
- 不清空表。
- 不修改生产 SQLite。
- 不自动切换 `DATABASE_URL`。

建议执行顺序：

```bash
python backend/scripts/mysql_migration/01_scan_sqlite_schema.py --sqlite-url sqlite:////app/db/wb_erp.db
python backend/scripts/mysql_migration/02_create_mysql_v2_schema.py --ddl docs/mysql-v2-schema.sql --dry-run
python backend/scripts/mysql_migration/03_migrate_legacy_tables.py --dry-run
python backend/scripts/mysql_migration/04_seed_v2_dimensions.py --dry-run
python backend/scripts/mysql_migration/05_seed_v2_facts.py --dry-run
python backend/scripts/mysql_migration/07_seed_v2_customer_sync_facts.py --dry-run
python backend/scripts/mysql_migration/06_validate_migration.py --dry-run
```

影子库容器准备：

```bash
docker compose up -d mysql
docker exec wb-erp-mysql mysqladmin ping -h 127.0.0.1 -u"$MYSQL_USER" -p"$MYSQL_PASSWORD"
```

影子库 schema dry-run：

```bash
python backend/scripts/mysql_migration/02_create_mysql_v2_schema.py --ddl docs/mysql-v2-schema.sql
```

真正创建影子库 schema 时再显式传入 `--apply` 和连接串：

```bash
python backend/scripts/mysql_migration/02_create_mysql_v2_schema.py \
  --ddl docs/mysql-v2-schema.sql \
  --mysql-url "mysql+pymysql://USER:PASSWORD@127.0.0.1:3306/wb_erp_shadow" \
  --apply
```

真正写 MySQL 前必须单独确认，并提供：

- SQLite 备份路径。
- MySQL 影子库连接串。
- `SYNC_ENABLED=false` 是否需要执行。
- 校验 SQL 清单。
- 回滚方案。
