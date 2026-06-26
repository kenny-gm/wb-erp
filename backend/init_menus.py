#!/usr/bin/env python3
"""初始化默认菜单数据"""
from app.database import SessionLocal
from app.models.models import MenuItem

db = SessionLocal()

# 默认菜单配置
default_menus = [
    {"key": "dashboard", "name": "仪表盘", "icon": "Odometer", "path": "/dashboard", "sort_order": 1},
    {"key": "products", "name": "产品管理", "icon": "Goods", "path": "/products", "sort_order": 2},
    {"key": "orders", "name": "订单管理", "icon": "Document", "path": "/orders", "sort_order": 3},
    {"key": "inventory", "name": "库存管理", "icon": "Box", "path": "/inventory", "sort_order": 4},
    {"key": "ads", "name": "广告分析", "icon": "TrendCharts", "path": "/ads", "sort_order": 5},
    {"key": "customer-service", "name": "客服工作台", "icon": "ChatDotRound", "path": "/customer-service", "sort_order": 6},
    {"key": "finance", "name": "财务分析", "icon": "Money", "path": "/finance", "sort_order": 7},
    {"key": "admin", "name": "系统管理", "icon": "Setting", "path": "/admin", "sort_order": 100, "required_role": "admin"},
    {"key": "admin-users", "name": "用户管理", "icon": "User", "path": "/admin/users", "parent_key": "admin", "sort_order": 101, "required_role": "admin"},
    {"key": "admin-shops", "name": "店铺管理", "icon": "Shop", "path": "/admin/shops", "parent_key": "admin", "sort_order": 102, "required_role": "admin"},
    {"key": "admin-products", "name": "产品权限", "icon": "Goods", "path": "/admin/products", "parent_key": "admin", "sort_order": 103, "required_role": "admin"},
    {"key": "admin-menus", "name": "菜单管理", "icon": "Menu", "path": "/admin/menus", "parent_key": "admin", "sort_order": 104, "required_role": "admin"},
    {"key": "admin-ui", "name": "界面设置", "icon": "Brush", "path": "/admin/ui", "parent_key": "admin", "sort_order": 105, "required_role": "admin"},
    {"key": "admin-settings", "name": "系统设置", "icon": "Setting", "path": "/admin/settings", "parent_key": "admin", "sort_order": 106, "required_role": "admin"},
    {"key": "admin-thresholds", "name": "预警设置", "icon": "Bell", "path": "/admin/thresholds", "parent_key": "admin", "sort_order": 107, "required_role": "admin"},
]

print("=== 初始化菜单数据 ===")

# 检查是否已有菜单
existing = db.query(MenuItem).count()
print(f"现有菜单数量: {existing}")

if existing == 0:
    # 创建默认菜单
    for menu_data in default_menus:
        menu = MenuItem(**menu_data)
        db.add(menu)
        print(f"创建菜单: {menu_data['name']}")
    
    db.commit()
    print("\n✅ 菜单初始化完成")
else:
    print("菜单已存在，跳过初始化")

# 显示所有菜单
print("\n当前菜单列表:")
menus = db.query(MenuItem).order_by(MenuItem.sort_order).all()
for m in menus:
    parent = f" (父: {m.parent_key})" if m.parent_key else ""
    role = f" [权限: {m.required_role}]" if m.required_role else ""
    print(f"  {m.sort_order:3d}. {m.icon} {m.name} - {m.path}{parent}{role}")

db.close()
