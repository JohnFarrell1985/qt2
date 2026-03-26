# Fin-R1 API Middleware 架构设计文档

## 1. 概述

Fin-R1 API Middleware 是连接 Web UI、vLLM 推理服务和 PostgreSQL 数据库的中间层，负责：
- 智能识别用户数据需求（实时/历史/量化分析）
- 从 PostgreSQL 查询历史数据
- 从外部 API 获取实时行情
- 构造 System Prompt 注入数据上下文
- 管理 SQL Agent 流程（AI生成SQL → 执行 → 分析）

## 2. 核心流程对比

### 2.1 流程一：数据预注入（传统方案）

```
用户提问
    ↓
Web UI → api-middleware /v1/chat/completions
    ↓
【意图识别】
    - 正则提取股票代码（\d{6}）
    - 从数据库加载股票名称映射（平安银行→000001）
    - 判断数据类型：实时/历史/技术指标/基本面
    ↓
【数据查询】
    - HistoryDataClient.get_stock_statistics(code, days)
    - HistoryDataClient.get_stock_history(code, days)
    - fetcher.get_quote(code) [实时API]
    ↓
【Prompt构建】
    System: 你是Fin-R1助手，基于以下数据分析...
            【历史数据统计】000001近30天...
            【技术指标】MACD: xxx, BOLL: xxx
            【实时行情】当前价: ¥xx.xx
    User: 分析000001
    ↓
vLLM (Fin-R1) → 生成回答
    ↓
返回给 Web UI
```

**优点**：简单直接，一次调用
**缺点**：AI可能忽略预注入的数据，产生幻觉

---

### 2.2 流程二：SQL Agent（推荐方案）

```
用户提问
    ↓
Web UI → api-middleware /v1/chat/completions-sql
    ↓
【路由判断】
    - 是否包含6位股票代码？
    - 是否包含股票关键词（查询/收盘/历史）？
    - 是 → 使用SQL Agent流程
    - 否 → 降级到普通流程
    ↓
【SQL Agent 流程】
    Step 1: AI生成SQL
        调用 vLLM (Fin-R1)
        Prompt: 你是专业量化助手...生成标准PostgreSQL查询...
        AI返回: "SELECT trade_date, close FROM stock_daily WHERE code = '000001'..."
        ↓
    Step 2: 后端执行SQL
        SQLAgent.execute_sql()
        - 安全验证（禁止INSERT/UPDATE/DELETE）
        - 预处理（INTERVAL语法转换）
        - 连接 PostgreSQL 执行
        返回: [{"trade_date": "2024-03-18", "close": 10.50}, ...]
        ↓
    Step 3: AI分析结果
        调用 vLLM (Fin-R1)
        Prompt: 根据PostgreSQL数据库查询结果...给出分析结论...
        AI返回: "根据数据库查询结果，平安银行最近5天收盘价..."
        ↓
【组装完整回复】
    full_response = """
    【查询SQL】SELECT trade_date, close...
    
    【查询结果】
    2024-03-18 | 10.50
    2024-03-17 | 10.35
    ...
    
    【分析结论】
    根据PostgreSQL数据库查询结果，平安银行...
    """
    ↓
返回 JSON 给 Web UI
```

**优点**：
- AI明确知道数据来源（SQL和结果都展示）
- 无法编造数据（必须基于查询结果）
- 按需查询，灵活性高

**缺点**：
- 需要2轮AI调用（生成SQL + 分析结果）
- 延迟稍高（多一次数据库往返）

---

## 3. 模块设计

### 3.1 模块结构

```
api-middleware/
├── main.py                  # FastAPI 主应用，路由定义
├── config.py                # 配置管理（环境变量）
├── database_client.py         # PostgreSQL 客户端（只读）
├── realtime_fetcher.py        # 实时数据获取（akshare）
├── sql_agent.py              # SQL Agent 核心（新增）
├── technical_indicators.py    # 技术指标计算
├── stock_analyzer.py          # 量化选股分析
└── requirements.txt
```

### 3.2 核心模块职责

#### main.py
- 路由注册：/v1/chat/completions, /v1/chat/completions-sql, /api/sql-query
- 意图识别：IntentRecognizer.analyze()
- Prompt构建：build_prompt()
- 流式/非流式响应处理

#### database_client.py
- HistoryDataClient：历史数据查询
- TechnicalIndicatorClient：技术指标计算
- FundamentalDataClient：基本面数据查询
- get_db_session()：数据库连接池管理

