"""合成 ML 记录与情绪数据工厂

Tables: ml_model_log, ml_prediction, data_sync_log,
        sentiment_daily, sentiment_ingest_log
"""
import json
from datetime import date, datetime, timedelta
from typing import List

import numpy as np

from src.data.models import MLModelLog, MLPrediction, DataSyncLog

SEED = 42


def create_ml_model_logs(session) -> List[MLModelLog]:
    logs = [
        MLModelLog(
            model_name="lgb_v1",
            train_start=date(2024, 2, 1),
            train_end=date(2024, 8, 31),
            n_features=5,
            n_samples=58000,
            ic_mean=0.052,
            icir=0.73,
            mse=0.0012,
            model_path="models/lgb_v1.pkl",
            params_json=json.dumps({"n_estimators": 500, "learning_rate": 0.05}),
            created_at=datetime(2024, 9, 1, 10, 0),
        ),
        MLModelLog(
            model_name="lgb_v2",
            train_start=date(2024, 2, 1),
            train_end=date(2024, 9, 30),
            n_features=5,
            n_samples=62000,
            ic_mean=0.058,
            icir=0.81,
            mse=0.0010,
            model_path="models/lgb_v2.pkl",
            params_json=json.dumps({"n_estimators": 800, "learning_rate": 0.03}),
            created_at=datetime(2024, 10, 1, 10, 0),
        ),
    ]
    session.add_all(logs)
    session.flush()
    return logs


def create_ml_predictions(session, model_logs: List[MLModelLog]) -> List[MLPrediction]:
    rng = np.random.RandomState(SEED + 60)
    predictions = []
    model = model_logs[-1]

    for i in range(1, 51):
        code = f"{i:06d}.SZ"
        pred_ret = float(rng.normal(0.003 if i <= 10 else -0.001, 0.01))
        signal = "buy" if pred_ret > 0.005 else ("sell" if pred_ret < -0.005 else "hold")

        predictions.append(MLPrediction(
            model_id=model.id,
            trade_date=date(2024, 11, 1),
            code=code,
            predicted_return=round(pred_ret, 6),
            rank_score=i,
            signal=signal,
        ))

    session.bulk_save_objects(predictions)
    session.flush()
    return predictions


def create_data_sync_logs(session) -> List[DataSyncLog]:
    logs = [
        DataSyncLog(
            sync_type="stock_list",
            start_time=datetime(2024, 6, 1, 8, 0),
            end_time=datetime(2024, 6, 1, 8, 2),
            status="success",
            records_count=50,
            message="同步50只股票基础信息",
        ),
        DataSyncLog(
            sync_type="daily_kline",
            start_time=datetime(2024, 6, 1, 8, 5),
            end_time=datetime(2024, 6, 1, 8, 35),
            status="success",
            records_count=12600,
            message="同步50只股票252个交易日日线",
        ),
        DataSyncLog(
            sync_type="financial_report",
            start_time=datetime(2024, 6, 1, 8, 40),
            end_time=datetime(2024, 6, 1, 8, 55),
            status="success",
            records_count=200,
            message="同步50只股票4期财报",
        ),
        DataSyncLog(
            sync_type="daily_kline",
            start_time=datetime(2024, 6, 2, 8, 5),
            end_time=None,
            status="failed",
            records_count=0,
            message="网络超时",
        ),
    ]
    session.add_all(logs)
    session.flush()
    return logs


def create_sentiment_daily(session) -> list:
    """情绪数据: 20 个交易日的合成情绪指标"""
    from src.sentiment.models import SentimentDaily

    rng = np.random.RandomState(SEED + 70)
    rows = []
    d = date(2024, 6, 3)
    end = date(2024, 6, 28)

    while d <= end:
        if d.weekday() < 5:
            composite = float(rng.uniform(-0.5, 0.8))
            state = "bull" if composite > 0.3 else ("bear" if composite < -0.2 else "shock")

            rows.append(SentimentDaily(
                trade_date=d,
                ad_ratio=round(float(rng.uniform(0.4, 2.0)), 2),
                limit_up_count=int(rng.uniform(20, 120)),
                limit_down_count=int(rng.uniform(5, 60)),
                burst_rate=round(float(rng.uniform(0.1, 0.6)), 3),
                new_high_60d=int(rng.uniform(50, 300)),
                new_low_60d=int(rng.uniform(10, 150)),
                market_volatility_5d=round(float(rng.uniform(0.005, 0.03)), 4),
                market_volatility_20d=round(float(rng.uniform(0.008, 0.025)), 4),
                volume_ratio=round(float(rng.uniform(0.6, 1.5)), 2),
                sector_concentration=round(float(rng.uniform(0.1, 0.5)), 3),
                north_net_flow=round(float(rng.uniform(-100, 150)), 2),
                margin_balance=round(float(rng.uniform(15000, 18000)), 2),
                earning_effect=round(float(rng.uniform(-0.5, 0.8)), 3),
                capital_mood=round(float(rng.uniform(-0.4, 0.6)), 3),
                volatility_mood=round(float(rng.uniform(-0.6, 0.4)), 3),
                sector_heat=round(float(rng.uniform(-0.3, 0.7)), 3),
                news_mood=round(float(rng.uniform(-0.5, 0.5)), 3),
                global_mood=round(float(rng.uniform(-0.4, 0.5)), 3),
                composite_sentiment=round(composite, 3),
                suggested_state=state,
                applied_state=state,
                state_confidence=round(float(rng.uniform(0.5, 0.95)), 3),
                hot_sectors=["电子", "新能源"] if composite > 0 else ["银行", "医药"],
                key_events=[{"event": "测试事件", "impact": "positive" if composite > 0 else "negative"}],
            ))
        d += timedelta(days=1)

    session.add_all(rows)
    session.flush()
    return rows


def create_sentiment_ingest_logs(session) -> list:
    from src.sentiment.models import SentimentIngestLog

    logs = [
        SentimentIngestLog(
            trade_date=date(2024, 6, 3),
            source_name="price_volume",
            schedule_slot="09:30",
            status="success",
            llm_provider=None,
            llm_model=None,
            collected_at=datetime(2024, 6, 3, 9, 30),
        ),
        SentimentIngestLog(
            trade_date=date(2024, 6, 3),
            source_name="news_sentiment",
            schedule_slot="12:00",
            status="success",
            llm_provider="dashscope",
            llm_model="qwen-plus",
            llm_tokens_in=2500,
            llm_tokens_out=350,
            llm_cost_cny=0.012,
            raw_data={"headlines": ["测试新闻A", "测试新闻B"]},
            cleaned_data={"score": 0.65, "summary": "市场情绪积极"},
            collected_at=datetime(2024, 6, 3, 12, 5),
        ),
        SentimentIngestLog(
            trade_date=date(2024, 6, 4),
            source_name="news_sentiment",
            schedule_slot="12:00",
            status="failed",
            error_message="API 超时",
            llm_provider="dashscope",
            llm_model="qwen-plus",
            collected_at=datetime(2024, 6, 4, 12, 5),
        ),
    ]
    session.add_all(logs)
    session.flush()
    return logs
