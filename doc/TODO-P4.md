# P4: 全栈可观测性 (Jaeger / Loki / Prometheus / Grafana / Alert)

> 最后更新: 2026-04-12
>
> 7 项 | 预估工作量 ~12 天
>
> 返回总览: [TODO.md](TODO.md) | P1-26 (structlog + 飞书告警) 已吸收至本文档

---

## 设计目标

量化交易系统的可观测性需要覆盖三大支柱: **Metrics (指标)**, **Logging (日志)**, **Tracing (链路追踪)**, 并在此基础上建立 **Alerting (告警)** 和 **Dashboard (看板)** 体系。

**为什么要做:**
- 20+ 模块协作 (datacollect → dataclean → sentiment → factor → ml → strategy → trading), 实盘环境下出了问题需要快速定位根因
- 当前使用基础 `logging`, 没有结构化字段, 无法按 strategy/factor/trade_id 过滤
- 数据采集的反爬/熔断/切源等事件缺乏持久化观测手段
- 因子衰减、模型漂移等 ML 问题需要长期趋势可视化
- 交易执行异常 (滑点偏大、订单被拒) 需要实时告警

```
┌─ Application ──────────────────────────────────────────────────────┐
│  qt-quant Python                                                   │
│  ┌──────────┐  ┌─────────────────┐  ┌─────────────────────┐       │
│  │structlog │  │prometheus_client│  │opentelemetry-sdk    │       │
│  │JSON→stdout│  │/metrics endpoint│  │OTLP gRPC exporter   │       │
│  └────┬─────┘  └───────┬─────────┘  └──────────┬──────────┘       │
└───────┼────────────────┼────────────────────────┼──────────────────┘
        │                │                        │
   ┌────▼─────┐    ┌─────▼──────┐          ┌──────▼──────┐
   │  Alloy   │    │ Prometheus │          │   Jaeger    │
   │Collector │    │  (scrape)  │          │  (OTLP v2)  │
   └────┬─────┘    └─────┬──────┘          └──────┬──────┘
        │                │                        │
   ┌────▼─────┐    ┌─────▼──────┐                 │
   │  Kafka   │    │Alertmanager│                 │
   └────┬─────┘    └─────┬──────┘                 │
        │                │                        │
   ┌────▼─────┐    ┌─────▼────────────┐           │
   │  Alloy   │    │PrometheusAlert   │           │
   │Consumer  │    │(飞书 Webhook)    │           │
   └────┬─────┘    └──────────────────┘           │
        │                                         │
   ┌────▼─────┐                                   │
   │   Loki   │◄──── trace_id 关联 ──────────────┘
   └────┬─────┘
        │
   ┌────▼─────┐
   │ Grafana  │  ← 统一看板: Loki + Prometheus + Jaeger
   └──────────┘
```

---

## 技术栈

| 类别 | 组件 | 版本 | 说明 |
|------|------|------|------|
| **Tracing** | Jaeger | v2.14+ (OTLP 原生) | 链路追踪存储 + UI |
| | opentelemetry-sdk | >=1.30 | Python 应用埋点 |
| | opentelemetry-exporter-otlp-proto-grpc | >=1.30 | OTLP gRPC 导出 |
| | opentelemetry-instrumentation-fastapi | >=0.51 | FastAPI 自动埋点 |
| | opentelemetry-instrumentation-sqlalchemy | >=0.51 | DB 查询自动埋点 |
| | opentelemetry-instrumentation-requests | >=0.51 | HTTP 请求自动埋点 |
| **Metrics** | Prometheus | latest | 指标存储 (TSDB, 30d retention) |
| | prometheus_client | >=0.21 | Python 指标暴露 |
| | Blackbox Exporter | latest | HTTP 探测 |
| | Node Exporter | latest | 主机指标 |
| | cAdvisor | v0.47+ | 容器指标 |
| **Logging** | Loki | 3.6+ | 日志聚合存储 |
| | Grafana Alloy | v1.12+ | 日志收集管线 (OTLP/Kafka) |
| | structlog | >=25.1 | Python 结构化日志 |
| **Dashboard** | Grafana | 12.4+ | 统一可视化 |
| **Alerting** | Alertmanager | latest | 告警路由 + 分组 + 静默 |
| | PrometheusAlert | latest | 飞书 Webhook 转发 |
| **消息队列** | Kafka | (复用现有) | Alloy 日志管线中间层 |

