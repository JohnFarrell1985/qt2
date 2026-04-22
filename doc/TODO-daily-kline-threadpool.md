# 待办：日K 多线程补全 + 分线程「请求源」策略（多标的）

> 状态：**未开始**（设计已定，择期实现）  
> 最后更新：2026-04-21  
> 关联设计：Cursor 计划「多线程 + 分线程反爬」；与 [12-数据采集模块](12-数据采集模块.md) 中 datacollect / K 线多源逻辑一致。  
> 范围：**A 股、ETF、指数** 等日 K 拉取与批量工具（`kline_bulk_sync`）共用底层腾讯/东财通道的，本清单一并适用；首版实现可从 ETF `sync_etf_daily` 切入，再平移到其它入口。

## 1. 背景

- 日 K 补全若按「单线程序列 / 每标的单路 I/O」跑，全市场或大批量时吞吐受单路限制。  
- 全链路改为「纯 asyncio + 原生 async HTTP/DB」成本高；**优先路径**为 **`ThreadPoolExecutor` 按「标的 `code`」分任务**，与现有 `requests` / `SmartHttpClient` / 同步 ORM 对齐。  
- 多线程并发时，**模块级共享的** `requests.Session`（[kline_bulk_sync](../src/data/kline_bulk_sync.py) 腾讯 `_qq_session`；**A 股/ETF/指数腾讯支路共用**）在并发下会竞态，须改为 **threading.local** 或等效。  
- 「反爬 / 分线程不同请求源」在工程上指：**不同 TLS 指纹**（`curl_cffi` `impersonate`）、**UA/连接/Session 隔离**、**可选多代理分出口**；**不能**在单机无代理时伪造多个公网 IP。

## 2. 目标

- 可配置**日 K 补全**并发度（默认 `1` 与现行为一致）；**配置项名** 首落可延续 `DATACOLLECT_ETF_DAILY_CONCURRENCY`（仅 ETF 一条链），若与 A10 / `kline_bulk` 统一，可再收敛为更中性名如 `DATACOLLECT_DAILY_KLINE_CONCURRENCY`（实现时定稿）。  
- **同一只标的** 内按段顺序拉取、写库，不交叉乱序。  
- 多源主源/探针在并行下用 **per-code 粘性**（如 `resolved_by_code[code]`），避免「全局 work 下标 `wi`」在并行中语义错误。  
- 全局限流/按域限流与现有 TokenBucket 协调，避免 N 路显著放大 429。  
- baostock 等**非线程安全**长连接：每线程 `login` **或** 全局互斥。  
- **分 worker 请求伪装**（多 `impersonate`、可选代理池分出口）在需要「多路看起来像不同 client」的入口**一致化**（ETF 补全、`kline_bulk` 高并发、将来 A10 如改为线程池等）。

## 3. 实现清单（建议顺序）

| 序号 | 项 | 说明 |
|------|----|------|
| 1 | 配置 | `src/common/config.py` 的 `DatacollectConfig`：并发度 + env；名称见 §2。 |
| 2 | 按 code 分桶 + 主源 | **首刀**：`akshare_financial_sync.sync_etf_daily`；待办段按 `code` 聚合；`resolved_by_code[code]`。 |
| 3 | 腾讯 K 线 Session | `kline_bulk_sync`：`_get_qq_session` → `threading.local()`；`reset_qq_session` 复查；与 **stock/etf/index** 及 `--concurrency>1` 的批量下载一致受益。 |
| 4 | 线程池入口 | `sync_etf_daily`：`ThreadPoolExecutor` + 锁保护共享计数/进度/stall 等。 |
| 5 | 分 worker 请求伪装 | `SmartHttpClient` 每 worker 实例；`impersonate` 池；`DATACOLLECT_PROXY_URLS` 按 worker 绑定。 |
| 6 | baostock / 共享 collector | 每线程 `login` 或全局锁；审计 AkShare 等模块级全局。 |
| 7 | 验收 | `concurrency=1` 对齐历史；`N>1` 下断点、ON CONFLICT、进度、stall 正确。 |
| 8 | **其它入口（后继）** | 见下节「现状对照」：`akshare_sync` A10 串行、全市场吞吐；`kline_bulk_sync` 已 `async`+`run_in_executor` 与腾讯 Session 问题绑定。 |
| 9 | （可选）asyncio 薄壳 | 与全站 asyncio 统一时再用 `run_in_executor`，**非首路径**。 |

## 4. 主要涉及路径

- `src/data/akshare_financial_sync.py` — `sync_etf_daily`（多线程首落地）。  
- `src/data/akshare_sync.py` — `sync_daily_incremental`（A10 日线增量，当前串行、不走腾讯 `_qq_session`；吞吐见 §5）。  
- `src/data/kline_bulk_sync.py` — `run` / `_async_download`、`_fetch_stock_daily` / `_fetch_etf_daily` / 指数、`_qq_*`、东财 `SmartHttpClient`、限流。  
- `src/datacollect/client.py` — `SmartHttpClient`。  
- `src/common/config.py` — `DatacollectConfig` 与 env。  
- `src/data/market_data.py` — QMT 日线下载，与上述 HTTP Session **无关**（另一问题域）。

## 5. 不同入口的现状对照（与「同样问题」是否同类）

| 入口 | 行为概要 | 与「全局 `_qq_session` + 并发」 | 与「提吞吐/多路并行」 |
|------|----------|--------------------------------|------------------------|
| [`akshare_sync.sync_daily_incremental`](../src/data/akshare_sync.py)（A10） | 全市场、批内 `for code` 串行，数据来自 `ak.stock_zh_a_hist` + limiter | **不经过** `kline_bulk` 的 `_qq_session`，**无** 该类共享 Session 竞态 | **有** 串行瓶颈，与「单线程日 K 补全」同类；要并行需在本模块单独加线程池/队列，**不能**只改 ETF 文件 |
| [`kline_bulk_sync`](../src/data/kline_bulk_sync.py) `stock` / `etf` / `index` / `all` | `asyncio` + `run_in_executor` + `concurrency`；腾讯/东财多源 | **`--concurrency>1` 且走腾讯** 时，与文档中 Session 问题 **同类**（多线程共单例 `requests.Session`） | 已多路并发，修 Session + 限流后更稳；东财走 `SmartHttpClient`（curl **threading.local**），与腾讯支路不是同一类 bug |
| [`akshare_financial_sync.sync_etf_daily`](../src/data/akshare_financial_sync.py) | 本 TODO 多线程**首**改造对象 | 若并发 + `kline` 腾讯支路，**须** 修 `_qq_session` | 目标即提 ETF 日 K 并发 |

**结论简述**：  
- **腾讯 Session 竞态**：集中在 **`kline_bulk_sync` 的腾讯支路**（各标的 + 高并发 CLI）；A10 默认路径**不在此列**。  
- **串行性能**：A10 与改前的 ETF 长链类似，是**另一维度**的「要并行化」；实现位置分散，本清单以 **K 线模块 + ETF 日 K 补全** 为优先，A10 列作后继。  

## 6. 风险与约束

- 对端频控/风控与并发度正相关，**提高 N 不保证线性加速**。  
- 仅使用项目内已有配置与正当 HTTP 行为；代理与指纹用于**工程隔离与降误伤**，不用于违反数据源服务条款的用途。
