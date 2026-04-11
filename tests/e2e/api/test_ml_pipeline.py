"""E2E-03: ML 训练→预测全链路

被测路径: POST /api/ml/train → FactorDataset → LGBFactorModel → save
         POST /api/ml/predict → load → signals

5 个测试用例: 模型训练、模型预测、训练→预测链、空数据集、模型路径不存在
"""
import os
import shutil

import pytest


class TestMLTraining:
    """ML 训练 E2E (TC-03-01)"""

    def test_model_train(self, client, seeded_db):
        """TC-03-01: 模型训练 — 5 因子 × 50 股票 → 返回 metrics + model_path"""
        all_codes = [f"{i:06d}.SZ" for i in range(1, 51)]

        resp = client.post("/api/ml/train", json={
            "factor_names": ["mom_20", "vol_20", "rsi_14",
                             "turnover_avg_20", "amplitude_20"],
            "stock_pool": all_codes,
            "start_date": "2024-02-01",
            "end_date": "2024-10-31",
            "label_period": 5,
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "model_path" in data
        assert "metrics" in data
        assert "feature_importance" in data

        model_path = data["model_path"]
        if os.path.exists(model_path):
            os.remove(model_path)


class TestMLPredict:
    """ML 预测 E2E (TC-03-02 ~ TC-03-03)"""

    @pytest.fixture
    def trained_model_path(self, client, seeded_db):
        """预训练模型 fixture"""
        all_codes = [f"{i:06d}.SZ" for i in range(1, 51)]
        resp = client.post("/api/ml/train", json={
            "factor_names": ["mom_20", "vol_20", "rsi_14",
                             "turnover_avg_20", "amplitude_20"],
            "stock_pool": all_codes,
            "start_date": "2024-02-01",
            "end_date": "2024-10-31",
            "label_period": 5,
        })
        assert resp.status_code == 200
        path = resp.json()["model_path"]
        yield path
        if os.path.exists(path):
            os.remove(path)

    def test_model_predict(self, client, seeded_db, trained_model_path):
        """TC-03-02: 模型预测 — 使用训练好的模型返回 signals"""
        all_codes = [f"{i:06d}.SZ" for i in range(1, 51)]
        resp = client.post("/api/ml/predict", json={
            "model_path": trained_model_path,
            "factor_names": ["mom_20", "vol_20", "rsi_14",
                             "turnover_avg_20", "amplitude_20"],
            "stock_pool": all_codes,
            "trade_date": "2024-11-01",
            "top_n": 10,
        })

        assert resp.status_code == 200
        data = resp.json()
        assert "signals" in data
        assert data["trade_date"] == "2024-11-01"

    def test_train_then_predict_chain(self, client, seeded_db, trained_model_path):
        """TC-03-03: 训练→预测链 — 同一流程内先 train 再 predict"""
        all_codes = [f"{i:06d}.SZ" for i in range(1, 51)]
        resp = client.post("/api/ml/predict", json={
            "model_path": trained_model_path,
            "factor_names": ["mom_20", "vol_20", "rsi_14",
                             "turnover_avg_20", "amplitude_20"],
            "stock_pool": all_codes,
            "trade_date": "2024-11-01",
            "top_n": 5,
        })

        assert resp.status_code == 200
        data = resp.json()
        assert "signals" in data


class TestMLErrorHandling:
    """ML 错误处理 E2E (TC-03-04 ~ TC-03-05)"""

    def test_empty_dataset_returns_error(self, client, seeded_db):
        """TC-03-04: 空数据集 — 不存在的 stock_pool 返回错误"""
        resp = client.post("/api/ml/train", json={
            "factor_names": ["mom_20"],
            "stock_pool": ["999999.SZ"],
            "start_date": "2024-02-01",
            "end_date": "2024-10-31",
            "label_period": 5,
        })

        assert resp.status_code in (400, 500)

    def test_nonexistent_model_returns_error(self, client, seeded_db):
        """TC-03-05: 模型路径不存在 — 返回 500"""
        resp = client.post("/api/ml/predict", json={
            "model_path": "nonexistent_model_path_12345.pkl",
            "factor_names": ["mom_20"],
            "stock_pool": ["000001.SZ"],
            "trade_date": "2024-11-01",
            "top_n": 10,
        })

        assert resp.status_code == 500