---

### P4-01: OpenTelemetry SDK 链路追踪埋点

| 属性 | 内容 |
|------|------|
| **模块** | common |
| **文件** | `src/common/tracing.py` (新增) |
| **工作量** | 2 天 |

**为什么要做:**
数据从采集到清洗到入库再到因子计算, 一条数据的完整生命周期跨越 5+ 模块。出问题时需要通过 `trace_id` 串联所有模块的处理日志, 一键定位瓶颈或故障点。

- Jaeger v2 使用 OTLP gRPC/HTTP 接收, 端口映射 `4317`(gRPC) / `4318`(HTTP)
- 采样策略由 `sampling-strategies.json` 控制, 测试环境 100% 采样

**埋点范围:**

| 模块 | Span 名称 | 关键属性 |
|------|----------|---------|
| datacollect | `collect.{source}.{data_type}` | source, data_type, stock_count, circuit_state |
| dataclean | `clean.{cleaner_type}` | cleaner, schema, llm_model, token_count |
| factor | `factor.calc.{factor_name}` | factor_name, stock_count, window |
| ml | `ml.train` / `ml.predict` | model_type, feature_count, sample_count |
| strategy | `strategy.{name}.signal` | strategy_name, signal_count, direction |
| trading | `trade.execute.{order_type}` | order_id, stock_code, quantity, price |
| sentiment | `sentiment.update` | csi_value, macro_state |

**落地方案:**
```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

def init_tracing(service_name: str = "qt-quant"):
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,  # e.g. "http://jaeger:4317"
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

tracer = trace.get_tracer("qt-quant")

# 使用示例
with tracer.start_as_current_span("collect.akshare.stock_daily",
        attributes={"source": "akshare", "data_type": "stock_daily", "stock_count": 5000}):
    result = collector.collect(task)
```

**自动埋点 (FastAPI + SQLAlchemy + requests):**
```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

FastAPIInstrumentor.instrument_app(app)
SQLAlchemyInstrumentor().instrument(engine=engine)
RequestsInstrumentor().instrument()
```

---

### P4-02: Prometheus 业务指标埋点

| 属性 | 内容 |
|------|------|
| **模块** | common / api |
| **文件** | `src/common/metrics.py` (新增), `src/api/routers/metrics_router.py` (新增) |
| **工作量** | 2 天 |

**为什么要做:**
Prometheus 指标是实时告警和长期趋势分析的基础。需要暴露业务指标 (采集成功率、因子 IC、模型漂移) 和系统指标 (API 延迟、DB 连接数), 供 Grafana 看板和 Alertmanager 规则使用。

- `game-agents` 通过自定义路径 `/api/v1/management/cache/metrics` 暴露指标
- Prometheus 15s 间隔 scrape, 应用级指标 10s 间隔

**指标清单:**

| 前缀 | 指标名 | 类型 | 说明 |
|------|--------|------|------|
| `qt_collect_` | `requests_total` | Counter | 采集请求总数 (labels: source, data_type, status) |
| | `latency_seconds` | Histogram | 采集请求延迟 (labels: source) |
| | `source_health_score` | Gauge | 数据源健康分 (labels: source) |
| | `circuit_breaker_state` | Gauge | 熔断器状态 0/1/2 (labels: source) |
| | `dead_letter_pending` | Gauge | 死信队列待处理数量 |
| | `data_freshness_lag_days` | Gauge | 数据新鲜度滞后天数 (labels: table_name) |
| `qt_factor_` | `ic_rolling_20d` | Gauge | 因子 20 日滚动 IC (labels: factor_name) |
| | `icir_rolling_20d` | Gauge | 因子 20 日滚动 ICIR (labels: factor_name) |
| | `active_count` | Gauge | 当前活跃因子数 |
| `qt_model_` | `prediction_ic` | Gauge | 模型预测 IC |
| | `drift_psi` | Gauge | 模型漂移 PSI (labels: feature_name) |
| | `retrain_total` | Counter | 重训练次数 |
| `qt_trade_` | `signals_total` | Counter | 信号生成数 (labels: strategy, direction) |
| | `orders_total` | Counter | 订单执行数 (labels: status) |
| | `pnl_daily` | Gauge | 日度 PnL |
| | `slippage_bps` | Histogram | 滑点 (bps) |
| `qt_sentiment_` | `composite_index` | Gauge | 综合情绪指数 |
| | `macro_state` | Gauge | 宏观状态编码 (0-5) |

