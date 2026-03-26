# Fin-R1 端到端完整跑通验证指南

本文档详细验证从Web UI → API中间层 → 数据库 → vLLM的完整数据链路。

## 🎯 整体架构验证

```
用户 (Web UI)
    │
    │ HTTP:8011
    ▼
ChatGPT-Next-Web (fin-r1-webui)
    │ 转发请求到API中间层
    │
    │ HTTP:8012
    ▼
API Middleware (api-middleware)
    │ 1. 意图识别 → 确定数据需求
    │ 2. 数据查询 → PostgreSQL/akshare
    │ 3. Prompt构建 → 注入数据
    │
    │ HTTP:8010
    ▼
vLLM (fin-r1-vllm)
    │ 基于带数据的Prompt生成回答
    │
    ▼
    返回AI分析结果
```

---

## ✅ 各组件数据流验证

### 1. Web UI 到 API中间层 ✅

**验证点**: Web UI能否正确连接并转发请求到API中间层

**配置检查**:
```yaml
# docker-compose.yml
fin-r1-webui:
  environment:
    - BASE_URL=http://172.17.0.1:8012  # 指向api-middleware
    - DEFAULT_MODEL=Fin-R1-Live
    - CUSTOM_MODELS=Fin-R1-Live
  depends_on:
    - api-middleware
```

**测试命令**:
```bash
# 1. 检查Web UI是否可访问
curl http://localhost:8011

# 2. 检查Web UI到API中间层的连接
curl http://localhost:8012/health

# 3. 测试完整对话链路（通过Web UI）
# 在Web UI中发送: "你好"
# 预期: 能收到vLLM的回复
```

**预期输出**:
```json
{
  "status": "healthy",
  "service": "fin-r1-middleware",
  "database": {"connected": true, ...}
}
```

---

### 2. API中间层到数据库 ✅

**验证点**: API中间层能否成功从PostgreSQL读取所有数据

**数据链路**:
```
api-middleware
    │
    │ SQL查询
    ▼
PostgreSQL (123.60.11.74:5432)
    ├── stock_daily (K线数据)
    ├── stock_financial_report (财务报表)
    ├── stock_financial_indicator (财务指标)
    └── stocks (股票基础信息)
```

**测试命令**:
```bash
# 1. 检查数据库连接
curl http://localhost:8012/api/database/status

# 2. 测试K线数据查询
curl http://localhost:8012/api/stock/000001/history?days=30

# 3. 测试技术指标计算
curl http://localhost:8012/api/stock/000001/indicators

# 4. 测试财务数据查询
curl http://localhost:8012/api/stock/000001/financial/summary

# 5. 测试V1版量化分析
curl http://localhost:8012/api/stock/000001/v1-analysis
```

**预期输出示例**:
```json
{
  "code": "000001",
  "name": "平安银行",
  "total_score": 82,
  "technical_data": {
    "ma_values": {"ma5": 10.42, "ma10": 10.25, ...},
    "macd": {"macd": 0.15, "signal": "金叉"},
    "rsi": 62
  },
  "fundamental_data": {
    "pe": 5.8,
    "pb": 0.62,
    "roe": 11.2
  }
}
```

**关键数据表验证**:

| 数据表 | 用途 | 验证查询 | 预期结果 |
|--------|------|---------|---------|
| stock_daily | K线+成交量 | `SELECT COUNT(*) FROM stock_daily WHERE code='000001'` | >0条 |
| stocks | 股票基础信息 | `SELECT * FROM stocks WHERE code='000001'` | 有记录 |
| stock_financial_report | 财务报表 | 财务报表API调用 | 返回数据 |
| stock_financial_indicator | 财务指标 | 财务摘要API调用 | 返回数据 |

---

### 3. API中间层到vLLM ✅

**验证点**: API中间层能否成功调用vLLM并获取AI回答

**数据链路**:
```
api-middleware (main.py)
    │
    │ 构建带数据的Prompt
    │ {"messages": [{"role": "system", "content": "数据..."}, ...]}
    │
    │ HTTP POST
    ▼
vLLM (port:8010)
    │ 处理Prompt
    ▼
返回AI分析文本
```

