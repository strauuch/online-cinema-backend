import pytest


@pytest.mark.asyncio
async def test_admin_list_users(admin_client):
    response = await admin_client.get("/api/v1/accounts/admin/users/")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_admin_get_user_detail(admin_client, user_factory):
    user = await user_factory.create_active_user(email="filter2@test.com")
    response = await admin_client.get(f"/api/v1/accounts/admin/users/{user.id}/")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == user.id
    assert data["email"] == user.email


@pytest.mark.asyncio
async def test_admin_update_user(admin_client, user_factory):
    user = await user_factory.create_active_user(email="filter3@test.com")

    response = await admin_client.patch(
        f"/api/v1/accounts/admin/users/{user.id}/",
        json={"is_active": False, "group_id": 1}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is False


@pytest.mark.asyncio
async def test_admin_update_user_is_active(admin_client, user_factory):
    user = await user_factory.create_active_user(email="filter4@test.com")
    response = await admin_client.patch(
        f"/api/v1/accounts/admin/users/{user.id}/",
        json={"is_active": False}
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


@pytest.mark.asyncio
async def test_admin_list_users_with_filters(admin_client, user_factory):
    await user_factory.create_active_user(email="filter1@test.com")
    response = await admin_client.get("/api/v1/accounts/admin/users/?is_active=true")
    assert response.status_code == 200