**落地方案:**
```python
from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, generate_latest

REGISTRY = CollectorRegistry()

COLLECT_REQUESTS = Counter(
    "qt_collect_requests_total", "Total collection requests",
    ["source", "data_type", "status"], registry=REGISTRY,
)
COLLECT_LATENCY = Histogram(
    "qt_collect_latency_seconds", "Collection request latency",
    ["source"], buckets=[0.5, 1, 2, 5, 10, 30, 60], registry=REGISTRY,
)
SOURCE_HEALTH = Gauge(
    "qt_collect_source_health_score", "Data source health score 0-100",
    ["source"], registry=REGISTRY,
)
CIRCUIT_STATE = Gauge(
    "qt_collect_circuit_breaker_state", "0=closed, 1=half_open, 2=open",
    ["source"], registry=REGISTRY,
)
DATA_FRESHNESS = Gauge(
    "qt_collect_data_freshness_lag_days", "Data freshness lag in trading days",
    ["table_name"], registry=REGISTRY,
)
FACTOR_IC = Gauge(
    "qt_factor_ic_rolling_20d", "Factor rolling 20d IC",
    ["factor_name"], registry=REGISTRY,
)
MODEL_PSI = Gauge(
    "qt_model_drift_psi", "Model feature PSI",
    ["feature_name"], registry=REGISTRY,
)
TRADE_PNL = Gauge("qt_trade_pnl_daily", "Daily PnL", registry=REGISTRY)
```

**FastAPI 端点:**
```python
from fastapi import APIRouter, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

router = APIRouter()

@router.get("/metrics")
def metrics():
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
```

---

### P4-03: 结构化日志 → Loki 管线

| 属性 | 内容 |
|------|------|
| **模块** | common |
| **文件** | `src/common/logging_config.py` (改造) |
| **工作量** | 1.5 天 |

**为什么要做:**
当前使用基础 `logging`, 日志为纯文本, 无法在 Grafana 中按 module/strategy/stock_code 维度过滤查询。需要结构化 JSON 日志 + trace_id 关联, 实现日志 → 追踪的一键跳转。

- 日志管线: 应用 stdout JSON → Alloy Collector → Kafka (`game-agents-logs` topic) → Alloy Consumer → Loki
- Loki 标签: `job`, `node`, `level`, `log_type`, `service`, `log_file`, `environment`, `host`
- Grafana `Game Agents Logs.json` 看板通过 `trace_id_hex` 外链到 Jaeger UI

**落地方案:**
```python
import structlog
from opentelemetry import trace

def add_trace_id(logger, method_name, event_dict):
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        add_trace_id,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)

log = structlog.get_logger()

# 使用示例
log.info("collect_completed",
    source="akshare", data_type="stock_daily",
    stock_count=5000, duration_ms=12345,
    module="datacollect",
)
# → {"timestamp":"2026-04-12T10:30:00","level":"info","event":"collect_completed",
#     "source":"akshare","data_type":"stock_daily","stock_count":5000,
#     "duration_ms":12345,"module":"datacollect","trace_id":"abc123...","span_id":"def456..."}
```

