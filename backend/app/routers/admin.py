"""
后台管理路由
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Response, File, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel

from app.database import get_db
from app.models.models import User, Product, UserRole, Shop, SystemSetting, ProductPermission, UISetting, MenuItem
from app.routers.auth import get_current_admin, get_password_hash

router = APIRouter(prefix="/api/admin", tags=["后台管理"])


# ========== 用户管理 ==========

class UserCreateAdmin(BaseModel):
    username: str
    password: str
    confirm_password: str
    role: str = "staff"
    allowed_menus: Optional[List[str]] = None
    allowed_owners: Optional[List[str]] = None


class UserUpdateAdmin(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    allowed_menus: Optional[List[str]] = None
    allowed_owners: Optional[List[str]] = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str]
    role: str
    is_active: bool
    allowed_menus: Optional[List[str]]
    allowed_owners: Optional[List[str]]
    created_at: datetime
    
    class Config:
        from_attributes = True


@router.get("/users/", response_model=List[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """获取用户列表"""
    users = db.query(User).all()
    return users


@router.get("/owners/")
def list_owners(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """获取所有负责人列表"""
    owners = db.query(Product.owner).filter(Product.owner != None, Product.owner != "").distinct().all()
    return sorted([o[0] for o in owners])


@router.post("/users/", response_model=UserResponse)
def create_user(
    data: UserCreateAdmin,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """创建用户（邮箱改为可选，增加确认密码）"""
    # 检查密码是否一致
    if data.password != data.confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的密码不一致")
    
    # 检查用户名
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    # 验证角色
    try:
        role = UserRole(data.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的角色: {data.role}")
    
    user = User(
        username=data.username,
        email=None,
        hashed_password=get_password_hash(data.password),
        role=role,
        is_active=True,
        allowed_menus=data.allowed_menus or [],
        allowed_owners=data.allowed_owners or []
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return user


@router.put("/users/{user_id}/", response_model=UserResponse)
def update_user(
    user_id: int,
    data: UserUpdateAdmin,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """更新用户"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    update_data = data.dict(exclude_unset=True)
    if "role" in update_data:
        update_data["role"] = UserRole(update_data["role"])
    
    for key, value in update_data.items():
        if value is not None:
            setattr(user, key, value)
    
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/reset-password/")
def reset_user_password(
    user_id: int,
    new_password: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """重置用户密码"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    user.hashed_password = get_password_hash(new_password)
    db.commit()
    
    return {"message": "密码已重置"}


@router.delete("/users/{user_id}/")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """删除用户"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    db.delete(user)
    db.commit()
    
    return {"message": "用户已删除"}


# ========== 产品权限管理 ==========

@router.post("/users/{user_id}/products/{product_id}/")
def grant_product_permission(
    user_id: int,
    product_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """授予产品权限"""
    existing = db.query(ProductPermission).filter(
        ProductPermission.user_id == user_id,
        ProductPermission.product_id == product_id
    ).first()
    
    if existing:
        return {"message": "权限已存在"}
    
    permission = ProductPermission(
        user_id=user_id,
        product_id=product_id
    )
    
    db.add(permission)
    db.commit()
    
    return {"message": "权限已授予"}


@router.delete("/users/{user_id}/products/{product_id}/")
def revoke_product_permission(
    user_id: int,
    product_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """撤销产品权限"""
    permission = db.query(ProductPermission).filter(
        ProductPermission.user_id == user_id,
        ProductPermission.product_id == product_id
    ).first()
    
    if permission:
        db.delete(permission)
        db.commit()
    
    return {"message": "权限已撤销"}


# ========== 店铺汇率设置 ==========

class ShopExchangeRate(BaseModel):
    currency: str
    exchange_rate: float


@router.get("/shops/{shop_id}/exchange-rate/")
def get_exchange_rate(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """获取店铺汇率"""
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="店铺不存在")
    return {
        "currency": shop.currency,
        "exchange_rate": shop.exchange_rate
    }


@router.put("/shops/{shop_id}/exchange-rate/")
def update_exchange_rate(
    shop_id: int,
    data: ShopExchangeRate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """更新店铺汇率"""
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="店铺不存在")
    
    shop.currency = data.currency
    shop.exchange_rate = data.exchange_rate
    db.commit()
    
    return {"message": "汇率已更新", "currency": shop.currency, "exchange_rate": shop.exchange_rate}


# ========== 界面设置 ==========

class UISettingSchema(BaseModel):
    system_name: Optional[str] = "WB ERP"
    browser_logo: Optional[str] = ""
    login_logo: Optional[str] = "🌿"
    login_title: Optional[str] = "WB ERP"
    login_subtitle: Optional[str] = "Wildberries 跨境电商管理系统"
    sidebar_logo: Optional[str] = "🍀 WB ERP"
    primary_color: Optional[str] = "#8b5cf6"
    footer_text: Optional[str] = ""
    
    class Config:
        from_attributes = True


@router.get("/ui-settings/")
def get_ui_settings(
    db: Session = Depends(get_db)
):
    """获取界面设置（公开接口，用于登录页）"""
    setting = db.query(UISetting).first()
    if not setting:
        setting = UISetting()
        db.add(setting)
        db.commit()
        db.refresh(setting)
    
    return {
        "id": setting.id,
        "system_name": setting.system_name or "WB ERP",
        "browser_logo_url": "/api/admin/browser-logo/",
        "login_logo_url": "/api/admin/login-logo/",
        "sidebar_logo_url": "/api/admin/sidebar-logo/" if setting.sidebar_logo and setting.sidebar_logo.startswith('/') else None,
        # 兼容旧前端，值用 URL 而非 base64
        "browser_logo": "/api/admin/browser-logo/",
        "login_logo": setting.login_logo or "",
        "login_title": setting.login_title or "WB ERP",
        "login_subtitle": setting.login_subtitle or "",
        "sidebar_logo": setting.sidebar_logo or "🍀 WB ERP",
        "primary_color": setting.primary_color or "#8b5cf6",
        "footer_text": setting.footer_text or "",
        "updated_at": setting.updated_at
    }


@router.get("/browser-logo/")
def get_browser_logo(db: Session = Depends(get_db)):
    """获取浏览器图标（返回实际图片，登录页 logo 用）"""
    result = db.execute(text("SELECT browser_logo FROM ui_settings LIMIT 1")).fetchone()
    logo_val = result[0] if result else None
    if not logo_val or logo_val == "":
        return Response(content="", media_type="image/png")
    # 如果是 URL 路径，走静态文件
    if logo_val.startswith('/') or logo_val.startswith('http'):
        import os
        if logo_val.startswith('http'):
            return Response(content="", media_type="image/png")
        file_path = logo_val.lstrip('/')
        full_path = "/opt/wb-erp/" + file_path
        if os.path.exists(full_path):
            with open(full_path, 'rb') as f:
                data = f.read()
            ext = file_path.split('.')[-1] if '.' in file_path else 'png'
            return Response(content=data, media_type=f"image/{ext}")
        return Response(content="", media_type="image/png")
    import re, base64
    match = re.search(r'data:image/(\w+);base64,(.+)', logo_val)
    if not match:
        return Response(content="", media_type="image/png")
    img_type = match.group(1)
    img_data = base64.b64decode(match.group(2))
    return Response(content=img_data, media_type=f"image/{img_type}")


@router.get("/login-logo/")
def get_login_logo(db: Session = Depends(get_db)):
    """获取登录页 logo 图片"""
    result = db.execute(text("SELECT login_logo FROM ui_settings LIMIT 1")).fetchone()
    logo_val = result[0] if result else None
    if not logo_val or logo_val == "":
        return Response(content="", media_type="image/png")
    if logo_val.startswith('/') or logo_val.startswith('http'):
        import os
        if logo_val.startswith('http'):
            return Response(content="", media_type="image/png")
        file_path = logo_val.lstrip('/')
        full_path = "/opt/wb-erp/" + file_path
        if os.path.exists(full_path):
            with open(full_path, 'rb') as f:
                data = f.read()
            ext = file_path.split('.')[-1] if '.' in file_path else 'png'
            return Response(content=data, media_type=f"image/{ext}")
        return Response(content="", media_type="image/png")
    import re, base64
    match = re.search(r'data:image/(\w+);base64,(.+)', logo_val)
    if not match:
        return Response(content="", media_type="image/png")
    img_type = match.group(1)
    img_data = base64.b64decode(match.group(2))
    return Response(content=img_data, media_type=f"image/{img_type}")


@router.post("/upload-logo/")
async def upload_logo(
    file: UploadFile = File(...),
    logo_type: str = "browser",
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """上传 logo 图片，返回 URL 路径"""
    import os, uuid
    if file.content_type and not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="只能上传图片")
    
    static_dir = "/opt/wb-erp/static/logos"
    os.makedirs(static_dir, exist_ok=True)
    
    ext = file.filename.split('.')[-1] if '.' in file.filename else 'png'
    filename = f"{logo_type}-logo.{ext}"
    filepath = os.path.join(static_dir, filename)
    
    with open(filepath, 'wb') as f:
        content = await file.read()
        f.write(content)
    
    logo_url = f"/static/logos/{filename}"
    
    # 更新数据库
    field = "browser_logo" if logo_type == "browser" else "login_logo"
    db.execute(text(f"UPDATE ui_settings SET {field} = :val WHERE id = 1"), {"val": logo_url})
    db.commit()
    
    return {"url": logo_url}


@router.put("/ui-settings/")
def update_ui_settings(
    data: UISettingSchema,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """更新界面设置"""
    # 使用原始SQL更新
    update_data = data.dict(exclude_unset=True)
    if update_data:
        set_clause = ", ".join([f"{k} = :{k}" for k in update_data.keys()])
        update_data["id"] = 1
        conn = db.connection()
        conn.execute(text(f"UPDATE ui_settings SET {set_clause} WHERE id = :id"), update_data)
        db.commit()
    
    # 返回更新后的数据
    result = db.execute(text("SELECT * FROM ui_settings WHERE id = 1")).fetchone()
    if result:
        return {
            "id": result[0],
            "login_logo": result[1] or "",
            "login_title": result[2] or "WB ERP",
            "login_subtitle": result[3] or "",
            "sidebar_logo": result[4] or "🍀 WB ERP",
            "primary_color": result[5] or "#8b5cf6",
            "footer_text": result[6] or "",
            "updated_at": result[7],
            "system_name": result[8] or "WB ERP",
            "browser_logo": result[9] or ""
        }
    return {"error": "设置不存在"}


# ========== 菜单管理 ==========

class MenuItemSchema(BaseModel):
    key: str
    name: str
    icon: Optional[str] = None
    path: str
    parent_key: Optional[str] = None
    sort_order: int = 0
    is_visible: bool = True
    required_role: Optional[str] = None
    
    class Config:
        from_attributes = True


@router.get("/menus/", response_model=List[MenuItemSchema])
def list_menus(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """获取菜单列表"""
    menus = db.query(MenuItem).order_by(MenuItem.sort_order.asc()).all()
    return menus


@router.post("/menus/", response_model=MenuItemSchema)
def create_menu(
    data: MenuItemSchema,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """创建菜单项"""
    if db.query(MenuItem).filter(MenuItem.key == data.key).first():
        raise HTTPException(status_code=400, detail="菜单key已存在")
    
    menu = MenuItem(**data.dict())
    db.add(menu)
    db.commit()
    db.refresh(menu)
    return menu


@router.put("/menus/{menu_id}/", response_model=MenuItemSchema)
def update_menu(
    menu_id: int,
    data: MenuItemSchema,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """更新菜单项"""
    menu = db.query(MenuItem).filter(MenuItem.id == menu_id).first()
    if not menu:
        raise HTTPException(status_code=404, detail="菜单项不存在")
    
    for key, value in data.dict(exclude_unset=True).items():
        setattr(menu, key, value)
    
    db.commit()
    db.refresh(menu)
    return menu


@router.delete("/menus/{menu_id}/")
def delete_menu(
    menu_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """删除菜单项"""
    menu = db.query(MenuItem).filter(MenuItem.id == menu_id).first()
    if not menu:
        raise HTTPException(status_code=404, detail="菜单项不存在")
    
    db.delete(menu)
    db.commit()
    return {"message": "菜单项已删除"}


@router.post("/menus/reorder/")
def reorder_menus(
    menu_ids: List[int],
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """重新排序菜单"""
    for index, menu_id in enumerate(menu_ids):
        menu = db.query(MenuItem).filter(MenuItem.id == menu_id).first()
        if menu:
            menu.sort_order = index
    
    db.commit()
    return {"message": "排序已更新"}


# ========== 系统设置 ==========

class SettingUpdate(BaseModel):
    value: str


@router.get("/settings/")
def list_settings(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """获取系统设置"""
    settings = db.query(SystemSetting).all()
    return {s.key: s.value for s in settings}


@router.put("/settings/{key}/")
def update_setting(
    key: str,
    data: SettingUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """更新系统设置"""
    setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    
    if setting:
        setting.value = data.value
    else:
        setting = SystemSetting(key=key, value=data.value)
        db.add(setting)
    
    db.commit()
    
    return {"message": "设置已更新"}


# ========== 统计信息 ==========

@router.get("/stats/")
def get_admin_stats(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """获取管理统计"""
    return {
        "users_count": db.query(User).count(),
        "shops_count": db.query(Shop).filter(Shop.is_active == True).count(),
        "products_count": db.query(ProductPermission).count()
    }

