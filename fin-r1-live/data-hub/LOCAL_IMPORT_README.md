# 本地离线数据导入指南

本文档介绍如何在本地（不通过Docker）运行离线数据导入脚本，快速将东方财富导出的CSV数据导入PostgreSQL。

## 适用场景

- **一次性导入**：本地有大量离线CSV数据需要导入
- **快速处理**：无需构建Docker镜像，直接运行
- **灵活调试**：方便调整导入逻辑和数据映射

## 环境要求

- Python 3.9+
- PostgreSQL 客户端连接（本地或远程）
- 足够的磁盘空间（CSV数据和解压空间）

## 快速开始

### 1. 安装依赖

```bash
cd data-hub

# 创建虚拟环境（推荐）
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置数据库连接

设置环境变量或在 `.env` 文件中配置：

```bash
# Windows PowerShell
$env:DATABASE_URL="postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data"

# Windows CMD
set DATABASE_URL=postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data

# Linux/Mac
export DATABASE_URL="postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data"
```

或创建 `.env` 文件：
```
DATABASE_URL=postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data
```

### 3. 执行导入

```bash
# 导入日线数据（指定本地数据目录）
python offline_data_importer.py \
  --data-dir "C:\Users\dongg\Downloads\export_data" \
  --import-type daily

# 导入财务数据
python offline_data_importer.py \
  --data-dir "C:\Users\dongg\Downloads\export_data" \
  --import-type finance

# 导入所有数据（日线+财务）
python offline_data_importer.py \
  --data-dir "C:\Users\dongg\Downloads\export_data" \
  --import-type all

# 覆盖已存在的数据
python offline_data_importer.py \
  --data-dir "C:\Users\dongg\Downloads\export_data" \
  --import-type daily \
  --overwrite

# 重置进度（重新导入所有文件）
python offline_data_importer.py \
  --data-dir "C:\Users\dongg\Downloads\export_data" \
  --import-type all \
  --reset-progress
```

## 数据目录结构

确保你的离线数据按照以下结构组织：

```
export_data/
├── a_stock_daily/              # A股日线数据
│   ├── 000001_SZ.csv          # 格式: 股票代码_交易所.csv
│   ├── 000002_SZ.csv
│   └── ...
├── a_stock_finance/            # A股财务数据
│   ├── income_vip/            # 利润表
│   ├── balancesheet_vip/      # 资产负债表
│   ├── cashflow_vip/          # 现金流量表
│   └── fina_indicator_vip/    # 财务指标
├── hk_daily/                  # 港股日线数据（可选）
└── hk_financial.csv           # 港股财务数据（可选）
```

## 导入过程说明

### 首次导入
```bash
# 日线数据文件通常较多，建议先导入日线
python offline_data_importer.py \
  --data-dir "C:\Users\dongg\Downloads\export_data" \
  --import-type daily

# 等待完成后再导入财务数据
python offline_data_importer.py \
  --data-dir "C:\Users\dongg\Downloads\export_data" \
  --import-type finance
```

### 断点续传
如果导入过程中断：
1. 进度会自动保存到 `logs/import_progress.json`
2. 再次运行相同命令会自动跳过已完成的文件
3. 无需任何额外操作，直接重新执行命令即可

### 覆盖已有数据
如果之前通过akshare下载了部分数据（122只股票），想要用离线数据覆盖：
```bash
python offline_data_importer.py \
  --data-dir "C:\Users\dongg\Downloads\export_data" \
  --import-type daily \
  --overwrite
