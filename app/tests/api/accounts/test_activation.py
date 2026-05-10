import datetime
import uuid
import pytest

from sqlalchemy import select

from app.database.models.accounts import UserModel, ActivationTokenModel


@pytest.mark.asyncio
async def test_activate_account_success(client, db_session, user_factory):
    user = await user_factory.create_user(is_active=False)

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