**Alloy Collector 配置 (qt-quant 版本):**
```river
// 收集 qt-quant 容器/进程的 JSON stdout 日志
local.file_match "qt_logs" {
  path_targets = [{"__path__" = "/var/log/qt-quant/*.log"}]
}
loki.source.file "qt_logs" {
  targets    = local.file_match.qt_logs.targets
  forward_to = [loki.write.default.receiver]
}
loki.write "default" {
  endpoint {
    url = "http://loki:3107/loki/api/v1/push"
  }
}
```

**Loki 标签映射 (与 Grafana 看板联动):**

| 标签 | 来源 | 用途 |
|------|------|------|
| `job` | "qt-quant" | 服务筛选 |
| `level` | structlog `level` 字段 | 日志级别过滤 |
| `module` | structlog `module` 字段 | datacollect/factor/ml/trading |
| `service` | "qt-quant" | 多服务区分 |
| `trace_id` | OpenTelemetry trace_id | 日志↔追踪关联 |

---

### P4-04: Grafana 看板

| 属性 | 内容 |
|------|------|
| **模块** | ops (基础设施) |
| **文件** | `ops/grafana/dashboards/` (新增目录) |
| **工作量** | 3 天 |

**为什么要做:**
Grafana 看板是整个可观测性体系的用户界面。运维和交易人员需要通过看板实时了解系统状态, 快速发现和定位问题。

- Grafana 12.4.2, PostgreSQL 元数据库
- Provisioning 自动导入数据源和看板
- `Game Agents Logs.json` 看板: Loki 数据源 + Jaeger 外链

**看板清单:**

#### Dashboard 1: 数据采集健康 (`qt-datacollect-health.json`)

| Panel | 数据源 | 可视化 | PromQL / LogQL |
|-------|--------|--------|----------------|
| 数据源健康矩阵 | Prometheus | Stat + 颜色映射 | `qt_collect_source_health_score` |
| 熔断器状态 | Prometheus | State Timeline | `qt_collect_circuit_breaker_state` |
| 采集请求速率 | Prometheus | Time Series | `rate(qt_collect_requests_total[5m])` |
| 采集延迟热力图 | Prometheus | Heatmap | `qt_collect_latency_seconds_bucket` |
| 数据新鲜度 | Prometheus | Table | `qt_collect_data_freshness_lag_days` |
| 死信队列深度 | Prometheus | Gauge | `qt_collect_dead_letter_pending` |
| 采集日志流 | Loki | Logs | `{job="qt-quant", module="datacollect"}` |

#### Dashboard 2: 因子 & 模型性能 (`qt-factor-model.json`)

| Panel | 数据源 | 可视化 | PromQL |
|-------|--------|--------|--------|
| 因子 IC 趋势 (Top 10) | Prometheus | Time Series | `topk(10, qt_factor_ic_rolling_20d)` |
| 因子 ICIR 排名 | Prometheus | Bar Gauge | `qt_factor_icir_rolling_20d` |
| 活跃因子数 | Prometheus | Stat | `qt_factor_active_count` |
| 模型预测 IC | Prometheus | Time Series | `qt_model_prediction_ic` |
| 模型漂移 PSI | Prometheus | Time Series | `qt_model_drift_psi` |
| 重训练时间线 | Prometheus | Annotations | `increase(qt_model_retrain_total[1d])` |

#### Dashboard 3: 交易执行 (`qt-trading.json`)

| Panel | 数据源 | 可视化 | PromQL |
|-------|--------|--------|--------|
| 日度 PnL 曲线 | Prometheus | Time Series | `qt_trade_pnl_daily` |
| 信号生成统计 | Prometheus | Pie Chart | `qt_trade_signals_total` by strategy |
| 订单执行状态 | Prometheus | Bar Chart | `qt_trade_orders_total` by status |
| 滑点分布 | Prometheus | Histogram | `qt_trade_slippage_bps_bucket` |
| 情绪指数 | Prometheus | Gauge + Threshold | `qt_sentiment_composite_index` |
| 宏观状态 | Prometheus | Stat + Value Mapping | `qt_sentiment_macro_state` |

#### Dashboard 4: 系统健康 (`qt-system-health.json`)

