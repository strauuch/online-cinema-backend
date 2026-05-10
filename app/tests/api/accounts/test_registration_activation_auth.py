import datetime
import uuid
from unittest.mock import AsyncMock

import pytest

from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError

from app.database.models.accounts import UserModel, ActivationTokenModel, UserProfileModel, RefreshTokenModel
from app.database.models.carts import CartModel

@pytest.mark.asyncio
async def test_register_user_success(client, db_session):
    payload = {"email": "newuser@example.com", "password": "StrongTestPass123!"}

    response = await client.post("/api/v1/accounts/register/", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == payload["email"]

    user = await db_session.scalar(
        select(UserModel).where(UserModel.email == payload["email"])
    )
    assert user is not None
    assert not user.is_active

    token = await db_session.scalar(
        select(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id)
    )
    assert token is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_password,error_msg",
    [
        ("short", "at least 8 characters"),
        ("NoDigitHere!", "at least one digit"),
        ("nodigitspecial", "at least one uppercase letter"),
        ("NOLOWERCASE123!", "at least one lower letter"),
    ],
)
async def test_register_weak_password(client, bad_password, error_msg):
    response = await client.post(
        "/api/v1/accounts/register/",
        json={"email": "weak@example.com", "password": bad_password},
    )
    assert response.status_code == 422
    assert error_msg in str(response.json())


@pytest.mark.asyncio
async def test_register_duplicate_email(client, db_session):
    payload = {"email": "duplicate@example.com", "password": "StrongTestPass123!"}
    await client.post("/api/v1/accounts/register/", json=payload)

    response = await client.post("/api/v1/accounts/register/", json=payload)
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]

@pytest.mark.asyncio
async def test_register_creates_profile_and_cart(client, db_session):
    payload = {"email": "full@test.com", "password": "StrongPass123!"}
    await client.post("/api/v1/accounts/register/", json=payload)

    user = await db_session.scalar(
        select(UserModel).where(UserModel.email == "full@test.com")
    )
    assert user is not None

    profile = await db_session.scalar(
        select(UserProfileModel).where(UserProfileModel.user_id == user.id)
    )
    cart = await db_session.scalar(
        select(CartModel).where(CartModel.user_id == user.id)
    )
    assert profile is not None
    assert cart is not None


@pytest.mark.asyncio
async def test_register_database_error(client, db_session, monkeypatch):
    async def fake_commit(*args, **kwargs):
        raise SQLAlchemyError("Test DB error")

    monkeypatch.setattr(db_session, "commit", fake_commit)
    monkeypatch.setattr(db_session, "flush", fake_commit)

    uniq_email = f"error_{uuid.uuid4()}@test.com"
    payload = {"email": uniq_email, "password": "StrongPass123!"}
    response = await client.post("/api/v1/accounts/register/", json=payload)
    assert response.status_code == 500
    assert "An error occurred during user creation" in response.json()["detail"]


@pytest.mark.asyncio
async def test_activate_account_success(client, db_session, user_factory):
    unique_email = f"admin_{uuid.uuid4()}@test.com"
    user = await user_factory.create_user(email=unique_email, is_active=False)

    token = ActivationTokenModel(user_id=user.id, token="test-token-123")
    db_session.add(token)
    await db_session.commit()

    stmt = select(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id)
    token_record = await db_session.scalar(stmt)
    assert token_record is not None

    payload = {"email": user.email, "token": "test-token-123"}

    response = await client.post("/api/v1/accounts/activate/", json=payload)
    assert response.status_code == 200
    assert response.json()["message"] == "User account activated successfully."

    await db_session.refresh(user)
    assert user.is_active is True

    token_after = await db_session.scalar(stmt)
    assert token_after is None


