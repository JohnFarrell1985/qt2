# Fin-R1 Data Hub 部署指南

## 🚀 快速部署（3步）

### 第 1 步: 准备环境

```bash
# 确保 PostgreSQL 可访问（123.60.11.74:5432）
telnet 123.60.11.74 5432

# 确保数据库已创建
docker run --rm --network host postgres:15-alpine \
  psql "postgresql://game_agents:1234+asdf@123.60.11.74:5432/postgres" \
  -c "CREATE DATABASE IF NOT EXISTS finr1_data;"
```

### 第 2 步: 启动服务

```bash
cd /home/data/fin-r1-live

# 方式A: 后台启动（推荐生产环境）
docker-compose up -d

# 方式B: 前台启动（首次部署观察用）
docker-compose up
```

### 第 3 步: 验证数据

```bash
# 查看数据同步日志（等待显示"启动完成"）
docker-compose logs -f data-hub

# 验证数据量
docker run --rm --network host postgres:15-alpine \
  psql "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data" \
  -c "SELECT '股票数', COUNT(*) FROM stocks UNION ALL SELECT '日线记录', COUNT(*) FROM stock_daily;"
```

---

## 📊 启动流程时序图

```
时间轴 ───────────────────────────────────────────────────────────────►

[0:00]  docker-compose up -d
          │
          ▼
[0:05]  data-hub 容器启动
          │
          ├── [0:06] 等待数据库连接 ◄──┐ 失败重试3次
          │          (10秒)          │
          │            │             │
          ▼            ▼             │
[0:16]  ✅ 连接成功                  │
          │                          │
          ▼                          │
[0:17]  创建数据表 (8个表)           │
          │                          │
          ├── stocks                 │
          ├── stock_daily            │
          ├── stock_realtime         │
          ├── market_index           │
          ├── sector_data            │
          ├── stock_financial_report │
          ├── stock_financial_indicator
          └── data_sync_log          │
          │                          │
[0:20]  ✅ 表创建完成               │
          │                          │
          ▼                          │
[0:21]  检查数据状态                 │
          │                          │
          ├── 股票数: 0              │
          ├── 记录数: 0              │
          └── 需要全量下载: True     │
          │                          │
          ▼                          │
[0:22]  开始全量下载 ◄───────────────┘
          │
          ├── [0:30] 获取股票列表 (5234只)
          │
          ├── [0:35] 保存股票基础信息
          │
          ├── [0:40] 开始下载日线数据
          │          │
          │          ├── [5:00] 完成 10% (100万条)
          │          ├── [15:00] 完成 50% (600万条)
          │          └── [30:00] 完成 100% (125万条)
          │
[30:00] ✅ 数据下载完成
          │
          ▼
[30:01]  验证数据质量
          │
          ├── 股票数: 5234 ✅
          ├── 日线记录: 1250000 ✅
          └── 质量评级: excellent ✅
          │
          ▼
[30:02]  容器正常退出 (exit code 0)
          │
          ▼
[30:03]  docker-compose 检测到 exit 0
          根据 restart: on-failure 策略
          不再重启（因为是正常退出）
          │
          ▼
[30:05]  api-middleware 启动
          （依赖于 data-hub 完成后的数据库）
          │
          ▼
[30:30]  WebUI 启动
          │
          ▼
[31:00]  ✅ 全部服务就绪！
          访问 http://IP:8011 使用
```

---

## 🔍 启动状态检查命令

### 检查启动是否完成

```bash
# 方法 1: 查看容器状态（data-hub 应该是 Exit 0）
docker-compose ps

# 预期输出:
# NAME              STATUS
# finr1-datahub     Exit 0           ← 正常完成
# finr1-middleware  Up 2 minutes
# fin-r1-webui      Up 2 minutes

# 方法 2: 查看日志最后几行
docker-compose logs data-hub | tail -20

# 预期看到:
# ✅ 启动完成: 数据质量良好
# 或
# ✅ 数据已是最新，无需下载

# 方法 3: 直接查询数据库
./data-hub/test_docker_startup.sh --status
```

### 监控实时进度

```bash
# 新终端窗口 1: 监控数据下载进度
watch -n 5 'docker-compose logs --tail=10 data-hub'

# 新终端窗口 2: 监控数据量增长
watch -n 10 'docker run --rm --network host postgres:15-alpine \
  psql "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data" \
  -c "SELECT COUNT(*) FROM stock_daily;"'

# 新终端窗口 3: 查看容器资源使用
docker stats finr1-datahub
```

---

## ⚙️ 启动模式对比

