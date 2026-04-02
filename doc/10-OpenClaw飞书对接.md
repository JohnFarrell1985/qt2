# OpenClaw + 飞书机器人对接方案

## 1. 架构设计

```
飞书用户
  │
  ▼ @机器人 发送指令
  │
飞书机器人 (Bot)
  │
  ▼ 消息事件推送
  │
OpenClaw (已部署, Docker)
  │
  ├──▶ 解析指令 → 调用 qt-quant API
  │                     │
  │                     ▼
  │              qt-quant FastAPI (8012)
  │                     │
  │                     ▼
  │              执行结果返回
  │
  ├──▶ 定时拉取日志/交易记录
  │
  └──▶ 告警推送 → 飞书群消息/卡片
```

## 2. 飞书机器人指令设计

### 2.1 数据查询类

| 指令 | 示例 | 对应 API |
|------|------|---------|
| 查股票 {code} | `查股票 000001` | `GET /api/data/stock/{code}/info` |
| 查行情 {code} | `查行情 600519` | `GET /api/data/stock/{code}/history` |
| 查持仓 | `查持仓` | `GET /api/trading/positions` |
| 查资产 | `查资产` | `GET /api/trading/asset` |
| 查委托 | `查委托` | `GET /api/trading/orders` |

### 2.2 策略管理类

| 指令 | 示例 | 对应 API |
|------|------|---------|
| 策略列表 | `策略列表` | `GET /strategy/strategies` |
| 策略排名 | `策略排名 sharpe` | `GET /strategy/strategies/rank/backtest_sharpe` |
| 执行计划 | `执行计划` | `GET /strategy/plan` |
| 宏观状态 | `宏观状态` | `GET /strategy/macro/summary` |
| 切换宏观 {state} | `切换宏观 bull_moderate` | `PUT /strategy/macro/state` |

### 2.3 ML 操作类

| 指令 | 示例 | 对应 API |
|------|------|---------|
| 迭代状态 | `迭代状态` | `GET /iterate/status` |
| 最佳因子 | `最佳因子` | `GET /iterate/best` |
| 启动迭代 | `启动迭代` (使用预设参数) | `POST /iterate/start` |

### 2.4 系统类

| 指令 | 示例 | 对应 API |
|------|------|---------|
| 系统状态 | `系统状态` | `GET /health` |
| 帮助 | `帮助` | 返回指令列表 |

## 3. OpenClaw 配置

### 3.1 Webhook 接收

OpenClaw 作为飞书机器人的消息接收端:

```json
{
  "event_type": "message",
  "content": "查股票 000001",
  "user_id": "xxx",
  "chat_id": "xxx"
}
```

### 3.2 指令解析配置

在 OpenClaw 配置中添加 qt-quant 工具:

```yaml
tools:
  - name: qt_quant_api
    description: "A股量化平台API"
    base_url: "http://qt-api:8012"
    endpoints:
      - name: stock_info
        method: GET
        path: "/api/data/stock/{code}/info"
        trigger: "查股票 (\\w+)"
      - name: positions
        method: GET
        path: "/api/trading/positions"
        trigger: "查持仓"
      - name: asset
        method: GET
        path: "/api/trading/asset"
        trigger: "查资产"
      - name: strategy_list
        method: GET
        path: "/strategy/strategies"
        trigger: "策略列表"
      - name: current_plan
        method: GET
        path: "/strategy/plan"
        trigger: "执行计划"
      - name: macro_summary
        method: GET
        path: "/strategy/macro/summary"
        trigger: "宏观状态"
      - name: iterate_status
        method: GET
        path: "/iterate/status"
        trigger: "迭代状态"
      - name: iterate_best
        method: GET
        path: "/iterate/best"
        trigger: "最佳因子"
      - name: health
        method: GET
        path: "/health"
        trigger: "系统状态"
```

## 4. Webhook 回调模块 (src/api/routers/webhook_router.py)

qt-quant 提供 webhook 端点供 OpenClaw 调用:

### 4.1 主动推送

qt-quant 在以下事件发生时主动推送到 OpenClaw/飞书:

| 事件 | 触发条件 | 推送内容 |
|------|---------|---------|
| 止损触发 | 风控模块触发止损 | 股票代码、亏损比例、已执行卖出 |
| 止盈触发 | 风控模块触发止盈 | 股票代码、盈利比例 |
| 日亏损限额 | 日内亏损超限 | 当日亏损比例、已停止交易 |
| 迭代完成 | AutoIterateEngine 运行结束 | 最佳因子组合、评分 |
| 数据同步异常 | 定时同步失败 | 错误信息 |
| 模型重训完成 | 定期重训完成 | 新模型指标 |

### 4.2 日志观测

OpenClaw 可通过以下端点观测日志:

```
GET /api/trading/orders       → 当日委托记录
GET /strategy/macro/history   → 宏观状态变更
GET /iterate/convergence      → ML 迭代收敛曲线
GET /iterate/status           → 当前迭代进度
```

## 5. Docker 网络配置

确保 OpenClaw 和 qt-quant 在同一 Docker 网络:

```yaml
# docker-compose.yml
services:
  qt-api:
    networks:
      - shared-net

networks:
  shared-net:
    external: true
    name: openclaw_default
```

## 6. 安全考虑

- OpenClaw → qt-quant 走内部 Docker 网络，不暴露外网
- 飞书消息通过 OpenClaw 中转，qt-quant 不直接接收飞书回调
- 交易相关指令 (下单/撤单) 需增加权限校验
- 建议只开放查询类指令给普通用户，操作类需管理员
