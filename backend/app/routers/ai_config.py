from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from app.database import get_db
from app.routers.auth import get_current_admin

router = APIRouter(prefix="/api/admin/ai-config", tags=["AI配置"])

class AIConfigCreate(BaseModel):
    name: str
    config_key: str
    api_provider: Optional[str] = "deepseek"
    api_model: Optional[str] = "deepseek-chat"
    api_key: Optional[str] = None
    prompt_template: str
    variables: Optional[str] = ""
    is_active: Optional[bool] = True

class AIConfigUpdate(BaseModel):
    name: Optional[str] = None
    api_provider: Optional[str] = None
    api_model: Optional[str] = None
    api_key: Optional[str] = None
    prompt_template: Optional[str] = None
    variables: Optional[str] = None
    is_active: Optional[bool] = None

class AIConfigResponse(BaseModel):
    id: int
    name: str
    config_key: str
    api_provider: Optional[str]
    api_model: Optional[str]
    api_key: Optional[str]
    prompt_template: str
    variables: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

from app.models.models import AIConfig, SystemSetting, AIReport, AdRecord, Product

# ========== 调度设置 ==========

@router.get("/schedule-settings")
def get_schedule_settings(db: Session = Depends(get_db), current_user = Depends(get_current_admin)):
    keys = ["daily_enabled", "daily_time", "weekly_enabled", "weekly_time", "monthly_enabled", "monthly_time"]
    result = {}
    for k in keys:
        s = db.query(SystemSetting).filter(SystemSetting.key == k).first()
        if s:
            v = s.value.lower() if isinstance(s.value, str) else s.value
            if v in ["true", "false"]:
                result[k] = v == "true"
            else:
                result[k] = s.value
        else:
            result[k] = False if "enabled" in k else "06:00"
    return result

@router.put("/schedule-settings")
def update_schedule_settings(data: dict, db: Session = Depends(get_db), current_user = Depends(get_current_admin)):
    for k, v in data.items():
        s = db.query(SystemSetting).filter(SystemSetting.key == k).first()
        if s:
            s.value = str(v)
        else:
            db.add(SystemSetting(key=k, value=str(v)))
    db.commit()
    return {"message": "调度设置已更新"}

# ========== 报告 ==========

@router.get("/reports")
def get_reports(skip: int = 0, limit: int = 50, db: Session = Depends(get_db), current_user = Depends(get_current_admin)):
    reports = db.query(AIReport).order_by(AIReport.created_at.desc()).offset(skip).limit(limit).all()
    return [{"id": r.id, "type": r.type, "date_range": r.date_range, "content": r.content, "created_at": r.created_at} for r in reports]

@router.delete("/reports/{report_id}")
def delete_report(report_id: int, db: Session = Depends(get_db), current_user = Depends(get_current_admin)):
    r = db.query(AIReport).filter(AIReport.id == report_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")
    db.delete(r)
    db.commit()
    return {"message": "已删除"}

# ========== CRUD接口 ==========

@router.get("/", response_model=List[AIConfigResponse])
def get_all_configs(db: Session = Depends(get_db), current_user = Depends(get_current_admin)):
    configs = db.query(AIConfig).order_by(AIConfig.id).all()
    return configs

@router.post("/", response_model=AIConfigResponse)
def create_config(config: AIConfigCreate, db: Session = Depends(get_db), current_user = Depends(get_current_admin)):
    existing = db.query(AIConfig).filter(AIConfig.config_key == config.config_key).first()
    if existing:
        existing.api_provider = config.api_provider
        existing.api_model = config.api_model
        existing.api_key = config.api_key
        existing.prompt_template = config.prompt_template
        existing.variables = config.variables
        existing.is_active = config.is_active
        existing.updated_at = datetime.now()
        db.commit()
        db.refresh(existing)
        return existing
    db_config = AIConfig(**config.model_dump())
    db.add(db_config)
    db.commit()
    db.refresh(db_config)
    return db_config

@router.put("/{config_id}", response_model=AIConfigResponse)
def update_config(config_id: int, config: AIConfigUpdate, db: Session = Depends(get_db), current_user = Depends(get_current_admin)):
    db_config = db.query(AIConfig).filter(AIConfig.id == config_id).first()
    if not db_config:
        raise HTTPException(status_code=404, detail="配置不存在")
    for key, value in config.model_dump(exclude_unset=True).items():
        setattr(db_config, key, value)
    db.commit()
    db.refresh(db_config)
    return db_config

@router.delete("/{config_id}")
def delete_config(config_id: int, db: Session = Depends(get_db), current_user = Depends(get_current_admin)):
    cfg = db.query(AIConfig).filter(AIConfig.id == config_id).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="配置不存在")
    db.delete(cfg)
    db.commit()
    return {"message": "已删除"}

