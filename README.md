# WB ERP - Wildberries 跨境电商 ERP 系统

## 项目简介

针对俄罗斯电商平台 Wildberries 的日常销售管理工具，支持：

- 📊 销售数据看板
- 📈 广告分析
- 💰 利润分析
- ⚙️ 后台管理

## 技术栈

- **后端**: Python + FastAPI
- **前端**: Vue 3 + Element Plus
- **数据库**: SQLite / PostgreSQL
- **部署**: Docker + Nginx

## 快速开始

### 1. 克隆项目

```bash
cd /root/.openclaw/workspace/wb-erp
```

### 2. 配置环境变量

创建 `.env` 文件：

```env
SECRET_KEY=your-secret-key-change-this-in-production
DATABASE_URL=sqlite:///./wberp.db
```

### 3. 使用 Docker Compose 启动

```bash
docker-compose up -d --build
```

### 4. 访问系统

- 前端: http://your-ip
- 后端 API: http://your-ip/api
- API 文档: http://your-ip/api/docs

### 5. 创建管理员账号

```bash
# 进入后端容器
docker exec -it wb-erp-backend bash

# 创建管理员
python -c "
from app.database import SessionLocal
from app.models.models import User
from app.utils.security import get_password_hash
from app.models.models import UserRole

db = SessionLocal()
user = User(
    username='admin',
    email='admin@example.com',
    hashed_password=get_password_hash('admin123'),
    role=UserRole.ADMIN,
    is_active=True
)
db.add(user)
db.commit()
print('管理员创建成功: admin / admin123')
"
```

## 目录结构

```
wb-erp/
├── backend/                 # 后端
│   ├── app/
│   │   ├── main.py         # 主入口
│   │   ├── config.py       # 配置
│   │   ├── database.py     # 数据库
│   │   ├── models/         # 数据模型
│   │   ├── routers/        # API 路由
│   │   ├── services/       # 业务服务
│   │   └── utils/          # 工具函数
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/               # 前端
│   ├── src/
│   │   ├── views/         # 页面
│   │   ├── router/        # 路由
│   │   └── stores/        # 状态管理
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml      # 容器编排
├── nginx.conf             # Nginx 配置
└── README.md
```

## 功能说明

### 1. 销售数据看板

- 实时显示销售额、订单量、转化率等
- 支持多维度筛选（时间、店铺、负责人、产品）
- 销售趋势图表
- 广告占比预警

### 2. 产品管理

- 从 WB 同步产品（只新增不覆盖）
- 自定义编辑产品名称、负责人、尺寸等
- 产品权限管理

### 3. 库存管理（暂无）

- 手动入库记录
- FIFO（先进先出）成本核算
- 多仓库支持（FBW/FBS/自有）

### 4. 利润分析（即将开发）

- 自动计算每单利润
- 成本构成分析
- 利润趋势图表

### 5. 广告分析

- CPM/CPC/ACOS/ROAS 等指标
- 优化建议

### 6. 后台管理

- 用户管理
- 店铺管理（API Token 配置）
- 系统设置（汇率、预警阈值）

## 部署说明

### 开发环境

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 前端
cd frontend
npm install
npm run dev
```

### 生产环境

```bash
# 构建并启动
docker-compose up -d --build

# 查看日志
docker-compose logs -f

# 停止
docker-compose down
```

### 更新代码

```bash
git pull
docker-compose down
docker-compose up -d --build
```

## 常见问题

### 1. 忘记密码怎么办？

```bash
# 进入后端容器重置密码
docker exec -it wb-erp-backend bash
python -c "
from app.database import SessionLocal
from app.models.models import User
from app.utils.security import get_password_hash

db = SessionLocal()
user = db.query(User).filter(User.username == 'admin').first()
user.hashed_password = get_password_hash('new_password')
db.commit()
print('密码已重置')
"
```

### 2. 如何备份数据？

```bash
# 备份 SQLite 数据库
cp wberp.db wberp.db.backup

# 如果使用 PostgreSQL
pg_dump -U user -d wberp > backup.sql
```

### 3. 如何查看 API 文档？

访问 http://your-ip/api/docs 或 http://your-ip/api/redoc

## License

MIT