| 模式 | 适用场景 | 命令 | 耗时 |
|------|----------|------|------|
| **自动检测** | 日常启动 | `docker-compose up -d` | 2-60分钟 |
| **强制全量** | 数据重置 | `python startup.py --full` | 30-60分钟 |
| **仅检查** | 状态确认 | `python startup.py --status` | <10秒 |
| **持续同步** | 定时任务 | `python startup.py --loop` | 常驻 |

### 自动检测模式详解

```python
if 数据库为空:
    执行全量下载 (30-60分钟)
elif 数据缺失 < 30天:
    执行增量同步 (2-5分钟)
else:
    提示"数据已是最新" (<1秒)
```

---

## 🛠️ 故障排查流程

### 故障 1: data-hub 反复重启

```bash
# 症状: docker-compose ps 显示 Restarting

# 1. 查看错误日志
docker-compose logs data-hub | grep -i error

# 2. 常见原因:
#    - 数据库连不上 → 检查网络和数据库服务
#    - 权限不足 → 检查日志目录权限
#    - 内存不足 → 检查宿主机内存

# 3. 手动运行排查
docker-compose run --rm data-hub python startup.py --status
```

### 故障 2: 数据下载太慢

```bash
# 症状: 1小时还没下载完

# 1. 查看当前进度
docker-compose logs data-hub | grep "下载历史数据"

# 2. 如果进度 < 50% 且长时间不动，可能是网络问题
#    重启容器重试
docker-compose restart data-hub

# 3. 减少并发数（如果网络不稳定）
#    修改 auto_sync.py 中的 CONCURRENT_DOWNLOADS = 3
```

### 故障 3: api-middleware 启动失败

```bash
# 症状: api-middleware 一直重启

# 1. 检查依赖服务状态
docker-compose ps

# 2. 确认 data-hub 已完成（Exit 0）
#    确认 vLLM 健康（Up）

# 3. 查看 api-middleware 日志
docker-compose logs api-middleware | grep -i error
```

---

## 📋 部署检查清单

首次部署时逐项确认:

- [ ] PostgreSQL 数据库 `finr1_data` 已创建
- [ ] 数据库用户 `game_agents` 有读写权限
- [ ] 宿主机可以访问 `123.60.11.74:5432`
- [ ] vLLM 模型目录 `/home/data/Fin-R1` 存在
- [ ] GPU 可用 (`nvidia-smi` 正常)
- [ ] docker-compose 版本 >= 1.29
- [ ] Docker 支持 host 网络模式
- [ ] 宿主机磁盘空间 > 10GB
- [ ] 宿主机内存 > 16GB

---

## 📝 常用维护命令

```bash
# 查看所有服务状态
docker-compose ps

# 查看资源使用
docker-compose stats

# 重启单个服务
docker-compose restart data-hub

# 强制重新下载数据
docker-compose run --rm data-hub python startup.py --full

# 查看数据同步历史
docker run --rm --network host postgres:15-alpine \
  psql "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data" \
  -c "SELECT * FROM data_sync_log ORDER BY start_time DESC LIMIT 5;"

# 备份数据（如需要）
docker run --rm --network host postgres:15-alpine pg_dump \
  "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data" \
  > backup_$(date +%Y%m%d).sql

# 清理旧日志
cd data-hub/logs && find . -name "*.log" -mtime +7 -delete
```

---

## 🎯 生产环境最佳实践

1. **首次部署**: 在前台运行观察日志
   ```bash
   docker-compose up data-hub
   # 确认数据下载完成后再按 Ctrl+C，然后后台启动
   docker-compose up -d
   ```

2. **日常维护**: 设置定时任务检查数据新鲜度
   ```bash
   # crontab -e
   0 9 * * * cd /home/data/fin-r1-live && docker-compose restart data-hub
   ```

3. **监控告警**: 监控数据量和最后更新日期
   ```bash
   # 添加到监控脚本
   LAST_DATE=$(docker run --rm --network host postgres:15-alpine \
     psql "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data" \
     -t -c "SELECT MAX(trade_date) FROM stock_daily;")
   
   if [ "$LAST_DATE" != "$(date +%Y-%m-%d)" ]; then
     echo "告警: 数据未更新到最新日期"
   fi
   ```

4. **日志管理**: 定期清理旧日志，避免磁盘占满

---

## 📞 获取帮助

如果遇到问题:

1. 查看详细日志: `docker-compose logs data-hub`
2. 检查启动文档: `data-hub/DOCKER_STARTUP_CHECK.md`
3. 运行测试脚本: `data-hub/test_docker_startup.sh`
4. 查看验证报告: `STARTUP_VERIFICATION.md`
