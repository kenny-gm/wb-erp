"""
产品管理路由
"""
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.models import Product, Shop, SyncLog, AdRecord, Order, OrderItem, AdKeywordStat
from app.routers.auth import get_current_user, get_current_admin
from app.services.sync_fixed import SyncService
from app.services.wb_api import WBAPIClient

router = APIRouter(prefix="/api/products", tags=["产品管理"])


# ========== 请求/响应模型 ==========

class ProductCreate(BaseModel):
    nm_id: int
    sku: str
    name: str
    custom_name: Optional[str] = None
    owner: Optional[str] = None
    weight: Optional[float] = None
    length: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    purchase_price: Optional[float] = None
    shipping_price: Optional[float] = None
    commission_rate: Optional[float] = None


class ProductUpdate(BaseModel):
    custom_name: Optional[str] = None
    owner: Optional[str] = None
    weight: Optional[float] = None
    length: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    purchase_price: Optional[float] = None
    shipping_price: Optional[float] = None
    commission_rate: Optional[float] = None


class ProductResponse(BaseModel):
    id: int
    nm_id: int
    sku: str
    shop_id: int
    shop_name: Optional[str] = None
    name: str
    custom_name: Optional[str] = None
    owner: Optional[str] = None
    weight: Optional[float] = None
    length: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    purchase_price: Optional[float] = None
    shipping_price: Optional[float] = None
    commission_rate: Optional[float] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ========== 路由 ==========

@router.get("/", response_model=List[ProductResponse])
def list_products(
    shop_id: Optional[int] = None,
    owner: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取产品列表"""
    query = db.query(Product, Shop.name.label("shop_name")).join(Shop, Product.shop_id == Shop.id)

    # 根据当前用户的 allowed_owners 进行过滤
    user_allowed_owners = getattr(current_user, 'allowed_owners', None) or []
    if user_allowed_owners:
        query = query.filter(Product.owner.in_(user_allowed_owners))

    # 获取总数(用于分页)
    count_query = db.query(func.count(Product.id))
    if user_allowed_owners:
        count_query = count_query.filter(Product.owner.in_(user_allowed_owners))
    if shop_id:
        count_query = count_query.filter(Product.shop_id == shop_id)
    if owner:
        count_query = count_query.filter(Product.owner == owner)
    if search:
        count_query = count_query.filter(
            Product.name.contains(search) |
            Product.custom_name.contains(search) |
            Product.sku.contains(search)
        )
    total = count_query.scalar() or 0

    if shop_id:
        query = query.filter(Product.shop_id == shop_id)
    if owner:
        query = query.filter(Product.owner == owner)
    if search:
        query = query.filter(
            Product.name.contains(search) |
            Product.custom_name.contains(search) |
            Product.sku.contains(search)
        )

    results = query.offset(skip).limit(limit).all()

    # 返回总数用于前端分页
    import json
    from datetime import datetime

    def to_dict(product):
        result = {}
        for k, v in product.__dict__.items():
            if k.startswith('_'):
                continue
            if isinstance(v, datetime):
                result[k] = v.isoformat()
            else:
                result[k] = v
        return result

    return Response(
        content=json.dumps({
            "products": [
                {
                    **to_dict(product),
                    "shop_name": shop_name,
                }
                for product, shop_name in results
            ],
            "total": total
        }),
        media_type="application/json",
        headers={"X-Total": str(total)}
    )


@router.get("/template/")
def download_product_template(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """下载所有产品的信息模板(供管理员填写)"""
    import io, csv
    from sqlalchemy import text

    # 使用原生SQL查询,直接获取数据库中的产品信息
    result = db.execute(text("""
        SELECT p.nm_id, p.sku, s.name as shop_name, p.custom_name, p.owner,
               p.weight, p.length, p.width, p.height,
               p.purchase_price, p.shipping_price
        FROM products p
        LEFT JOIN shops s ON p.shop_id = s.id
        ORDER BY p.id
    """))

    output = io.StringIO()
    writer = csv.writer(output)
    # 表头:产品标识列 + 可编辑列
    writer.writerow(["nm_id", "sku", "店铺名称", "custom_name", "owner", "weight", "length", "width", "height", "purchase_price", "shipping_price"])

    # 写入所有产品数据
    for row in result:
        writer.writerow([
            row.nm_id or "",
            row.sku or "",
            row.shop_name or "",
            row.custom_name or "",
            row.owner or "",
            row.weight or "",
            row.length or "",
            row.width or "",
            row.height or "",
            row.purchase_price or "",
            row.shipping_price or ""
        ])

    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=product_template.csv"}
    )


@router.post("/import/")
async def import_products(file: UploadFile = File(...), db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    """批量导入产品信息"""
    import io, csv
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="仅支持CSV文件")
    content = await file.read()
    try:
        decoded = content.decode("utf-8-sig")
    except:
        decoded = content.decode("gbk")
    reader = csv.DictReader(io.StringIO(decoded))
    imported = 0
    errors = []
    for i, row in enumerate(reader, 2):
        try:
            nm_id = row.get("nm_id", "").strip()
            if not nm_id:
                errors.append("第" + str(i) + "行: nm_id不能为空")
                continue
            product = db.query(Product).filter(Product.nm_id == nm_id).first()
            if not product:
                errors.append("第" + str(i) + "行: 产品" + nm_id + "不存在")
                continue
            for field in ["custom_name", "owner", "weight", "length", "width", "height", "purchase_price", "shipping_price"]:
                if field in row and row[field]:
                    try:
                        if field in ["weight", "length", "width", "height", "purchase_price", "shipping_price"]:
                            setattr(product, field, float(row[field]))
                        else:
                            setattr(product, field, row[field])
                    except:
                        pass
            db.commit()
            imported += 1
        except Exception as e:
            errors.append("第" + str(i) + "行: " + str(e))
    return {"message": "成功导入" + str(imported) + "条记录", "errors": errors[:20]}


@router.get("/{product_id}/", response_model=ProductResponse)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取产品详情"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")
    return product


@router.put("/{product_id}/", response_model=ProductResponse)
def update_product(
    product_id: int,
    data: ProductUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """更新产品(自定义字段)"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")

    # 更新可编辑字段
    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(product, key, value)

    db.commit()
    db.refresh(product)
    return product


