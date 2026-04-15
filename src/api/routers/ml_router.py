"""ML训练/预测API"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.common.logger import get_logger

router = APIRouter(prefix="/api/ml", tags=["机器学习"])
logger = get_logger(__name__)


class TrainRequest(BaseModel):
    factor_names: List[str]
    stock_pool: List[str]
    start_date: str
    end_date: str
    label_period: int = 5
    params: Optional[dict] = None


class PredictRequest(BaseModel):
    model_path: str
    factor_names: List[str]
    stock_pool: List[str]
    trade_date: str
    top_n: int = 10


@router.post("/train")
def train_model(req: TrainRequest):
    """训练LightGBM模型"""
    from src.ml.dataset import FactorDataset
    from src.ml.lgb_model import LGBFactorModel

    try:
        ds = FactorDataset()
        X, y = ds.build(
            factor_names=req.factor_names,
            stock_pool=req.stock_pool,
            start_date=datetime.strptime(req.start_date, "%Y-%m-%d").date(),
            end_date=datetime.strptime(req.end_date, "%Y-%m-%d").date(),
            label_period=req.label_period,
        )
        if X.empty:
            raise HTTPException(status_code=400, detail="数据集为空")

        split = ds.train_val_test_split()
        model = LGBFactorModel(params=req.params)
        metrics = model.train(
            split["X_train"], split["y_train"],
            split["X_val"], split["y_val"],
        )

        model_path = f"models/lgb_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pkl"
        model.save(model_path)

        return {
            "status": "success",
            "model_path": model_path,
            "metrics": metrics,
            "feature_importance": model.get_feature_importance(20).to_dict(),
        }
    except Exception as e:
        logger.error(f"训练失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/predict")
def predict(req: PredictRequest):
    """使用已训练模型预测"""
    from src.ml.lgb_model import LGBFactorModel
    from src.ml.strategy_builder import StrategyBuilder
    from src.data.factor_data import FactorDataManager

    try:
        model = LGBFactorModel()
        model.load(req.model_path)

        mgr = FactorDataManager()
        trade_date = datetime.strptime(req.trade_date, "%Y-%m-%d").date()
        factor_df = mgr.get_factor_values(
            req.factor_names, req.stock_pool, trade_date, trade_date
        )
        if factor_df.empty:
            raise HTTPException(status_code=400, detail="无因子数据")

        builder = StrategyBuilder(model, top_n=req.top_n)
        signals = builder.generate_signals(factor_df, trade_date)
        return {"trade_date": req.trade_date, "signals": signals}
    except Exception as e:
        logger.error(f"预测失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
