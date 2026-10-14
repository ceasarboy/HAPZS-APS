# APS-HAP 移植安装指南

## 一、系统要求

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| 操作系统 | Windows 10/11 64位 | 推荐 Windows 11 |
| Python | 3.13.x | 使用项目自带的嵌入式版本 |
| Node.js | 24.x | 使用项目自带的便携版 |
| PostgreSQL | 15+ | 需单独安装 |
| Redis | 7.x | 需单独安装 |

## 二、项目目录结构

```
aps-hap/
├── backend/                    # 后端（FastAPI + Python）
│   ├── app/                    # 应用代码
│   ├── alembic/                # 数据库迁移
│   ├── requirements.txt        # Python依赖清单
│   ├── .env                    # 环境变量配置
│   └── alembic.ini             # 数据库迁移配置
├── frontend/                   # 前端（React + TypeScript）
│   ├── src/                    # 源代码
│   ├── node_modules/           # 前端依赖（已打包）
│   ├── package.json            # Node.js依赖清单
│   ├── .env                    # 前端环境变量
│   └── vite.config.ts          # Vite配置
├── offline/                    # 离线安装包
│   ├── python_packages/        # Python离线依赖包（55个.whl文件，58.7MB）
│   └── runtime/                # 运行时环境
│       ├── python-3.13.5-embed-amd64.zip  # Python嵌入式版本（10.4MB）
│       ├── get-pip.py          # pip安装脚本
│       ├── nodejs/             # Node.js便携版（97.7MB，含npm）
│       ├── Redis-x64-5.0.14.1.zip         # Redis Windows版（12MB）
│       └── download_links.txt             # PostgreSQL下载链接（约300MB，需单独下载）
├── deploy/                     # 部署配置
│   ├── docker-compose.yml      # Docker部署方案
│   └── nginx.conf              # Nginx配置
└── INSTALL.md                  # 本文档
```

## 三、安装步骤

### 步骤1：安装 PostgreSQL

> **注意**：PostgreSQL安装包约300MB，因体积较大未打包到项目中。
> 请从以下链接下载，或查看 `offline/runtime/download_links.txt`：
> - 直接下载：https://get.enterprisedb.com/postgresql/postgresql-16.14-2-windows-x64.exe
> - 官方页面：https://www.postgresql.org/download/windows/

1. 运行PostgreSQL安装包
2. 安装时设置超级用户密码为 `123456`（或安装后修改 .env 配置）
3. 端口保持默认 5432
4. Locale 选择 `C` 或 `Chinese, China`
5. 安装完成后，打开 pgAdmin 或命令行，创建数据库：
   ```sql
   CREATE DATABASE aps_hap WITH ENCODING 'UTF8';
   ```

### 步骤2：安装 Redis

#### 方式A：使用项目自带的安装包（推荐移植场景）

1. 解压 `offline/runtime/Redis-x64-5.0.14.1.zip` 到任意目录（如 `C:\Redis`）
2. 启动 Redis 服务：
   ```cmd
   cd C:\Redis
   redis-server.exe
   ```
3. 默认端口 6379，无密码
4. 可选：将 Redis 注册为 Windows 服务：
   ```cmd
   redis-server.exe --service-install redis.windows.conf
   redis-server.exe --service-start
   ```

#### 方式B：自行下载

1. 下载 Redis Windows 版：https://github.com/tporadowski/redis/releases
2. 后续步骤同方式A

### 步骤3：配置 Python 环境

#### 方式A：使用项目自带的嵌入式 Python（推荐移植场景）

1. 解压 `offline/runtime/python-3.13.5-embed-amd64.zip` 到 `offline/runtime/python/`
2. 编辑 `offline/runtime/python/python313._pth`，取消注释 `import site`：
   ```
   python313.zip
   .

   # Uncomment to run site.main() automatically
   import site
   ```
3. 安装 pip：
   ```cmd
   cd offline\runtime\python
   python.exe ..\get-pip.py
   ```