**测试命令**:
```bash
# 1. 检查vLLM健康状态
curl http://localhost:8010/v1/models

# 2. 测试Chat Completion（带数据注入）
curl -X POST http://localhost:8012/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Fin-R1-Live",
    "messages": [
      {"role": "user", "content": "分析000001的MACD和基本面"}
    ],
    "temperature": 0.7
  }'
```

**预期输出**:
```json
{
  "id": "chatcmpl-xxx",
  "model": "Fin-R1-Live",
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "根据最新数据分析，平安银行(000001)的MACD呈现金叉信号..."
    }
  }]
}
```

**Prompt注入验证**:

当用户提问"分析000001的MACD"时，系统自动注入的数据包括:
```
【历史数据统计】
000001 近60天统计: ...

【技术指标分析】
000001 技术指标:
  移动平均线: MA5=¥10.42 > MA10=¥10.25 ...
  MACD指标: MACD=0.15, Signal=0.08, 信号: 金叉（买入信号）
  布林带: ...
  RSI指标: ...

【实时行情】
平安银行(000001): ¥10.52 (+1.35%) ...
```

---

### 4. Data Hub数据下载链路 ✅

**验证点**: Data Hub能否自动下载所有必要数据

**数据链路**:
```
Docker启动 data-hub
    │
    ▼
startup_auto_resume.py
    │
    ├── 等待PostgreSQL连接
    ├── 初始化所有表结构
    ├── 检查数据状态
    │       ├── 空数据库 → 全量下载
    │       ├── 有缺失 → 断点续传
    │       └── 最新数据 → 增量更新
    │
    ▼
akshare (东方财富API)
    │ 获取: 股票列表、K线数据、财务数据
    ▼
PostgreSQL (保存数据)
```

**测试命令**:
```bash
# 1. 检查Data Hub日志（验证自动下载）
docker-compose logs -f data-hub

# 2. 验证数据量
psql "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data" \
  -c "SELECT 
    (SELECT COUNT(*) FROM stocks) as stocks_count,
    (SELECT COUNT(*) FROM stock_daily) as daily_count,
    (SELECT MAX(trade_date) FROM stock_daily) as latest_date;"

# 3. 验证断点续传表
psql "..." -c "SELECT status, COUNT(*) FROM stock_download_progress GROUP BY status;"
```

**预期输出**:
```
 stocks_count | daily_count | latest_date
--------------+-------------+-------------
         5234 |     1250000 | 2025-03-16

  status  | count
----------+-------
 success  |  4700
 pending  |   500
 failed   |    34
```

---

## 🔄 完整端到端测试流程

### 测试场景1: 基础对话（验证链路通）

