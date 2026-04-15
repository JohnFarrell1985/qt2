"""Tests for auto_discover in src/strategy/registry.py."""
import importlib
import types

import pytest
from unittest.mock import patch

from src.strategy.registry import auto_discover, registry


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset registry state before each test."""
    original = dict(registry._classes)
    yield
    registry._classes.clear()
    registry._classes.update(original)


class TestAutoDiscover:
    @pytest.mark.timeout(30)
    def test_returns_int(self):
        result = auto_discover(package_paths=[])
        assert isinstance(result, int)
        assert result == 0

    @pytest.mark.timeout(30)
    def test_skips_missing_packages(self):
        result = auto_discover(package_paths=["nonexistent.package.xyz"])
        assert result == 0

    @pytest.mark.timeout(30)
    def test_imports_existing_module_without_path(self):
        """Module without __path__ (not a package) is imported but not walked."""
        fake_mod = types.ModuleType("fake_strat_mod")

        with patch.object(importlib, "import_module", return_value=fake_mod) as mock_import:
            result = auto_discover(package_paths=["fake_strat_mod"])
            mock_import.assert_called_once_with("fake_strat_mod")
        assert result == 0

    @pytest.mark.timeout(30)
    def test_discovers_from_package_with_submodules(self):
        """Simulate a package with __path__ and submodules."""
        fake_pkg = types.ModuleType("fake_pkg")
        fake_pkg.__path__ = ["/fake/path"]

        from src.strategy.base import BaseStrategy

        class FakeStrategy(BaseStrategy):
            name = "test_discovered"
            tier = "rule"
            description = "Test auto-discovered strategy"

            def pick(self, trade_date, stock_pool, **kwargs):
                return []

        real_import = importlib.import_module

        def mock_import(name):
            if name == "fake_pkg":
                return fake_pkg
            if name == "fake_pkg.sub":
                registry.register(FakeStrategy)
                return types.ModuleType("fake_pkg.sub")
            return real_import(name)

        def mock_walk(path, prefix=""):
            yield None, "fake_pkg.sub", False

        with patch.object(importlib, "import_module", side_effect=mock_import):
            with patch("src.strategy.registry.pkgutil.walk_packages", side_effect=mock_walk):
                result = auto_discover(package_paths=["fake_pkg"])

        assert result >= 1
        assert registry.get("test_discovered") is FakeStrategy

    @pytest.mark.timeout(30)
    def test_handles_import_error_in_submodule(self):
        """Submodule import error is caught gracefully."""
        fake_pkg = types.ModuleType("broken_pkg")
        fake_pkg.__path__ = ["/broken"]

        real_import = importlib.import_module

        def mock_import(name):
            if name == "broken_pkg":
                return fake_pkg
            if name.startswith("broken_pkg."):
                raise ImportError(f"No module {name}")
            return real_import(name)

        def mock_walk(path, prefix=""):
            yield None, "broken_pkg.broken_sub", False

        with patch.object(importlib, "import_module", side_effect=mock_import):
            with patch("src.strategy.registry.pkgutil.walk_packages", side_effect=mock_walk):
                result = auto_discover(package_paths=["broken_pkg"])

        assert result == 0

    @pytest.mark.timeout(30)
    def test_default_package_paths(self):
        """auto_discover with None uses default paths."""
        with patch.object(importlib, "import_module", side_effect=ImportError("mocked")):
            result = auto_discover(package_paths=None)
        assert result == 0