| Panel | 数据源 | 可视化 | 说明 |
|-------|--------|--------|------|
| CPU / 内存 / 磁盘 | Prometheus | Time Series | Node Exporter 指标 |
| 容器资源 | Prometheus | Table | cAdvisor 指标 |
| API 延迟 (P50/P95/P99) | Prometheus | Time Series | FastAPI 请求延迟 |
| DB 连接池 | Prometheus | Gauge | SQLAlchemy pool 指标 |
| HTTP 探测 | Prometheus | Stat | Blackbox Exporter 探活 |

**Grafana Provisioning:**
```yaml
# ops/grafana/provisioning/datasources/datasources.yml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    isDefault: true
  - name: Loki
    type: loki
    url: http://loki:3107
  - name: Jaeger
    type: jaeger
    url: http://jaeger:16686
```

---

### P4-05: 告警管线

| 属性 | 内容 |
|------|------|
| **模块** | ops (基础设施) |
| **文件** | `ops/prometheus/rules/qt_rules.yml`, `ops/prometheus/alertmanager/alertmanager.yml` |
| **工作量** | 1.5 天 |

**为什么要做:**
量化系统的异常需要分钟级感知, 不能等人工发现。数据源被封、因子失效、订单被拒等事件需要立即推送到飞书, 避免错过交易窗口或产生资金损失。

- Alertmanager: `group_wait: 10s`, `group_interval: 3m`, `repeat_interval: 1h`
- 接收器: Webhook → PrometheusAlert → 飞书
- 规则格式: `host_rules.yml` 覆盖 CPU/内存/磁盘/容器/Blackbox

**告警规则:**

```yaml
# ops/prometheus/rules/qt_rules.yml
groups:
  - name: qt-datacollect
    rules:
    - alert: DataSourceUnhealthy
      expr: qt_collect_source_health_score < 30
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "数据源 {{ $labels.source }} 健康分过低"
        description: "健康分 {{ $value }}, 可能遭遇反爬或源不可用"

    - alert: CircuitBreakerOpen
      expr: qt_collect_circuit_breaker_state == 2
      for: 10m
      labels:
        severity: critical
      annotations:
        summary: "数据源 {{ $labels.source }} 熔断超过 10 分钟"
        description: "熔断器持续 OPEN 状态, 该源的所有采集任务已停止"

    - alert: DataFreshnessLag
      expr: qt_collect_data_freshness_lag_days > 2
      for: 30m
      labels:
        severity: warning
      annotations:
        summary: "表 {{ $labels.table_name }} 数据滞后 {{ $value }} 个交易日"

    - alert: DeadLetterQueueGrowing
      expr: qt_collect_dead_letter_pending > 100
      for: 15m
      labels:
        severity: warning
      annotations:
        summary: "死信队列堆积 {{ $value }} 条待处理任务"

  - name: qt-factor-model
    rules:
    - alert: FactorDecay
      expr: qt_factor_ic_rolling_20d < 0.01
      for: 5d
      labels:
        severity: warning
      annotations:
        summary: "因子 {{ $labels.factor_name }} IC 连续 5 天低于 0.01"
        description: "因子可能已失效, 建议降权或剔除"

    - alert: ModelDrift
      expr: qt_model_drift_psi > 0.2
      for: 1h
      labels:
        severity: warning
      annotations:
        summary: "模型特征 {{ $labels.feature_name }} PSI > 0.2"
        description: "特征分布发生显著漂移, 建议触发重训练"

  - name: qt-trading
    rules:
    - alert: DailyLossExceeded
      expr: qt_trade_pnl_daily < -0.02
      for: 0m
      labels:
        severity: critical
      annotations:
        summary: "日度亏损超过 2%"
        description: "当前日度 PnL: {{ $value }}, 考虑紧急止损"

    - alert: OrderRejectionHigh
      expr: rate(qt_trade_orders_total{status="rejected"}[1h]) / rate(qt_trade_orders_total[1h]) > 0.10
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "订单拒绝率超过 10%"
        description: "可能 QMT 连接异常或资金不足"

  - name: qt-infra
    rules:
    - alert: HighDiskUsage
      expr: (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes) < 0.15
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "磁盘空间不足 15%"

    - alert: HighMemoryUsage
      expr: (node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes > 0.90
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "内存使用率超过 90%"

    - alert: APILatencyHigh
      expr: histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m])) > 5
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "API P99 延迟超过 5 秒"
```