**步骤**:
1. 打开Web UI (http://IP:8011)
2. 输入: "你好"
3. 预期: 收到vLLM的问候回复

**验证点**:
- ✅ Web UI → API中间层连通
- ✅ API中间层 → vLLM连通
- ✅ 基础对话功能正常

---

### 测试场景2: 股票K线查询（验证历史数据）

**步骤**:
1. Web UI输入: "查看000001近30天的走势"
2. 预期: AI回答包含平安银行的K线走势分析

**数据链路验证**:
- ✅ IntentRecognizer识别"走势"关键词
- ✅ 查询stock_daily获取30天K线数据
- ✅ 数据注入到System Prompt
- ✅ vLLM基于数据生成走势分析

**预期回答示例**:
> 根据近30天数据，平安银行(000001)呈上升趋势：
> - 当前价格¥10.52，较30日前上涨8.5%
> - 最高价¥11.20，最低价¥9.80
> - 最近3个交易日：¥10.30 → ¥10.38 → ¥10.52

---

### 测试场景3: 技术指标分析（验证实时计算）

**步骤**:
1. Web UI输入: "分析000001的MACD和布林带"
2. 预期: AI回答包含MACD金叉/死叉信号、布林带位置

**数据链路验证**:
- ✅ 识别"MACD"、"布林带"技术指标关键词
- ✅ 获取60天K线数据
- ✅ 实时计算MACD、BOLL、RSI
- ✅ 数据注入到Prompt

**预期回答示例**:
> **技术指标分析**:
> - **MACD**: DIF=0.15, DEA=0.08，呈现**金叉信号**，动能向上
> - **布林带**: 股价位于中轨(¥10.15)与上轨(¥10.85)之间，强势区
> - **RSI(14)**: 62，处于强势区间，未超买
> - **均线**: MA5>MA10>MA20>MA60，多头排列

---

### 测试场景4: 基本面分析（验证财务数据）

**步骤**:
1. Web UI输入: "贵州茅台600519的基本面如何，ROE多少"
2. 预期: AI回答包含ROE、PE、盈利增长等数据

**数据链路验证**:
- ✅ 识别"基本面"、"ROE"关键词
- ✅ 查询stock_financial_indicator获取财务指标
- ✅ 查询stock_financial_report获取财务报表
- ✅ 数据注入到Prompt

**预期回答示例**:
> **基本面分析**:
> - **ROE**: 28.5%，远超行业平均(15%)，资本回报率优秀
> - **估值**: PE=28.5倍，PB=8.2倍，处于合理区间
> - **盈利能力**: 毛利率91.5%，净利率49.8%，盈利能力极强
> - **成长性**: 营收同比+15%，净利润同比+20%

---

### 测试场景5: 量化选股（验证V1提示词）

**步骤**:
1. Web UI输入: "帮我筛选近期技术面强势、基本面健康的股票"
2. 预期: AI返回符合条件的股票列表及评分

**数据链路验证**:
- ✅ 识别"筛选"、"技术面"、"基本面"关键词
- ✅ 调用stock_analyzer批量分析
- ✅ 四维度评分（技术50+量能25+板块15+基本面10）
- ✅ 返回评分≥75分的股票

**预期回答示例**:
> 根据V1版量化选股标准，为您筛选出以下3只符合条件的股票：
>
> **1. 平安银行(000001) - 82分 ✅**
> - 技术面: 42/50分（均线多头排列+MACD金叉）
> - 量能: 21/25分（换手合理+放量上涨）
> - 基本面: 8/10分（PE=5.8低估+ROE=11.2%）
> - 建议: 推荐买入，风险等级中低
>
> **2. 五粮液(000858) - 78分 ✅**
> ...

---

### 测试场景6: 综合分析（验证全部数据）

**步骤**:
1. Web UI输入: "全面分析宁德时代300750，包括技术面、基本面和估值"
2. 预期: AI回答综合了K线走势、技术指标、财务报表、实时行情

**数据链路验证**:
- ✅ 识别多维度数据需求
- ✅ 同时查询：实时行情 + K线 + 技术指标 + 财务数据
- ✅ 所有数据整合到Prompt
- ✅ AI生成综合分析

---

## 📋 数据完整性检查清单

### 必需数据表检查

| 数据表 | 用途 | 最小记录数 | 检查命令 |
|--------|------|-----------|---------|
| stocks | 股票基础信息 | 5000+ | `SELECT COUNT(*) FROM stocks;` |
| stock_daily | K线历史数据 | 100万+ | `SELECT COUNT(*) FROM stock_daily;` |
| stock_financial_report | 财务报表 | 3万+ | `SELECT COUNT(*) FROM stock_financial_report;` |
| stock_financial_indicator | 财务指标 | 3万+ | `SELECT COUNT(*) FROM stock_financial_indicator;` |
| stock_download_progress | 下载进度 | 5000+ | `SELECT COUNT(*) FROM stock_download_progress;` |
| data_sync_log | 同步日志 | 10+ | `SELECT COUNT(*) FROM data_sync_log;` |

### 数据时效性检查

```bash
# 检查最新数据日期
psql "..." -c "SELECT MAX(trade_date) FROM stock_daily;"
# 预期: 应该是今天或昨天的日期

# 检查财务数据最新日期
psql "..." -c "SELECT MAX(report_date) FROM stock_financial_report;"
# 预期: 应该是最近一个财报季
```

---

## 🛠️ 故障排查指南

### 故障1: Web UI无法访问

**症状**: 打开http://IP:8011无响应

**排查**:
```bash
# 检查容器状态
docker-compose ps

# 检查Web UI日志
docker-compose logs fin-r1-webui

# 检查端口占用
netstat -tlnp | grep 8011
```

### 故障2: API中间层无法连接数据库

**症状**: 查询股票数据返回空

**排查**:
```bash
# 检查API中间层健康状态
curl http://localhost:8012/health

# 检查数据库连接
docker run --rm --network host postgres:15-alpine \
  psql "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data" \
  -c "SELECT 1;"

# 检查API中间层日志
docker-compose logs api-middleware
```

### 故障3: AI回答没有数据

**症状**: AI回答"我没有获取到相关数据"

**排查**:
```bash
# 检查IntentRecognizer是否识别到股票代码
docker-compose logs api-middleware | grep "意图分析"

# 检查数据查询是否成功
docker-compose logs api-middleware | grep "获取.*数据失败"

# 直接测试数据查询API
curl http://localhost:8012/api/stock/000001/history
```

### 故障4: vLLM无响应

**症状**: API中间层请求超时

**排查**:
```bash
# 检查vLLM健康状态
curl http://localhost:8010/v1/models

# 检查vLLM资源使用
docker stats fin-r1-vllm

# 检查vLLM日志
docker-compose logs fin-r1-vllm | tail -50
```

### 故障5: 数据下载不完整

**症状**: Data Hub反复重启或数据量不足

**排查**:
```bash
# 检查Data Hub日志
docker-compose logs data-hub

# 检查下载进度
psql "..." -c "SELECT status, COUNT(*) FROM stock_download_progress GROUP BY status;"

# 手动触发续传
docker-compose restart data-hub
```

---

## ✅ 最终验证结论

### 如果所有测试通过，说明:

1. ✅ **Web UI** → API中间层链路正常
2. ✅ **API中间层** → PostgreSQL数据库连通
3. ✅ **API中间层** → vLLM模型服务连通
4. ✅ **Data Hub** 数据下载完整（5000+股票、100万+K线）
5. ✅ **技术指标计算** 正常（MACD/BOLL/RSI/MA）
6. ✅ **财务数据查询** 正常（报表+指标）
7. ✅ **意图识别** 准确（自动识别数据需求）
8. ✅ **Prompt构建** 完整（数据成功注入）
9. ✅ **AI模型** 能基于数据生成分析

### 系统完全跑通的标志:

```bash
# 运行完整测试脚本
./test_end_to_end.sh

# 预期输出:
# ✅ Web UI 可访问
# ✅ API中间层 健康
# ✅ 数据库连接 正常
# ✅ 历史K线数据 完整 (1,250,000条)
# ✅ 财务数据 完整
# ✅ vLLM 响应正常
# ✅ 技术指标计算 准确
# ✅ V1量化选股 正常工作
# ✅ 完整对话链路 通顺
#
# 🎉 所有测试通过！系统完全跑通！
```

---

## 📝 快速验证命令汇总

```bash
# 1. 一键健康检查
curl -s http://localhost:8012/health | jq

# 2. 数据量检查
psql "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data" \
  -c "SELECT 'stocks', COUNT(*) FROM stocks UNION ALL SELECT 'daily', COUNT(*) FROM stock_daily;"

# 3. 单股分析测试
curl -s http://localhost:8012/api/stock/000001/v1-analysis | jq '.total_score, .recommendation'

# 4. Chat Completion测试
curl -s -X POST http://localhost:8012/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Fin-R1-Live", "messages": [{"role": "user", "content": "分析000001"}]}' | jq '.choices[0].message.content'

# 5. 批量选股测试
curl -s http://localhost:8012/api/screening/v1?min_score=75 | jq '.total_candidates'
```

---

**结论**: 按照本指南验证，可100%确认项目是否完全跑通！
