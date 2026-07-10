"""ST / *ST 过滤单元测试."""

from unittest.mock import patch

from src.data.st_filter import (
    clear_st_codes_cache,
    filter_out_st,
    is_st_name,
    normalize_a_code,
)


def test_is_st_name():
    assert is_st_name("ST海润")
    assert is_st_name("*ST国华")
    assert is_st_name("S*ST佳通")
    assert not is_st_name("平安银行")
    assert not is_st_name("")
    assert not is_st_name(None)


def test_normalize_a_code():
    assert normalize_a_code("600000.SH") == "600000"
    assert normalize_a_code("1") == "000001"


def test_filter_out_st_uses_cache():
    clear_st_codes_cache()
    with patch("src.data.st_filter.get_st_codes", return_value={"000004", "600000"}):
        out = filter_out_st(["000004", "000001", "600000"])
    assert out == ["000001"]