#### sql_agent.py
- SQLAgent.generate_sql()：AI生成SQL
- SQLAgent.execute_sql()：执行SQL并返回结果
- SQLAgent.preprocess_sql()：SQL预处理（INTERVAL转换、添加LIMIT）
- SQLAgent.analyze_result()：AI分析查询结果
- SQLAgent.process_query()：完整流程封装

## 4. 数据库表结构

### 4.1 历史数据表

```sql
-- 股票日线数据（核心表）
CREATE TABLE stock_daily (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(10) NOT NULL,           -- 股票代码：000001
    trade_date DATE NOT NULL,           -- 交易日期
    open FLOAT,                         -- 开盘价
    high FLOAT,                         -- 最高价
    low FLOAT,                          -- 最低价
    close FLOAT,                        -- 收盘价
    pre_close FLOAT,                    -- 昨收价
    volume BIGINT,                      -- 成交量（股）
    amount FLOAT,                       -- 成交额（元）
    change_pct FLOAT,                   -- 涨跌幅%
    turnover_rate FLOAT,                -- 换手率
    amplitude FLOAT,                    -- 振幅
    UNIQUE(code, trade_date)
);

-- 索引优化
CREATE INDEX idx_stock_daily_code_date ON stock_daily(code, trade_date);
CREATE INDEX idx_stock_daily_trade_date ON stock_daily(trade_date);

-- 股票基础信息
CREATE TABLE stocks (
    code VARCHAR(10) PRIMARY KEY,
    name VARCHAR(50) NOT NULL,          -- 股票名称：平安银行
    exchange VARCHAR(10),               -- SH/SZ/BJ
    industry VARCHAR(50),               -- 所属行业
    sector VARCHAR(50),                 -- 所属板块
    pe_ttm FLOAT,                       -- 市盈率
    pb FLOAT,                           -- 市净率
    roe FLOAT,                          -- ROE
    market_cap FLOAT                    -- 总市值
);
```

## 5. 配置说明

### 5.1 环境变量 (.env)

```bash
# 数据库连接（必填）
DATABASE_URL=postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data

# vLLM 服务（必填）
VLLM_BASE_URL=http://172.17.0.1:8010
VLLM_MODEL=/models/Fin-R1

# 服务配置
HOST=0.0.0.0
PORT=8012

# 功能开关
ENABLE_DB_HISTORY=true      # 启用历史数据查询
ENABLE_REALTIME_API=true    # 启用实时API

# 日志级别
LOG_LEVEL=INFO
```

### 5.2 Web UI 配置

```bash
# 使用SQL Agent端点（推荐）
BASE_URL=http://<服务器IP>:8012/v1/chat/completions-sql

# 使用普通端点（不启用SQL Agent）
BASE_URL=http://<服务器IP>:8012/v1/chat/completions
```

## 6. API 端点列表

### 6.1 主要端点

| 端点 | 方法 | 说明 |
|-----|------|------|
| /v1/chat/completions | POST | 普通Chat Completion（数据预注入） |
| /v1/chat/completions-sql | POST | SQL Agent Chat Completion（推荐） |
| /api/sql-query | POST | SQL Agent 原始接口（返回SQL和结果） |
| /health | GET | 健康检查 |

### 6.2 数据查询端点

| 端点 | 方法 | 说明 |
|-----|------|------|
| /api/stock/{code}/realtime | GET | 获取实时行情 |
| /api/stock/{code}/history | GET | 获取历史数据 |
| /api/stock/{code}/indicators | GET | 获取技术指标 |
| /api/stock/{code}/full-analysis | GET | 综合分析（实时+历史+技术） |
| /api/stock/{code}/v1-analysis | GET | V1版量化选股分析 |
| /api/screening/v1 | POST | V1版批量股票筛选 |

## 7. 使用示例

### 7.1 SQL Agent 查询

```bash
curl -X POST http://localhost:8012/v1/chat/completions-sql \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Fin-R1-Live",
    "messages": [{"role": "user", "content": "查询000001最近5天的收盘价"}],
    "stream": false
  }'
```

**返回示例**：
```json
{
  "model": "Fin-R1-Live",
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "【查询SQL】\nSELECT trade_date, close FROM stock_daily WHERE code = '000001' ORDER BY trade_date DESC LIMIT 5\n\n【查询结果】\ntrade_date | close\n2024-03-18 | 10.50\n2024-03-17 | 10.35\n...\n\n【分析结论】\n根据PostgreSQL数据库查询结果..."
    }
  }]
}
```

### 7.2 直接SQL查询

```bash
curl -X POST http://localhost:8012/api/sql-query \
  -H "Content-Type: application/json" \
  -d '{"question": "平安银行最近30天最高价和最低价"}'
```

