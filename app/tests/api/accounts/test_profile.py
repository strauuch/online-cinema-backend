import pytest

from io import BytesIO
from PIL import Image
from sqlalchemy import select

from app.database.models.accounts import UserProfileModel


@pytest.mark.asyncio
async def test_update_own_profile(authenticated_client, db_session):
    img = Image.new("RGB", (100, 100), color="blue")
    img_bytes = BytesIO()
    img.save(img_bytes, format="JPEG")
    img_bytes.seek(0)

    files = {
        "first_name": (None, "John"),
        "last_name": (None, "Doe"),
        "gender": (None, "man"),
        "date_of_birth": (None, "1995-05-15"),
        "info": (None, "Test profile"),
        "avatar": ("avatar.jpg", img_bytes, "image/jpeg"),
    }

    response = await authenticated_client.patch(
        "/api/v1/accounts/me/profile/", files=files
    )
    assert response.status_code == 200

    data = response.json()
    assert data["first_name"] == "john"
    assert data["last_name"] == "doe"
    assert "avatar" in data


@pytest.mark.asyncio
async def test_get_me(authenticated_client):
    response = await authenticated_client.get("/api/v1/accounts/me/")
    assert response.status_code == 200
    data = response.json()
    assert "email" in data
    assert "profile" in data
