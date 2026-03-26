# 离线数据导入指南

本文档介绍如何使用离线数据导入工具，将东方财富导出的CSV数据导入到PostgreSQL数据库。

## 数据目录结构

确保你的离线数据按照以下结构组织：

```
export_data/
├── a_stock_daily/              # A股日线数据
│   ├── 000001_SZ.csv
│   ├── 000002_SZ.csv
│   └── ...
├── a_stock_finance/            # A股财务数据
│   ├── income_vip/            # 利润表
│   │   ├── 000001.csv
│   │   └── ...
│   ├── balancesheet_vip/      # 资产负债表
│   ├── cashflow_vip/          # 现金流量表
│   ├── fina_indicator_vip/    # 财务指标
│   ├── fina_mainbz_vip/       # 主营业务
│   ├── express_vip/           # 业绩快报
│   └── forecast_vip/          # 业绩预告
├── hk_daily/                  # 港股日线数据
└── hk_financial.csv           # 港股财务数据
```

## 使用方法

### 1. 挂载数据目录

在 `docker-compose.yml` 中添加数据目录挂载：

```yaml
data-hub:
  volumes:
    - ./data-hub/logs:/app/logs
    - /path/to/export_data:/app/offline_data  # 添加离线数据挂载
```

### 2. 执行导入

#### 导入日线数据
```bash
# 只导入日线数据
docker exec finr1-datahub python offline_data_importer.py \
  --data-dir /app/offline_data \
  --import-type daily

# 覆盖已存在的数据
docker exec finr1-datahub python offline_data_importer.py \
  --data-dir /app/offline_data \
  --import-type daily \
  --overwrite
```

#### 导入财务数据
```bash
# 只导入财务数据
docker exec finr1-datahub python offline_data_importer.py \
  --data-dir /app/offline_data \
  --import-type finance
```

#### 导入所有数据
```bash
# 导入日线和财务数据
docker exec finr1-datahub python offline_data_importer.py \
  --data-dir /app/offline_data \
  --import-type all
```

#### 重置进度（重新导入）
```bash
# 重置导入进度，从头开始导入
docker exec finr1-datahub python offline_data_importer.py \
  --data-dir /app/offline_data \
  --import-type all \
  --reset-progress
```

### 3. 查看导入进度

导入进度会自动保存在 `/app/logs/import_progress.json`，你可以查看已完成的文件列表：

```bash
docker exec finr1-datahub cat /app/logs/import_progress.json
```

## 数据映射

### 日线数据字段映射

| CSV字段 | 数据库字段 | 说明 |
|---------|-----------|------|
| `trade_date`/`date` | `trade_date` | 交易日期 |
| `open` | `open` | 开盘价 |
| `high` | `high` | 最高价 |
| `low` | `low` | 最低价 |
| `close` | `close` | 收盘价 |
| `pre_close` | `pre_close` | 昨收价 |
| `vol` | `volume` | 成交量 |
| `amount` | `amount` | 成交额 |
| `change` | `change` | 涨跌额 |
| `pct_chg` | `change_pct` | 涨跌幅% |

### 财务数据字段映射

财务数据以JSON格式存储在 `data_json` 字段中，关键字段提取到独立列：

| 关键指标 | 数据库字段 | 说明 |
|---------|-----------|------|
| `total_revenue` | `total_revenue` | 营业总收入 |
| `n_income` | `net_profit` | 净利润 |
| `basic_eps` | `basic_eps` | 基本每股收益 |

## 断点续传

导入工具支持断点续传功能：

1. **自动记录进度**：每成功导入一个文件，会自动记录到进度文件
2. **跳过已导入**：再次运行时自动跳过已完成的文件
3. **增量导入**：支持随时停止和继续

## 性能优化建议

1. **批量导入**：日线数据文件较多时，建议分批导入
2. **避开交易时间**：建议在非交易时间进行大规模导入
3. **监控资源**：大量数据导入时监控PostgreSQL的CPU和内存使用

## 常见问题

### Q: 导入过程中断怎么办？
A: 重新运行相同的命令，会自动从断点继续。

### Q: 如何重新导入已完成的文件？
A: 使用 `--reset-progress` 参数重置进度，或使用 `--overwrite` 覆盖数据。

### Q: 数据格式不匹配怎么办？
A: 检查CSV文件是否符合预期的字段名，可以手动修改CSV标题行。

### Q: 导入速度太慢？
A: 
- 日线数据文件通常较大，请耐心等待
- 可以考虑分批导入（只复制部分文件到挂载目录）
- 确保PostgreSQL服务器有足够的资源

## 数据覆盖策略

默认情况下，导入工具会：
- **跳过已存在的数据**：如果 `code` + `trade_date` 已存在，则跳过
- **使用 `--overwrite`**：更新已存在的数据
- **使用 `--reset-progress`**：忽略之前的进度，重新导入所有文件

## 验证导入结果

导入完成后，可以在PostgreSQL中验证数据：

```sql
-- 查看日线数据统计
SELECT 
    COUNT(*) as 总记录数,
    COUNT(DISTINCT code) as 股票数,
    MIN(trade_date) as 最早日期,
    MAX(trade_date) as 最新日期
FROM stock_daily;

-- 查看某只股票的数据
SELECT * FROM stock_daily 
WHERE code = '000001' 
ORDER BY trade_date DESC 
LIMIT 10;
```

## 联系支持

如遇到问题，请查看日志文件 `/app/logs/import_progress.json` 获取详细信息。
