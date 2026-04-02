# API 接口文档

## 访问方式

- **Swagger UI**: `http://host:8012/docs` (交互式)
- **ReDoc**: `http://host:8012/redoc` (阅读式)
- **OpenAPI JSON**: `http://host:8012/openapi.json`

## 接口概览

### 系统
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 系统信息 |
| GET | `/health` | 健康检查 |

### 数据查询 (`/api/data/`)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/data/stocks` | 股票列表 (支持 exchange/industry 过滤) |
| GET | `/api/data/stock/{code}/history` | 股票历史行情 |
| GET | `/api/data/stock/{code}/info` | 股票基本信息 |

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

### 回测 (`/api/backtest/`)
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/backtest/run` | 运行回测 |

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
| POST | `/strategy/strategies` | 创建策略 |
| GET | `/strategy/strategies` | 列出策略 |
| GET | `/strategy/strategies/{name}` | 策略详情 |
| PUT | `/strategy/strategies/{name}/status` | 设置状态 |
| GET | `/strategy/strategies/rank/{metric}` | 策略排名 |
| POST | `/strategy/pools` | 创建标的池 |
| GET | `/strategy/pools` | 列出标的池 |
| POST | `/strategy/pools/{name}/refresh` | 刷新动态池 |
| POST | `/strategy/pools/init-builtin` | 初始化内置池 |
| GET | `/strategy/macro/summary` | 宏观环境摘要 |
| GET | `/strategy/macro/states` | 所有宏观状态 |
| PUT | `/strategy/macro/state` | 切换宏观状态 |
| GET | `/strategy/macro/history` | 状态变更历史 |
| GET | `/strategy/macro/mapping` | 状态→策略映射 |
| POST | `/strategy/allocations` | 创建策略分配 |
| GET | `/strategy/allocations` | 查看分配 |
| GET | `/strategy/plan` | 当前执行计划 |

### 自动迭代 (`/iterate/`)
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/iterate/start` | 启动自动迭代 (后台) |
| GET | `/iterate/status` | 迭代进度 |
| GET | `/iterate/convergence` | 收敛曲线 |
| GET | `/iterate/factor-frequency` | 因子频率统计 |
| GET | `/iterate/best` | 最佳结果 |

## 请求/响应示例

### 训练模型
```json
POST /api/ml/train
{
    "factor_names": ["roe", "eps", "momentum_20", "vol_20"],
    "stock_pool": ["000001", "600519", "000002"],
    "start_date": "2024-01-01",
    "end_date": "2025-12-31",
    "label_period": 5,
    "params": {"num_leaves": 63, "learning_rate": 0.05}
}
```

### 创建策略
```json
POST /strategy/strategies
{
    "name": "momentum_v1",
    "factor_names": ["mom_20", "vol_20", "rsi_14"],
    "factor_weights": {"mom_20": 0.5, "vol_20": 0.3, "rsi_14": 0.2},
    "description": "动量因子策略",
    "applicable_macro": ["bull_strong", "bull_moderate"]
}
```

### 启动自动迭代
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