**返回示例**：
```json
{
  "success": true,
  "question": "平安银行最近30天最高价和最低价",
  "sql": "SELECT MAX(high), MIN(low) FROM stock_daily WHERE code = '000001' AND trade_date >= CURRENT_DATE - INTERVAL '30 days'",
  "query_result": {
    "columns": ["max", "min"],
    "rows": [["11.20", "9.80"]]
  },
  "analysis": "根据数据库查询结果...",
  "full_response": "【查询SQL】...【查询结果】...【分析结论】..."
}
```

## 8. 安全设计

### 8.1 SQL 安全防护

```python
# 禁止危险操作
forbidden_keywords = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER', 'TRUNCATE']

# 强制添加LIMIT
if 'LIMIT' not in sql.upper():
    sql += " LIMIT 50"

# 预处理INTERVAL语法（避免PostgreSQL参数化问题）
sql = re.sub(r"CURRENT_DATE\s*-\s*INTERVAL\s+'(\d+)\s*days?'", replace_with_date, sql)
```

### 8.2 数据库安全

- 使用只读账号（无写入权限）
- 参数化查询防止SQL注入
- 连接池管理（pool_size=5, max_overflow=10）

## 9. 性能优化

### 9.1 缓存策略

- 股票名称映射：5分钟缓存（减少数据库查询）
- 实时数据：30秒TTL缓存（避免频繁调用akshare）

### 9.2 查询优化

- 数据库索引：idx_stock_daily_code_date (code, trade_date)
- 限制返回条数：默认LIMIT 50，最大LIMIT 100
- 日期范围限制：默认只查最近30天

## 10. 故障排查

### 10.1 查看日志

```bash
# api-middleware 日志
docker logs -f finr1-middleware | grep -E "(SQL|查询|Agent|错误)"

# 数据库查询统计
docker logs -f finr1-middleware | grep "数据查询统计"
```

### 10.2 常见问题

| 问题 | 原因 | 解决方案 |
|-----|------|---------|
| AI始终假设数据 | SQL Agent未触发或Prompt未正确注入 | 检查BASE_URL是否使用completions-sql端点 |
| 股票代码识别失败 | stocks表无该股票名称映射 | 运行update_stock_names脚本填充名称 |
| 数据库查询返回空 | stock_daily表无数据 | 确认离线数据导入成功 |
| SQL执行报错 | INTERVAL语法或字段名错误 | 检查sql_agent.py预处理逻辑 |

## 11. 扩展建议

### 11.1 未来优化方向

1. **混合模式**：简单查询用预注入，复杂查询用SQL Agent
2. **缓存层**：Redis缓存热点查询结果
3. **异步流式**：SQL Agent支持流式返回（先返SQL，再返结果）
4. **多数据源**：支持Tushare、Akshare、Wind等多种数据源

### 11.2 监控告警

```bash
# 监控指标
- 查询响应时间（P99 < 2s）
- SQL Agent触发率（目标 > 80%）
- 数据库连接池使用率（告警阈值 > 80%）
- 错误率（告警阈值 > 1%）
```

---

## 附录：核心代码片段

### A. 意图识别器

```python
class IntentRecognizer:
    STOCK_CODES = re.compile(r'\b(\d{6})\b')
    
    @classmethod
    def analyze(cls, messages):
        content = " ".join([m.content for m in messages if m.role == "user"])
        
        # 提取股票代码
        codes = cls.STOCK_CODES.findall(content)
        
        # 从名称识别代码（动态加载）
        name_map = cls._load_stock_name_map()
        for name, code in name_map.items():
            if name in content:
                codes.append(code)
        
        return {
            "stock_codes": list(set(codes)),
            "need_history": any(kw in content for kw in ["历史", "走势", "K线"]),
            "need_technical": any(kw in content for kw in ["MACD", "BOLL", "RSI"]),
            ...
        }
```

### B. SQL Agent 核心

```python
class SQLAgent:
    @staticmethod
    def process_query(user_question, vllm_client):
        # 1. 生成SQL
        sql = SQLAgent.generate_sql(user_question, vllm_client)
        
        # 2. 执行SQL
        result = SQLAgent.execute_sql(sql)
        
        # 3. AI分析
        analysis = SQLAgent.analyze_result(user_question, result, vllm_client)
        
        return {
            "sql": sql,
            "result": result,
            "analysis": analysis,
            "full_response": f"【查询SQL】{sql}\n\n【查询结果】{result}\n\n【分析结论】{analysis}"
        }
```

---

**文档版本**: v1.0  
**最后更新**: 2026-03-18  
**作者**: Fin-R1 Team
