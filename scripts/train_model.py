"""模型训练入口脚本"""
import sys
sys.path.insert(0, ".")

from datetime import date
from src.common.logger import get_logger
from src.ml.dataset import FactorDataset
from src.ml.lgb_model import LGBFactorModel
from src.ml.feature_selection import FactorSelector

logger = get_logger(__name__)


def main():
    factor_names = [
        "total_assets", "net_profit", "roe", "eps", "bps",
        "revenue_growth_yoy", "profit_growth_yoy",
        "gross_margin", "net_margin", "market_cap",
    ]
    stock_pool = []

    from src.data.qmt_client import QMTClient
    try:
        client = QMTClient()
        codes = client.get_stock_list_in_sector("沪深A股")
        stock_pool = [c.split(".")[0] for c in codes[:500]]
    except Exception:
        logger.warning("QMT未连接, 使用空股票池")
        return

    logger.info(f"训练股票池: {len(stock_pool)} 只")

    ds = FactorDataset()
    X, y = ds.build(
        factor_names=factor_names,
        stock_pool=stock_pool,
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        label_period=5,
    )

    if X.empty:
        logger.error("数据集为空，请先同步数据")
        return

    split = ds.train_val_test_split()

    model = LGBFactorModel()
    metrics = model.train(
        split["X_train"], split["y_train"],
        split["X_val"], split["y_val"],
    )
    logger.info(f"训练结果: {metrics}")

    importance = model.get_feature_importance(20)
    logger.info(f"因子重要性Top20:\n{importance}")

    model.save("models/lgb_latest.pkl")
    logger.info("模型已保存")


if __name__ == "__main__":
    main()
