"""CleanerRegistry 单元测试

测试 src/dataclean/registry.py 的:
- 单例行为
- register / get / list_schemas
- get_schema / get_prompt
- _register_defaults 内置注册
- 未知名称返回 None
"""
import pytest
from pydantic import BaseModel

from src.dataclean.registry import CleanerRegistry, CleanerRegistryEntry


class _DummySchema(BaseModel):
    value: str = ""


@pytest.fixture()
def fresh_registry():
    """每个测试用隔离的注册表, 测试后恢复原状"""
    original_entries = CleanerRegistry._entries
    fresh_entries: dict = {}
    CleanerRegistry._entries = fresh_entries
    registry = CleanerRegistry()
    yield registry
    CleanerRegistry._entries = original_entries


class TestCleanerRegistrySingleton:

    @pytest.mark.timeout(30)
    def test_singleton_returns_same_instance(self):
        a = CleanerRegistry()
        b = CleanerRegistry()
        assert a is b

    @pytest.mark.timeout(30)
    def test_singleton_shares_state(self):
        a = CleanerRegistry()
        b = CleanerRegistry()
        assert a._entries is b._entries


class TestCleanerRegistryRegister:

    @pytest.mark.timeout(30)
    def test_register_and_get(self, fresh_registry: CleanerRegistry):
        fresh_registry.register("test_schema", _DummySchema, "prompt text", "desc")
        entry = fresh_registry.get("test_schema")
        assert entry is not None
        assert entry.schema_cls is _DummySchema
        assert entry.prompt_template == "prompt text"
        assert entry.description == "desc"

    @pytest.mark.timeout(30)
    def test_register_overwrites(self, fresh_registry: CleanerRegistry):
        fresh_registry.register("x", _DummySchema, "old_prompt")
        fresh_registry.register("x", _DummySchema, "new_prompt")
        entry = fresh_registry.get("x")
        assert entry is not None
        assert entry.prompt_template == "new_prompt"

    @pytest.mark.timeout(30)
    def test_get_unknown_returns_none(self, fresh_registry: CleanerRegistry):
        assert fresh_registry.get("nonexistent") is None

    @pytest.mark.timeout(30)
    def test_get_schema(self, fresh_registry: CleanerRegistry):
        fresh_registry.register("s1", _DummySchema, "p1")
        assert fresh_registry.get_schema("s1") is _DummySchema
        assert fresh_registry.get_schema("missing") is None

    @pytest.mark.timeout(30)
    def test_get_prompt(self, fresh_registry: CleanerRegistry):
        fresh_registry.register("s2", _DummySchema, "my prompt")
        assert fresh_registry.get_prompt("s2") == "my prompt"
        assert fresh_registry.get_prompt("missing") is None


class TestCleanerRegistryList:

    @pytest.mark.timeout(30)
    def test_list_schemas_empty(self, fresh_registry: CleanerRegistry):
        assert fresh_registry.list_schemas() == []

    @pytest.mark.timeout(30)
    def test_list_schemas_populated(self, fresh_registry: CleanerRegistry):
        fresh_registry.register("alpha", _DummySchema, "p_alpha", "Alpha desc")
        fresh_registry.register("beta", _DummySchema, "p_beta", "Beta desc")
        schemas = fresh_registry.list_schemas()
        assert len(schemas) == 2
        names = {s["name"] for s in schemas}
        assert names == {"alpha", "beta"}
        for s in schemas:
            assert "schema" in s
            assert "description" in s


class TestRegisterDefaults:

    @pytest.mark.timeout(30)
    def test_defaults_populated(self):
        """_register_defaults 在模块加载时运行, 全局 registry 应含内置条目"""
        from src.dataclean.registry import cleaner_registry
        schemas = cleaner_registry.list_schemas()
        registered_names = {s["name"] for s in schemas}
        expected = {"sentiment", "sector_signal", "fund_flow", "macro_indicator", "stock_event", "risk_alert"}
        assert expected.issubset(registered_names)

    @pytest.mark.timeout(30)
    def test_defaults_have_prompts(self):
        from src.dataclean.registry import cleaner_registry
        for name in ("sentiment", "sector_signal", "fund_flow", "macro_indicator", "stock_event", "risk_alert"):
            prompt = cleaner_registry.get_prompt(name)
            assert prompt is not None and len(prompt) > 0, f"{name} 缺少 prompt"

    @pytest.mark.timeout(30)
    def test_defaults_schema_classes_are_basemodel(self):
        from src.dataclean.registry import cleaner_registry
        for name in ("sentiment", "sector_signal", "fund_flow"):
            schema_cls = cleaner_registry.get_schema(name)
            assert schema_cls is not None
            assert issubclass(schema_cls, BaseModel)


class TestCleanerRegistryEntry:

    @pytest.mark.timeout(30)
    def test_entry_attributes(self):
        entry = CleanerRegistryEntry(_DummySchema, "tmpl", "d")
        assert entry.schema_cls is _DummySchema
        assert entry.prompt_template == "tmpl"
        assert entry.description == "d"
