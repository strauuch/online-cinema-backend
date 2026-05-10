import pytest


@pytest.mark.asyncio
async def test_update_profile_unauthorized(client):
    response = await client.patch(
        "/api/v1/accounts/me/profile/", data={"first_name": "Hacker"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_profile_invalid_data(authenticated_client):
    response = await authenticated_client.patch(
        "/api/v1/accounts/me/profile/", data={"gender": "invalid_gender"}
    )
    assert response.status_code == 422
