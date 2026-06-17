#!/usr/bin/env python3
"""
sync_dingtalk.py - ERP 数据同步到钉钉 AI 表格
每2小时自动运行一次
"""
import sys, os, json, urllib.request, sqlite3, time

sys.path.insert(0, '/app/backend')

MCP_URL = os.getenv("DINGTALK_MCP_URL")
if not MCP_URL:
    raise RuntimeError("DINGTALK_MCP_URL environment variable is required")

TABLES = {
    'products':    {'base': 'Y1OQX0akWm6KBXgLCbyoaYA6VGlDd3mE', 'table': 'hERWDMS'},
    'ad_daily':    {'base': 'vy20BglGWOr1GXO0tgMQaz2q8A7depqY', 'table': 'hERWDMS'},
}

# product_sales_stats 专用配置
PSS_BASE = 'vy20BglGWOr1GXO0tgMQDpO28A7depqY'
PSS_TBL = 'hERWDMS'
PSS_FIELDS = {
    'shop_name': 'Os6nuZe', 'stat_date': 'D83Qr9I', 'nm_id': '1t2SsJZ',
    'sku': 'oLh89L1', 'product_name': 'e06nA1I', 'visitors': 'ZyfXUou',
    'cart_count': 'MV1uDqb', 'cart_rate': 'wcPoJL0', 'order_count': 'BLCWXOx',
    'sales': 'iz0AoOm', 'conversion_rate': 'CRHDWQt', 'ad_cost': 'D265YQo',
    'ad_ratio': '9doVryi', 'impressions': '9NTrpTv', 'ad_visitors': '9Hix4IG',
    'ad_ctr': 'umjVhf6', 'ad_cart_count': 'BHu7wUu', 'ad_order_count': 'Ue7l4aG',
    'ad_conv_rate': 'mQQwfli', 'ad_cart_rate': '7QEYOSg',
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
        print(f"  {i//batch_size + 1}: {len(new_ids)} 条")
        time.sleep(0.3)
    return total

def ensure_views():
    """确保视图存在"""
    conn = sqlite3.connect('/app/db/wb_erp.db')
    conn.execute('''CREATE VIEW IF NOT EXISTS daily_stats AS
SELECT shop_id, DATE(order_date) as stat_date,
    COUNT(*) as order_count, SUM(total_amount) as order_sum,
    SUM(ad_cost) as ad_cost, SUM(product_cost) as product_cost,
    SUM(profit) as profit, AVG(profit_rate) as avg_profit_rate
FROM orders WHERE order_date IS NOT NULL
GROUP BY shop_id, DATE(order_date)''')
    conn.execute('''CREATE VIEW IF NOT EXISTS ad_daily AS
SELECT shop_id, record_date as stat_date,
    SUM(impressions) as impressions, SUM(clicks) as clicks,
    SUM(cost) as cost, SUM(cost_cny) as cost_cny,
    SUM(order_count) as order_count, SUM(sales) as sales,
    SUM(sales_cny) as sales_cny, SUM(visitors) as visitors,
    SUM(cart_count) as cart_count
FROM ad_records WHERE record_date IS NOT NULL
GROUP BY shop_id, record_date''')
    conn.execute('''CREATE VIEW IF NOT EXISTS product_sales_stats AS
SELECT p.id as product_id, p.nm_id, p.sku,
    COALESCE(p.custom_name, p.name) as product_name,
    p.shop_id, s.name as shop_name, ar.record_date as stat_date,
    COALESCE(SUM(ar.visitors), 0) as visitors,
    COALESCE(SUM(ar.cart_count), 0) as cart_count,
    COALESCE(SUM(ar.order_count), 0) as order_count,
    COALESCE(SUM(ar.sales), 0) as sales,
    COALESCE(SUM(adv.cost), 0) as ad_cost,
    COALESCE(SUM(adv.impressions), 0) as impressions,
    COALESCE(SUM(adv.visitors), 0) as ad_visitors,
    COALESCE(SUM(adv.clicks), 0) as ad_clicks,
    COALESCE(SUM(adv.cart_count), 0) as ad_cart_count,
    COALESCE(SUM(adv.order_count), 0) as ad_order_count
FROM ad_records ar
JOIN products p ON ar.product_id = p.id
JOIN shops s ON ar.shop_id = s.id
LEFT JOIN ad_records adv ON adv.product_id = ar.product_id
    AND adv.record_date = ar.record_date AND adv.ad_type = "advertising" AND adv.shop_id = ar.shop_id
WHERE ar.ad_type = "product_analytics"
GROUP BY p.id, p.nm_id, p.sku, product_name, p.shop_id, s.name, ar.record_date''')
    conn.commit()
    conn.close()

def sync_table(table_name, query, field_ids, date_fields=None):
    if date_fields is None:
        date_fields = []
    print(f"=== {table_name} ===")
    ensure_views()
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

def sync_product_sales():
    """同步 product_sales_stats（按产品+日期聚合）"""
    print("=== product_sales_stats ===")
    ensure_views()
    conn = sqlite3.connect('/app/db/wb_erp.db')
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT * FROM product_sales_stats').fetchall()
    conn.close()

    records = []
    for r in rows:
        visitors = r['visitors'] or 0
        ad_visitors = r['ad_visitors'] or 0
        sales = r['sales'] or 0
        cart_rate = round(r['cart_count'] / visitors * 100, 2) if visitors > 0 else 0
        conversion_rate = round(r['order_count'] / visitors * 100, 2) if visitors > 0 else 0
        ad_ratio = round(r['ad_cost'] / sales * 100, 2) if sales > 0 else 0
        ad_ctr = round(r['ad_clicks'] / ad_visitors * 100, 2) if ad_visitors > 0 else 0
        ad_cart_rate = round(r['ad_cart_count'] / ad_visitors * 100, 2) if ad_visitors > 0 else 0
        ad_conv_rate = round(r['ad_order_count'] / ad_visitors * 100, 2) if ad_visitors > 0 else 0

        cells = {}
        if r['shop_name']: cells[PSS_FIELDS['shop_name']] = r['shop_name']
        if r['stat_date']: cells[PSS_FIELDS['stat_date']] = str(r['stat_date'])[:10]
        if r['nm_id']: cells[PSS_FIELDS['nm_id']] = str(r['nm_id'])
        if r['sku']: cells[PSS_FIELDS['sku']] = r['sku']
        if r['product_name']: cells[PSS_FIELDS['product_name']] = r['product_name']
        if visitors > 0: cells[PSS_FIELDS['visitors']] = visitors
        if r['cart_count'] > 0: cells[PSS_FIELDS['cart_count']] = r['cart_count']
        if cart_rate > 0: cells[PSS_FIELDS['cart_rate']] = cart_rate
        if r['order_count'] > 0: cells[PSS_FIELDS['order_count']] = r['order_count']
        if sales > 0: cells[PSS_FIELDS['sales']] = round(sales, 2)
        if conversion_rate > 0: cells[PSS_FIELDS['conversion_rate']] = conversion_rate
        if r['ad_cost'] > 0: cells[PSS_FIELDS['ad_cost']] = round(r['ad_cost'], 2)
        if ad_ratio > 0: cells[PSS_FIELDS['ad_ratio']] = ad_ratio
        if r['impressions'] > 0: cells[PSS_FIELDS['impressions']] = r['impressions']
        if ad_visitors > 0: cells[PSS_FIELDS['ad_visitors']] = ad_visitors
        if ad_ctr > 0: cells[PSS_FIELDS['ad_ctr']] = ad_ctr
        if r['ad_cart_count'] > 0: cells[PSS_FIELDS['ad_cart_count']] = r['ad_cart_count']
        if r['ad_order_count'] > 0: cells[PSS_FIELDS['ad_order_count']] = r['ad_order_count']
        if ad_conv_rate > 0: cells[PSS_FIELDS['ad_conv_rate']] = ad_conv_rate
        if ad_cart_rate > 0: cells[PSS_FIELDS['ad_cart_rate']] = ad_cart_rate
        records.append({'cells': cells})

    total = batch_create_records(PSS_BASE, PSS_TBL, records, batch_size=30)
    print(f"  共 {total} 条\n")

# products（增量）
sync_table('products',
    'SELECT p.*, s.name as shop_name FROM products p JOIN shops s ON p.shop_id=s.id',
    {'gSslSFb':'nm_id','iQ3Fo1b':'sku','CkU3TqC':'shop_name','hDrKugK':'name',
     't24OGah':'custom_name','c89gMQn':'owner','aGjL6pI':'weight','G8lHB8t':'length',
     'J9LMdML':'width','qog0vRw':'height','D7nyFQU':'purchase_price',
     '62CyMra':'shipping_price','vpzamm1':'commission_rate','dDGlOsK':'created_at',
     'DV2gH2C':'updated_at'},
    date_fields=['dDGlOsK','DV2gH2C']
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

# product_sales_stats
sync_product_sales()

print("=== 钉钉同步完成 ===")