```

## 数据字段映射

### 日线数据字段映射

| CSV字段 | 数据库字段 | 数据类型 | 说明 |
|---------|-----------|---------|------|
| `trade_date`/`date` | `trade_date` | Date | 交易日期 |
| `open` | `open` | Float | 开盘价 |
| `high` | `high` | Float | 最高价 |
| `low` | `low` | Float | 最低价 |
| `close` | `close` | Float | 收盘价 |
| `pre_close` | `pre_close` | Float | 昨收价 |
| `vol` | `volume` | BigInt | 成交量（股） |
| `amount` | `amount` | Float | 成交额（元） |
| `change` | `change` | Float | 涨跌额 |
| `pct_chg` | `change_pct` | Float | 涨跌幅% |

**注意**：离线数据可能缺少 `turnover_rate`（换手率）和 `amplitude`（振幅）字段，导入时会留空。

### 财务数据字段映射

财务数据以JSON格式存储在 `data_json` 字段中，以下关键字段会提取到独立列：

| CSV字段 | 数据库字段 | 说明 |
|---------|-----------|------|
| `total_revenue` | `total_revenue` | 营业总收入 |
| `n_income` | `net_profit` | 净利润 |
| `basic_eps` | `basic_eps` | 基本每股收益 |

## 性能优化

### 大批量导入优化
如果数据量很大（数千个文件）：

1. **分批导入**：
   ```bash
   # 只复制部分文件到新目录导入
   mkdir partial_import
   cp export_data/a_stock_daily/0000*.csv partial_import/
   
   python offline_data_importer.py \
     --data-dir partial_import \
     --import-type daily
   ```

2. **监控导入进度**：
   查看 `logs/import_progress.json` 了解已完成和剩余文件数量

3. **调整PostgreSQL配置**（如果是本地数据库）：
   ```sql
   -- 临时增大批量插入缓冲区
   SET work_mem = '256MB';
   SET maintenance_work_mem = '512MB';
   ```

## 常见问题

### Q: 导入速度慢？
A: 正常，日线数据文件通常包含几千行，每个文件需要几秒钟。5000个文件预计需要几小时。

### Q: 如何处理导入错误？
A: 错误会记录在日志中，查看控制台输出。常见错误：
- 编码问题：CSV文件编码不是UTF-8
- 数据格式：日期格式不匹配
- 缺失字段：CSV列名与预期不符

### Q: 可以只导入特定股票？
A: 可以，只复制需要的CSV文件到新目录：
```bash
mkdir selected_stocks
cp export_data/a_stock_daily/000001*.csv selected_stocks/
cp export_data/a_stock_daily/000002*.csv selected_stocks/

python offline_data_importer.py \
  --data-dir selected_stocks \
  --import-type daily
```

### Q: 导入完成后如何验证？
A: 连接到PostgreSQL查询：
```sql
-- 查看日线数据统计
SELECT 
    COUNT(*) as 总记录数,
    COUNT(DISTINCT code) as 股票数量,
    MIN(trade_date) as 最早日期,
    MAX(trade_date) as 最新日期
FROM stock_daily;

-- 查看某只股票的数据样例
SELECT * FROM stock_daily 
WHERE code = '000001' 
ORDER BY trade_date DESC 
LIMIT 5;
```

## 导入后步骤

1. **验证数据完整性**：
   ```bash
   python data_validator.py
   ```

2. **更新股票基础信息**：
   ```bash
   # 可选：更新股票名称、行业等信息
   python -c "
   from database import get_db_session, Stock
   # 自定义更新逻辑
   "
   ```

3. **重建索引**（如果数据量很大）：
   ```sql
   -- 在PostgreSQL中执行
   REINDEX INDEX idx_code_date;
   REINDEX INDEX idx_trade_date;
   REINDEX INDEX idx_code_only;
   REINDEX INDEX idx_code_date_desc;
   ```

## 清理

导入完成后，可以清理：
```bash
# 删除进度文件（如不再需要断点续传）
rm logs/import_progress.json

# 删除虚拟环境（如果不再需要）
deactivate
rm -rf venv/
```

## 与Docker的关系

- **本地导入**：一次性批量导入历史离线数据
- **Docker data-hub**：持续同步最新数据（近几天）

两者互补，不冲突。导入完成后，Docker服务可以继续增量更新最新数据。