@router.post("/{product_id}/assign-owner/")
def assign_owner(
    product_id: int,
    owner: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """分配负责人"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")

    product.owner = owner
    db.commit()

    return {"message": f"产品 {product.nm_id} 分配给 {owner}"}


@router.post("/{product_id}/sync/")
def sync_single_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """根据 product_id 同步单个产品的重量和尺寸"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")

    shop = db.query(Shop).filter(Shop.id == product.shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="店铺不存在")

    # 使用WB API获取产品详情
    from app.services.wb_api import WBAPIClient
    client = WBAPIClient(shop.api_token)

    # 调用Content API获取产品列表(包含dimensions)
    cards = client.get_products(limit=100, offset=0, locale='ru')

    # 查找对应nm_id的产品
    nm_id_str = str(product.nm_id)
    for card in cards:
        if str(card.get('nmID', '')) == nm_id_str:
            dimensions = card.get('dimensions', {})
            product.weight = dimensions.get('weightBrutto', 0)
            product.length = dimensions.get('length', 0)
            product.width = dimensions.get('width', 0)
            product.height = dimensions.get('height', 0)
            db.commit()
            return {
                "success": True,
                "message": f"产品 {product.nm_id} 同步成功",
                "weight": product.weight,
                "dimensions": f"{product.length}x{product.width}x{product.height}"
            }

    return {"success": False, "message": f"在WB API未找到产品 {product.nm_id}"}


@router.post("/sync/{shop_id}/")
def sync_products_from_wildberries(
    shop_id: int,
    overwrite: bool = False,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """从 WB 同步产品"""
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="店铺不存在")

    sync_service = SyncService(db, shop)
    result = sync_service.sync_products(overwrite=overwrite)

    if result["success"]:
        return {
            "success": True,
            "message": f"成功同步 {result['count']} 个产品,更新 {result['updated']} 个"
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=f"同步失败: {result.get('error')}"
        )