**Alertmanager 配置:**
```yaml
# ops/prometheus/alertmanager/alertmanager.yml
global:
  resolve_timeout: 1m

route:
  group_by: ['alertname']
  group_wait: 10s
  group_interval: 3m
  repeat_interval: 1h
  receiver: 'feishu-webhook'
  routes:
    - match:
        severity: critical
      receiver: 'feishu-webhook'
      repeat_interval: 15m

receivers:
  - name: feishu-webhook
    webhook_configs:
      - url: http://prometheus-alert-center:8080/prometheus/alert
```

---

### P4-06: 基础设施部署 (Docker Compose)

| 属性 | 内容 |
|------|------|
| **模块** | ops (基础设施) |
| **文件** | `ops/docker-compose.yml`, `ops/.env`, 以及 `ops/` 下各组件配置 |
| **工作量** | 1.5 天 |

**为什么要做:**
一键部署完整的可观测性栈, 开发和生产环境一致。Docker Compose 模式, 减少运维成本。

**目录结构:**
```
ops/
├── docker-compose.yml
├── .env
├── alloy/
│   └── alloy-consumer.river
├── loki/
│   └── loki-config.yml
├── jaeger/
│   └── sampling-strategies.json
├── prometheus/
│   ├── config/
│   │   ├── prometheus.yml
│   │   ├── rules/
│   │   │   ├── qt_rules.yml
│   │   │   └── host_rules.yml
│   │   └── targets/
│   │       └── nodes.yml
│   └── alertmanager/
│       └── config/
│           └── alertmanager.yml
├── prometheus-alert-center/
│   └── config/
│       └── app.conf
└── grafana/
    ├── provisioning/
    │   ├── datasources/
    │   │   └── datasources.yml
    │   └── dashboards/
    │       └── dashboards.yml
    └── dashboards/
        ├── qt-datacollect-health.json
        ├── qt-factor-model.json
        ├── qt-trading.json
        └── qt-system-health.json
```

**Docker Compose (核心服务):**

| 服务 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| `loki` | `grafana/loki:3.6.4` | 3107 | 日志存储 |
| `jaeger` | `jaegertracing/jaeger:2.14.1` | 16686(UI), 4317(gRPC), 4318(HTTP) | 链路追踪 |
| `prometheus` | `prom/prometheus:latest` | 9090 | 指标存储 (30d retention) |
| `grafana` | `grafana/grafana:12.4.2` | 3000 | 统一看板 |
| `alertmanager` | `quay.io/prometheus/alertmanager` | 9093 | 告警路由 |
| `prometheus-alert-center` | `feiyu563/prometheus-alert:latest` | 8080 | 飞书转发 |
| `blackbox_exporter` | `quay.io/prometheus/blackbox-exporter` | 9115 | HTTP 探测 |
| `node_exporter` | `quay.io/prometheus/node-exporter` | 9100 | 主机指标 |
| `cadvisor` | `zhangnew/cadvisor:v0.47.2` | 8080 | 容器指标 |
| `alloy-consumer` | `grafana/alloy:v1.12.2` | 12345 | 日志管线 (可选, 需 Kafka) |

---

### P4-07: `collect_metrics` 持久化表 + 应用级 ORM

| 属性 | 内容 |
|------|------|
| **模块** | datacollect / common |
| **文件** | `src/datacollect/models.py` (扩展), `src/common/metrics.py` (扩展) |
| **工作量** | 0.5 天 |

**为什么要做:**
Prometheus 默认 30 天 retention, 超过 30 天的指标数据会被清理。对于因子 IC 趋势、模型漂移历史等长期分析需求, 需要将关键指标持久化到 PostgreSQL, 支持 SQL 查询和长期回溯。

