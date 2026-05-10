import pytest


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
