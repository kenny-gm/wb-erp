#!/bin/bash
# WB ERP 定时同步脚本
# 只同步距上次同步已超过 sync_interval_hours 的店铺
LOG=/opt/wb-erp/logs/sync.log
INTERNAL_KEY="wb-erp…2026"

echo "$(date): 开始同步检查" >> $LOG

# 容器内 Python datetime.now() 是 UTC，但数据库存的是 CST (Asia/Shanghai naive)
# 用 now() + 8h 来得到当前 CST naive
shop_data=$(docker exec wb-erp-backend python3 -c "
import sys
sys.path.insert(0, '/app/backend')
from app.database import SessionLocal
from app.models.models import Shop
from datetime import datetime, timedelta

db = SessionLocal()
try:
    shops = db.query(Shop).filter(Shop.is_active == 1).all()
    now_cst = datetime.now() + timedelta(hours=8)  # naive CST
    for s in shops:
        interval = s.sync_interval_hours or 24
        last = s.last_sync_at  # naive CST
        if last is None:
            due = True
            hours_since = None
        else:
            hours_since = (now_cst - last).total_seconds() / 3600
            due = hours_since >= interval
        print(f'{s.id}|{interval}|{hours_since:.2f}|{due}')
finally:
    db.close()
" 2>&1)

# 过滤出该同步的店铺
tmpfile=$(mktemp)
echo "$shop_data" > "$tmpfile"

shops_to_sync=""
while IFS='|' read -r shop_id interval hours_since due; do
    if [ "$due" = "True" ]; then
        shops_to_sync="$shops_to_sync $shop_id"
        echo "$(date): 店铺 $shop_id (间隔${interval}h, 已过${hours_since}h) → 该同步" >> $LOG
    else
        echo "$(date): 店铺 $shop_id (间隔${interval}h, 已过${hours_since}h) → 跳过" >> $LOG
    fi
done < "$tmpfile"
rm -f "$tmpfile"

if [ -z "$shops_to_sync" ]; then
    echo "$(date): 没有店铺需要同步" >> $LOG
    exit 0
fi

count=$(echo $shops_to_sync | wc -w | tr -d ' ')
echo "$(date): 开始同步 ($count 个店铺)$shops_to_sync" >> $LOG

for shop_id in $shops_to_sync; do
    echo "$(date): 同步店铺 $shop_id..." >> $LOG
    RESULT=$(curl -s -X POST "http://localhost:8000/api/shops/internal-sync/${shop_id}/?api_key=${INTERNAL_KEY}&sync_type=all")
    echo "$RESULT" >> $LOG
done

echo "$(date): 同步完成" >> $LOG
