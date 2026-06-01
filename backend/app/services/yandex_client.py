"""
Yandex Market API 客户端

API 文档: https://yandex.ru/dev/market/partner-doc/ref/

数据源说明:
- 订单数据: POST /v2/campaigns/{campaignId}/stats/orders (需要 ALL_METHODS_READ_ONLY)
- 商品目录: POST /v2/campaigns/{campaignId}/offers (需要 ALL_METHODS_READ_ONLY)
- 报表(广告/访客等): POST /v2/reports/* (需要 promotion 或 finance-and-accounting 权限，当前 token 无此权限)

权限状态（2026-05-26）:
- Token: <YOUR_YANDEX_TOKEN>（已撤销，请替换为新 Token）
- scopes: ALL_METHODS_READ_ONLY
- 可用: /v2/campaigns, /v2/campaigns/{id}/stats/orders, /v2/campaigns/{id}/offers
- 不可用: /v2/reports/* (需要 promotion 或 finance-and-accounting)

⚠️ 注意：如果此 Token 已泄露，请前往 Yandex Partner Market 后台撤销并重建

MVP 口径（2026-05-27）:
- 商品同步: POST /v2/campaigns/{id}/offers，按 business_id + offer_id 聚合
- 订单同步: POST /v2/campaigns/{id}/stats/orders，按 product_id + day 聚合写入 AdRecord
- 访客/点击/加购/广告费: 暂不接入，等更高权限 Token
"""
import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timedelta, date
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger("yandex_api")