4. 离线安装依赖包：
   ```cmd
   cd offline\runtime\python
   python.exe -m pip install --no-index --find-links=..\..\python_packages -r ..\..\..\backend\requirements.txt
   ```

#### 方式B：使用系统安装的 Python（推荐开发场景）

1. 下载安装 Python 3.13：https://www.python.org/downloads/
2. 创建虚拟环境：
   ```cmd
   cd backend
   python -m venv venv
   venv\Scripts\activate
   ```
3. 离线安装依赖：
   ```cmd
   pip install --no-index --find-links=..\offline\python_packages -r requirements.txt
   ```

### 步骤4：配置后端

1. 复制 `.env.example` 为 `.env`：
   ```cmd
   cd backend
   copy .env.example .env
   ```

2. 编辑 `.env`，确认配置：
   ```env
   # 数据库配置（密码需与PostgreSQL安装时一致）
   DATABASE_URL=postgresql+asyncpg://postgres:123456@localhost:5432/aps_hap

   # Redis配置
   REDIS_URL=redis://localhost:6379/0

   # Celery配置
   CELERY_BROKER_URL=redis://localhost:6379/1
   CELERY_RESULT_BACKEND=redis://localhost:6379/2

   # HAP明道云配置
   HAP_APP_ID=4d2d7733-c047-4bf9-896a-505b33f0be66
   HAP_APPKEY=5f36052d10a2d00d
   HAP_SIGN=MmU2NjE4NzJkZGM5NjhmZjA1MWI0MjY4OGU0MTA4Yzc2ZjZiNTc3YzZlMWRkODJmM2E5MGM3YjIwZWVjMzk5Yw==
   HAP_BASE_URL=https://api.mingdao.com

   # API密钥
   API_KEY=aps-hap-local-2026

   # 求解引擎
   SOLVER_ENGINE=ortools
   OPENAPS_HOME=./openaps
   ```

3. 执行数据库迁移：
   ```cmd
   cd backend
   set PYTHONPATH=.
   python -m alembic upgrade head
   ```

4. 启动后端服务：
   ```cmd
   cd backend
   set PYTHONPATH=.
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
   ```

5. 验证后端：浏览器打开 http://localhost:8001/health，应返回 `{"status": "healthy"}`

### 步骤5：配置前端

#### 方式A：使用项目自带的 Node.js 便携版（推荐移植场景）

1. 将 `offline/runtime/nodejs` 添加到 PATH：
   ```cmd
   set PATH=e:\openaps\aps-hap\offline\runtime\nodejs;%PATH%
   ```
   或在启动脚本中设置

2. 前端依赖已打包在 `frontend/node_modules/` 中，无需 `npm install`

3. 复制 `.env.example` 为 `.env`：
   ```cmd
   cd frontend
   copy .env.example .env
   ```

4. 编辑 `.env`，确认配置：
   ```env
   VITE_API_BASE_URL=http://localhost:8001/api/v1
   ```

5. 启动前端开发服务器：
   ```cmd
   cd frontend
   npx vite --host 0.0.0.0 --port 3000
   ```

#### 方式B：使用系统安装的 Node.js

1. 下载安装 Node.js 24：https://nodejs.org/
2. 如果 `node_modules` 不存在，执行：
   ```cmd
   cd frontend
   npm install
   ```
3. 启动前端：
   ```cmd
   cd frontend
   npx vite --host 0.0.0.0 --port 3000
   ```

### 步骤6：验证系统

1. 打开浏览器访问 http://localhost:3000
2. 检查功能页面是否正常加载
3. 在"数据管理"页面点击"从HAP拉取"同步数据
4. 在"排产"页面执行排产任务

## 四、一键启动脚本

创建 `start.bat` 文件：

