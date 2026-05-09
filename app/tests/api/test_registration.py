import pytest
from sqlalchemy import select
from app.database.models.accounts import UserModel, ActivationTokenModel


@pytest.mark.asyncio
async def test_register_user_success(client, db_session):
    payload = {
        "email": "newuser@example.com",
        "password": "StrongTestPass123!"
    }

    response = await client.post("/api/v1/accounts/register/", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == payload["email"]

    user = await db_session.scalar(select(UserModel).where(UserModel.email == payload["email"]))
    assert user is not None
    assert not user.is_active

    token = await db_session.scalar(select(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id))
    assert token is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_password,error_msg", [
    ("short", "at least 8 characters"),
    ("NoDigitHere!", "at least one digit"),
    ("nodigitspecial", "at least one uppercase letter"),
    ("NOLOWERCASE123!", "at least one lower letter"),
])
async def test_register_weak_password(client, bad_password, error_msg):
    response = await client.post("/api/v1/accounts/register/", json={
        "email": "weak@example.com",
        "password": bad_password
    })
    assert response.status_code == 422
    assert error_msg in str(response.json())


@pytest.mark.asyncio
async def test_register_duplicate_email(client, db_session):
    payload = {"email": "duplicate@example.com", "password": "StrongTestPass123!"}
    await client.post("/api/v1/accounts/register/", json=payload)

    response = await client.post("/api/v1/accounts/register/", json=payload)
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]