class YandexClient:
    """Yandex Market Partner API 客户端"""

    BASE_URL = "https://api.partner.market.yandex.ru"

    def __init__(self, api_token: str):
        self.api_token = api_token
        self.headers = {
            "Api-Key": api_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ============================================================
    # 基础请求
    # ============================================================

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self.BASE_URL}{path}"
        kwargs.setdefault("headers", self.headers)
        kwargs.setdefault("timeout", 30.0)
        with httpx.Client() as client:
            resp = client.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp

    def _get(self, path: str, **kwargs) -> dict:
        return self._request("GET", path, **kwargs).json()

    def _post(self, path: str, **kwargs) -> dict:
        return self._request("POST", path, **kwargs).json()

    # ============================================================
    # 1. 获取 campaigns（按 business 分组）
    # ============================================================

    def get_campaigns(self) -> Dict[int, dict]:
        """
        GET /v2/campaigns
        返回 Dict[business_id, business_info]
        """
        all_campaigns = []
        page = 1
        page_size = 100

        while True:
            resp = self._get(f"/v2/campaigns?page={page}&pageSize={page_size}")
            page_body = resp.get("campaigns", [])
            if not page_body:
                break
            all_campaigns.extend(page_body)
            pager = resp.get("pager", {})
            current_page = pager.get("currentPage", 0)
            pages_count = pager.get("pagesCount", 0)
            if current_page >= pages_count - 1:
                break
            page += 1

        businesses: Dict[int, dict] = {}
        for c in all_campaigns:
            bid = c.get("business", {}).get("id")
            if not bid:
                continue
            bid = int(bid)
            if bid not in businesses:
                businesses[bid] = {
                    "business_id": bid,
                    "business_name": c.get("business", {}).get("name", ""),
                    "campaigns": [],
                }
            businesses[bid]["campaigns"].append({
                "campaign_id": int(c.get("id", 0)),
                "domain": c.get("domain", ""),
                "placement_type": c.get("placementType", ""),
                "api_availability": c.get("apiAvailability", ""),
            })

        logger.info(f"get_campaigns: {len(businesses)} businesses")
        return businesses

    # ============================================================
    # 2. 测试连接
    # ============================================================

    def test_connection(self) -> bool:
        """至少有一个 apiAvailability=AVAILABLE 的 campaign 即认为连接可用"""
        try:
            businesses = self.get_campaigns()
            for biz in businesses.values():
                for c in biz.get("campaigns", []):
                    if c.get("api_availability") == "AVAILABLE":
                        return True
            return False
        except Exception as e:
            logger.warning(f"test_connection 异常: {e}")
            return False

    # ============================================================
    # 3. 获取单个 campaign 的商品列表
    # ============================================================

    def get_campaign_offers(self, campaign_id: int) -> List[dict]:
        """
        POST /v2/campaigns/{campaignId}/offers
        返回店铺商品列表（shopSku -> marketSku 映射）
        """
        try:
            resp = self._post(
                f"/v2/campaigns/{campaign_id}/offers",
                json={"campaignId": campaign_id}
            )
            result = resp.get("result", {})
            offers = result.get("offers", [])
            return offers
        except Exception as e:
            logger.error(f"get_campaign_offers campaign={campaign_id} 失败: {e}")
            return []

    # ============================================================
    # 4. 获取订单数据（分页，支持日期范围）
    # ============================================================

    def get_orders(
        self,
        campaign_id: int,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[dict]:
        """
        POST /v2/campaigns/{campaignId}/stats/orders
        遍历所有分页，返回订单列表。

        注意：Yandex API pageToken 分页机制有限制，
        某些 token 权限下最多返回约 100 条历史订单。
        建议使用 dateFrom/dateTo 限制范围。

        返回订单列表，每条订单关键字段:
          id, creationDate, status, currency,
          items: [{shopSku, marketSku, offerName, count, prices}],
          commissions: [{type, actual}],
          payments: [{type, total, date}]
        """
        all_orders = []
        body: Dict[str, Any] = {"campaignId": campaign_id}
        if date_from:
            body["dateFrom"] = date_from
        if date_to:
            body["dateTo"] = date_to
        page = 1
        while True:
            try:
                body["page"] = page
                resp = self._post(
                    f"/v2/campaigns/{campaign_id}/stats/orders",
                    json=body
                )
                result = resp.get("result", {})
                orders = result.get("orders", [])
                if not orders:
                    break
                all_orders.extend(orders)

                pager = result.get("pager", {})
                pages_count = pager.get("pagesCount", 1)
                if page >= pages_count:
                    break
                page += 1
            except Exception as e:
                logger.error(f"get_orders campaign={campaign_id} 分页失败: {e}")
                break

        logger.info(f"get_orders campaign={campaign_id}: 共 {len(all_orders)} 条订单")
        return all_orders

    # ============================================================
    # 5. 获取商品目录（遍历 business 下所有 campaign，按 offer_id 去重）
    # ============================================================

    def get_all_offers(self, business_id: int, campaign_ids: List[int]) -> List[dict]:
        """
        遍历 business 下所有 campaign，收集所有 offer，按 offer_id 去重。

        返回去重后的 offer 列表，每条:
          {
            "offer_id": shopSku,
            "offer_name": name,
            "campaign_id": int,
          }
        """
        seen: Dict[str, dict] = {}
        for cid in campaign_ids:
            offers = self.get_campaign_offers(cid)
            for offer in offers:
                oid = offer.get("shopSku", "") or offer.get("offerId", "")
                if not oid:
                    continue
                if oid not in seen:
                    seen[oid] = {
                        "offer_id": oid,
                        "offer_name": offer.get("name", "") or offer.get("offerName", ""),
                        "campaign_id": cid,
                    }
        logger.info(f"get_all_offers business={business_id}: 去重后 {len(seen)} 个商品")
        return list(seen.values())

    # ============================================================
    # 6. 获取订单聚合数据（遍历所有 campaign，按 product_id + day 聚合）
    # ============================================================

    def get_orders_aggregated(
        self,
        business_id: int,
        campaign_ids: List[int],
        date_from: str,
        date_to: str,
    ) -> List[dict]:
        """
        遍历 business 下所有 campaign 的订单数据，
        按 shopSku（offer_id）+ date 聚合 BUYER 类型金额。

        用于生成 AdRecord(product_analytics)。

        返回:
        [
            {
                "offer_id": "shopSku",
                "offer_name": "...",
                "day": "YYYY-MM-DD",
                "order_count": int,    # 商品件数或订单行数
                "sales_amount": float,  # BUYER 类型 price.total 之和
                "campaign_id": int,
            }
        ]
        """
        # records: { (offer_id, day_str): { offer_id, offer_name, day, order_ids_set, quantity, sales_amount } }
        # order_ids_set 用于去重统计 distinct order count
        raw: Dict[tuple, dict] = {}

        for cid in campaign_ids:
            orders = self.get_orders(cid, date_from, date_to)
            for order in orders:
                creation_date = order.get("creationDate", "")
                date_str = creation_date[:10] if creation_date else date_from
                order_id = str(order.get("id", ""))
                is_fake = order.get("fake", False)
                if is_fake:
                    continue

                order_status = str(order.get("status", "")).upper()
                if any(b in order_status for b in ("CANCELLED", "REFUNDED", "RETURNED", "UNPAID", "CANCELED")):
                    continue

                items = order.get("items", [])
                for item in items:
                    shop_sku = item.get("shopSku", "")
                    if not shop_sku:
                        continue

                    buyer_total = 0.0
                    prices = item.get("prices", [])
                    for p in prices:
                        if p.get("type") == "BUYER":
                            buyer_total += float(p.get("total", 0))

                    key = (shop_sku, date_str)
                    if key not in raw:
                        raw[key] = {
                            "offer_id": shop_sku,
                            "offer_name": item.get("offerName", ""),
                            "day": date_str,
                            "order_ids": set(),
                            "quantity": 0,
                            "sales_amount": 0.0,
                        }

                    raw[key]["order_ids"].add(order_id)
                    raw[key]["quantity"] += int(item.get("count", 0))
                    raw[key]["sales_amount"] += buyer_total

        # 聚合：distinct order_count + quantity + sales_amount
        result = []
        for key, data in raw.items():
            result.append({
                "offer_id": data["offer_id"],
                "offer_name": data["offer_name"],
                "day": data["day"],
                "order_count": len(data["order_ids"]),   # distinct order 单数
                "order_items": data["quantity"],          # 商品件数（销量）
                "sales_amount": data["sales_amount"],
            })
        logger.info(f"get_orders_aggregated: business={business_id}, {len(result)} 条聚合记录")
        return result

    # ============================================================
    # 7. 获取原始订单列表（用于 Order/OrderItem 写入）
    # ============================================================

    def get_orders_for_db(
        self,
        business_id: int,
        campaign_ids: List[int],
        date_from: str,
        date_to: str,
    ) -> List[dict]:
        """
        遍历 business 下所有 campaign，返回扁平化订单明细行。
        每行代表订单中一个商品条目，用于写入 Order / OrderItem。

        返回:
        [
            {
                "order_id": str,
                "order_date": "YYYY-MM-DD",
                "offer_id": "shopSku",
                "offer_name": "...",
                "quantity": int,
                "price": float,        # BUYER 类型单件价格
                "total_price": float,  # BUYER 类型总价
                "currency": "CNY",
                "campaign_id": int,
            }
        ]
        """
        rows = []
        for cid in campaign_ids:
            orders = self.get_orders(cid, date_from, date_to)
            for order in orders:
                creation_date = order.get("creationDate", "")
                date_str = creation_date[:10] if creation_date else date_from
                order_id = str(order.get("id", ""))
                is_fake = order.get("fake", False)
                currency = order.get("currency", "CNY")

                if is_fake:
                    continue

                # 过滤取消/退款/未支付状态订单
                order_status = str(order.get("status", "")).upper()
                if any(b in order_status for b in ("CANCELLED", "REFUNDED", "RETURNED", "UNPAID", "CANCELED")):
                    continue

                items = order.get("items", [])
                for item in items:
                    shop_sku = item.get("shopSku", "")
                    if not shop_sku:
                        continue

                    # BUYER 类型单件价格
                    buyer_price = 0.0
                    buyer_total = 0.0
                    prices = item.get("prices", [])
                    for p in prices:
                        if p.get("type") == "BUYER":
                            buyer_price = float(p.get("price", 0))
                            buyer_total = float(p.get("total", 0))
                            break

                    rows.append({
                        "order_id": order_id,
                        "order_date": date_str,
                        "offer_id": shop_sku,
                        "offer_name": item.get("offerName", ""),
                        "quantity": int(item.get("count", 0)),
                        "price": buyer_price,
                        "total_price": buyer_total,
                        "currency": currency,
                        "campaign_id": cid,
                    })

        logger.info(f"get_orders_for_db: business={business_id}, {len(rows)} 条订单明细行")
        return rows