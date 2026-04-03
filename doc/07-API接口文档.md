# API 接口文档

## 访问方式

- **Swagger UI**: `http://host:8012/docs` (交互式, 推荐)
- **ReDoc**: `http://host:8012/redoc` (阅读式)
- **OpenAPI JSON**: `http://host:8012/openapi.json`

---

## 核心接口: 策略执行

### POST /strategy/execute

**这是整个系统最重要的接口**——输入当前持仓和资金, 输出今日操作清单。

内部流程: 策略信号生成 → 持仓监控 → 信号仲裁 → 仓位分配 → 操作清单

#### 请求

```json
POST /strategy/execute
{
    "total_capital": 500000,
    "available_cash": 300000,
    "holdings": [
        {
            "code": "000001.SZ",
            "buy_date": "2025-05-20",
            "buy_price": 10.0,
            "quantity": 1000,
            "current_price": 9.2,
            "highest_price": 10.5,
            "hold_days": 8,
            "strategy_name": "momentum",
            "profit_pct": -8.0
        }
    ],
    "price_map": {
        "000001.SZ": 9.2,
        "600519.SH": 1800.0
    }
}
```

#### 参数说明

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `total_capital` | float | 是 | 总资产 (元) |
| `available_cash` | float | 是 | 可用现金 (元) |
| `holdings` | array | 是 | 当前持仓列表 (空数组=空仓) |
| `price_map` | object | 否 | 标的最新价格映射 (用于仓位分配) |

Holdings 每项字段:

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | string | 标的代码 (QMT 格式) |
| `buy_date` | string | 买入日期 (YYYY-MM-DD) |
| `buy_price` | float | 买入均价 |
| `quantity` | int | 持仓数量 |
| `current_price` | float | 当前价格 |
| `highest_price` | float | 持仓以来最高价 (移动止损用) |
| `hold_days` | int | 已持仓天数 |
| `strategy_name` | string | 来源策略名 |
| `profit_pct` | float | 浮动盈亏 (%) |

#### 响应

```json
{
    "summary": {
        "macro_state": "range_bound",
        "strategies_run": 4,
        "raw_signals": 15,
        "final_sells": 1,
        "final_buys": 2,
        "cash_after_sells": 309200
    },
    "actions": [
        {
            "code": "000001.SZ",
            "direction": "sell",
            "priority": 1,
            "target_quantity": 1000,
            "target_amount": 9200,
            "reasons": ["硬止损: 亏损-8.0%≥-8.0%"],
            "strategy_name": "risk_monitor",
            "strategy_tier": "risk"
        },
        {
            "code": "600519.SH",
            "direction": "buy",
            "priority": 2,
            "target_quantity": 100,
            "target_amount": 180000,
            "reasons": ["多因子得分 0.85, 排名前10"],
            "strategy_name": "multifactor_equal",
            "strategy_tier": "scoring"
        },
        {
            "code": "128095.SZ",
            "direction": "buy",
            "priority": 3,
            "target_quantity": 10,
            "target_amount": 10500,
            "reasons": ["双低=108.5, 价格=105.00, 溢价率=3.5%"],
            "strategy_name": "cb_dual_low",
            "strategy_tier": "rule"
        }
    ]
}
```

---

## 接口概览

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 系统信息 (版本、运行时间) |
| GET | `/health` | 健康检查 |

### 数据查询 (`/api/data/`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/data/stocks` | 股票列表 (支持 exchange/industry 过滤) |
| GET | `/api/data/stock/{code}/history` | 股票历史行情 |
| GET | `/api/data/stock/{code}/info` | 股票基本信息 |

### 数据同步 (`/api/data/sync/`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/data/sync/full` | 全量同步 (后台执行) |
| POST | `/api/data/sync/incremental` | 增量同步 |

参数:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `incremental` | true | 是否增量 (false=全量重下) |
| `sync_minute` | false | 是否同步分钟线 |
| `minute_periods` | — | 分钟线周期 (逗号分隔: 5m,15m,1m) |
| `days_back` | 5 | 增量同步回看天数 |

### 因子分析 (`/api/factor/`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/factor/list` | 因子列表 (支持 category 过滤) |
| GET | `/api/factor/categories` | 因子分类列表 |

