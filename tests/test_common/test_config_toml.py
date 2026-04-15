"""Tests for load_toml_config and DistillConfig in src/common/config.py"""
import pytest

from src.common.config import load_toml_config, DistillConfig, settings


class TestLoadTomlConfig:
    @pytest.mark.timeout(30)
    def test_load_valid_toml(self, tmp_path):
        toml_file = tmp_path / "test.toml"
        toml_file.write_text(
            '[section]\nkey = "value"\ncount = 42\n',
            encoding="utf-8",
        )
        result = load_toml_config(str(toml_file))
        assert isinstance(result, dict)
        assert "section" in result
        assert result["section"]["key"] == "value"
        assert result["section"]["count"] == 42

    @pytest.mark.timeout(30)
    def test_missing_file_returns_empty(self, tmp_path):
        result = load_toml_config(str(tmp_path / "nonexistent.toml"))
        assert result == {}

    @pytest.mark.timeout(30)
    def test_none_path_uses_default(self):
        result = load_toml_config(None)
        assert isinstance(result, dict)

    @pytest.mark.timeout(30)
    def test_nested_toml(self, tmp_path):
        toml_file = tmp_path / "nested.toml"
        toml_file.write_text(
            '[ml]\nmodel_dir = "./models"\n\n[ml.iterate]\nmax_iterations = 100\n',
            encoding="utf-8",
        )
        result = load_toml_config(str(toml_file))
        assert result["ml"]["model_dir"] == "./models"
        assert result["ml"]["iterate"]["max_iterations"] == 100


class TestDistillConfig:
    @pytest.mark.timeout(30)
    def test_default_values(self):
        cfg = DistillConfig()
        assert cfg.teacher_a == "deepseek"
        assert cfg.teacher_b == "qwen"
        assert cfg.judge_model == "deepseek-r1"
        assert cfg.consensus_threshold == 0.7
        assert cfg.student_model == "finbert2-base"
        assert cfg.lora_rank == 16
        assert cfg.lora_alpha == 32
        assert cfg.use_onnx is True
        assert cfg.int8 is False
        assert cfg.flywheel_schedule == "weekly"
        assert cfg.enabled is False

    @pytest.mark.timeout(30)
    def test_custom_override(self):
        cfg = DistillConfig(teacher_a="qwen", lora_rank=8, enabled=True)
        assert cfg.teacher_a == "qwen"
        assert cfg.lora_rank == 8
        assert cfg.enabled is True


class TestSettingsDistill:
    @pytest.mark.timeout(30)
    def test_settings_has_distill(self):
        assert hasattr(settings, "distill")
        assert isinstance(settings.distill, DistillConfig)

    @pytest.mark.timeout(30)
    def test_distill_defaults_match(self):
        assert settings.distill.teacher_a in ("deepseek", "qwen")
        assert isinstance(settings.distill.consensus_threshold, float)
