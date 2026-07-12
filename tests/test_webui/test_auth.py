"""Tests for src/webui/auth.py (模拟盘用户鉴权)"""
import pytest

from src.webui.auth import AuthError, AuthManager, hash_password, verify_password
from src.webui.store import MemoryStore


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def auth(store):
    created = []
    return AuthManager(store, on_register=lambda u: created.append(u))


def test_password_hash_roundtrip():
    h, salt = hash_password("1234")
    assert verify_password("1234", h, salt)
    assert not verify_password("wrong", h, salt)


def test_hash_uses_random_salt():
    h1, s1 = hash_password("same")
    h2, s2 = hash_password("same")
    assert s1 != s2 and h1 != h2  # 不同盐 → 不同哈希


def test_seed_root(store):
    AuthManager(store)
    assert store.get_user("root") is not None
    # root 口令为 1234
    a = AuthManager(store)
    assert a.login("root", "1234")


def test_register_then_resolve(auth):
    token = auth.register("alice", "pw1")
    assert auth.resolve(token) == "alice"


def test_register_duplicate_rejected(auth):
    auth.register("bob", "x")
    with pytest.raises(AuthError):
        auth.register("bob", "y")


def test_register_requires_username_and_password(auth):
    with pytest.raises(AuthError):
        auth.register("", "x")
    with pytest.raises(AuthError):
        auth.register("u", "")


def test_login_wrong_password(auth):
    auth.register("carol", "right")
    with pytest.raises(AuthError):
        auth.login("carol", "wrong")


def test_login_unknown_user(auth):
    with pytest.raises(AuthError):
        auth.login("nobody", "x")


def test_logout_invalidates_token(auth):
    token = auth.register("dave", "pw")
    assert auth.resolve(token) == "dave"
    auth.logout(token)
    assert auth.resolve(token) is None


def test_resolve_none_token(auth):
    assert auth.resolve(None) is None
    assert auth.resolve("bogus") is None


def test_on_register_callback_called(store):
    created = []
    a = AuthManager(store, on_register=lambda u: created.append(u), seed_root=False)
    a.register("erin", "pw")
    assert "erin" in created