### 机器学习 (`/api/ml/`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/ml/train` | 训练 LightGBM 模型 |
| POST | `/api/ml/predict` | 使用模型预测 |

#### 训练模型

```json
POST /api/ml/train
{
    "factor_names": ["roe", "eps", "momentum_20", "vol_20"],
    "stock_pool": ["000001", "600519", "000002"],
    "start_date": "2024-01-01",
    "end_date": "2025-12-31",
    "label_period": 2,
    "params": {"num_leaves": 63, "learning_rate": 0.05}
}
```

#### 模型预测

```json
POST /api/ml/predict
{
    "model_path": "models/best_lgb.pkl",
    "factor_names": ["roe", "eps", "momentum_20", "vol_20"],
    "stock_list": ["000001.SZ", "600519.SH"]
}
```

### 回测 (`/api/backtest/`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/backtest/run` | 运行回测 |

```json
POST /api/backtest/run
{
    "stock_pool": "000001,600519",
    "start_date": "2025-01-01",
    "end_date": "2025-12-31"
}
```

### 交易管理 (`/api/trading/`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/trading/positions` | 查询持仓 |
| GET | `/api/trading/asset` | 查询资产 |
| GET | `/api/trading/orders` | 查询委托 |
| POST | `/api/trading/order` | 提交委托 |

### 策略管理 (`/strategy/`)

| 方法 | 路径 | 说明 |
|------|------|------|
| **POST** | **`/strategy/execute`** | **核心: 执行策略获取操作清单** |
| POST | `/strategy/signals/generate` | 指定策略生成信号 |
| POST | `/strategy/strategies` | 创建策略 |
| GET | `/strategy/strategies` | 列出策略 |
| GET | `/strategy/strategies/{name}` | 策略详情 |
| PUT | `/strategy/strategies/{name}/status` | 设置状态 |
| GET | `/strategy/strategies/rank/{metric}` | 策略排名 |
| POST | `/strategy/pools` | 创建标的池 |
| GET | `/strategy/pools` | 列出标的池 |
| POST | `/strategy/pools/{name}/refresh` | 刷新动态池 |
| POST | `/strategy/pools/init-builtin` | 初始化内置池 |
| GET | `/strategy/plan` | 当前执行计划 |
| GET | `/strategy/registry` | 查看所有已注册策略 |
| GET | `/strategy/registry/{tier}` | 按档位查看策略 |
| POST | `/strategy/allocations` | 创建策略分配 |
| GET | `/strategy/allocations` | 查看分配 |
| GET | `/strategy/macro/summary` | 宏观环境摘要 |
| GET | `/strategy/macro/states` | 所有宏观状态 |
| PUT | `/strategy/macro/state` | 切换宏观状态 |
| GET | `/strategy/macro/history` | 状态变更历史 |
| GET | `/strategy/macro/mapping` | 状态→策略映射 |

### 自动迭代 (`/iterate/`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/iterate/start` | 启动自动迭代 (后台) |
| GET | `/iterate/status` | 迭代进度 |
| GET | `/iterate/convergence` | 收敛曲线 |
| GET | `/iterate/factor-frequency` | 因子频率统计 |
| GET | `/iterate/best` | 最佳结果 |

#### 启动自动迭代

```json
POST /iterate/start
{
    "factor_names": ["roe", "eps", "bps", "mom_20", "vol_20", "rsi_14"],
    "stock_pool": ["000001", "000002", "600519"],
    "train_start": "2023-01-01",
    "train_end": "2025-06-30",
    "test_start": "2025-07-01",
    "test_end": "2026-03-31",
    "max_iterations": 50,
    "target_sharpe": 1.5
}
```

---

## 错误码

| HTTP 状态码 | 说明 |
|------------|------|
| 200 | 成功 |
| 400 | 请求参数错误 (如缺少必填字段) |
| 404 | 资源不存在 (如策略名不存在) |
| 409 | 冲突 (如策略名已存在) |
| 500 | 服务端错误 |

所有错误返回格式:

```json
{
    "detail": "策略 'xxx' 不存在"
}
```
