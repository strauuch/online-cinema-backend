import pytest
from datetime import timedelta

from app.security.passwords import hash_password, verify_password
from app.security.utils import generate_secure_token
from app.security.token_manager import JWTAuthManager
from app.exceptions.security import TokenExpiredError, InvalidTokenError

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def manager():
    return JWTAuthManager(
        secret_key_access="test_access_secret",
        secret_key_refresh="test_refresh_secret",
        algorithm="HS256",
    )


# ==============================================================================
# passwords.py
# ==============================================================================


def test_hash_password_returns_string():
    result = hash_password("SomePassword1!")
    assert isinstance(result, str)


def test_hash_password_is_not_plaintext():
    password = "SomePassword1!"
    assert hash_password(password) != password


def test_hash_password_same_input_different_hashes():
    # bcrypt uses a random salt each time
    h1 = hash_password("SomePassword1!")
    h2 = hash_password("SomePassword1!")
    assert h1 != h2


def test_verify_password_correct():
    password = "SomePassword1!"
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True


def test_verify_password_wrong():
    hashed = hash_password("SomePassword1!")
    assert verify_password("WrongPassword1!", hashed) is False


def test_verify_password_empty_string():
    hashed = hash_password("SomePassword1!")
    assert verify_password("", hashed) is False


def test_verify_password_case_sensitive():
    hashed = hash_password("somepassword1!")
    assert verify_password("SOMEPASSWORD1!", hashed) is False


# ==============================================================================
# utils.py
# ==============================================================================


def test_generate_secure_token_returns_string():
    token = generate_secure_token()
    assert isinstance(token, str)


def test_generate_secure_token_default_length_nonempty():
    token = generate_secure_token()
    assert len(token) > 0


def test_generate_secure_token_custom_length():
    # token_urlsafe output is longer than the byte length due to base64 encoding
    token = generate_secure_token(length=16)
    assert len(token) >= 16


def test_generate_secure_token_uniqueness():
    tokens = {generate_secure_token() for _ in range(10)}
    assert len(tokens) == 10


# ==============================================================================
# token_manager.py — access tokens
# ==============================================================================


def test_create_access_token_returns_string(manager):
    token = manager.create_access_token({"user_id": 1})
    assert isinstance(token, str)
    assert len(token) > 0


def test_decode_access_token_returns_payload(manager):
    token = manager.create_access_token({"user_id": 42})
    payload = manager.decode_access_token(token)
    assert payload["user_id"] == 42


def test_decode_access_token_expired_raises(manager):
    token = manager.create_access_token(
        {"user_id": 1}, expires_delta=timedelta(seconds=-1)
    )
    with pytest.raises(TokenExpiredError):
        manager.decode_access_token(token)


def test_decode_access_token_invalid_raises(manager):
    with pytest.raises(InvalidTokenError):
        manager.decode_access_token("this.is.not.a.token")


def test_decode_access_token_wrong_secret_raises(manager):
    other = JWTAuthManager("wrong_secret", "test_refresh_secret", "HS256")
    token = other.create_access_token({"user_id": 1})
    with pytest.raises(InvalidTokenError):
        manager.decode_access_token(token)


def test_decode_access_token_with_refresh_secret_raises(manager):
    # refresh token must not be accepted as access token
    token = manager.create_refresh_token({"user_id": 1})
    with pytest.raises(InvalidTokenError):
        manager.decode_access_token(token)


def test_verify_access_token_valid_does_not_raise(manager):
    token = manager.create_access_token({"user_id": 1})
    manager.verify_access_token_or_raise(token)  # should not raise


def test_verify_access_token_expired_raises(manager):
    token = manager.create_access_token(
        {"user_id": 1}, expires_delta=timedelta(seconds=-1)
    )
    with pytest.raises(TokenExpiredError):
        manager.verify_access_token_or_raise(token)


def test_verify_access_token_invalid_raises(manager):
    with pytest.raises(InvalidTokenError):
        manager.verify_access_token_or_raise("garbage")


# ==============================================================================
# token_manager.py — refresh tokens
# ==============================================================================


def test_create_refresh_token_returns_string(manager):
    token = manager.create_refresh_token({"user_id": 1})
    assert isinstance(token, str)


def test_decode_refresh_token_returns_payload(manager):
    token = manager.create_refresh_token({"user_id": 99})
    payload = manager.decode_refresh_token(token)
    assert payload["user_id"] == 99


def test_decode_refresh_token_expired_raises(manager):
    token = manager.create_refresh_token(
        {"user_id": 1}, expires_delta=timedelta(seconds=-1)
    )
    with pytest.raises(TokenExpiredError):
        manager.decode_refresh_token(token)


def test_decode_refresh_token_invalid_raises(manager):
    with pytest.raises(InvalidTokenError):
        manager.decode_refresh_token("bad.token.here")


def test_decode_refresh_token_wrong_secret_raises(manager):
    other = JWTAuthManager("test_access_secret", "wrong_refresh_secret", "HS256")
    token = other.create_refresh_token({"user_id": 1})
    with pytest.raises(InvalidTokenError):
        manager.decode_refresh_token(token)


def test_verify_refresh_token_valid_does_not_raise(manager):
    token = manager.create_refresh_token({"user_id": 1})
    manager.verify_refresh_token_or_raise(token)  # should not raise


def test_verify_refresh_token_expired_raises(manager):
    token = manager.create_refresh_token(
        {"user_id": 1}, expires_delta=timedelta(seconds=-1)
    )
    with pytest.raises(TokenExpiredError):
        manager.verify_refresh_token_or_raise(token)


def test_verify_refresh_token_invalid_raises(manager):
    with pytest.raises(InvalidTokenError):
        manager.verify_refresh_token_or_raise("garbage")


# ==============================================================================
# token_manager.py — access vs refresh token isolation
# ==============================================================================


def test_access_and_refresh_tokens_are_different(manager):
    data = {"user_id": 1}
    access = manager.create_access_token(data)
    refresh = manager.create_refresh_token(data)
    assert access != refresh


def test_custom_expiry_is_respected(manager):
    # token with 1-hour delta should decode fine
    token = manager.create_access_token(
        {"user_id": 5}, expires_delta=timedelta(hours=1)
    )
    payload = manager.decode_access_token(token)
    assert payload["user_id"] == 5
