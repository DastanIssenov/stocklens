import jwt
import pytest

from app.core.config import Settings, get_settings
from app.core.security import TokenError, create_token, decode_token, hash_password, verify_password


def test_password_hash_roundtrip() -> None:
    h = hash_password("correct horse 1")
    assert h.startswith("$argon2id$")
    assert verify_password("correct horse 1", h)
    assert not verify_password("wrong", h)
    assert not verify_password("x", "not-a-hash")


def test_token_roundtrip_and_type_check() -> None:
    access = create_token(42, "access")
    refresh = create_token(42, "refresh")
    assert decode_token(access, "access")["sub"] == "42"
    assert decode_token(refresh, "refresh")["type"] == "refresh"
    with pytest.raises(TokenError):
        decode_token(access, "refresh")
    with pytest.raises(TokenError):
        decode_token(refresh, "access")


def test_tampered_and_expired_tokens_rejected() -> None:
    with pytest.raises(TokenError):
        decode_token(create_token(1, "access") + "x", "access")
    s = get_settings()
    expired = jwt.encode({"sub": "1", "type": "access", "exp": 1}, s.jwt_secret.get_secret_value(), "HS256")
    with pytest.raises(TokenError):
        decode_token(expired, "access")


def test_settings_normalise_db_url_and_hide_secrets() -> None:
    s = Settings(database_url="postgres://u:p@h:5432/db", alpaca_key="abc", _env_file=None)
    assert s.database_url == "postgresql+asyncpg://u:p@h:5432/db"
    assert "abc" not in repr(s)
    assert s.alpaca_configured is False  # secret missing
    assert Settings(cors_origins="a, b", _env_file=None).cors_origin_list == ["a", "b"]


def test_prod_refuses_default_jwt_secret() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="prod", jwt_secret="dev-only-change-me-please-32-bytes-min")
    assert Settings(_env_file=None, environment="prod", jwt_secret="x" * 40).environment == "prod"
