# Data Hub Docker 启动流程检查报告

## 当前启动流程

```
Docker 启动
    ↓
CMD ["python", "auto_sync.py"]
    ↓
main() 函数执行
    ↓
AutoSyncManager.run()
    ├── 1. init_database() - 创建所有表
    │   └── 创建 8 个数据表
    │       - stocks
    │       - stock_daily
    │       - stock_realtime
    │       - market_index
    │       - sector_data
    │       - stock_financial_report      ← 基本面表
    │       - stock_financial_indicator   ← 基本面表
    │       - data_sync_log
    │
    ├── 2. check_database_status() - 检查数据状态
    │   ├── 检查 stock_daily 表记录数
    │   ├── 获取最小/最大日期
    │   └── 判断是否需要全量/增量下载
    │
    └── 3. 执行下载
        ├── run_full_download() - 全量下载
        │   ├── fetch_stock_list() - 获取股票列表
        │   ├── 保存 stocks 表
        │   └── download_all_history() - 下载日线数据
        │       └── 并发下载所有股票日线数据
        │
        └── run_incremental_sync() - 增量同步
            └── 下载缺失的最新数据
```

## ✅ 已确认正常工作的部分

### 1. 数据库初始化
- `init_database()` 会创建所有 8 个表（包括基本面数据表）
- 使用 SQLAlchemy ORM，自动处理表结构创建

### 2. 日线数据下载
- 自动获取全部 A 股列表（5000+只）
- 并发下载（5个并发）提高速度
- 支持断点续传和增量更新
- 数据完整性检查（验证返回4000+只股票）

### 3. 错误处理
- 数据库连接失败会返回 False
- 下载失败会记录日志并继续
- 容器退出码反映执行状态

## ⚠️ 发现的问题

### 问题 1: Dockerfile 缺少基本面数据文件

**现状**: Dockerfile 只复制了3个文件：
```dockerfile
COPY database.py .
COPY history_downloader.py .
COPY auto_sync.py .
```

**缺失**: `fundamental_fetcher.py` 和 `fundamental_sync.py` 没有在 Dockerfile 中复制

**影响**: 虽然数据库表会创建（在 database.py 中定义），但容器内没有基本面数据下载功能

**解决方案**: 更新 Dockerfile 复制基本面数据文件（如果需要基本面数据自动下载）

### 问题 2: auto_sync.py 没有自动下载基本面数据

**现状**: `run_full_download()` 只下载：
1. 股票列表（stocks）
2. 日线数据（stock_daily）

**缺失**: 没有自动下载：
- 财务报表（stock_financial_report）
- 财务指标（stock_financial_indicator）
- 大盘指数（market_index）
- 板块数据（sector_data）

**解决方案**: 在 auto_sync.py 中添加基本面数据同步逻辑（可选，因为基本面数据更新频率低）

### 问题 3: 网络依赖

**现状**: 容器启动依赖：
1. PostgreSQL 数据库可连接（123.60.11.74:5432）
2. akshare 数据源可访问（东方财富）

**风险**: 如果网络不通，容器会退出并报错

**解决方案**: 已配置 `restart: on-failure` 在 docker-compose.yml 中

### 问题 4: 首次下载时间长

**现状**: 全量下载 5000+ 只股票，每只 250 个交易日
- 估计数据量：约 125万 条记录
- 预计耗时：20-60分钟（取决于网络）

**建议**: 首次部署时观察日志，确认数据下载进度

## 🚀 验证 Docker 启动流程

### 本地测试步骤

```bash
# 1. 构建镜像
cd /home/data/fin-r1-live
docker-compose build data-hub

# 2. 启动容器（前台运行查看日志）
docker-compose run --rm data-hub

# 3. 查看日志输出
# 预期看到：
# - 🚀 Fin-R1 Data Hub 自动同步启动
# - ✅ 数据库表结构检查完成
# - 🔍 检查数据库数据状态...
# - 📥 执行全量历史数据下载...
# - ✅ 全量下载完成: XXXXX 条记录
```

### 生产部署步骤

