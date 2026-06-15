#!/usr/bin/env python3
"""
sync_dingtalk.py - ERP 数据同步到钉钉 AI 表格
Crond: 每2小时执行一次
"""
import sys, os, json, urllib.request, sqlite3, time

sys.path.insert(0, '/app/backend')

MCP_URL = 'https://mcp-gw.dingtalk.com/server/bca43adceffe04aa480abdff760e8272a2c1ce6f64be41653f23149fbe06bae1?key=29bccabbf0e05d979d525beed09e8f24'

TABLES = {
    'products':    {'base': 'Y1OQX0akWm6KBXgLCbyoaYA6VGlDd3mE', 'table': 'hERWDMS'},
    'daily_stats': {'base': 'QOG9lyrgJPB1LGOXCvQLwar1WzN67Mw4', 'table': 'hERWDMS'},
    'ad_daily':    {'base': 'vy20BglGWOr1GXO0tgMQaz2q8A7depqY', 'table': 'hERWDMS'},
}

def call_mcp(method, arguments):
    data = json.dumps({
        'jsonrpc': '2.0', 'method': 'tools/call',
        'params': {'name': method, 'arguments': arguments}, 'id': 1
    }).encode()
    req = urllib.request.Request(MCP_URL, data=data, headers={
        'Content-Type': 'application/json', 'Accept': 'application/json'
    })
    resp = urllib.request.urlopen(req, timeout=60)
    result = json.loads(resp.read())
    if result.get('result', {}).get('isError'):
        raise Exception(json.dumps(result['result']))
    return result['result']

def batch_create_records(base_id, table_id, records, batch_size=50):
    total = 0
    for i in range(0, len(records), batch_size):
        batch = records[i:i+batch_size]
        payload = {'baseId': base_id, 'tableId': table_id, 'records': batch}
        result = call_mcp('create_records', payload)
        new_ids = result.get('data', {}).get('newRecordIds', [])
        if not new_ids:
            new_ids = result.get('structuredContent', {}).get('data', {}).get('newRecordIds', [])
        total += len(new_ids)
        print(f"  批次 {i//batch_size + 1}: {len(new_ids)} 条")
        time.sleep(0.3)
    return total

def ensure_views():
    """确保 daily_stats 和 ad_daily 视图存在"""
    conn = sqlite3.connect('/app/db/wb_erp.db')
    conn.execute('''
CREATE VIEW IF NOT EXISTS daily_stats AS
SELECT shop_id, DATE(order_date) as stat_date,
    COUNT(*) as order_count, SUM(total_amount) as order_sum,
    SUM(ad_cost) as ad_cost, SUM(product_cost) as product_cost,
    SUM(profit) as profit, AVG(profit_rate) as avg_profit_rate
FROM orders WHERE order_date IS NOT NULL
GROUP BY shop_id, DATE(order_date)
''')
    conn.execute('''
CREATE VIEW IF NOT EXISTS ad_daily AS
SELECT shop_id, record_date as stat_date,
    SUM(impressions) as impressions, SUM(clicks) as clicks,
    SUM(cost) as cost, SUM(cost_cny) as cost_cny,
    SUM(order_count) as order_count, SUM(sales) as sales,
    SUM(sales_cny) as sales_cny, SUM(visitors) as visitors,
    SUM(cart_count) as cart_count
FROM ad_records WHERE record_date IS NOT NULL
GROUP BY shop_id, record_date
''')
    conn.commit()
    conn.close()

def sync_table(table_name, query, field_ids, date_fields=None):
    if date_fields is None:
        date_fields = []
    print(f"=== {table_name} ===")
    ensure_views()  # 先确保视图存在
    conn = sqlite3.connect('/app/db/wb_erp.db')
    conn.row_factory = sqlite3.Row
    rows = conn.execute(query).fetchall()
    conn.close()
    records = []
    for r in rows:
        cells = {}
        for fname, fkey in field_ids.items():
            val = r[fkey] if fkey in dict(r.keys()) else None
            if val is None:
                continue
            if fname in date_fields:
                cells[fname] = str(val)[:10]
            elif isinstance(val, float):
                cells[fname] = round(val, 4)
            else:
                cells[fname] = val
        records.append({'cells': cells})
    total = batch_create_records(TABLES[table_name]['base'], TABLES[table_name]['table'], records)
    print(f"  共 {total} 条\n")
    return total

# products
sync_table('products',
    'SELECT p.*, s.name as shop_name FROM products p JOIN shops s ON p.shop_id=s.id',
    {'gSslSFb':'nm_id','iQ3Fo1b':'sku','CkU3TqC':'shop_name','hDrKugK':'name',
     't24OGah':'custom_name','c89gMQn':'owner','aGjL6pI':'weight','G8lHB8t':'length',
     'J9LMdML':'width','qog0vRw':'height','D7nyFQU':'purchase_price',
     '62CyMra':'shipping_price','vpzamm1':'commission_rate','dDGlOsK':'created_at',
     'DV2gH2C':'updated_at'},
    date_fields=['dDGlOsK','DV2gH2C']
)

# daily_stats
sync_table('daily_stats',
    'SELECT ds.*, s.name as shop_name FROM daily_stats ds JOIN shops s ON ds.shop_id=s.id ORDER BY ds.stat_date DESC',
    {'PQ8wMJ8':'shop_name','aZj44wo':'stat_date','JeB1BEQ':'order_count',
     'Cf2RE0c':'order_sum','uyarTBG':'ad_cost','yLsHHWA':'product_cost',
     'OfdiY1Q':'profit','GPdSUrZ':'avg_profit_rate'},
    date_fields=['aZj44wo']
)

# ad_daily
sync_table('ad_daily',
    'SELECT ad.*, s.name as shop_name FROM ad_daily ad JOIN shops s ON ad.shop_id=s.id ORDER BY ad.stat_date DESC',
    {'Z2rbE68':'shop_name','Vkt2wOz':'stat_date','HTbOgqQ':'impressions',
     'CBZvy2m':'clicks','un4hDew':'cost','WN6PSkc':'cost_cny',
     '0WdxnUX':'order_count','j8iqx5e':'sales','Txn1kEu':'sales_cny',
     'HDvbr1U':'visitors','jOldiLu':'cart_count'},
    date_fields=['Vkt2wOz']
)

print("=== 钉钉同步完成 ===")