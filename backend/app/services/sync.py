"""
数据同步服务
支持:
1. 新店铺:自动同步90天历史数据(按天分批)
2. 已存在店铺:增量同步(只拉取新数据)
3. 数据去重:存在则更新,不存在则插入
"""
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.models import (
    Shop, Product, Order, OrderItem, InventorySnapshot,
    AdRecord, AdKeywordStat, SyncLog, InventoryRecord
)
from app.services.wb_api import WBAPIClient
from app.services.wb_product_card import apply_wb_card_fields, product_name_from_card

logger = logging.getLogger("sync")


class SyncService:
    """数据同步服务"""

    # 新店铺同步历史天数
    HISTORY_DAYS = 30

    # 每批请求间隔(秒),避免限流
    BATCH_INTERVAL = 1.0

    def __init__(self, db: Session, shop: Shop):
        self.db = db
        self.shop = shop
        self.client = WBAPIClient(shop.api_token)
        self.shop_id = shop.id

    def is_new_shop(self) -> bool:
        """判断是否为新店铺(从未同步过)"""
        return self.shop.last_sync_at is None

    def _create_sync_log(self, sync_type: str) -> SyncLog:
        """创建同步日志"""
        sync_log = SyncLog(
            shop_id=self.shop_id,
            sync_type=sync_type,
            status="running"
        )
        self.db.add(sync_log)
        self.db.commit()
        return sync_log

    def _finish_sync_log(self, sync_log: SyncLog, success: bool, count: int = 0, message: str = ""):
        """完成同步日志"""
        sync_log.status = "success" if success else "failed"
        sync_log.records_count = count
        sync_log.message = message
        sync_log.finished_at = datetime.now(ZoneInfo("Asia/Shanghai"))
        self.db.commit()

    # ==================== 商品同步 ====================

    def sync_products(self, limit: int = 1000, overwrite: bool = False) -> dict:
        """
        同步商品

        Args:
            limit: 每批获取数量
            overwrite: 是否覆盖已存在的商品

        Returns:
            {"success": bool, "count": int, "updated": int}
        """
        sync_log = self._create_sync_log("products")
        
        try:
            count = 0
            updated = 0
            
            # 先更新时间戳，避免API失败时也记录同步时间
            self.shop.last_sync_at = datetime.now(ZoneInfo("Asia/Shanghai"))
            self.db.commit()
            
            logger.info(f"开始同步产品，shop_id={self.shop_id}")
            
            # 先尝试Content API
            cards = self.client.get_products(limit=limit, offset=0, locale="ru")
            logger.info(f"Content API返回: {len(cards)}个产品")

            # 如果Content API返回空,使用Statistics API
            if not cards:
                logger.info("Content API返回空,尝试Statistics API")
                cards = self.client.get_products_from_statistics()
                logger.info(f"Statistics API返回: {len(cards)}个产品")

            if not cards:
                logger.info("没有产品数据")
                self._finish_sync_log(sync_log, True, 0, "没有产品数据")
                return {"success": True, "count": 0, "updated": 0}

            # 打印第一个产品的结构用于调试
            logger.info(f"第一个产品数据示例: {json.dumps(cards[0], ensure_ascii=False)[:300]}")

            for card in cards:
                # 根据API来源解析字段
                nm_id = str(card.get("nmID", card.get("nmId", "")))
                if not nm_id:
                    logger.warning(f"产品缺少nmID: {card}")
                    continue

                # vendorCode 或 supplierArticle 是 SKU
                vendor_code = card.get("vendorCode", card.get("supplierArticle", ""))

                # 获取产品名称
                name = product_name_from_card(card, vendor_code or f"产品 {nm_id}")

                logger.info(f"处理产品: nmID={nm_id}, vendorCode={vendor_code}, name={name[:30]}")

                # 查找已存在商品
                existing = self.db.query(Product).filter(
                    Product.nm_id == nm_id,
                    Product.shop_id == self.shop_id
                ).first()

                # 提取尺寸信息
                dimensions = card.get("dimensions", {})

                if existing:
                    apply_wb_card_fields(existing, card)
                    if overwrite:
                        # 更新已存在商品
                        existing.name = name
                        existing.sku = vendor_code
                        existing.weight = dimensions.get("weightBrutto", 0)
                        existing.length = dimensions.get("length", 0)
                        existing.width = dimensions.get("width", 0)
                        existing.height = dimensions.get("height", 0)
                        updated += 1
                        logger.info(f"更新产品: {nm_id}")
                    continue
                else:
                    # 检查nm_id是否已在其他店铺存在(nm_id全局唯一)
                    existing_global = self.db.query(Product).filter(
                        Product.nm_id == nm_id
                    ).first()
                    if existing_global:
                        # nm_id已存在,直接跳过(不重复创建)
                        logger.info(f"nmID={nm_id}已存在于店铺{existing_global.shop_id},跳过")
                        continue
                    # 创建新商品
                    product = Product(
                        nm_id=nm_id,
                        sku=vendor_code,
                        shop_id=self.shop_id,
                        name=name,
                        custom_name=name,
                        weight=dimensions.get("weightBrutto", 0),
                        length=dimensions.get("length", 0),
                        width=dimensions.get("width", 0),
                        height=dimensions.get("height", 0),
                    )
                    apply_wb_card_fields(product, card)
                    self.db.add(product)
                    count += 1
                    logger.info(f"新增产品: nmID={nm_id}, name={name[:30]}")

            self._finish_sync_log(sync_log, True, count, f"新增 {count} 个，更新 {updated} 个")
            
            return {"success": True, "count": count, "updated": updated}
            
        except Exception as e:
            logger.error(f"同步商品失败: {e}")
            self._finish_sync_log(sync_log, False, 0, str(e))
            return {"success": False, "error": str(e)}

    # ==================== 订单同步 ====================

    def sync_orders(self, days: Optional[int] = 30, incremental: bool = True) -> dict:
        """
        同步订单 - 使用产品销售漏斗API获取销售数据
        """
        sync_log = self._create_sync_log("orders")

        try:
            products = self.db.query(Product).filter(
                Product.shop_id == self.shop_id,
                Product.nm_id.isnot(None)
            ).all()

            nm_ids = [int(p.nm_id) for p in products if p.nm_id and p.nm_id.isdigit()]

            if not nm_ids:
                self._finish_sync_log(sync_log, True, 0, "没有产品")
                return {"success": True, "count": 0, "updated": 0}

            # 限制为7天
            if days is None or days > 7:
                days = 7
            date_to = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
            date_from = (datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=7)).strftime("%Y-%m-%d")
            logger.info(f"DEBUG: date_from={date_from}, date_to={date_to}")

            # 获取产品销售漏斗数据
            analytics_result = self.client.get_product_sales_funnel(nm_ids, date_from, date_to)

            if not analytics_result:
                self._finish_sync_log(sync_log, True, 0, "无数据")
                return {"success": True, "count": 0, "updated": 0}

            # 聚合每日销售数据 (analytics_result格式: {nm_id: {date: data}})
            daily_sales = {}
            for nm_id, dates_data in analytics_result.items():
                for date_str, day_data in dates_data.items():
                    if date_str not in daily_sales:
                        daily_sales[date_str] = {"order_count": 0, "order_sum": 0}
                    daily_sales[date_str]["order_count"] += day_data.get("order_count", 0)
                    daily_sales[date_str]["order_sum"] += day_data.get("order_sum", 0)

            count = 0
            updated = 0

            for date_str, day_data in daily_sales.items():
                try:
                    order_date = datetime.strptime(date_str, "%Y-%m-%d")
                except:
                    continue

                total_amount = day_data.get("order_sum", 0)
                order_count = day_data.get("order_count", 0)

                if order_count == 0:
                    continue

                order_id = f"analytics_{self.shop_id}_{date_str}"

                existing = self.db.query(Order).filter(
                    Order.order_id == order_id,
                    Order.shop_id == self.shop_id
                ).first()

                if existing:
                    existing.total_amount = total_amount
                    existing.updated_at = datetime.now(ZoneInfo("Asia/Shanghai"))
                    updated += 1
                else:
                    order = Order(
                        order_id=order_id,
                        shop_id=self.shop_id,
                        status="new",
                        total_amount=total_amount,
                        commission=0,
                        logistics_fee=0,
                        order_date=order_date
                    )
                    self.db.add(order)
                    count += 1

            self.db.commit()
            self._finish_sync_log(sync_log, True, count, f"新增 {count} 条,更新 {updated} 条")
            return {"success": True, "count": count, "updated": updated}

        except Exception as e:
            self.db.rollback()
            self._finish_sync_log(sync_log, False, 0, str(e))
            return {"success": False, "error": str(e)}


    def sync_inventory(self) -> dict:
        sync_log = self._create_sync_log("inventory")
        try:
            self._finish_sync_log(sync_log, True, 0, "跳过库存同步")
            return {"success": True, "count": 0}
        except Exception as e:
            self._finish_sync_log(sync_log, False, 0, str(e))
            return {"success": False, "error": str(e)}


    def sync_ads(self, days: Optional[int] = 30) -> dict:
        sync_log = self._create_sync_log("ads")

        try:
            date_to = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")

            if days:
                date_from = (datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=days)).strftime("%Y-%m-%d")
            elif self.shop.last_sync_at:
                date_from = (self.shop.last_sync_at - timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                date_from = (datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=7)).strftime("%Y-%m-%d")

            # 首先获取广告列表,建立 advert_id -> nm_id 的正确映射
            adverts = self.client.get_adverts()

            # 构建 advert_id -> set(nm_ids) 映射,只保留该广告真正投放的产品
            advert_to_nm_ids = {}
            advert_info = {}
            for ad in adverts:
                ad_id = ad.get("id")
                if not ad_id:
                    continue
                nm_ids = set()
                for nm_setting in ad.get("nm_settings", []):
                    nm_id = str(nm_setting.get("nm_id", ""))
                    if nm_id:
                        nm_ids.add(nm_id)
                advert_to_nm_ids[ad_id] = nm_ids

                # 保存广告详情(payment_type, placements)
                settings = ad.get("settings", {})
                advert_info[ad_id] = {
                    "payment_type": settings.get("payment_type", ""),
                    "placements": settings.get("placements", {})
                }

            # 获取广告统计
            all_advert_ids = list(advert_to_nm_ids.keys())
            stats = self.client.get_ad_stats(ids=all_advert_ids, date_from=date_from, date_to=date_to)

            count = 0
            updated = 0

            for stat in stats:
                advert_id = stat.get("advertId")
                if not advert_id:
                    continue

                # 获取该广告对应的nm_ids
                target_nm_ids = advert_to_nm_ids.get(advert_id, set())
                if not target_nm_ids:
                    continue

                # 获取广告详情
                ad_detail = advert_info.get(advert_id, {})
                payment_type = ad_detail.get("payment_type", "")
                placements_dict = ad_detail.get("placements", {})
                if isinstance(placements_dict, dict):
                    if placements_dict.get("recommendations"):
                        placements = "recommendations"
                    elif placements_dict.get("search"):
                        placements = "search"
                    else:
                        placements = ""
                else:
                    placements = ""

                # 如果 payment_type=cpm 但 placements 为空,尝试从数据库历史数据推断
                if payment_type == "cpm" and not placements:
                    existing_record = self.db.query(AdRecord).filter(
                        AdRecord.advert_id == advert_id,
                        AdRecord.placements.in_(["recommendations", "search"])
                    ).first()
                    if existing_record:
                        placements = existing_record.placements

                days_data = stat.get("days", [])

                # 第一步:按平台收集数据
                # platform_data[(nm_id, date_str, platform)] = {sum, views, clicks, orders, sum_price}
                platform_data = {}
                platform_names = {1: "web", 32: "ios", 64: "android"}

                for day_data in days_data:
                    date_str = day_data.get("date", "")
                    if date_str:
                        record_date = date_str[:10]
                    else:
                        record_date = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")

                    apps = day_data.get("apps", [])
                    for app in apps:
                        app_type = app.get("appType", 0)
                        platform = platform_names.get(app_type, "other")

                        nms = app.get("nms", [])
                        for nm_data in nms:
                            nm_id = str(nm_data.get("nmId", ""))
                            # 只处理该广告投放的产品
                            if not nm_id or nm_id not in target_nm_ids:
                                continue

                            key = (nm_id, record_date, platform)
                            if key not in platform_data:
                                platform_data[key] = {
                                    "sum": 0, "views": 0, "clicks": 0, "orders": 0,
                                    "sum_price": 0
                                }

                            # 累加数据
                            platform_data[key]["sum"] += nm_data.get("sum", 0) or 0
                            platform_data[key]["views"] += nm_data.get("views", 0) or 0
                            platform_data[key]["clicks"] += nm_data.get("clicks", 0) or 0
                            platform_data[key]["orders"] += nm_data.get("orders", 0) or 0
                            platform_data[key]["sum_price"] += nm_data.get("sum_price", 0) or 0

                # 第二步:写入平台明细数据
                for (nm_id, record_date, platform), data in platform_data.items():
                    product = self.db.query(Product).filter(
                        Product.nm_id == nm_id,
                        Product.shop_id == self.shop_id
                    ).first()

                    if not product:
                        continue

                    nm_sum = data["sum"]
                    nm_views = data["views"]
                    nm_clicks = data["clicks"]
                    nm_orders = data["orders"]
                    nm_sum_price = data["sum_price"]
                    nm_cpc = (nm_sum / nm_clicks) if nm_clicks > 0 else 0

                    # 转换为datetime对象进行查询
                    record_date_dt = datetime.strptime(record_date, "%Y-%m-%d")

                    # 优先查找platform为空或匹配的记录
                    existing = self.db.query(AdRecord).filter(
                        AdRecord.shop_id == self.shop_id,
                        AdRecord.product_id == product.id,
                        AdRecord.advert_id == advert_id,
                        AdRecord.record_date == record_date_dt,
                        AdRecord.ad_type == "advertising",
                        AdRecord.platform == platform
                    ).first()

                    # 如果没找到且platform非空,尝试查找platform为空的记录进行更新
                    if not existing and platform:
                        existing = self.db.query(AdRecord).filter(
                            AdRecord.shop_id == self.shop_id,
                            AdRecord.product_id == product.id,
                            AdRecord.advert_id == advert_id,
                            AdRecord.record_date == record_date_dt,
                            AdRecord.ad_type == "advertising",
                            AdRecord.platform == ""
                        ).first()

                    if existing:
                        existing.impressions = nm_views
                        existing.visitors = nm_clicks
                        existing.cost = nm_sum
                        existing.order_count = nm_orders
                        existing.sales = round(nm_sum_price, 2)
                        # 只有API返回有效值时才更新payment_type和placements
                        if payment_type:
                            existing.payment_type = payment_type
                        if placements:
                            existing.placements = placements
                        # 更新platform字段
                        if platform:
                            existing.platform = platform
                        existing.cpc = round(nm_cpc, 2)
                        existing.cpm = round((nm_sum / nm_views * 1000), 2) if nm_views > 0 else 0
                        existing.ctr = round((nm_clicks / nm_views * 100), 2) if nm_views > 0 else 0
                        existing.conversion_rate = round((nm_orders / nm_clicks * 100), 2) if nm_clicks > 0 else 0
                        updated += 1
                    else:
                        ad_record = AdRecord(
                            product_id=product.id,
                            shop_id=self.shop_id,
                            advert_id=advert_id,
                            ad_type="advertising",
                            impressions=nm_views,
                            visitors=nm_clicks,
                            cost=nm_sum,
                            order_count=nm_orders,
                            sales=round(nm_sum_price, 2),
                            payment_type=payment_type,
                            placements=placements,
                            record_date=datetime.strptime(record_date, "%Y-%m-%d"),
                            platform=platform,
                            ctr=round((nm_clicks / nm_views * 100), 2) if nm_views > 0 else 0,
                            cpc=round(nm_cpc, 2),
                            cpm=round((nm_sum / nm_views * 1000), 2) if nm_views > 0 else 0,
                            conversion_rate=round((nm_orders / nm_clicks * 100), 2) if nm_clicks > 0 else 0
                        )
                        self.db.add(ad_record)
                        count += 1

            self.shop.last_sync_at = datetime.now(ZoneInfo("Asia/Shanghai"))
            self.db.commit()

            self._finish_sync_log(sync_log, True, count, "New " + str(count) + ", updated " + str(updated))

            return {"success": True, "count": count, "updated": updated}

        except Exception as e:
            logger.error("Sync ads failed: " + str(e))
            self._finish_sync_log(sync_log, False, 0, str(e))
            return {"success": False, "error": str(e)}


    def sync_keyword_stats(self, days: Optional[int] = 30) -> dict:
        """同步关键词统计(来自 normquery/stats API)

        仅适用于 CPC搜索 和 CPM搜索 广告,获取搜索词维度的数据
        (CPM推荐广告无搜索词概念,不适用此接口)

        Args:
            days: 同步天数,默认30天

        Returns:
            {"success": bool, "count": int, "updated": int}
        """
        sync_log = self._create_sync_log("keyword_stats")

        try:
            date_to = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
            if days:
                date_from = (datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=days)).strftime("%Y-%m-%d")
            elif self.shop.last_sync_at:
                date_from = (self.shop.last_sync_at - timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                date_from = (datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=7)).strftime("%Y-%m-%d")

            # 获取广告列表
            adverts = self.client.get_adverts()

            # 筛选出有搜索 placement 的广告(cpc_search, cpm_search)
            search_adverts = []
            for ad in adverts:
                ad_id = ad.get("id")
                if not ad_id:
                    continue
                settings = ad.get("settings", {})
                payment_type = settings.get("payment_type", "")
                placements_dict = settings.get("placements", {})

                if isinstance(placements_dict, dict) and placements_dict.get("search"):
                    # CPC搜索 或 CPM搜索
                    for nm_setting in ad.get("nm_settings", []):
                        nm_id = nm_setting.get("nm_id")
                        if nm_id:
                            search_adverts.append({
                                "advertId": ad_id,
                                "nmId": nm_id,
                                "payment_type": payment_type
                            })

            if not search_adverts:
                logger.info("No search adverts found for keyword stats")
                self._finish_sync_log(sync_log, True, 0, "No search adverts")
                return {"success": True, "count": 0, "updated": 0}

            # 批量调用关键词统计 API(每次最多50条)
            count = 0
            updated = 0
            batch_size = 50

            for i in range(0, len(search_adverts), batch_size):
                batch = search_adverts[i:i+batch_size]
                items = [{"advertId": a["advertId"], "nmId": a["nmId"]} for a in batch]
                advert_map = {a["advertId"]: a for a in batch}

                result = self.client.get_keyword_stats(items, date_from, date_to)

                items_data = result.get("items", []) or []

                for item in items_data:
                    advert_id = item.get("advertId")
                    nm_id = item.get("nmId")
                    ad_info = advert_map.get(advert_id, {})
                    payment_type = ad_info.get("payment_type", "cpc")

                    daily_stats = item.get("dailyStats", []) or []

                    for day_stat in daily_stats:
                        date_str = day_stat.get("date", "")
                        if not date_str:
                            continue

                        stat = day_stat.get("stat", {})
                        keyword = stat.get("normQuery", "")
                        if not keyword:
                            continue

                        clicks = stat.get("clicks", 0) or 0
                        orders = stat.get("orders", 0) or 0
                        spend = stat.get("spend", 0) or 0
                        cpc = stat.get("cpc", 0) or 0
                        avg_pos = stat.get("avgPos", 0) or 0
                        atbs = stat.get("atbs", 0) or 0
                        shks = stat.get("shks", 0) or 0

                        # 计算 CTR, CPM
                        views = stat.get("views", 0) or 0
                        ctr = (clicks / views * 100) if views > 0 else 0
                        cpm = (spend / views * 1000) if views > 0 else 0

                        # 查找 product
                        product = self.db.query(Product).filter(
                            Product.nm_id == str(nm_id),
                            Product.shop_id == self.shop_id
                        ).first()

                        if not product:
                            continue

                        record_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()

                        # 查询是否已有关键词记录
                        existing = self.db.query(AdKeywordStat).filter(
                            AdKeywordStat.shop_id == self.shop_id,
                            AdKeywordStat.product_id == product.id,
                            AdKeywordStat.advert_id == advert_id,
                            AdKeywordStat.keyword == keyword,
                            AdKeywordStat.date == record_date
                        ).first()

                        if existing:
                            # 更新
                            existing.clicks = clicks
                            existing.views = views
                            existing.order_count = orders
                            existing.spend = spend
                            existing.ctr = ctr
                            existing.cpm = cpm
                            existing.cpc = cpc
                            existing.avg_position = avg_pos
                            existing.atbs = atbs
                            existing.shks = shks
                            updated += 1
                        else:
                            # 新增
                            new_record = AdKeywordStat(
                                shop_id=self.shop_id,
                                product_id=product.id,
                                advert_id=advert_id,
                                nm_id=nm_id,
                                platform="search",
                                keyword=keyword,
                                date=record_date,
                                clicks=clicks,
                                views=views,
                                order_count=orders,
                                spend=spend,
                                ctr=ctr,
                                cpm=cpm,
                                cpc=cpc,
                                avg_position=avg_pos,
                                atbs=atbs,
                                shks=shks,
                                payment_type=payment_type
                            )
                            self.db.add(new_record)
                            count += 1

                # 每批间隔避免限流
                if i + batch_size < len(search_adverts):
                    time.sleep(self.BATCH_INTERVAL)

            self.db.commit()
            self._finish_sync_log(sync_log, True, count, "New " + str(count) + ", updated " + str(updated))
            return {"success": True, "count": count, "updated": updated}

        except Exception as e:
            logger.error("Sync keyword stats failed: " + str(e))
            self._finish_sync_log(sync_log, False, 0, str(e))
            return {"success": False, "error": str(e)}


    def sync_all(self, history: bool = False) -> dict:
        """
        全量同步

        Args:
            history: 是否同步历史数据(新店铺用)

        Returns:
            各模块同步结果
        """
        results = {}

        # 1. 先同步商品(必须先执行,订单依赖商品)
        logger.info("开始同步商品...")
        results["products"] = self.sync_products(overwrite=True)

        if not results["products"]["success"]:
            return results

        # 2. 同步订单
        logger.info("开始同步订单...")
        results["orders"] = self.sync_orders()

        # 3. 同步库存
        logger.info("开始同步库存...")
        results["inventory"] = self.sync_inventory()

        # 4. 同步广告
        logger.info("开始同步广告...")
        if history or self.is_new_shop():
            results["ads"] = self.sync_ads(days=self.HISTORY_DAYS)
        else:
            results["ads"] = self.sync_ads()

        # 4.5 同步关键词统计(仅搜索广告)
        logger.info("开始同步关键词统计...")
        if history or self.is_new_shop():
            results["keyword_stats"] = self.sync_keyword_stats(days=self.HISTORY_DAYS)
        else:
            results["keyword_stats"] = self.sync_keyword_stats()

        # 5. 同步产品销售漏斗数据(依赖产品数据)
        logger.info("开始同步产品销售漏斗数据...")
        if history or self.is_new_shop():
            results["product_sales"] = self.sync_product_sales(days=self.HISTORY_DAYS)
        else:
            results["product_sales"] = self.sync_product_sales()

        logger.info("全量同步完成!")
        return results

    def sync_product_sales(self, days: Optional[int] = 30) -> dict:
        """
        同步产品销售漏斗数据
        从WB API获取产品销售数据,保存到ad_records表(ad_type='product_analytics')

        Args:
            days: 同步天数,默认30天

        Returns:
            {"success": bool, "count": int, "updated": int}
        """
        sync_log = self._create_sync_log("product_sales")

        try:
            # 获取店铺所有产品
            products = self.db.query(Product).filter(
                Product.shop_id == self.shop_id,
                Product.nm_id != "0"  # 排除店铺汇总
            ).all()

            if not products:
                self._finish_sync_log(sync_log, True, 0, "无产品需要同步")
                return {"success": True, "count": 0, "updated": 0}

            # 设置日期范围
            date_to = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
            date_from = (datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=7)).strftime("%Y-%m-%d")
            logger.info(f"DEBUG: date_from={date_from}, date_to={date_to}")

            # 获取产品nm_id列表
            nm_ids = [int(p.nm_id) for p in products if p.nm_id and p.nm_id.isdigit()]

            if not nm_ids:
                self._finish_sync_log(sync_log, True, 0, "无有效产品ID")
                return {"success": True, "count": 0, "updated": 0}

            logger.info(f"开始同步产品销售数据: {len(nm_ids)}个产品, {date_from} - {date_to}")

            # 调用WB API获取产品销售漏斗数据
            product_sales_data = self.client.get_product_sales_funnel(nm_ids, date_from, date_to)

            if not product_sales_data:
                self._finish_sync_log(sync_log, True, 0, "API返回空数据")
                return {"success": True, "count": 0, "updated": 0}

            # 建立nm_id到product.id的映射
            nm_to_product = {p.nm_id: p.id for p in products}

            count = 0
            updated = 0

            # 遍历产品数据
            for nm_id_str, daily_data in product_sales_data.items():
                product_id = nm_to_product.get(nm_id_str)
                if not product_id:
                    continue

                # 遍历每日数据
                for date_str, stats in daily_data.items():
                    try:
                        record_date = date_str  # 直接使用 YYYY-MM-DD 格式
                        record_date_dt = datetime.strptime(record_date, "%Y-%m-%d")
                    except:
                        continue

                    # 查找或创建记录
                    existing = self.db.query(AdRecord).filter(
                        AdRecord.shop_id == self.shop_id,
                        AdRecord.product_id == product_id,
                        AdRecord.record_date == record_date_dt,
                        AdRecord.ad_type == "product_analytics"
                    ).first()

                    if existing:
                        # 更新现有记录 - product_analytics直接使用API字段
                        existing.impressions = 0  # API无此字段
                        existing.visitors = stats.get("visitors", 0)
                        existing.cart_count = stats.get("cart_count", 0)
                        existing.order_count = stats.get("order_count", 0)
                        existing.sales = stats.get("order_sum", 0)
                        updated += 1
                    else:
                        # 创建新记录
                        ad_record = AdRecord(
                            shop_id=self.shop_id,
                            product_id=product_id,
                            ad_type="product_analytics",
                            impressions=0,  # API无此字段
                            visitors=stats.get("visitors", 0),
                            cart_count=stats.get("cart_count", 0),
                            order_count=stats.get("order_count", 0),
                            sales=stats.get("order_sum", 0),
                            record_date=datetime.strptime(record_date, "%Y-%m-%d")
                        )
                        self.db.add(ad_record)
                        count += 1

            self.db.commit()

            total = count + updated
            logger.info(f"产品销售数据同步完成: 新增{count}条, 更新{updated}条, 总计{total}条")

            self._finish_sync_log(sync_log, True, total, f"同步{total}条产品销售数据")
            return {"success": True, "count": count, "updated": updated, "total": total}

        except Exception as e:
            logger.error(f"同步产品销售数据失败: {e}")
            self._finish_sync_log(sync_log, False, 0, str(e))
            return {"success": False, "error": str(e)}


# ==================== 订单利润计算 ====================

def calculate_order_profit(db: Session, order: Order) -> Order:
    """计算订单利润"""
    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()

    total_product_cost = 0

    for item in items:
        if item.product_id:
            # FIFO 计算产品成本
            records = db.query(InventoryRecord).filter(
                InventoryRecord.product_id == item.product_id,
                InventoryRecord.remaining_quantity > 0
            ).order_by(InventoryRecord.inbound_at).all()

            remaining_qty = item.quantity
            item_cost = 0

            for record in records:
                if remaining_qty <= 0:
                    break

                take_qty = min(remaining_qty, record.remaining_quantity)
                item_cost += take_qty * record.product_cost
                record.remaining_quantity -= take_qty
                remaining_qty -= take_qty

            item.product_cost = item_cost
            total_product_cost += item_cost

    # 计算利润
    order.product_cost = total_product_cost
    order.profit = (
        order.total_amount
        - order.commission
        - order.logistics_fee
        - order.product_cost
        - order.ad_cost
        - order.other_cost
    )

    # 计算利润率
    if order.total_amount > 0:
        order.profit_rate = order.profit / order.total_amount

    return order
