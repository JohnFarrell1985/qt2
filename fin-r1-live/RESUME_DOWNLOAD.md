# 断点续传功能文档

## 📋 功能概述

Fin-R1 Data Hub 现在支持**断点续传**功能，确保每个股票的数据都能完整下载：

1. **独立进度追踪** - 每只股票有独立的下载状态记录
2. **中断恢复** - 下载中断后可从中断处继续
3. **失败重试** - 自动重试失败的任务（最多3次）
4. **实时进度** - 实时显示下载进度和统计

## 🗄️ 数据表结构

### stock_download_progress（新增）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger | 主键 |
| code | String(10) | 股票代码 |
| sync_type | String(20) | 同步类型（history_full/history_inc/fundamental） |
| status | String(20) | 状态（pending/running/success/failed） |
| start_date | Date | 计划开始日期 |
| end_date | Date | 计划结束日期 |
| actual_start_date | Date | 实际最早数据日期 |
| actual_end_date | Date | 实际最晚数据日期 |
| records_count | Integer | 已下载记录数 |
| expected_count | Integer | 预期记录数（约250个交易日） |
| retry_count | Integer | 已重试次数 |
| max_retries | Integer | 最大重试次数（默认3） |
| error_message | String(500) | 错误信息 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |
| completed_at | DateTime | 完成时间 |

## 🚀 使用方法

### 1. 全新下载（初始化进度记录）

```bash
cd data-hub

# 方式1: 初始化进度记录并立即下载
python history_downloader_with_resume.py

# 方式2: 只初始化进度记录，不下载
python history_downloader_with_resume.py --init-only
```

**输出示例**:
```
============================================================
 股票下载进度状态
============================================================
总股票数: 5234
  ✅ 已完成 (success): 0
  ⏳ 待下载 (pending): 5234
  🔄 下载中 (running): 0
  ❌ 失败 (failed): 0

完成率: 0.00%

最近更新（前20条，按股票代码排序）:
代码      类型            状态         记录数    进度      重试    更新时间
--------------------------------------------------------------------------------
000001    history_full   ⏳ pending   0         0.0%     0/3     --
000002    history_full   ⏳ pending   0         0.0%     0/3     --
000063    history_full   ⏳ pending   0         0.0%     0/3     --
...
```

### 2. 断点续传

当下载中断后（如网络断开、容器重启），可以从中断处继续：

```bash
# 查看当前状态
python resume_manager.py status

# 执行断点续传（只下载未完成的）
python resume_manager.py resume
# 或
python history_downloader_with_resume.py --resume
```

**输出示例**:
```
============================================================
 执行断点续传
============================================================

待下载: 523 只
可重试: 5 只

开始断点续传...

下载进度: 100%|████████████████| 523/523 [05:30<00:00, 1.58it/s]

✅ 断点续传完成，共下载 125,000 条记录

最终状态:
============================================================
下载状态汇总
============================================================
总计: 5234 只股票
完成: 5234 只 (100.0%)
待下载: 0 只
下载中: 0 只
失败: 0 只
总记录数: 1,250,000

✅ 所有股票下载完成或已达到最大重试次数
============================================================
```

### 3. 重试失败的任务

```bash
# 查看失败的任务
python resume_manager.py status

# 重试所有失败的任务
python resume_manager.py retry
# 或
python history_downloader_with_resume.py --retry
```

**重试逻辑**:
- 失败的任务最多重试3次
- 每次重试会重置状态为 `pending`
- 超过3次后标记为最终失败

### 4. 查看下载状态

```bash
# 文本格式（默认）
python resume_manager.py status

# JSON格式导出
python resume_manager.py report --format json

# CSV格式导出
python resume_manager.py report --format csv
```

### 5. 数据一致性验证

```bash
# 对比进度记录和实际数据
python resume_manager.py verify
```

**输出示例**:
```
============================================================
进度记录与实际数据对比
============================================================
总进度记录: 5234
缺失日线数据: 0 只
数据不一致: 3 只

⚠️  以下股票数据量不一致:
  000001: 进度 245 条，实际 247 条，差异 +2 条
  000002: 进度 245 条，实际 246 条，差异 +1 条
```

### 6. 重置进度

```bash
# 重置单个股票
python resume_manager.py reset --code 000001

# 重置所有进度（谨慎操作！）
python resume_manager.py reset --all
```

## 📊 断点续传流程图

```
全新下载
    │
    ├── 1. 初始化进度记录（所有股票状态=pending）
    │
    ├── 2. 开始下载
    │       ├── 股票A: pending → running → success ✅
    │       ├── 股票B: pending → running → failed ❌（记录错误）
    │       ├── 股票C: pending → running → success ✅
    │       └── ...
    │
    └── 3. 下载中断（网络断开/容器重启）
            │
            ├── 股票D: running（未完成，保留状态）
            ├── 股票E~Z: pending（未开始）
            └── 股票B: failed（已记录错误）
                    │
                    ▼
            容器重启/网络恢复
                    │
                    ▼
            断点续传 --resume
                    │
                    ├── 只下载 pending 状态的股票（E~Z）
                    ├── 重试 failed 且未达上限的股票（B）
                    └── 跳过已成功的股票（A、C）
                    │
                    ▼
            所有股票下载完成
```

