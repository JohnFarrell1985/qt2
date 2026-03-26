# Fin-R1 Live Data Middleware

为 Fin-R1 金融大模型提供**实时A股数据 + 历史数据**的完整中间层解决方案。

## 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户层 (Web UI)                          │
│              ChatGPT-Next-Web (http://IP:8011)                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    API中间层 (api-middleware)                    │
│                    Port: 8012 / 依赖: vLLM + DB                  │
│  ┌─────────────────────┐  ┌─────────────────────┐              │
│  │   实时数据获取      │  │   历史数据查询        │              │
│  │   - akshare API    │  │   - PostgreSQL只读    │              │
│  │   - 秒级行情       │  │   - 2024年至今全量    │              │
│  │   - 市场概览       │  │   - 统计指标计算      │              │
│  └─────────────────────┘  └─────────────────────┘              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
           ┌───────────────┴───────────────┐
           ▼                               ▼
┌──────────────────────┐      ┌──────────────────────────┐
│   Fin-R1 vLLM        │      │    PostgreSQL             │
│   GPU推理服务         │      │    123.60.11.74:5432     │
│   Port: 8010          │      │    Database: finr1_data  │
│   Model: Fin-R1      │      │    - stock_daily         │
└──────────────────────┘      │    - stocks              │
                              └──────────────────────────┘
                                        ▲
                                        │
                           ┌────────────┴────────────┐
                           ▼                         │
              ┌──────────────────────┐               │
              │   数据枢纽 (data-hub) │               │
              │   - 自动检查数据完整性│───────────────┘
              │   - 自动下载缺失数据  │
              │   - 增量更新          │
              └──────────────────────┘
```

**完整服务栈** (docker-compose 一键启动):
| 服务 | 端口 | 功能 | 依赖 |
|------|------|------|------|
| fin-r1-vllm | 8010 | GPU模型推理 | - |
| data-hub | - | 自动同步历史数据 | PostgreSQL |
| api-middleware | 8012 | 实时+历史数据中间层 | vLLM + PostgreSQL |
| fin-r1-webui | 8011 | Web界面 | api-middleware |

**数据库配置**: 使用现有的 PostgreSQL 服务器 `123.60.11.74:5432`
- 用户名: `game_agents`
- 数据库: `finr1_data` (独立数据库，与其他项目区分)

## 目录结构

```
fin-r1-live/
├── README.md                   # 本文档
├── deploy.sh                   # 一键部署脚本 ⭐
├── docker-compose.yml          # 完整服务栈编排（vLLM+中间层+WebUI）
│
├── api-middleware/             # 【实时API中间层】⭐
│   ├── main.py                 # FastAPI主服务（含技术指标、量化选股API）
│   ├── realtime_fetcher.py     # 实时数据获取(akshare)
│   ├── database_client.py      # 历史数据+基本面+技术指标客户端
│   ├── technical_indicators.py # 技术指标计算（MACD/BOLL/RSI/MA）
│   ├── stock_analyzer.py       # V1版量化选股分析器（四维度评分）
│   ├── config.py               # 配置管理
│   ├── requirements.txt        # 依赖
│   └── Dockerfile              # 镜像构建
│
└── data-hub/                   # 【历史数据模块】
    ├── database.py                         # ORM模型与DAO
    ├── history_downloader.py               # 历史数据下载器
    ├── history_downloader_with_resume.py   # 支持断点续传的下载器 ⭐
    ├── resume_manager.py                   # 断点续传管理器
    ├── auto_sync.py                        # 自动同步模块
    ├── requirements.txt                    # 依赖
    └── Dockerfile                          # 镜像构建
```

**核心特性 - 自动断点续传**: 每次启动自动检测缺失数据，断点续传下载，失败自动重试

**核心特性 - 智能数据访问**: 通过提示词自动获取实时行情、历史K线、技术指标(MACD/BOLL/RSI/MA)、公司基本面(财务报表/ROE/盈利分析)

**核心特性 - V1版量化选股**: 完整支持量化选股提示词，技术面(50分)+量能(25分)+基本面(10分)+板块(15分)四维度评分系统

**外部镜像** (docker-compose 直接使用):
- `vllm/vllm-openai:v0.4.0` - Fin-R1模型推理服务
- `yidadaa/chatgpt-next-web:latest` - WebUI界面

## 快速部署

### 环境要求

- **PostgreSQL**: 使用现有的服务器 `123.60.11.74:5432`
  - 会自动创建数据库 `finr1_data`
- **vLLM**: 需要已运行在 `http://172.17.0.1:8010`
- **GPU**: 需要NVIDIA GPU，支持通过 `.env` 文件配置使用特定GPU
  - 单GPU服务器: 使用默认配置即可
  - 多GPU服务器（如A800）: 可通过 `GPU_DEVICE_ID` 指定使用哪个GPU（如device=2）

### 一键部署（推荐）

```bash
# 1. 上传到服务器（替换为你的服务器IP）
scp -r fin-r1-live root@你的服务器IP:/home/data/
scp deploy.sh root@你的服务器IP:/home/data/fin-r1-live/

# 2. SSH登录服务器配置
ssh root@你的服务器IP
cd /home/data/fin-r1-live

# 3. （可选）配置GPU设备（多GPU服务器需要）
cp .env.example .env
# 编辑 .env 文件，设置GPU_DEVICE_ID（如A800使用device=2）
# vim .env

# 4. 执行部署
chmod +x deploy.sh
./deploy.sh
```

部署完成后，服务将监听以下端口：
- **8011**: Web UI界面（浏览器直接访问）
- **8012**: API中间层（应用程序调用）
- **8010**: vLLM服务（仅限服务器本地）

部署脚本会自动完成：
1. 构建Docker镜像
2. **自动同步历史数据**：检查数据库中是否有从2024-01-01开始的数据，如果没有则自动下载，有缺失则自动补全
3. 启动实时API中间层

### 自动数据同步逻辑

`data-hub` 服务启动时会自动：

```
检查数据库状态
    ↓
数据是否完整（从2024-01-01至今）？
    ├─ 是 → 跳过下载
    └─ 否 → 判断缺失情况
              ↓
        缺失超过30天？
          ├─ 是 → 全量下载全部股票历史数据
          └─ 否 → 增量下载缺失部分
```

- **首次部署**: 自动下载2024年1月1日至今的全部历史数据
- **后续启动**: 自动检查并补全到今天的数据
- **增量更新**: 只下载缺失的交易日数据

### Docker Compose 部署（推荐）

```bash
cd /home/data/fin-r1-live

# 1. 启动完整服务栈（包含数据同步、vLLM、中间层、WebUI）
docker-compose up

# 2. 或在后台运行
docker-compose up -d

# 3. 查看所有服务日志
docker-compose logs -f

# 4. 查看特定服务日志
docker-compose logs -f fin-r1-vllm     # vLLM模型服务
docker-compose logs -f api-middleware  # API中间层
docker-compose logs -f fin-r1-webui    # Web界面

# 5. 查看数据同步进度（重要！首次启动需等待数据下载完成）
docker-compose logs -f data-hub

# 当 data-hub 日志显示以下内容时，表示数据已就绪：
# ✅ 启动完成: 数据质量良好
# 或
# ✅ 数据已是最新，无需下载
```

**启动顺序** (docker-compose 自动处理):
1. `fin-r1-vllm` - 启动GPU模型服务（需要几分钟加载模型）
2. `data-hub` - **自动断点续传下载历史数据** ⭐
3. `api-middleware` - 启动数据中间层（等待vLLM就绪）
4. `fin-r1-webui` - 启动Web界面

### 自动断点续传机制 ⭐

**data-hub 服务每次启动都会自动执行断点续传：**

```
全新部署 → 自动下载所有股票数据（约30-60分钟）
   ↓
中断恢复 → 自动从断点继续下载（无需人工干预）
   ↓
失败重试 → 自动重试失败的股票（最多3次）
   ↓
增量更新 → 自动下载最新数据（每天只需几分钟）
```

**关键特性：**
- ✅ 每只股票独立记录下载进度
- ✅ 容器重启后自动从中断处继续
- ✅ 网络故障自动恢复和重试
- ✅ 失败任务最多重试3次
- ✅ 数据最终一定会完整

**查看下载进度：**
```bash
# 实时查看下载日志
docker-compose logs -f data-hub

# 查看详细进度（在容器内执行）
docker exec -it finr1-datahub python resume_manager.py status

# 验证数据量
docker run --rm --network host postgres:15-alpine \
  psql "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data" \
  -c "SELECT '股票数', COUNT(*) FROM stocks UNION ALL SELECT '日线记录', COUNT(*) FROM stock_daily;"
```

详见: [AUTO_RESUME_GUIDE.md](./AUTO_RESUME_GUIDE.md)

### 手动部署（分步）

```bash
cd /home/data/fin-r1-live

# 1. 初始化数据库表
docker run --rm --network host \
  -e DATABASE_URL=postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data \
  -v $(pwd)/data-hub:/app \
  -w /app \
  python:3.9-slim \
  bash -c "pip install sqlalchemy psycopg2-binary && python -c 'from database import init_database; init_database()'"

# 2. 构建镜像
docker build -t finr1-middleware:latest ./api-middleware
docker build -t finr1-datahub:latest ./data-hub

# 3. 自动同步数据（检查并下载缺失数据）
docker run --rm --network host \
  -e DATABASE_URL=postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data \
  finr1-datahub:latest \
  python auto_sync.py

# 4. 启动中间层
docker run -d \
  --name finr1-middleware \
  --network host \
  -e VLLM_BASE_URL=http://172.17.0.1:8010 \
  -e DATABASE_URL=postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data \
  --restart unless-stopped \
  finr1-middleware:latest
```

## 公网访问配置（8011和8012端口已开放）

如果服务器的8011(WebUI)和8012(API)端口已开放公网访问，需要配置WebUI使用公网IP连接API中间层：

### 方式1: 使用docker-compose（推荐）

编辑 `.env` 文件，设置你的服务器公网IP：
```bash
# .env 文件
BASE_URL=http://你的服务器公网IP:8012
```

然后重新启动：
```bash
docker-compose down
docker-compose up -d
```

### 方式2: 手动启动WebUI

```bash
# 停止旧WebUI
docker stop fin-r1-webui && docker rm fin-r1-webui

# 启动新WebUI（使用公网IP连接中间层）
docker run -d \
  --name fin-r1-webui \
  -p 8011:3000 \
  -e BASE_URL=http://你的服务器公网IP:8012 \
  -e API_KEY="none" \
  -e HOST="0.0.0.0" \
  -e PORT=3000 \
  -e DEFAULT_MODEL="Fin-R1-Live" \
  -e DISABLE_OPENAI_MODEL_LIST=true \
  -e CUSTOM_MODELS="Fin-R1-Live" \
  yidadaa/chatgpt-next-web:latest
```

### ⚠️ 安全提示

8011和8012端口开放公网访问后，建议采取以下安全措施：

1. **配置防火墙限制IP白名单**（UFW示例）：
```bash
# 允许特定IP访问
ufw allow from 你的办公IP to any port 8011
ufw allow from 你的办公IP to any port 8012
# 拒绝其他IP
ufw deny 8011
ufw deny 8012
```

2. **设置API密钥**（在 `.env` 文件中）：
```bash
API_KEY=your-strong-secret-key
```

3. **使用Nginx反向代理并启用HTTPS**（生产环境强烈推荐）

## 更新WebUI

```bash
# 停止旧WebUI
docker stop fin-r1-webui && docker rm fin-r1-webui

# 启动新WebUI（指向中间层）
docker run -d \
  --name fin-r1-webui \
  -p 8011:3000 \
  -e BASE_URL=http://172.17.0.1:8012 \
  -e API_KEY="none" \
  -e HOST="0.0.0.0" \
  -e PORT=3000 \
  -e DEFAULT_MODEL="Fin-R1-Live" \
  -e DISABLE_OPENAI_MODEL_LIST=true \
  -e CUSTOM_MODELS="Fin-R1-Live" \
  yidadaa/chatgpt-next-web:latest
```

## API接口

**访问方式**:
- **服务器本地**: `http://localhost:8012/...`
- **公网访问**: `http://你的服务器IP:8012/...`（8012端口已开放）

### 健康检查
```bash
# 服务器本地测试
curl http://localhost:8012/health

# 公网访问测试（替换为你的服务器IP）
curl http://你的服务器IP:8012/health
```

### 实时数据
```bash
# 替换 localhost 为你的服务器IP即可公网访问

# 实时行情
curl http://localhost:8012/api/stock/000001/realtime

# 市场概览
curl http://localhost:8012/api/market/overview

# 搜索股票
curl "http://localhost:8012/api/search?keyword=茅台"

# V1版量化分析
curl http://localhost:8012/api/stock/000001/v1-analysis

# 批量选股
curl "http://localhost:8012/api/screening/v1?min_score=75"
```

### 历史数据
```bash
# 历史K线
curl "http://localhost:8012/api/stock/000001/history?days=30"

# 技术指标（MACD/BOLL/RSI/MA）
curl http://localhost:8012/api/stock/000001/indicators

# 统计分析
curl "http://localhost:8012/api/stock/000001/analysis?days=60"

# 财务数据摘要
curl http://localhost:8012/api/stock/000001/financial/summary

# 数据库状态
curl http://localhost:8012/api/database/status
```

### Chat Completion
```bash
curl http://localhost:8012/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Fin-R1-Live",
    "messages": [{"role": "user", "content": "分析一下茅台(600519)近3个月走势和今天行情"}],
    "stream": false
  }'
```

## 智能数据选择

系统根据用户问题自动选择数据源：

| 用户提问 | 实时数据 | 历史数据 | 用途 |
|---------|---------|---------|------|
| "今天茅台怎么样" | ✅ API | ❌ | 当前价格、涨跌幅 |
| "近3个月走势如何" | ❌ | ✅ DB | 历史K线、技术指标 |
| "分析一下技术面" | ✅ API | ✅ DB | 实时+趋势综合 |
| "2024年表现如何" | ❌ | ✅ DB | 全年统计分析 |
| "推荐几只股票" | ✅ API | ✅ DB | 市场热点+历史筛选 |

## 历史数据管理

### 自动同步（推荐）

服务启动时自动检查并下载缺失数据：

```bash
# 使用 docker-compose
docker-compose up data-hub

# 或手动执行自动同步
docker run --rm --network host \
  -e DATABASE_URL=postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data \
  finr1-datahub:latest \
  python auto_sync.py
```

### 持续同步模式（后台定时更新）

```bash
# 每24小时自动检查并同步一次
docker run -d --name finr1-sync \
  --network host \
  -e DATABASE_URL=postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data \
  finr1-datahub:latest \
  python auto_sync.py --loop

# 或指定间隔（如每6小时）
docker run -d --name finr1-sync \
  --network host \
  -e DATABASE_URL=postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data \
  finr1-datahub:latest \
  python auto_sync.py --loop --interval 6
```

### 手动全量下载

```bash
docker run --rm --network host \
  -e DATABASE_URL=postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data \
  finr1-datahub:latest \
  python history_downloader.py
```

### 检查数据状态（不下载）

```bash
docker run --rm --network host \
  -e DATABASE_URL=postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data \
  finr1-datahub:latest \
  python auto_sync.py --status
```

## 数据库表结构

| 表名 | 说明 | 数据来源 |
|------|------|----------|
| `stocks` | 股票基础信息 | data-hub初始化 |
| `stock_daily` | 日线历史数据 | data-hub下载 |
| `stock_realtime` | 实时数据缓存 | api-middleware写入 |
| `market_index` | 大盘指数 | data-hub下载 |
| `data_sync_log` | 同步日志 | 自动记录 |

## 性能对比

| 场景 | 纯API模式 | 本方案(DB+API) |
|------|----------|---------------|
| 历史K线查询(30天) | 5-10秒 | **<100ms** |
| 实时行情查询 | 2-3秒 | 2-3秒 |
| 技术分析(统计) | 需实时计算 | **预计算** |
| 并发支持 | 低 | 高 |
| 数据完整度 | 仅限近期 | 2024年至今 |

## 故障排查

### 服务状态检查

```bash
# 查看所有服务状态
docker-compose ps

# 检查 vLLM 服务
curl http://localhost:8010/v1/models
docker-compose logs -f fin-r1-vllm

# 检查 API中间层
curl http://localhost:8012/health
docker-compose logs -f api-middleware

# 检查 WebUI
curl http://localhost:8011
```

### 数据库连接检查

```bash
# 检查PostgreSQL连接
docker run --rm --network host postgres:15-alpine \
  psql "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data" \
  -c "SELECT COUNT(*) FROM stock_daily;"

# 手动连接数据库
docker run --rm -it --network host postgres:15-alpine \
  psql "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data"
```

### 常见问题

**Q: vLLM 启动失败**
```bash
# 检查GPU是否可用
nvidia-smi

# 检查模型目录是否存在
ls -la /home/data/Fin-R1

# 查看vLLM日志
docker-compose logs fin-r1-vllm
```

**Q: GPU配置问题（多GPU服务器）**

如果使用特定的GPU（如A800的device=2），编辑 `.env` 文件设置GPU编号：
```bash
# .env 文件
GPU_DEVICE_ID=2  # 使用第2号GPU，或使用all表示所有GPU
```

然后重启服务：
```bash
docker-compose down
docker-compose up -d
```

**查看可用GPU**：
```bash
nvidia-smi
# 查看GPU编号，然后设置对应的GPU_DEVICE_ID
```

**Q: WebUI无法连接**
```bash
# 检查中间层是否就绪
curl http://localhost:8012/health

# 检查WebUI配置
docker-compose logs fin-r1-webui
```

## 数据清单与排序功能

### 数据完整性检查

```bash
cd data-hub

# 1. 检查所有数据表状态
python data_inventory.py --check

# 2. 查看缺失的数据
python data_inventory.py --missing

# 3. 导出CSV格式的股票列表（按代码排序）
python data_inventory.py --export csv --sort code > stock_list.csv

# 4. 导出JSON格式（按完整度排序）
python data_inventory.py --export json --sort completeness > stock_status.json
```

### 数据排序演示

```bash
cd data-hub

# 运行所有排序演示
python sort_data_demo.py

# 运行指定演示
python sort_data_demo.py --demo 1  # 按股票代码排序
python sort_data_demo.py --demo 2  # 按股票名称排序
python sort_data_demo.py --demo 3  # 按日期排序日线数据
python sort_data_demo.py --demo 4  # 按完整度排序
python sort_data_demo.py --demo 5  # 多字段排序（交易所+代码）
```

**排序选项**:
- `code` - 按股票代码排序
- `name` - 按股票名称排序
- `completeness` - 按数据完整度排序
- `daily_count` - 按日线数据量排序
- `exchange` - 按交易所分组排序

### 已下载的数据表

| 表名 | 说明 | 记录数 |
|------|------|--------|
| `stocks` | 股票基础信息（5000+只） | ~5,000 |
| `stock_daily` | 日线历史数据（2024至今） | ~1,250,000 |
| `stock_realtime` | 实时行情缓存 | ~5,000 |
| `market_index` | 大盘指数数据 | ~1,250 |
| `sector_data` | 板块行业数据 | ~100,000 |
| `stock_financial_report` | 财务报表数据 | ~40,000 |
| `stock_financial_indicator` | 财务分析指标 | ~40,000 |
| `data_sync_log` | 同步日志 | - |

**推荐但未实现的数据源**:
- 个股新闻 (舆情分析)
- 龙虎榜数据 (追踪游资)
- 资金流向 (主力意图)
- 机构持股 (跟踪机构)
- 大宗交易 (机构行为)

详见: [DATA_INVENTORY.md](./DATA_INVENTORY.md)

## 文件说明

| 文件/目录 | 用途 |
|----------|------|
| `deploy.sh` | 一键部署脚本 |
| `docker-compose.yml` | 服务编排 |
| `api-middleware/` | 实时API服务代码 |
| `data-hub/` | 历史数据模块代码 |
| `data-hub/data_inventory.py` | 数据清单和完整性检查 |
| `data-hub/sort_data_demo.py` | 数据排序演示脚本 |
| `DATA_INVENTORY.md` | 数据清单完整文档 |

## 技术栈

- **Web框架**: FastAPI + Uvicorn
- **数据源**: akshare (东方财富)
- **数据库**: PostgreSQL 15
- **ORM**: SQLAlchemy 2.0
- **容器**: Docker + Docker Compose

## License

MIT License - 仅供学习研究使用，数据来源于公开接口。