@pytest.mark.asyncio
async def test_activate_with_expired_token(client, db_session, user_factory):
    unique_email = f"user_{uuid.uuid4()}@test.com"
    user = await user_factory.create_user(email=unique_email, is_active=False)
    token = ActivationTokenModel(
        user_id=user.id,
        token="expired-token-123",
        expires_at=datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=1),
    )
    db_session.add(token)
    await db_session.commit()

    payload = {"email": user.email, "token": "expired-token-123"}
    response = await client.post("/api/v1/accounts/activate/", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired activation token."


@pytest.mark.asyncio
async def test_activate_already_active_user(client, db_session, user_factory):
    unique_email = f"user_{uuid.uuid4()}@test.com"
    user = await user_factory.create_active_user(email=unique_email)

    token = ActivationTokenModel(user_id=user.id, token="some-token")
    db_session.add(token)
    await db_session.commit()

    payload = {"email": user.email, "token": "some-token"}
    response = await client.post("/api/v1/accounts/activate/", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "User account is already active."


@pytest.mark.asyncio
async def test_resend_activation_token(client, db_session, user_factory):
    user = await user_factory.create_user(is_active=False)

    payload = {"email": user.email}
    response = await client.post("/api/v1/accounts/activate/resend/", json=payload)

    assert response.status_code == 200
    assert "will receive a new activation link" in response.json()["message"]


@pytest.mark.asyncio
async def test_resend_for_active_user_fails(client, db_session, user_factory):
    unique_email = f"user_{uuid.uuid4()}@test.com"
    user = await user_factory.create_active_user(email=unique_email)

    payload = {"email": user.email}
    response = await client.post("/api/v1/accounts/activate/resend/", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "User account is already active."

@pytest.mark.asyncio
async def test_activate_expired_token_deletes_it(client, db_session, user_factory):
    user = await user_factory.create_user(is_active=False)
    expired_token = ActivationTokenModel(
        user_id=user.id,
        expires_at=datetime.datetime.now(
            datetime.timezone.utc) - datetime.timedelta(days=1)
    )
    db_session.add(expired_token)
    await db_session.commit()

    response = await client.post("/api/v1/accounts/activate/", json={
        "email": user.email,
        "token": expired_token.token
    })
    assert response.status_code == 400

    remaining = await db_session.scalar(select(ActivationTokenModel).where(
        ActivationTokenModel.user_id == user.id
    ))
    assert remaining is None


@pytest.mark.asyncio
async def test_resend_activation_token_deletes_old_one(client, db_session, user_factory):
    user = await user_factory.create_user(is_active=False)

    old_token = ActivationTokenModel(user_id=user.id)
    db_session.add(old_token)
    await db_session.commit()

    await client.post("/api/v1/accounts/activate/resend/", json={"email": user.email})

    tokens = await db_session.scalars(
        select(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id)
    )
    assert len(list(tokens)) == 1


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_activate_invalid_token_no_record(client, user_factory):
    unique_email = f"user_{uuid.uuid4()}@test.com"
    user = await user_factory.create_user(is_active=False, email=unique_email)

    response = await client.post("/api/v1/accounts/activate/", json={
        "email": user.email,
        "token": "non-existent-token-999"
    })
    assert response.status_code == 400
    assert "Invalid or expired activation token." in response.json()["detail"]

@pytest.mark.asyncio
async def test_resend_for_nonexistent_user(client):
    unique_email = f"user_{uuid.uuid4()}@test.com"
    response = await client.post(
        "/api/v1/accounts/activate/resend/",
        json={"email": unique_email}
    )
    assert response.status_code == 200
    assert "will receive a new activation link" in response.json()["message"]


@pytest.mark.asyncio
async def test_login_success(client, db_session, user_factory, jwt_manager):
    user = await user_factory.create_active_user(email="login@test.com")

    response = await client.post(
        "/api/v1/accounts/login/",
        data={"username": user.email, "password": "StrongTestPass123!"},
    )

    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data

    refresh_record = await db_session.scalar(
        select(RefreshTokenModel).where(RefreshTokenModel.user_id == user.id)
    )
    assert refresh_record is not None


@pytest.mark.asyncio
async def test_login_inactive_user(client, db_session, user_factory):
    user = await user_factory.create_user(is_active=False, email="inactive@test.com")

    response = await client.post(
        "/api/v1/accounts/login/",
        data={"username": user.email, "password": "StrongTestPass123!"},
    )

    assert response.status_code == 403
    assert "not activated" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_invalid_credentials(client):
    response = await client.post(
        "/api/v1/accounts/login/",
        data={"username": "wrong@example.com", "password": "WrongPass123!"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


@pytest.mark.asyncio
async def test_logout_success(client, db_session, user_factory, jwt_manager):
    user = await user_factory.create_active_user()
    login_resp = await client.post(
        "/api/v1/accounts/login/",
        data={"username": user.email, "password": "StrongTestPass123!"},
    )
    refresh_token = login_resp.json()["refresh_token"]

    response = await client.post(
        "/api/v1/accounts/logout/",
        json={"refresh_token": refresh_token},
        headers={"Authorization": f"Bearer {login_resp.json()['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Successfully logged out."


@pytest.mark.asyncio
async def test_refresh_token_success(client, db_session, user_factory, jwt_manager):
    user = await user_factory.create_active_user()
    login_resp = await client.post(
        "/api/v1/accounts/login/",
        data={"username": user.email, "password": "StrongTestPass123!"},
    )
    refresh_token = login_resp.json()["refresh_token"]

    response = await client.post(
        "/api/v1/accounts/refresh/", json={"refresh_token": refresh_token}
    )

    assert response.status_code == 200
    assert "access_token" in response.json()

@pytest.mark.asyncio
async def test_logout_invalid_token(authenticated_client):
    response = await authenticated_client.post(
        "/api/v1/accounts/logout/",
        json={"refresh_token": "invalid-token"}
    )
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_login_inactive_user_auto_resend_token(client, db_session, user_factory):
    user = await user_factory.create_user(is_active=False)

    response = await client.post(
        "/api/v1/accounts/login/",
        data={"username": user.email, "password": "StrongTestPass123!"}
    )
    assert response.status_code == 403
    assert "new activation link" in response.json()["detail"].lower()

    tokens = await db_session.scalars(select(ActivationTokenModel).where(
        ActivationTokenModel.user_id == user.id
    ))
    assert len(list(tokens)) == 1


@pytest.mark.asyncio
async def test_logout_token_not_belonging_to_user(authenticated_client, user_factory):
    other_user = await user_factory.create_active_user()
    resp = await authenticated_client.post(
        "/api/v1/accounts/logout/",
        json={"refresh_token": "fake-token-that-doesnt-belong"}
    )
    assert resp.status_code == 401



@pytest.mark.asyncio
async def test_logout_db_error(client, db_session, user_factory, monkeypatch):
    unique_email = f"logout_err_{uuid.uuid4()}@test.com"
    user = await user_factory.create_active_user(email=unique_email)

    login_resp = await client.post(
        "/api/v1/accounts/login/",
        data={"username": user.email, "password": "StrongTestPass123!"}
    )
    tokens = login_resp.json()
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    mock_commit = AsyncMock(side_effect=SQLAlchemyError("DB fail"))
    monkeypatch.setattr(db_session, "commit", mock_commit)

    response = await client.post(
        "/api/v1/accounts/logout/",
        json={"refresh_token": refresh_token},
        headers={"Authorization": f"Bearer {access_token}"}
    )
    assert response.status_code == 500


@pytest.mark.asyncio
async def test_refresh_invalid_jwt(client):
    response = await client.post(
        "/api/v1/accounts/refresh/",
        json={"refresh_token": "invalid.jwt.token"}
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_refresh_user_not_found(client, db_session, user_factory, jwt_manager):
    user = await user_factory.create_active_user()
    login_resp = await client.post(
        "/api/v1/accounts/login/",
        data={"username": user.email, "password": "StrongTestPass123!"}
    )
    refresh_token = login_resp.json()["refresh_token"]

    await db_session.execute(delete(UserModel).where(UserModel.id == user.id))
    await db_session.commit()

    response = await client.post(
        "/api/v1/accounts/refresh/",
        json={"refresh_token": refresh_token}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_refresh_token_not_in_db(client, user_factory, jwt_manager):
    user = await user_factory.create_active_user()
    refresh_token = jwt_manager.create_refresh_token({"user_id": user.id})

    response = await client.post(
        "/api/v1/accounts/refresh/",
        json={"refresh_token": refresh_token}
    )
    assert response.status_code == 401