**ORM 模型:**
```python
class CollectMetrics(Base):
    """采集指标持久化 (补充 Prometheus 30d retention)"""
    __tablename__ = "collect_metrics"

    id = Column(Integer, primary_key=True)
    trace_id = Column(String(32), index=True)
    source = Column(String(50), nullable=False)
    data_type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)  # success / failed / timeout / blocked
    latency_ms = Column(Integer)
    response_size_bytes = Column(Integer)
    circuit_state = Column(String(20))
    health_score = Column(Float)
    error_type = Column(String(50))
    error_msg = Column(Text)
    metadata = Column(JSONB)
    created_at = Column(DateTime, default=func.now(), index=True)

# BRIN 索引 (时序数据最优)
Index("ix_collect_metrics_created_brin", CollectMetrics.created_at, postgresql_using="brin")
```

**`CollectResult` 扩展:**
```python
@dataclass
class CollectResult:
    source: str
    raw_text: str
    url: str | None
    collected_at: datetime
    metadata: dict
    trace_id: str | None = None    # OpenTelemetry trace_id
    latency_ms: int | None = None  # 请求耗时
```

**历史查询示例:**
```sql
-- 过去 90 天各数据源的成功率趋势
SELECT source,
       date_trunc('day', created_at) AS day,
       COUNT(*) FILTER (WHERE status = 'success') * 100.0 / COUNT(*) AS success_rate
FROM collect_metrics
WHERE created_at > NOW() - INTERVAL '90 days'
GROUP BY source, day
ORDER BY day;
```

---

## `.env` 新增参数

```bash
# ===== 可观测性 (P4) =====
# OpenTelemetry
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317   # Jaeger OTLP gRPC
OTEL_SERVICE_NAME=qt-quant
OTEL_SAMPLING_RATE=1.0                               # 1.0=全量采样 (生产可降至 0.1)

# Prometheus
PROMETHEUS_METRICS_ENABLED=true
PROMETHEUS_METRICS_PATH=/metrics

# Structlog
LOG_FORMAT=json                                      # json / console (开发用 console)
LOG_LEVEL=INFO

# Grafana
GRAFANA_PORT=3000
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=admin

# Alerting
FEISHU_WEBHOOK_URL=                                  # 飞书自定义机器人 Webhook
FEISHU_WEBHOOK_SECRET=                               # 飞书签名密钥
ALERT_ENABLED=true
```

---

## Python 依赖

```
# pyproject.toml [project.optional-dependencies] observability
opentelemetry-sdk>=1.30
opentelemetry-exporter-otlp-proto-grpc>=1.30
opentelemetry-instrumentation-fastapi>=0.51b0
opentelemetry-instrumentation-sqlalchemy>=0.51b0
opentelemetry-instrumentation-requests>=0.51b0
prometheus-client>=0.21
structlog>=25.1
```

---

## 实施步骤

| 阶段 | 任务 | 工作量 | 前置 |
|------|------|--------|------|
| Phase 1 | P4-03 结构化日志 (structlog) | 1.5 天 | 无 (可独立先行) |
| Phase 1 | P4-07 collect_metrics ORM | 0.5 天 | 无 |
| Phase 2 | P4-01 OpenTelemetry 埋点 | 2 天 | P4-03 (trace_id 关联) |
| Phase 2 | P4-02 Prometheus 指标 | 2 天 | 无 |
| Phase 3 | P4-06 Docker Compose 部署 | 1.5 天 | P4-01/02/03 |
| Phase 3 | P4-04 Grafana 看板 | 3 天 | P4-06 |
| Phase 3 | P4-05 告警规则 | 1.5 天 | P4-06 |

---

## 与现有 TODO 的关系

| 原 TODO | 处置 |
|---------|------|
| P1-26: 可观测性 (structlog + 飞书告警) | 已吸收至 P4-03 (structlog) + P4-05 (告警). P1-26 标记为 "→ 已合并至 P4" |
| 架构 review 待办: CollectResult trace_id/latency_ms + collect_metrics 表 | 已纳入 P4-07 |