```bat
@echo off
chcp 65001 >nul
echo ================================
echo  APS-HAP 系统启动
echo ================================

echo [1/3] 启动 Redis...
start "Redis" redis-server.exe --port 6379
timeout /t 2 >nul

echo [2/3] 启动后端...
start "APS-Backend" cmd /k "cd /d e:\openaps\aps-hap\backend && set PYTHONPATH=. && python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload"
timeout /t 3 >nul

echo [3/3] 启动前端...
start "APS-Frontend" cmd /k "cd /d e:\openaps\aps-hap\frontend && npx vite --host 0.0.0.0 --port 3000"

echo.
echo ================================
echo  系统已启动！
echo  前端: http://localhost:3000
echo  后端: http://localhost:8001
echo  API文档: http://localhost:8001/docs
echo ================================
pause
```

## 五、常见问题

### Q1: 后端启动报错 "Cannot connect to database"
- 检查 PostgreSQL 服务是否已启动
- 检查 `.env` 中 `DATABASE_URL` 的密码是否正确
- 确认 `aps_hap` 数据库已创建

### Q2: 后端启动报错 "Cannot connect to Redis"
- 检查 Redis 服务是否已启动
- 确认 Redis 端口 6379 未被占用

### Q3: 前端页面空白或报错 "Network Error"
- 确认后端服务已启动（http://localhost:8001/health）
- 检查 `.env` 中 `VITE_API_BASE_URL` 是否正确
- 确认防火墙未阻止 8001 端口

### Q4: 排产任务无结果
- 确认已执行"从HAP拉取"同步基础数据
- 检查 PostgreSQL 中是否有产品、产线、需求计划等数据
- 查看后端控制台的错误日志

### Q5: pip离线安装失败 "No matching distribution"
- 确保使用 `--only-binary=:all:` 时所有包都有对应平台的 wheel
- 尝试去掉 `--only-binary=:all:` 允许从源码编译（需要 C 编译器）
- 或使用系统安装的 Python 直接 `pip install -r requirements.txt`

### Q6: 嵌入式Python无法安装包
- 确保已编辑 `python313._pth` 文件取消 `import site` 注释
- 确保已通过 `get-pip.py` 安装了 pip

## 六、技术栈说明

| 层级 | 技术 | 版本 | 用途 |
|------|------|------|------|
| 后端框架 | FastAPI | 0.136 | RESTful API |
| ASGI服务器 | Uvicorn | 0.46 | 异步HTTP服务 |
| ORM | SQLAlchemy | 2.0 | 数据库操作 |
| 数据库迁移 | Alembic | 1.18 | 版本管理 |
| 数据库 | PostgreSQL | 15+ | 主数据存储 |
| 缓存/消息 | Redis | 7 | 缓存+Celery Broker |
| 任务队列 | Celery | 5.5 | 异步任务 |
| 求解引擎 | OR-Tools | 9.15 | CP-SAT 排产求解 |
| 前端框架 | React | 18 | SPA应用 |
| UI组件库 | Ant Design | 5 | 界面组件 |
| 图表库 | ECharts | 5 | 数据可视化 |
| 构建工具 | Vite | 5 | 前端构建 |
| 状态管理 | Zustand | 4 | 全局状态 |
| HTTP客户端 | Axios | 1.7 | API请求 |
| 外部平台 | 明道云 HAP | V3 | 数据源+回写 |

## 七、数据初始化

### 从明道云同步数据

1. 确保 `.env` 中的 HAP 配置正确（APP_ID、APPKEY、SIGN）
2. 启动后端服务
3. 在前端"数据管理"页面，逐表点击"从HAP拉取"
4. 或调用API全量同步：
   ```
   POST http://localhost:8001/api/v1/sync/pull-all
   Header: X-API-Key: aps-hap-local-2026
   ```

### 手动导入测试数据

```cmd
cd backend
set PYTHONPATH=.
python ..\scripts\insert_test_data.py
```

## 八、端口说明

| 服务 | 端口 | 说明 |
|------|------|------|
| 前端开发服务器 | 3000 | Vite dev server |
| 后端API | 8001 | FastAPI + Uvicorn |
| PostgreSQL | 5432 | 数据库 |
| Redis | 6379 | 缓存+消息队列 |

确保以上端口未被其他程序占用。
