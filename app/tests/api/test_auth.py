import pytest
from sqlalchemy import select
from app.database.models.accounts import UserModel, RefreshTokenModel


@pytest.mark.asyncio
async def test_login_success(client, db_session, user_factory, jwt_manager):
    user = await user_factory.create_active_user(email="login@test.com")

    response = await client.post("/api/v1/accounts/login/", json={
        "username": user.email,
        "password": "StrongTestPass123!"
    })

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

    response = await client.post("/api/v1/accounts/login/", json={
        "username": user.email,
        "password": "StrongTestPass123!"
    })

    assert response.status_code == 403
    assert "not activated" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_invalid_credentials(client):
    response = await client.post("/api/v1/accounts/login/", json={
        "username": "wrong@example.com",
        "password": "WrongPass123!"
    })
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


@pytest.mark.asyncio
async def test_logout_success(client, db_session, user_factory, jwt_manager):
    user = await user_factory.create_active_user()
    # Логинимся
    login_resp = await client.post("/api/v1/accounts/login/", json={
        "username": user.email,
        "password": "StrongTestPass123!"
    })
    refresh_token = login_resp.json()["refresh_token"]

    # Логаут
    response = await client.post("/api/v1/accounts/logout/", json={
        "refresh_token": refresh_token
    }, headers={"Authorization": f"Bearer {login_resp.json()['access_token']}"})

    assert response.status_code == 200
    assert response.json()["message"] == "Successfully logged out."


@pytest.mark.asyncio
async def test_refresh_token_success(client, db_session, user_factory, jwt_manager):
    user = await user_factory.create_active_user()
    login_resp = await client.post("/api/v1/accounts/login/", json={
        "username": user.email,
        "password": "StrongTestPass123!"
    })
    refresh_token = login_resp.json()["refresh_token"]

    response = await client.post("/api/v1/accounts/refresh/", json={
        "refresh_token": refresh_token
    })

    assert response.status_code == 200
    assert "access_token" in response.json()