## 🔄 自动断点续传配置

### Docker 启动时自动恢复

修改 `docker-compose.yml`：

```yaml
data-hub:
  build:
    context: ./data-hub
    dockerfile: Dockerfile
  container_name: finr1-datahub
  env_file:
    - .env
  environment:
    - DATABASE_URL=...
    - LOG_LEVEL=INFO
  volumes:
    - ./data-hub/logs:/app/logs
  # 修改启动命令为支持断点续传的脚本
  command: >
    sh -c "python startup.py --resume || python startup.py"
  restart: on-failure
  network_mode: host
```

### 定时任务自动续传

添加 cron 任务（`crontab -e`）：

```bash
# 每6小时检查并续传一次
0 */6 * * * cd /home/data/fin-r1-live && docker-compose run --rm data-hub python resume_manager.py resume >> /var/log/fin-r1-resume.log 2>&1
```

## 🛠️ 故障排查

### 问题 1: 下载进度卡在某个股票不动

**症状**: 进度长时间不更新

**解决**:
```bash
# 1. 查看当前下载状态
python resume_manager.py status

# 2. 如果某只股票卡在 running 状态超过10分钟，重置它
docker run --rm --network host postgres:15-alpine \
  psql "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data" \
  -c "UPDATE stock_download_progress SET status='pending' WHERE code='000001' AND status='running';"

# 3. 重新执行断点续传
python resume_manager.py resume
```

### 问题 2: 某些股票反复失败

**症状**: 失败重试3次后仍然失败

**解决**:
```bash
# 1. 查看失败详情
python resume_manager.py status

# 2. 手动检查这些股票是否停牌或退市
# 访问东方财富网确认

# 3. 如果是已退市股票，可以跳过
# 编辑代码将这些股票加入黑名单

# 4. 或者继续忽略（失败不会阻塞其他股票）
```

### 问题 3: 数据量和预期不符

**症状**: 实际数据量比预期少或多

**解决**:
```bash
# 1. 验证数据一致性
python resume_manager.py verify

# 2. 如果某些股票数据缺失，重置并重新下载
python resume_manager.py reset --code 000001
python resume_manager.py resume
```

## 📈 性能指标

| 指标 | 预期值 | 说明 |
|------|--------|------|
| 初始化进度记录 | < 30秒 | 5234条记录 |
| 单只股票下载 | 0.5-2秒 | 取决于网络 |
| 并发下载 | 5只同时 | 可配置 |
| 断点检测时间 | < 1秒 | 查询pending状态 |
| 进度更新频率 | 每只股票 | 下载完成后更新 |

## 📝 日志文件

断点续传日志保存在 `data-hub/logs/resume.log`：

```
2025-03-16 10:00:00 - 初始化 5234 只股票的进度记录
2025-03-16 10:00:30 - 开始下载，并发数: 5
2025-03-16 10:05:00 - 进度: 10.0% | 成功: 523/5234 | 失败: 2 | 记录: 130,000
2025-03-16 10:15:00 - 网络中断，容器重启
2025-03-16 10:20:00 - 断点续传启动，待下载: 4709只
2025-03-16 11:00:00 - 下载完成，成功率: 99.9%
```

## 🔧 高级配置

### 修改并发数

编辑 `history_downloader_with_resume.py`：

```python
CONCURRENT_DOWNLOADS = 10  # 默认5，根据网络调整
```

### 修改重试次数

编辑 `database.py` 中的 `StockDownloadProgress`：

```python
max_retries = Column(Integer, default=5)  # 默认3次
```

### 调整超时时间

```python
AKSHARE_TIMEOUT = 120  # 默认60秒，网络慢时增加
```

## ✅ 最佳实践

1. **首次下载**: 在前台运行观察进度
   ```bash
   python history_downloader_with_resume.py
   ```

2. **定时续传**: 设置 cron 任务定期检查

3. **数据验证**: 每周运行一次验证脚本
   ```bash
   python resume_manager.py verify
   ```

4. **日志监控**: 监控日志文件大小，定期清理
   ```bash
   find data-hub/logs -name "*.log" -mtime +7 -delete
   ```

## 📞 获取帮助

```bash
# 查看帮助
python history_downloader_with_resume.py --help
python resume_manager.py --help

# 测试模式（只下载50只）
python history_downloader_with_resume.py --sample 50

# 只检查状态，不下载
python history_downloader_with_resume.py --status
```
