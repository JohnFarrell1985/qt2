"""
量化回测模块

- fees: A股/港股通手续费计算
- data_loader: PostgreSQL 数据加载
- engine: 单笔交易 & 组合回测引擎
- stock_picker: 选股接口 (Mock / Random / LGB)
- strategy_runner: T+1 隔日卖出 & 连续持仓策略引擎
- engine_minute: 分钟线回测引擎 (新增)
- performance: 绩效统计 (夏普/Calmar/最大回撤)
- cli: 命令行工具
"""
