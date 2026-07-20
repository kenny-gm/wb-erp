"""
WB API 客户端
支持多个API分类的统一调用接口
"""

import httpx
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from app.config import settings


@dataclass
class RateLimiter:
    """API 限流控制器"""
    limit: int  # 时间窗口内最大请求数
    interval: float  # 时间窗口（秒）
    burst: int  # 允许的突发请求数
    window_seconds: int = 60  # 滑动窗口大小
    
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.requests = []
    
    def wait_if_needed(self):
        """如果需要，等待到有可用配额"""
        now = time.time()
        # 清理过期请求
        self.requests = [t for t in self.requests if now - t < self.window_seconds]
        
        # 检查是否需要等待
        if len(self.requests) >= self.limit:
            # 计算需要等待的时间
            wait_time = self.window_seconds - (now - self.requests[0])
            if wait_time > 0:
                time.sleep(wait_time)
        
        # 记录本次请求
        self.requests.append(now)
    
    def add_cost(self, cost: int = 1):
        """增加请求消耗（用于错误处理）"""
        for _ in range(cost):
            self.requests.append(time.time())


class WBAPIClient:
    """Wildberries API 客户端"""
    
    # API域名映射
    API_DOMAINS = {
        "common": "https://common-api.wildberries.ru",
        "content": "https://content-api.wildberries.ru",
        "marketplace": "https://marketplace-api.wildberries.ru",
        "analytics": "https://seller-analytics-api.wildberries.ru",
        "statistics": "https://statistics-api.wildberries.ru",
        "promotion": "https://advert-api.wildberries.ru",
        "finance": "https://finance-api.wildberries.ru",
    }
    
    # 限流配置（按文档）
    RATE_LIMITS = {
        # 内容 - 高频操作
        "content": RateLimiter(
            limit=100,       # 100请求/分钟
            interval=0.6,    # 600ms 间隔
            burst=10,        # 突发10个
            window_seconds=60
        ),
        # 订单库存 - 高频操作
        "marketplace": RateLimiter(
            limit=300,       # 300请求/分钟
            interval=0.2,    # 200ms 间隔
            burst=20,        # 突发20个
            window_seconds=60
        ),
        # 分析报表 - 1分钟3次
        "analytics": RateLimiter(
            limit=3,         # 3请求/分钟
            interval=20.0,   # 20秒 间隔
            burst=1,         # 不允许突发
            window_seconds=60
        ),
        # 统计报表 - 1分钟3次
        "statistics": RateLimiter(
            limit=3,         # 3请求/分钟
            interval=20.0,   # 20秒 间隔
            burst=1,         # 不允许突发
            window_seconds=60
        ),
        # 广告推广 - 1分钟3次
        "promotion": RateLimiter(
            limit=3,         # 3请求/分钟
            interval=20.0,   # 20秒 间隔
            burst=1,         # 不允许突发
            window_seconds=60
        ),
        # 财务 - 敏感操作
        "finance": RateLimiter(
            limit=60,        # 60请求/分钟
            interval=1.0,    # 1秒 间隔
            burst=5,         # 突发5个
            window_seconds=60
        ),
    }
    
    # 错误码对应的请求消耗倍数
    ERROR_COST_MULTIPLIER = {
        409: 5,   # 状态更新错误
        429: 5,   # 限流错误
    }
    
    def __init__(self, api_token: str):
        self.api_token = api_token
        self.headers = {
            "Authorization": api_token,
            "Content-Type": "application/json"
        }
    
    def _get_limiter(self, category: str) -> RateLimiter:
        """获取指定分类的限流器"""
        if category not in self.RATE_LIMITS:
            return self.RATE_LIMITS["marketplace"]
        return self.RATE_LIMITS[category]
    
    def _request(
        self,
        method: str,
        category: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        retry: int = 3,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """发送 API 请求"""
        url = f"{self.API_DOMAINS.get(category, '')}{endpoint}"
        limiter = self._get_limiter(category)
        timeout_seconds = timeout if timeout is not None else float(settings.WB_API_TIMEOUT)
        
        last_error = None
        
        for attempt in range(retry):
            try:
                limiter.wait_if_needed()
                
                with httpx.Client(timeout=timeout_seconds) as client:
                    if method == "GET":
                        response = client.get(url, headers=self.headers, params=params)
                    elif method == "POST":
                        response = client.post(url, headers=self.headers, params=params, json=json_data)
                    elif method == "PUT":
                        response = client.put(url, headers=self.headers, params=params, json=json_data)
                    elif method == "DELETE":
                        response = client.delete(url, headers=self.headers, params=params)
                    else:
                        raise ValueError(f"Unsupported method: {method}")
                    
                    if response.status_code == 200:
                        return response.json()
                    elif response.status_code == 204:
                        return {}
                    elif response.status_code == 429:
                        print(f"Rate limited (429), waiting... attempt {attempt + 1}/{retry}")
                        limiter.add_cost(5)
                        time.sleep(60)
                        continue
                    elif response.status_code == 409:
                        limiter.add_cost(5)
                        if attempt < retry - 1:
                            time.sleep(35)
                            continue
                        raise Exception(f"API 请求失败 [{response.status_code}]: {response.text}")
                    elif response.status_code == 401:
                        raise Exception(f"API 认证失败 (401): Token 无效或已过期")
                    elif response.status_code == 403:
                        raise Exception(f"API 权限不足 (403): {response.text[:200]}")
                    elif response.status_code == 404:
                        raise Exception(f"API 端点不存在 [404]: {url}")
                    else:
                        raise Exception(f"API 请求失败 [{response.status_code}]: {response.text[:200]}")
                        
            except httpx.TimeoutException:
                last_error = Exception("API 请求超时")
                if attempt < retry - 1:
                    time.sleep(2)
                    continue
            except httpx.NetworkError:
                last_error = Exception("网络错误")
                if attempt < retry - 1:
                    time.sleep(35)
                    continue
            except Exception as e:
                if "认证失败" in str(e) or "权限不足" in str(e):
                    raise
                last_error = e
                if attempt < retry - 1:
                    time.sleep(2)
                    continue
        
        raise last_error or Exception("API 请求失败")
    
    # ========== 通用接口 ==========
    def ping(self) -> bool:
        """测试 API 连接"""
        try:
            self._request("GET", "common", "/api/v1/seller-info")
            return True
        except Exception:
            return False
    
    # ========== 商品相关 ==========
    def get_products(self, limit: int = 100, offset: int = 0, locale: str = "ru") -> List[Dict[str, Any]]:
        """获取商品列表 - 使用cursor分页"""
        try:
            response = self._request(
                "POST", "content", f"/content/v2/get/cards/list?locale={locale}",
                json_data={
                    "settings": {
                        "sort": {"ascending": False},
                        "filter": {"withPhoto": -1},
                        "cursor": {"limit": limit}
                    }
                }
            )
            return response.get("cards", [])
        except Exception as e:
            print(f"get_products错误: {e}")
            return []
    
    def get_products_all(self, locale: str = "ru") -> List[Dict[str, Any]]:
        """获取所有商品"""
        all_products = []
        limit = 100
        cursor = {"limit": limit}
        
        while True:
            response = self._request(
                "POST", "content", f"/content/v2/get/cards/list?locale={locale}",
                json_data={
                    "settings": {
                        "sort": {"ascending": False},
                        "filter": {"withPhoto": -1},
                        "cursor": cursor,
                    }
                }
            )
            products = response.get("cards", [])
            all_products.extend(products)

            next_cursor = response.get("cursor") or {}
            total = int(next_cursor.get("total") or len(products))
            updated_at = next_cursor.get("updatedAt")
            nm_id = next_cursor.get("nmID")
            if total < limit or not products or not updated_at or not nm_id:
                break
            cursor = {"limit": limit, "updatedAt": updated_at, "nmID": nm_id}
        
        return all_products
    
    # ========== 订单相关 ==========
    def get_new_orders(self) -> List[Dict[str, Any]]:
        """获取新订单"""
        response = self._request("GET", "marketplace", "/api/v3/orders/new")
        return response.get("orders", [])
    
    def get_orders(self, limit: int = 1000, offset: int = 0) -> List[Dict[str, Any]]:
        """获取订单列表"""
        response = self._request(
            "GET", "marketplace", "/api/v3/orders",
            params={"limit": limit, "offset": offset}
        )
        return response.get("orders", [])
    
    # ========== 库存相关 ==========
    def get_warehouses(self) -> List[Dict[str, Any]]:
        """获取仓库列表"""
        response = self._request("GET", "marketplace", "/api/v3/warehouses")
        return response
    
    def get_inventory(self, warehouse_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取库存数据"""
        params = {}
        if warehouse_id:
            params["warehouseId"] = warehouse_id
        
        response = self._request(
            "GET", "marketplace", "/api/v3/stocks",
            params=params
        )
        return response.get("stocks", [])
    
    # ========== 广告相关 ==========
    def get_adverts(self) -> List[Dict[str, Any]]:
        """获取广告列表"""
        response = self._request("GET", "promotion", "/api/advert/v2/adverts")
        return response.get("adverts", []) if isinstance(response, dict) else response
    
    def get_ad_stats(self, ids: Optional[List[int]] = None, date_from: Optional[str] = None, date_to: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取广告统计 - 分批调用，每次最多50个广告ID"""
        try:
            if not ids:
                adverts = self.get_adverts()
                ids = [adv.get("id") for adv in adverts if adv.get("id")]
            
            if not ids:
                return []
            
            # 分批获取，每次最多50个广告ID
            all_stats = []
            batch_size = 50
            
            for i in range(0, len(ids), batch_size):
                batch_ids = ids[i:i+batch_size]
                
                params = {"ids": ",".join(map(str, batch_ids))}
                if date_from:
                    params["beginDate"] = date_from
                if date_to:
                    params["endDate"] = date_to
                
                response = self._request("GET", "promotion", "/adv/v3/fullstats", params=params)
                
                if isinstance(response, list):
                    all_stats.extend(response)
                elif isinstance(response, dict) and "data" in response:
                    all_stats.extend(response.get("data", []))
                
                # 添加延迟避免限流
                if i + batch_size < len(ids):
                    import time
                    time.sleep(35)
            
            return all_stats
        except Exception as e:
            print(f"Ad stats API error: {e}")
            return []

    def get_keyword_stats(self, items: List[Dict[str, int]], date_from: str, date_to: str) -> Dict[str, Any]:
        """获取关键词统计 - normquery/stats API
        
        Args:
            items: 广告ID和nmId列表，格式：[{"advertId": 123, "nmId": 456}, ...]
            date_from: 开始日期 YYYY-MM-DD
            date_to: 结束日期 YYYY-MM-DD
        """
        try:
            response = self._request(
                "POST", "promotion", "/adv/v1/normquery/stats",
                json_data={
                    "from": date_from,
                    "to": date_to,
                    "items": items
                }
            )
            return response if response else {}
        except Exception as e:
            print(f"Keyword stats API error: {e}")
            return {}
    
    # ========== 分析相关 ==========
    def get_sales_history(self, date_from: str, date_to: str) -> List[Dict[str, Any]]:
        """获取销售历史"""
        try:
            response = self._request(
                "POST", "analytics", "/api/analytics/v3/sales-funnel/products/history",
                json_data={"period": {"begin": date_from, "end": date_to}}
            )
            return response.get("data", {}).get("products", []) if response else []
        except Exception as e:
            print(f"Sales history API error: {e}")
            return []
    
    def get_sales_funnel(self, date_from: str, date_to: str) -> Dict[str, Any]:
        """获取销售漏斗"""
        response = self._request(
            "POST", "analytics", "/api/v1/sales-funnel",
            json_data={"dateFrom": date_from, "dateTo": date_to}
        )
        return response or {}
    
    def get_product_stats(self, date_from: str, date_to: str, nm_ids: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        """获取产品统计"""
        try:
            json_data = {
                "period": {"begin": date_from, "end": date_to},
                "brandNames": [],
                "objectIDs": [],
                "nmIDs": nm_ids or []
            }
            
            response = self._request(
                "POST", "analytics", "/api/v2/nm-report",
                json_data=json_data
            )
            return response.get("data", {}).get("cards", []) if response else []
        except Exception as e:
            print(f"Product stats API error: {e}")
            return []

    def get_products_from_statistics(self) -> List[Dict[str, Any]]:
        """
        从Statistics API获取商品列表（当Content API不可用时使用）
        通过库存数据获取唯一的商品列表
        """
        try:
            response = self._request(
                "GET", "statistics", "/api/v1/supplier/stocks",
                params={"dateFrom": "2020-01-01"}
            )
            if isinstance(response, list):
                # 从库存数据中提取唯一的产品
                products = {}
                for item in response:
                    nm_id = item.get("nmId")
                    if nm_id:
                        products[nm_id] = {
                            "nmId": nm_id,
                            "supplierArticle": item.get("supplierArticle", ""),
                            "TechSize": item.get("techSize", ""),
                            "Barcode": item.get("barcode", ""),
                            "Quantity": item.get("quantity", 0),
                            "InWayToClient": item.get("inWayToClient", 0),
                            "InWayFromClient": item.get("inWayFromClient", 0),
                            "QuantityFull": item.get("quantityFull", 0),
                        }
                return list(products.values())
            return []
        except Exception as e:
            print(f"Get products from statistics error: {e}")
            return []


    def get_product_sales_funnel(self, nm_ids: List[int], date_from: str, date_to: str) -> Dict[str, Any]:
        """
        获取产品销售漏斗数据
        接口：POST /api/analytics/v3/sales-funnel/products/history
        返回：{nm_id: {date: {visitors, cart_count, order_count, order_sum}}}
        """
        try:
            if not nm_ids:
                return {}
            
            all_product_data = {}
            batch_size = 20
            
            for i in range(0, len(nm_ids), batch_size):
                batch_nm_ids = nm_ids[i:i+batch_size]
                
                json_data = {
                    "nmIds": [int(nm_id) for nm_id in batch_nm_ids],
                    "selectedPeriod": {
                        "start": date_from,
                        "end": date_to
                    }
                }
                
                response = self._request(
                    "POST", "analytics", "/api/analytics/v3/sales-funnel/products/history",
                    json_data=json_data,
                    timeout=90.0
                )
                
                if not response:
                    continue
                
                products = response if isinstance(response, list) else []
                
                for product in products:
                    nm_id = str(product.get("product", {}).get("nmId"))
                    if not nm_id:
                        continue
                    
                    history_list = product.get("history", [])
                    
                    for day_data in history_list:
                        date = day_data.get("date", "")
                        if not date:
                            continue
                        
                        if nm_id not in all_product_data:
                            all_product_data[nm_id] = {}
                        
                        all_product_data[nm_id][date] = {
                            "visitors": day_data.get("openCount", 0),
                            "cart_count": day_data.get("cartCount", 0),
                            "order_count": day_data.get("orderCount", 0),
                            "order_sum": day_data.get("orderSum", 0)
                        }
                
                import time
                time.sleep(0.5)
            
            return all_product_data
        except Exception as e:
            print(f"Product sales funnel API error: {e}")
            return []


# 注册为平台客户端
from app.services.platform_client import register_platform_client, BasePlatformClient
register_platform_client("wildberries", WBAPIClient)
