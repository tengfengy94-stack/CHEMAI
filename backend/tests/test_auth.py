"""auth.py 单元测试：哈希、token 往返、过期与类型区分（tasks 2.1）。"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app import auth


def test_password_hash_roundtrip():
    h = auth.hash_password("chem2026")
    assert h != "chem2026"
    assert auth.verify_password("chem2026", h)
    assert not auth.verify_password("错的密码", h)


def test_token_roundtrip_preserves_sub_and_type():
    token = auth.create_token("teacher01", "access")
    payload = auth.decode_token(token, "access")
    assert payload["sub"] == "teacher01"
    assert payload["type"] == "access"


def test_expired_token_is_rejected():
    payload = {
        "sub": "teacher01",
        "type": "access",
        "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
    }
    token = jwt.encode(payload, auth.jwt_secret(), algorithm=auth.ALGORITHM)
    with pytest.raises(jwt.InvalidTokenError):
        auth.decode_token(token, "access")


def test_refresh_token_cannot_be_used_as_access():
    with pytest.raises(jwt.InvalidTokenError):
        auth.decode_token(auth.create_token("teacher01", "refresh"), "access")


def test_access_token_cannot_be_used_as_refresh():
    with pytest.raises(jwt.InvalidTokenError):
        auth.decode_token(auth.create_token("teacher01", "access"), "refresh")


def test_tampered_token_is_rejected():
    token = auth.create_token("teacher01", "access")
    with pytest.raises(jwt.InvalidTokenError):
        auth.decode_token(token[:-4] + "0000", "access")


def test_dummy_hash_is_a_working_argon2_hash():
    """哑哈希本身不可被任何密码验证通过，但校验过程真的在跑（耗时对齐用）。"""
    assert not auth.verify_password("chem2026", auth._DUMMY_HASH)