@router.get("/owners/list/")
def list_owners(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取负责人列表(根据当前用户权限过滤)"""
    query = db.query(Product.owner).filter(Product.owner != None, Product.owner != "")

    # 根据当前用户的 allowed_owners 进行过滤
    user_allowed_owners = getattr(current_user, 'allowed_owners', None) or []
    if user_allowed_owners:
        query = query.filter(Product.owner.in_(user_allowed_owners))

    owners = query.distinct().all()
    return [o[0] for o in owners if o[0]]


@router.get("/{product_id}/ads/")
def get_product_ads(
    product_id: int,
    date_from: str = None,
    date_to: str = None,
    ad_type: str = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取产品广告数据 - 优先从本地数据库读取"""
    from datetime import datetime, timedelta

    # 获取产品信息
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")

    # 获取店铺货币信息和汇率
    shop = db.query(Shop).filter(Shop.id == product.shop_id).first()
    shop_currency = shop.currency if shop and shop.currency else "RUB"
    exchange_rate = shop.exchange_rate if shop and shop.exchange_rate else 12.5

    # 设置默认日期
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    if not date_from:
        date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # ============ 从ad_records表获取product_analytics数据 ============
    from sqlalchemy import func, text, cast, String

    # 1. 获取产品销售漏斗数据(product_analytics类型)
    product_analytics_query = text("""
        SELECT
            COALESCE(SUM(visitors), 0) as total_visitors,
            COALESCE(SUM(cart_count), 0) as cart_count,
            COALESCE(SUM(order_count), 0) as orders,
            COALESCE(SUM(sales), 0) as sales
        FROM ad_records
        WHERE product_id = :product_id
        AND ad_type = 'product_analytics'
        AND date(record_date) >= :date_from
        AND date(record_date) <= :date_to
    """)

    import logging
    logger = logging.getLogger(__name__)
    analytics_result = db.execute(product_analytics_query, {
        "product_id": product_id,
        "date_from": date_from,
        "date_to": date_to
    }).first()

    # 从product_analytics数据获取核心指标
    total_visitors = int(analytics_result.total_visitors) if analytics_result.total_visitors else 0
    cart_count = int(analytics_result.cart_count) if analytics_result.cart_count else 0
    orders = int(analytics_result.orders) if analytics_result.orders else 0
    sales = float(analytics_result.sales) if analytics_result.sales else 0
    # 如果店铺货币是CNY,转换为RUB
    if shop_currency == "CNY":
        sales = sales * exchange_rate

    # 2. 获取广告数据 - 按广告类型拆分 (CPM推荐/CPM搜索/CPC搜索)
    # DB中 payment_type+placements 组合对应关系:
    #   cpm + recommendations = CPM推荐
    #   cpm + search         = CPM搜索
    #   cpc + search         = CPC搜索
    ad_stats = {}
    for db_ptype, label in [
        ('cpm_recommend', 'CPM推荐'),
        ('cpm_search', 'CPM搜索'),
        ('cpc_search', 'CPC搜索')
    ]:
        # 解析DB的payment_type和placements
        if db_ptype == 'cpm_recommend':
            sql_ptype = 'cpm'; sql_placements = 'recommendations'
        elif db_ptype == 'cpm_search':
            sql_ptype = 'cpm'; sql_placements = 'search'
        else:  # cpc_search
            sql_ptype = 'cpc'; sql_placements = 'search'

        q = text("""
            SELECT
                COALESCE(SUM(visitors), 0) as ad_visitors,
                COALESCE(SUM(cost), 0) as ad_spend,
                COALESCE(SUM(impressions), 0) as ad_impressions,
                COALESCE(SUM(order_count), 0) as ad_orders,
                COALESCE(SUM(cart_count), 0) as ad_cart_count
            FROM ad_records
            WHERE product_id = :product_id
            AND ad_type = 'advertising'
            AND payment_type = :payment_type
            AND placements = :placements
            AND date(record_date) >= :date_from
            AND date(record_date) <= :date_to
        """)
        r = db.execute(q, {
            "product_id": product_id,
            "payment_type": sql_ptype,
            "placements": sql_placements,
            "date_from": date_from,
            "date_to": date_to
        }).first()
        ad_stats[db_ptype] = {
            'visitors': float(r.ad_visitors) if r.ad_visitors else 0,
            'spend': float(r.ad_spend) if r.ad_spend else 0,
            'impressions': int(r.ad_impressions) if r.ad_impressions else 0,
            'orders': int(r.ad_orders) if r.ad_orders else 0,
            'cart': int(r.ad_cart_count) if r.ad_cart_count else 0,
        }

    # 汇总
    ad_visitors = sum(s['visitors'] for s in ad_stats.values())
    ad_spend = sum(s['spend'] for s in ad_stats.values())
    ad_impressions = sum(s['impressions'] for s in ad_stats.values())
    ad_orders = sum(s['orders'] for s in ad_stats.values())
    ad_cart_count = sum(s['cart'] for s in ad_stats.values())

    # 3. 计算衍生指标
    ad_ctr = ad_visitors / ad_impressions if ad_impressions > 0 else 0
    # 广告加购率改为使用产品维度的加购数/访客数(WB广告API不返回加购数据)
    cart_rate = cart_count / total_visitors if total_visitors > 0 else 0
    cpc = ad_spend / ad_visitors if ad_visitors > 0 else 0

    # 4. 计算环比变化(对比上一个同等时间段)
    try:
        from datetime import datetime, timedelta
        start_dt = datetime.strptime(date_from, "%Y-%m-%d")
        end_dt = datetime.strptime(date_to, "%Y-%m-%d")
        duration = (end_dt - start_dt).days
        prev_start = (start_dt - timedelta(days=duration)).strftime("%Y-%m-%d")
        prev_end = (start_dt - timedelta(days=1)).strftime("%Y-%m-%d")

        # 查询上一周期数据
        prev_query = text("""
            SELECT
                COALESCE(SUM(ar.sales), 0) as prev_sales,
                COALESCE(SUM(ar.order_count), 0) as prev_orders,
                COALESCE(SUM(ar.visitors), 0) as prev_visitors,
                COALESCE(SUM(ar.cart_count), 0) as prev_cart
            FROM ad_records ar
            WHERE ar.product_id = :product_id
            AND ar.ad_type = 'product_analytics'
            AND date(ar.record_date) >= :date_from
            AND date(ar.record_date) <= :date_to
        """)
        prev_analytics = db.execute(prev_query, {
            "product_id": product_id,
            "date_from": prev_start,
            "date_to": prev_end
        }).first()

        prev_ad_query = text("""
            SELECT
                COALESCE(SUM(ar.cost), 0) as prev_ad_spend,
                COALESCE(SUM(ar.order_count), 0) as prev_ad_orders,
                COALESCE(SUM(ar.visitors), 0) as prev_ad_visitors
            FROM ad_records ar
            WHERE ar.product_id = :product_id
            AND ar.ad_type = 'advertising'
            AND date(ar.record_date) >= :date_from
            AND date(ar.record_date) <= :date_to
        """)
        prev_ads = db.execute(prev_ad_query, {
            "product_id": product_id,
            "date_from": prev_start,
            "date_to": prev_end
        }).first()

        prev_sales = float(prev_analytics.prev_sales) if prev_analytics and prev_analytics.prev_sales else 0
        prev_orders = int(prev_analytics.prev_orders) if prev_analytics and prev_analytics.prev_orders else 0
        prev_visitors = int(prev_analytics.prev_visitors) if prev_analytics and prev_analytics.prev_visitors else 0
        prev_cart = int(prev_analytics.prev_cart) if prev_analytics and prev_analytics.prev_cart else 0
        prev_ad_spend = float(prev_ads.prev_ad_spend) if prev_ads and prev_ads.prev_ad_spend else 0
        prev_ad_orders = int(prev_ads.prev_ad_orders) if prev_ads and prev_ads.prev_ad_orders else 0
        prev_ad_visitors = int(prev_ads.prev_ad_visitors) if prev_ads and prev_ads.prev_ad_visitors else 0

        # 计算变化百分比
        sales_change = ((sales - prev_sales) / prev_sales * 100) if prev_sales > 0 else 0
        orders_change = ((orders - prev_orders) / prev_orders * 100) if prev_orders > 0 else 0
        visitors_change = ((total_visitors - prev_visitors) / prev_visitors * 100) if prev_visitors > 0 else 0
        cart_change = ((cart_count - prev_cart) / prev_cart * 100) if prev_cart > 0 else 0
        ad_spend_change = ((ad_spend - prev_ad_spend) / prev_ad_spend * 100) if prev_ad_spend > 0 else 0
        ad_orders_change = ((ad_orders - prev_ad_orders) / prev_ad_orders * 100) if prev_ad_orders > 0 else 0
        ad_visitors_change = ((ad_visitors - prev_ad_visitors) / prev_ad_visitors * 100) if prev_ad_visitors > 0 else 0
    except Exception as e:
        print(f"Error calculating changes: {e}")
        sales_change = orders_change = visitors_change = cart_change = 0
        ad_spend_change = ad_orders_change = ad_visitors_change = 0

    # 5. 汇总数据(用于返回)
    summary = {
        "sales": float(sales),  # 销售额(来自product_analytics)
        "orders": int(orders),  # 订单数(来自product_analytics)
        "total_visitors": int(total_visitors),  # 总访客(来自product_analytics)
        "total_cart": int(cart_count),
        "cart_change": round(cart_change, 1),  # 总加购(来自product_analytics)
        "ad_visitors": int(ad_visitors),  # 广告访客
        "ad_orders": int(ad_orders),  # 广告订单
        "ad_cart": int(ad_cart_count),  # 广告加购
        "ad_spend": float(ad_spend),  # 广告费
        "ad_ctr": float(ad_ctr * 100),  # 广告点击率(百分比)
        "ad_cart_rate": float(cart_rate),  # 加购率
        "cpc": float(cpc),  # CPC
        # 按广告类型拆分
        "ad_by_type": {
            "cpm_recommend": {
                "visitors": int(ad_stats['cpm_recommend']['visitors']),
                "orders": int(ad_stats['cpm_recommend']['orders']),
                "cart": int(ad_stats['cpm_recommend']['cart']),
                "spend": float(ad_stats['cpm_recommend']['spend']),
            },
            "cpm_search": {
                "visitors": int(ad_stats['cpm_search']['visitors']),
                "orders": int(ad_stats['cpm_search']['orders']),
                "cart": int(ad_stats['cpm_search']['cart']),
                "spend": float(ad_stats['cpm_search']['spend']),
            },
            "cpc_search": {
                "visitors": int(ad_stats['cpc_search']['visitors']),
                "orders": int(ad_stats['cpc_search']['orders']),
                "cart": int(ad_stats['cpc_search']['cart']),
                "spend": float(ad_stats['cpc_search']['spend']),
            },
        },
        # 环比变化
        "sales_change": round(sales_change, 1),
        "orders_change": round(orders_change, 1),
        "visitors_change": round(visitors_change, 1),
        "ad_spend_change": round(ad_spend_change, 1),
        "ad_orders_change": round(ad_orders_change, 1),
        "ad_visitors_change": round(ad_visitors_change, 1),
    }

    # 5. 获取日级数据用于图表
    daily_analytics = db.query(
        AdRecord.record_date,
        func.sum(AdRecord.visitors).label('impressions'),
        func.sum(AdRecord.cart_count).label('add_to_cart'),
        func.sum(AdRecord.order_count).label('orders'),
        func.sum(AdRecord.sales).label('sales')
    ).filter(
        AdRecord.product_id == product_id,
        AdRecord.ad_type == "product_analytics",
        AdRecord.record_date >= date_from,
        AdRecord.record_date <= date_to
    ).group_by(AdRecord.record_date).all()

    daily_ads = db.query(
        AdRecord.record_date,
        func.sum(AdRecord.visitors).label('clicks'),
        func.sum(AdRecord.cost).label('cost'),
        func.sum(AdRecord.impressions).label('impressions'),
        func.sum(AdRecord.order_count).label('ad_orders')
    ).filter(
        AdRecord.product_id == product_id,
        AdRecord.ad_type == "advertising",
        AdRecord.record_date >= date_from,
        AdRecord.record_date <= date_to
    ).group_by(AdRecord.record_date).all()

    # 合并日级数据
    daily_agg = {}
    for record in daily_analytics:
        date_key = record.record_date.strftime("%Y-%m-%d") if isinstance(record.record_date, datetime) else str(record.record_date)
        daily_agg[date_key] = {
            "date": date_key,
            "total_visitors": record.impressions or 0,
            "add_to_cart": record.add_to_cart or 0,
            "orders": record.orders or 0,
            "sales": record.sales or 0,
            "ad_visitors": 0,
            "ad_impressions": 0,
            "spend": 0,
            "ad_orders": 0
        }

    for record in daily_ads:
        date_key = record.record_date.strftime("%Y-%m-%d") if isinstance(record.record_date, datetime) else str(record.record_date)
        if date_key not in daily_agg:
            daily_agg[date_key] = {
                "date": date_key,
                "total_visitors": 0,
                "add_to_cart": 0,
                "orders": 0,
                "sales": 0,
                "ad_visitors": 0,
                "ad_impressions": 0,
                "spend": 0,
                "ad_orders": 0
            }
        daily_agg[date_key]["ad_visitors"] += record.clicks or 0
        daily_agg[date_key]["ad_impressions"] += record.impressions or 0
        daily_agg[date_key]["spend"] += record.cost or 0
        daily_agg[date_key]["ad_orders"] += record.ad_orders or 0

    # 获取店铺汇率用于计算广告占比
    shop = db.query(Shop).filter(Shop.id == product.shop_id).first()
    exchange_rate = shop.exchange_rate if shop and shop.exchange_rate else 12.5

    import logging
    logger = logging.getLogger(__name__)
    if daily_agg:
        first_day = list(daily_agg.values())[0]
        # 计算每日广告占比和加购率
    for date_key, day_data in daily_agg.items():
        sales_cny = day_data.get("sales", 0) or 0
        ad_spend = day_data.get("spend", 0) or 0
        visitors = day_data.get("total_visitors", 0) or 0
        cart_count = day_data.get("add_to_cart", 0) or 0
        if visitors > 0:
            sales_rub = sales_cny * exchange_rate
            day_data["ad_ratio"] = round((ad_spend / sales_rub) * 100, 1) if sales_rub > 0 else 0
            day_data["cart_rate"] = round((cart_count / visitors) * 100, 1)
            day_data["conversion_rate"] = round((day_data.get("orders", 0) or 0) / visitors * 100, 2)
        else:
            day_data["ad_ratio"] = 0
            day_data["cart_rate"] = 0
            day_data["conversion_rate"] = 0

    # 获取广告活动列表
    logger.info(f"DEBUG adverts_query: product_id={product_id}, date_from={date_from}, date_to={date_to}")
    adverts_query = db.query(
        AdRecord.advert_id,
        AdRecord.ad_type,
        func.sum(AdRecord.cost).label("total_cost"),
        func.sum(AdRecord.visitors).label("total_clicks"),
        func.sum(AdRecord.impressions).label("total_impressions")
    ).filter(
        AdRecord.product_id == product_id,
        AdRecord.ad_type == "advertising",
        AdRecord.record_date >= date_from,
        AdRecord.record_date <= date_to
    ).group_by(AdRecord.advert_id, AdRecord.ad_type).all()
    adverts = [{"id": r.advert_id or 0, "name": f"广告 {r.advert_id or 0}", "status": 11, "type": r.ad_type or "cpm", "bid_type": "manual", "cost": r.total_cost or 0, "clicks": r.total_clicks or 0} for r in adverts_query[:10]]

    # 按广告活动和日期汇总详细数据(不按平台分组,每日一行)
    ad_details_query = db.query(
        AdRecord.advert_id,
        AdRecord.ad_type,
        AdRecord.record_date,
        AdRecord.payment_type,
        AdRecord.placements,
        func.sum(AdRecord.impressions).label("impressions"),
        func.sum(AdRecord.visitors).label("clicks"),
        func.sum(AdRecord.cost).label("cost"),
        func.sum(AdRecord.sales).label("sales"),
        func.sum(AdRecord.order_count).label("orders")
    ).filter(
        AdRecord.product_id == product_id,
        AdRecord.ad_type == "advertising",
        AdRecord.record_date >= date_from,
        AdRecord.record_date <= date_to
    ).group_by(
        AdRecord.advert_id, AdRecord.ad_type, AdRecord.record_date,
        AdRecord.payment_type, AdRecord.placements
    ).all()

    # 转换为带 type_name 的格式
    # 根据 payment_type 和 placements 确定广告类型
    def get_ad_type(payment_type, placements):
        if payment_type == "cpm" and placements == "recommendations":
            return "cpm_recommend"
        elif payment_type == "cpm" and placements == "search":
            return "cpm_search"
        elif payment_type == "cpc" and placements == "search":
            return "cpc_search"
        else:
            return "cpm_search"  # 默认

    type_name_map = {
        "cpm_search": "CPM搜索",
        "cpm_recommend": "CPM推荐",
        "cpc_search": "CPC搜索"
    }
    ad_details = []
    for r in ad_details_query:
        date_str = r.record_date.strftime("%Y-%m-%d") if isinstance(r.record_date, datetime) else str(r.record_date)[:10]
        clicks = r.clicks or 0
        impressions = r.impressions or 0
        orders = r.orders or 0
        cost = r.cost or 0
        sales = r.sales or 0

        # 根据 payment_type 和 placements 计算广告类型
        ad_type = get_ad_type(r.payment_type, r.placements)

        ad_details.append({
            "advert_id": r.advert_id or 0,
            "date": date_str,
            "type": ad_type,
            "type_name": type_name_map.get(ad_type, "CPM搜索"),
            "impressions": impressions,
            "clicks": clicks,
            "cost": cost,
            "orders": orders,
            "add_to_cart": 0,
            "ctr": (clicks / impressions * 100) if impressions > 0 else 0,
            "cart_rate": 0,
            "conversion_rate": (orders / clicks * 100) if clicks > 0 else 0,
            "spend": cost,
            "sales": sales,
            "cpc": (cost / clicks) if clicks > 0 else 0,
            "cpm": (cost / impressions * 1000) if impressions > 0 else 0,
            "acos": (cost / sales) if sales > 0 else 0,
            "roas": (sales / cost) if cost > 0 else 0
        })

    return {"summary": summary, "daily_data": list(daily_agg.values()), "adverts": adverts, "ad_details": ad_details, "source": "database"}

    # ============ 数据库无数据,尝试API ============
    from app.services.wb_api import WBAPIClient

    shop = db.query(Shop).filter(Shop.id == product.shop_id).first()
    if not shop or not shop.api_token:
        raise HTTPException(status_code=400, detail="店铺没有API Token")

    client = WBAPIClient(shop.api_token)
    adverts = client.get_adverts()

    product_ads = []
    product_ad_ids = []
    nm_id = str(product.nm_id)
    for ad in adverts:
        for nm in ad.get("nm_settings", []):
            if str(nm.get("nm_id")) == nm_id:
                ad_data = {
                    "id": ad.get("id"),
                    "name": ad.get("settings", {}).get("name", ""),
                    "status": ad.get("status"),
                    "type": ad.get("type", ""),
                    "type_name": ad.get("type_name", ""),
                    "payment_type": ad.get("settings", {}).get("payment_type", ""),
                    "bid_type": ad.get("bid_type")
                }
                if ad_data not in product_ads:
                    product_ads.append(ad_data)
                    product_ad_ids.append(ad.get("id"))

    daily_data = []
    summary = {"impressions": 0, "clicks": 0, "ctr": 0, "spend": 0, "sales": 0, "roas": 0, "acos": 0}

    if product_ad_ids:
        try:
            stats = client.get_ad_stats(ids=product_ad_ids, date_from=date_from, date_to=date_to)
            for stat in stats:
                for day in stat.get("days", []):
                    date = day.get("date", "")[:10]
                    summary["impressions"] += day.get("views", 0)
                    summary["clicks"] += day.get("clicks", 0)
                    summary["spend"] += day.get("sum", 0)
                    for app in day.get("apps", []):
                        for nm in app.get("nms", []):
                            if str(nm.get("nmId")) == nm_id:
                                daily_data.append({"date": date, "impressions": nm.get("views", 0), "clicks": nm.get("clicks", 0), "spend": nm.get("sum", 0), "orders": nm.get("orders", 0), "sales": nm.get("sum_price", 0)})
                                summary["sales"] += nm.get("sum_price", 0)
        except Exception as e:
            print(f"获取广告统计失败: {e}")

    if summary["impressions"] > 0:
        summary["ctr"] = summary["clicks"] / summary["impressions"]
    if summary["spend"] > 0:
        summary["roas"] = summary["sales"] / summary["spend"]
        summary["acos"] = (summary["spend"] / summary["sales"]) * 100 if summary["sales"] > 0 else 0

    return {"summary": summary, "daily_data": daily_data, "adverts": product_ads, "source": "api"}


@router.get("/{product_id}/traffic-source/")
def get_product_traffic_source(
    product_id: int,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取产品流量来源分析 - 广告访客 vs 自然访客"""
    from datetime import datetime, timedelta

    # 获取产品信息
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")

    # 设置默认日期
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    if not date_from:
        date_from = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    # 获取产品分析数据(总访客)
    analytics_query = db.query(AdRecord).filter(
        AdRecord.product_id == product_id,
        AdRecord.record_date >= date_from,
        AdRecord.record_date <= date_to,
        AdRecord.ad_type == "product_analytics"
    )
    analytics_records = analytics_query.all()

    total_visitors = sum(r.impressions or 0 for r in analytics_records)

    # 获取广告访客数据
    advertising_query = db.query(AdRecord).filter(
        AdRecord.product_id == product_id,
        AdRecord.record_date >= date_from,
        AdRecord.record_date <= date_to,
        AdRecord.ad_type == "advertising"
    )
    advertising_records = advertising_query.all()

    ad_visitors = sum(r.impressions or 0 for r in advertising_records)
    ad_clicks = sum(r.visitors or 0 for r in advertising_records)

    # 计算自然访客
    natural_visitors = max(0, total_visitors - ad_visitors)

    # 计算比例
    if total_visitors > 0:
        ad_ratio = round(ad_visitors / total_visitors * 100, 1)
        natural_ratio = round(natural_visitors / total_visitors * 100, 1)
    else:
        ad_ratio = 0
        natural_ratio = 0

    return {
        "product_id": product_id,
        "product_name": product.name,
        "date_from": date_from,
        "date_to": date_to,
        "total_visitors": total_visitors,
        "ad_visitors": ad_visitors,
        "ad_clicks": ad_clicks,
        "natural_visitors": natural_visitors,
        "other_visitors": 0,
        "ad_ratio": ad_ratio,
        "natural_ratio": natural_ratio,
        "other_ratio": 0
    }


@router.get("/{product_id}/keyword-stats")
def get_product_keyword_stats(
    product_id: int,
    date_from: str = None,
    date_to: str = None,
    advert_id: int = None,
    payment_type: str = None,  # cpm 或 cpc
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取产品关键词统计数据"""
    from datetime import datetime, timedelta
    from sqlalchemy import func
    from app.models.models import AdKeywordStat

    # 获取产品信息
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")

    # 设置默认日期
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    if not date_from:
        date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # 构建查询
    query = db.query(
        AdKeywordStat.keyword,
        AdKeywordStat.payment_type,
        func.sum(AdKeywordStat.clicks).label("clicks"),
        func.sum(AdKeywordStat.views).label("views"),
        func.sum(AdKeywordStat.order_count).label("orders"),
        func.sum(AdKeywordStat.shks).label("shks"),
        func.sum(AdKeywordStat.spend).label("spend"),
        func.avg(AdKeywordStat.ctr).label("ctr"),
        func.avg(AdKeywordStat.cpm).label("cpm"),
        func.avg(AdKeywordStat.cpc).label("cpc"),
        func.avg(AdKeywordStat.avg_position).label("avg_position"),
        func.sum(AdKeywordStat.atbs).label("atbs")
    ).filter(
        AdKeywordStat.product_id == product_id,
        AdKeywordStat.date >= date_from,
        AdKeywordStat.date <= date_to
    )

    # 可选:按广告ID筛选
    if advert_id:
        query = query.filter(AdKeywordStat.advert_id == advert_id)

    # 可选:按广告类型筛选 (cpm/cpc)
    if payment_type:
        query = query.filter(AdKeywordStat.payment_type == payment_type)

    # 分组聚合(按关键词和广告类型)
    keyword_stats = query.group_by(AdKeywordStat.keyword, AdKeywordStat.payment_type).all()

    # 计算汇总
    total_clicks = sum(k.clicks or 0 for k in keyword_stats)
    total_orders = sum(k.orders or 0 for k in keyword_stats)
    total_spend = sum(k.spend or 0 for k in keyword_stats)

    # 构建结果
    keywords = []
    for k in keyword_stats:
        clicks = k.clicks or 0
        orders = k.orders or 0
        spend = k.spend or 0
        keywords.append({
            "keyword": k.keyword,
            "payment_type": k.payment_type or "",
            "clicks": clicks,
            "views": k.views or 0,
            "orders": orders,
            "shks": k.shks or 0,
            "spend": spend,
            "ctr": round(k.ctr or 0, 2),
            "cpm": round(k.cpm or 0, 2),
            "cpc": round(k.cpc or 0, 2),
            "avg_position": round(k.avg_position or 0, 1),
            "atbs": k.atbs or 0,
            "cart_rate": round((k.atbs or 0) / clicks * 100, 2) if clicks > 0 else 0,
            "conv_rate": round(orders / clicks * 100, 2) if clicks > 0 else 0
        })

    # 按点击数排序
    keywords.sort(key=lambda x: x["clicks"], reverse=True)

    return {
        "product_id": product_id,
        "date_from": date_from,
        "date_to": date_to,
        "total_clicks": total_clicks,
        "total_orders": total_orders,
        "total_spend": total_spend,
        "avg_cpc": round(total_spend / total_clicks, 2) if total_clicks > 0 else 0,
        "keywords": keywords
    }


@router.get("/{product_id}/keyword-daily")
def get_product_keyword_daily(
    product_id: int,
    keyword: str,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取产品某个关键词的每日数据"""
    from datetime import datetime, timedelta
    from app.models.models import AdKeywordStat

    # 获取产品信息
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")

    # 设置默认日期
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    if not date_from:
        date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # 查询每日数据
    daily_data = db.query(AdKeywordStat).filter(
        AdKeywordStat.product_id == product_id,
        AdKeywordStat.keyword == keyword,
        AdKeywordStat.date >= date_from,
        AdKeywordStat.date <= date_to
    ).order_by(AdKeywordStat.date).all()

    result = []
    for d in daily_data:
        clicks = d.clicks or 0
        views = d.views or 0
        orders = d.order_count or 0
        shks = d.shks or 0
        spend = d.spend or 0
        result.append({
            "date": d.date.strftime("%Y-%m-%d") if hasattr(d.date, 'strftime') else str(d.date),
            "keyword": d.keyword,
            "clicks": clicks,
            "views": views,
            "orders": orders,
            "shks": shks,
            "spend": spend,
            "ctr": round(d.ctr or 0, 2),
            "cpm": round(d.cpm or 0, 2),
            "cpc": round(d.cpc or 0, 2),
            "avg_position": round(d.avg_position or 0, 1),
            "atbs": d.atbs or 0,
            "cart_rate": round((d.atbs or 0) / clicks * 100, 2) if clicks > 0 else 0,
            "conv_rate": round(orders / clicks * 100, 2) if clicks > 0 else 0
        })

    return {
        "product_id": product_id,
        "keyword": keyword,
        "date_from": date_from,
        "date_to": date_to,
        "daily_data": result
    }

@router.get("/{product_id}/cpm-recommendations")
def get_product_cpm_recommendations(
    product_id: int,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取产品CPM推荐广告数据(按日期和平台分组)"""
    from datetime import datetime, timedelta

    # 获取产品信息
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")

    # 设置默认日期
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    if not date_from:
        date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # 查询CPM推荐广告数据
    # 策略1: 查询 payment_type='cpm' AND placements='recommendations'
    # 策略2: 如果策略1无结果,查询 advert_id=32645323 (CPM推荐的唯一广告ID) 的记录
    # 这是因为同步数据时有些记录的 payment_type/placements 未正确填充
    # 查询CPM推荐广告数据(按日期分组聚合)
    records = db.query(
        AdRecord.record_date,
        func.sum(AdRecord.impressions).label('impressions'),
        func.sum(AdRecord.visitors).label('visitors'),
        func.sum(AdRecord.cost).label('cost'),
        func.sum(AdRecord.order_count).label('order_count'),
        func.sum(AdRecord.cart_count).label('cart_count'),
        func.max(AdRecord.ctr).label('ctr'),
    ).filter(
        AdRecord.product_id == product_id,
        AdRecord.payment_type == "cpm",
        AdRecord.placements == "recommendations",
        AdRecord.record_date >= date_from,
        AdRecord.record_date < f"{date_to} 23:59:59"
    ).group_by(AdRecord.record_date).order_by(AdRecord.record_date.desc()).all()

    # 如果策略1无结果,使用策略2(按 advert_id 查询)
    if not records:
        records = db.query(
            AdRecord.record_date,
            func.sum(AdRecord.impressions).label('impressions'),
            func.sum(AdRecord.visitors).label('visitors'),
            func.sum(AdRecord.cost).label('cost'),
            func.sum(AdRecord.order_count).label('order_count'),
            func.sum(AdRecord.cart_count).label('cart_count'),
            func.max(AdRecord.ctr).label('ctr'),
        ).filter(
            AdRecord.product_id == product_id,
            AdRecord.advert_id == 32645323,
            AdRecord.record_date >= date_from,
            AdRecord.record_date < f"{date_to} 23:59:59"
        ).group_by(AdRecord.record_date).order_by(AdRecord.record_date.desc()).all()

    result = []
    for r in records:
        visitors = float(r.visitors or 0)
        cost = float(r.cost or 0)
        impressions = float(r.impressions or 0)
        result.append({
            "record_date": r.record_date.strftime("%Y-%m-%d") if r.record_date else None,
            "impressions": impressions,
            "visitors": visitors,
            "cost": cost,
            "order_count": int(r.order_count or 0),
            "cart_count": int(r.cart_count or 0),
            "ctr": float(r.ctr or 0) if r.ctr else 0,
            "cpm": round(cost / impressions * 1000, 2) if impressions else 0,
            "cpc": round(cost / visitors, 2) if visitors else 0
        })

    return {
        "product_id": product_id,
        "date_from": date_from,
        "date_to": date_to,
        "data": result
    }


@router.get("/{product_id}/cpm-search")
def get_product_cpm_search(
    product_id: int,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取产品CPM搜索广告数据(按日期和平台分组)"""
    from datetime import datetime, timedelta

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")

    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    if not date_from:
        date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # CPM搜索：payment_type='cpm' AND placements='search'
    records = db.query(
        AdRecord.record_date,
        func.sum(AdRecord.impressions).label('impressions'),
        func.sum(AdRecord.visitors).label('visitors'),
        func.sum(AdRecord.cost).label('cost'),
        func.sum(AdRecord.order_count).label('order_count'),
        func.sum(AdRecord.cart_count).label('cart_count'),
        func.max(AdRecord.ctr).label('ctr'),
    ).filter(
        AdRecord.product_id == product_id,
        AdRecord.payment_type == "cpm",
        AdRecord.placements == "search",
        AdRecord.record_date >= date_from,
        AdRecord.record_date < f"{date_to} 23:59:59"
    ).group_by(AdRecord.record_date).order_by(AdRecord.record_date.desc()).all()

    result = []
    for r in records:
        visitors = float(r.visitors or 0)
        cost = float(r.cost or 0)
        impressions = float(r.impressions or 0)
        result.append({
            "record_date": r.record_date.strftime("%Y-%m-%d") if r.record_date else None,
            "impressions": impressions,
            "visitors": visitors,
            "cost": cost,
            "order_count": int(r.order_count or 0),
            "cart_count": int(r.cart_count or 0),
            "ctr": float(r.ctr or 0) if r.ctr else 0,
            "cpm": round(cost / impressions * 1000, 2) if impressions else 0,
            "cpc": round(cost / visitors, 2) if visitors else 0
        })

    return {
        "product_id": product_id,
        "date_from": date_from,
        "date_to": date_to,
        "data": result
    }


@router.get("/{product_id}/cpc-search")
def get_product_cpc_search(
    product_id: int,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取产品CPC搜索广告数据(按日期和平台分组)"""
    from datetime import datetime, timedelta

    # 获取产品信息
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")

    # 设置默认日期
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    if not date_from:
        date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # 查询CPC搜索广告数据
    # 策略1: 查询 payment_type='cpc' AND placements='search'
    # 策略2: 如果策略1无结果,查询该产品的所有广告记录(因为同步时 payment_type/placements 可能未正确填充)
    # 查询CPC搜索广告数据（按日期分组聚合）
    records = db.query(
        AdRecord.record_date,
        func.sum(AdRecord.impressions).label('impressions'),
        func.sum(AdRecord.visitors).label('visitors'),
        func.sum(AdRecord.cost).label('cost'),
        func.sum(AdRecord.order_count).label('order_count'),
        func.sum(AdRecord.cart_count).label('cart_count'),
        func.max(AdRecord.ctr).label('ctr'),
    ).filter(
        AdRecord.product_id == product_id,
        AdRecord.payment_type == "cpc",
        AdRecord.placements == "search",
        AdRecord.record_date >= date_from,
        AdRecord.record_date < f"{date_to} 23:59:59"
    ).group_by(AdRecord.record_date).order_by(AdRecord.record_date.desc()).all()

    result = []
    for r in records:
        visitors = float(r.visitors or 0)
        cost = float(r.cost or 0)
        impressions = float(r.impressions or 0)
        result.append({
            "record_date": r.record_date.strftime("%Y-%m-%d") if r.record_date else None,
            "impressions": impressions,
            "visitors": visitors,
            "cost": cost,
            "order_count": int(r.order_count or 0),
            "cart_count": int(r.cart_count or 0),
            "ctr": float(r.ctr or 0) if r.ctr else 0,
            "cpm": round(cost / impressions * 1000, 2) if impressions else 0,
            "cpc": round(cost / visitors, 2) if visitors else 0
        })

    return {
        "product_id": product_id,
        "date_from": date_from,
        "date_to": date_to,
        "data": result
    }