```bash
# 1. 启动所有服务（后台）
docker-compose up -d

# 2. 查看 data-hub 日志
docker-compose logs -f data-hub

# 3. 等待数据下载完成（首次可能需要30-60分钟）
# 当日志显示 "✅ 全量下载完成" 时，数据已就绪

# 4. 验证数据
docker run --rm --network host postgres:15-alpine \
  psql "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data" \
  -c "SELECT COUNT(*) FROM stock_daily;"
```

## 📊 预期启动输出

### 首次启动（空数据库）

```
🚀 Fin-R1 Data Hub 自动同步启动
✅ 数据库表结构检查完成
🔍 检查数据库数据状态...
  - 股票数: 0
  - 记录数: 0
  - 最早日期: None
  - 最晚日期: None
  - 需要全量下载: True
  - 需要增量同步: False
  - 缺失天数: 450
📥 执行全量历史数据下载...
开始全量历史数据下载
起始日期: 2024-01-01
正在获取股票列表...
✅ 成功获取 5234 只股票
交易所分布: {'SH': 2189, 'SZ': 2845, 'BJ': 200}
已保存 5234 只股票基础信息
下载历史数据: 100%|████████████████| 5234/5234 [25:30<00:00,  3.42it/s]
全量下载完成: 1250000 条记录
```

### 后续启动（已有数据）

```
🚀 Fin-R1 Data Hub 自动同步启动
✅ 数据库表结构检查完成
🔍 检查数据库数据状态...
  - 股票数: 5234
  - 记录数: 1250000
  - 最早日期: 2024-01-02
  - 最晚日期: 2025-03-14
  - 需要全量下载: False
  - 需要增量同步: True
  - 缺失天数: 2
📥 执行增量数据同步...
开始增量同步: 2025-03-15 到 2025-03-16
增量同步完成: 更新 4800 只股票, 新增 9600 条记录
```

### 数据已是最新

```
🚀 Fin-R1 Data Hub 自动同步启动
✅ 数据库表结构检查完成
🔍 检查数据库数据状态...
  - 股票数: 5234
  - 记录数: 1308000
  - 最早日期: 2024-01-02
  - 最晚日期: 2025-03-16
  - 需要全量下载: False
  - 需要增量同步: False
  - 缺失天数: 0
✅ 数据已是最新，无需下载
```

## 🔧 修复建议

### 1. 更新 Dockerfile（添加基本面文件）

如果需要基本面数据自动下载，更新 Dockerfile：

```dockerfile
# 复制代码
COPY database.py .
COPY history_downloader.py .
COPY auto_sync.py .
COPY fundamental_fetcher.py .    # 新增
COPY fundamental_sync.py .         # 新增
```

### 2. 添加基本面数据同步（可选）

在 `auto_sync.py` 的 `run()` 方法中添加：

```python
# 4. 同步基本面数据（每季度执行一次）
if self.should_sync_fundamental():
    logger.info("📥 同步基本面数据...")
    await self.sync_fundamental_data()
```

### 3. 当前推荐的 Docker Compose 配置

```yaml
data-hub:
  build:
    context: ./data-hub
    dockerfile: Dockerfile
  container_name: finr1-datahub
  env_file:
    - .env
  environment:
    - DATABASE_URL=${DATABASE_URL:-postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data}
    - LOG_LEVEL=${LOG_LEVEL:-INFO}
  volumes:
    - ./data-hub/logs:/app/logs
  # 自动启动并检查数据，完成后退出
  restart: on-failure
  network_mode: host
  deploy:
    restart_policy:
      condition: on-failure
      delay: 10s
      max_attempts: 3
```

## ✅ 结论

**当前状态**: Docker 启动流程 **基本可用**，能自动完成：
1. ✅ 数据库建表
2. ✅ 股票列表下载
3. ✅ 日线历史数据下载

**需要优化**: 如果需要基本面数据自动下载，需要更新 Dockerfile 和 auto_sync.py

**生产建议**:
1. 首次部署时在前台运行 `docker-compose run --rm data-hub` 观察日志
2. 确认数据下载完成后再启动 api-middleware
3. 或者使用 `depends_on` 配合健康检查