@router.get("/{config_id}", response_model=AIConfigResponse)
def get_config(config_id: int, db: Session = Depends(get_db), current_user = Depends(get_current_admin)):
    cfg = db.query(AIConfig).filter(AIConfig.id == config_id).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="配置不存在")
    return cfg

# ========== 报告生成 ==========

@router.post("/generate-report")
async def generate_ai_report(type: str = "day", db: Session = Depends(get_db), current_user = Depends(get_current_admin)):
    from datetime import timedelta
    from sqlalchemy import func, text
    today = datetime.now().date()
    
    if type == "day":
        d = today - timedelta(days=1)
        date_range = d.strftime("%Y-%m-%d")
        start_str, end_str = date_range, date_range
    elif type == "week":
        monday = today - timedelta(days=today.weekday() + 7)
        sunday = monday + timedelta(days=6)
        date_range = monday.strftime("%Y年%m月%d日") + " - " + sunday.strftime("%m月%d日")
        start_str, end_str = monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")
    else:
        last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        end_last_month = today.replace(day=1) - timedelta(days=1)
        date_range = last_month.strftime("%Y年%m月")
        start_str, end_str = last_month.strftime("%Y-%m-%d"), end_last_month.strftime("%Y-%m-%d")
    
    api_config = db.query(AIConfig).filter(AIConfig.config_key == "deepseek_api", AIConfig.is_active == True).first()
    if not api_config or not api_config.api_key:
        raise HTTPException(status_code=400, detail="请先配置 DeepSeek API Key")
    
    type_to_key = {"day": "daily_summary", "week": "weekly_summary", "month": "monthly_summary"}
    config_key = type_to_key.get(type, type + "_summary")
    config = db.query(AIConfig).filter(AIConfig.config_key == config_key, AIConfig.is_active == True).first()
    if not config or not config.prompt_template:
        raise HTTPException(status_code=400, detail="请先配置提示词")
    
    end_date_next = (datetime.strptime(end_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    sys_setting = db.execute(text("SELECT value FROM system_settings WHERE `key` = 'cny_to_rub'")).fetchone()
    exchange_rate = float(sys_setting[0]) if sys_setting and sys_setting[0] else 12.5
    
    main_stats = db.query(
        func.coalesce(func.sum(AdRecord.sales), 0).label("sales"),
        func.coalesce(func.sum(AdRecord.impressions), 0).label("visitors"),
        func.coalesce(func.sum(AdRecord.order_count), 0).label("orders"),
        func.coalesce(func.sum(AdRecord.cart_count), 0).label("cart")
    ).filter(
        AdRecord.record_date >= start_str,
        AdRecord.record_date < end_date_next,
        AdRecord.ad_type == "product_analytics",
        AdRecord.shop_id == 1
    ).first()
    
    ad_cost_stats = db.query(
        func.coalesce(func.sum(AdRecord.cost), 0).label("ad_cost")
    ).filter(
        AdRecord.record_date >= start_str,
        AdRecord.record_date < end_date_next,
        AdRecord.ad_type == "advertising",
        AdRecord.shop_id == 1
    ).first()
    
    sales_rub = float(main_stats.order_sum or 0) * exchange_rate
    visitors = int(main_stats.visitors or 0)
    orders = int(main_stats.order_count or 0)
    cart = int(main_stats.cart or 0)
    ad_cost = float(ad_cost_stats.ad_cost or 0)
    
    prev_start = (datetime.strptime(start_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    prev_end = start_str
    
    prev_stats = db.query(
        func.coalesce(func.sum(AdRecord.sales), 0).label("sales"),
        func.coalesce(func.sum(AdRecord.impressions), 0).label("visitors"),
        func.coalesce(func.sum(AdRecord.order_count), 0).label("orders")
    ).filter(
        AdRecord.record_date >= prev_start,
        AdRecord.record_date < prev_end,
        AdRecord.ad_type == "product_analytics",
        AdRecord.shop_id == 1
    ).first()
    
    prev_ad_cost_stats = db.query(
        func.coalesce(func.sum(AdRecord.cost), 0).label("ad_cost")
    ).filter(
        AdRecord.record_date >= prev_start,
        AdRecord.record_date < prev_end,
        AdRecord.ad_type == "advertising",
        AdRecord.shop_id == 1
    ).first()
    
    prev_sales = float(prev_stats.order_sum or 0) * exchange_rate
    prev_visitors = int(prev_stats.visitors or 0)
    prev_orders = int(prev_stats.order_count or 0)
    
    def chg(v):
        return ("+" + str(v) + "%" if v > 0 else str(v) + "%")
    
    sales_change = round((sales_rub - prev_sales) / prev_sales * 100, 1) if prev_sales > 0 else 0
    visitors_change = round((visitors - prev_visitors) / prev_visitors * 100, 1) if prev_visitors > 0 else 0
    orders_change = round((orders - prev_orders) / prev_orders * 100, 1) if prev_orders > 0 else 0
    
    conversion_rate = round(orders / visitors * 100, 2) if visitors > 0 else 0
    add_to_cart_rate = round(cart / visitors * 100, 2) if visitors > 0 else 0
    ad_ratio = round(ad_cost / sales_rub * 100, 2) if sales_rub > 0 else 0
    
    items_query = db.query(
        Product.id,
        Product.nm_id,
        Product.name,
        func.coalesce(func.sum(AdRecord.sales), 0).label("sales"),
        func.coalesce(func.sum(AdRecord.impressions), 0).label("visitors"),
        func.coalesce(func.sum(AdRecord.order_count), 0).label("orders"),
        func.coalesce(func.sum(AdRecord.cart_count), 0).label("cart")
    ).join(AdRecord, AdRecord.product_id == Product.id).filter(
        AdRecord.record_date >= start_str,
        AdRecord.record_date < end_date_next,
        AdRecord.ad_type == "product_analytics",
        AdRecord.shop_id == 1
    ).group_by(Product.id).order_by(func.sum(AdRecord.sales).desc()).limit(20).all()
    
    items = []
    for row in items_query:
        v = row.visitors or 1
        items.append({
            "nm_id": row.nm_id,
            "sales": float(row.order_sum or 0) * exchange_rate,
            "conversion_rate": round((row.order_count or 0) / v * 100, 2),
            "add_to_cart_rate": round((row.cart or 0) / v * 100, 2)
        })
    
    data_text = "【核心数据】\n日期范围：" + date_range + "\n总销售额：" + str(round(sales_rub, 0)) + "元 (" + chg(sales_change) + ")\n总访客数：" + str(visitors) + " (" + chg(visitors_change) + ")\n总订单数：" + str(orders) + " (" + chg(orders_change) + ")\n转化率：" + str(conversion_rate) + "%\n加购率：" + str(add_to_cart_rate) + "%\n广告费：" + str(round(ad_cost, 2)) + "元\n广告占比：" + str(ad_ratio) + "%\n\n【单品数据 TOP 10】\n"
    for i, item in enumerate(items[:10]):
        data_text += str(i+1) + ". nm_id=" + str(item['nm_id']) + ": 销售额" + str(round(item['sales'], 0)) + "元, 转化率" + str(item['conversion_rate']) + "%, 加购率" + str(item['add_to_cart_rate']) + "%\n"
    
    prompt = config.prompt_template
    prompt = prompt.replace("{{date_range}}", date_range)
    prompt = prompt.replace("{{total_sales}}", str(round(sales_rub, 0)))
    prompt = prompt.replace("{{total_visitors}}", str(visitors))
    prompt = prompt.replace("{{total_orders}}", str(orders))
    prompt = prompt.replace("{{total_ad_cost}}", str(round(ad_cost, 2)))
    prompt = prompt.replace("{{avg_conversion_rate}}", str(conversion_rate))
    prompt = prompt.replace("{{avg_cart_rate}}", str(add_to_cart_rate))
    prompt = prompt.replace("{{avg_ad_ratio}}", str(ad_ratio))
    prompt = prompt.replace("{{sales_change}}", chg(sales_change))
    prompt = prompt.replace("{{visitors_change}}", chg(visitors_change))
    prompt = prompt.replace("{{orders_change}}", chg(orders_change))
    top_products = "\n".join(["nm_id=" + str(items[i]['nm_id']) + ": 销售额" + str(round(items[i]['sales'], 0)) + "元" for i in range(min(5, len(items)))])
    bottom_products = "\n".join(["nm_id=" + str(items[i]['nm_id']) + ": 销售额" + str(round(items[i]['sales'], 0)) + "元" for i in range(max(0, len(items)-3), len(items))])
    prompt = prompt.replace("{{top_products}}", top_products or "无")
    prompt = prompt.replace("{{bottom_products}}", bottom_products or "无")
    prompt = prompt.replace("{{danger_products}}", "无")
    prompt = prompt.replace("{{warning_products}}", "无")
    
    try:
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": "Bearer " + api_config.api_key, "Content-Type": "application/json"},
                json={"model": api_config.api_model or "deepseek-chat", "messages": [{"role": "user", "content": prompt}]}
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=500, detail="AI API 调用失败: " + resp.text)
            ai_response = resp.json()["choices"][0]["message"]["content"]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="AI 生成失败: " + str(e))
    
    report = AIReport(type=type, date_range=date_range, content=ai_response, created_at=datetime.now())
    db.add(report)
    db.commit()
    db.refresh(report)
    
    return {"id": report.id, "message": "报告生成成功", "date_range": date_range}
