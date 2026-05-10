import pytest
import uuid
import datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.accounts import UserModel, PasswordResetTokenModel

@pytest.mark.asyncio
async def test_change_password_success(authenticated_client, db_session, user_factory):
    user = await user_factory.create_active_user(email="changepass@test.com")

    login_resp = await authenticated_client.post(
        "/api/v1/accounts/login/",
        data={"username": user.email, "password": "StrongTestPass123!"},
    )
    token = login_resp.json()["access_token"]
    authenticated_client.headers["Authorization"] = f"Bearer {token}"

    response = await authenticated_client.post(
        "/api/v1/accounts/password-change/",
        json={
            "old_password": "StrongTestPass123!",
            "new_password": "NewSuperStrongPass456!",
        },
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Password changed successfully."


@pytest.mark.asyncio
async def test_change_password_wrong_old_password(authenticated_client):
    response = await authenticated_client.post(
        "/api/v1/accounts/password-change/",
        json={
            "old_password": "WrongOld123!",
            "new_password": "NewPass123!"
        }
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid old password."


@pytest.mark.asyncio
async def test_change_password_wrong_old(authenticated_client):
    response = await authenticated_client.post(
        "/api/v1/accounts/password-change/",
        json={"old_password": "WrongOldPass123!", "new_password": "NewPass123!"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid old password."


@pytest.mark.asyncio
async def test_change_password_same_as_old(authenticated_client):
    response = await authenticated_client.post(
        "/api/v1/accounts/password-change/",
        json={
            "old_password": "StrongTestPass123!",
            "new_password": "StrongTestPass123!",
        },
    )
    assert response.status_code == 400
    assert "different from the old one" in response.json()["detail"]

@pytest.mark.asyncio
async def test_change_password_db_error(authenticated_client, db_session, monkeypatch):
    async def fake_commit(*args, **kwargs):
        raise SQLAlchemyError("DB error")
    monkeypatch.setattr(db_session, "commit", fake_commit)

    response = await authenticated_client.post(
        "/api/v1/accounts/password-change/",
        json={"old_password": "StrongTestPass123!", "new_password": "NewPass456!"}
    )
    assert response.status_code == 500


@pytest.mark.asyncio
async def test_password_reset_full_flow(client, db_session, user_factory):
    user = await user_factory.create_active_user(email="reset@test.com")

    resp1 = await client.post(
        "/api/v1/accounts/password-reset/request/", json={"email": user.email}
    )
    assert resp1.status_code == 200

    token_record = await db_session.scalar(
        select(PasswordResetTokenModel).where(
            PasswordResetTokenModel.user_id == user.id
        )
    )
    assert token_record is not None

    new_password = "NewVeryStrongPass123!"
    resp2 = await client.post(
        "/api/v1/accounts/reset-password/complete/",
        json={
            "email": user.email,
            "token": token_record.token,
            "password": new_password,
        },
    )

    assert resp2.status_code == 200
    assert resp2.json()["message"] == "Password reset successfully."

    await db_session.refresh(user)
    assert user.verify_password(new_password)


@pytest.mark.asyncio
async def test_password_reset_invalid_token(client, db_session, user_factory):
    user = await user_factory.create_active_user()
    await client.post(
        "/api/v1/accounts/password-reset/request/", json={"email": user.email}
    )

    response = await client.post(
        "/api/v1/accounts/reset-password/complete/",
        json={
            "email": user.email,
            "token": "invalid-token-123",
            "password": "NewPass123!",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid email or token."

@pytest.mark.asyncio
async def test_password_reset_request_for_inactive_user(client, user_factory):
    unique_email = f"user_{uuid.uuid4()}@test.com"
    user = await user_factory.create_user(email=unique_email, is_active=False)
    resp = await client.post("/api/v1/accounts/password-reset/request/",
                           json={"email": user.email})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_password_reset_expired_token(client, db_session, user_factory):
    user = await user_factory.create_active_user()
    token = PasswordResetTokenModel(
        user_id=user.id,
        expires_at=datetime.datetime.now(
            datetime.timezone.utc) - datetime.timedelta(hours=1)
    )
    db_session.add(token)
    await db_session.commit()

    resp = await client.post("/api/v1/accounts/reset-password/complete/", json={
        "email": user.email,
        "token": token.token,
        "password": "NewPass123!"
    })
    assert resp.status_code == 400
