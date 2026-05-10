import pytest

from io import BytesIO
from PIL import Image
from sqlalchemy import select
from unittest.mock import patch

from app.database.models.accounts import UserProfileModel
from app.exceptions.storage import S3FileUploadError


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
    assert data["email"] is not None
    assert "profile" in data


@pytest.mark.asyncio
async def test_update_profile_text_only(authenticated_client):
    response = await authenticated_client.patch(
        "/api/v1/accounts/me/profile/",
        data={
            "first_name": "John",
            "last_name": "Doe",
            "info": "Updated bio"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["first_name"] == "john"
    assert data["last_name"] == "doe"


@pytest.mark.asyncio
async def test_update_profile_basic(authenticated_client):
    response = await authenticated_client.patch(
        "/api/v1/accounts/me/profile/",
        data={"first_name": "Updated", "last_name": "User", "info": "New bio"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["first_name"] == "updated"
    assert data["last_name"] == "user"


@pytest.mark.asyncio
async def test_update_profile_with_avatar(authenticated_client):
    img = Image.new("RGB", (150, 150), color="red")
    img_bytes = BytesIO()
    img.save(img_bytes, format="JPEG")
    img_bytes.seek(0)

    files = {
        "first_name": (None, "AvatarUser"),
        "avatar": ("avatar.jpg", img_bytes, "image/jpeg"),
    }

    response = await authenticated_client.patch(
        "/api/v1/accounts/me/profile/", files=files
    )
    assert response.status_code == 200
    data = response.json()
    assert data["first_name"] == "avataruser"
    assert "avatar" in data and data["avatar"] is not None


@pytest.mark.asyncio
async def test_update_profile_s3_upload_fails(authenticated_client, s3_storage_fake):
    img = Image.new("RGB", (100, 100), color="red")
    img_bytes = BytesIO()
    img.save(img_bytes, format="JPEG")
    img_bytes.seek(0)

    with patch.object(s3_storage_fake, "upload_file", side_effect=S3FileUploadError("Simulated failure")):
        response = await authenticated_client.patch(
            "/api/v1/accounts/me/profile/",
            files={"avatar": ("fail.jpg", img_bytes, "image/jpeg")}
        )

    assert response.status_code == 502


@pytest.mark.asyncio
async def test_update_profile_no_avatar(authenticated_client):
    response = await authenticated_client.patch(
        "/api/v1/accounts/me/profile/", data={"info": "Updated without avatar"}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_profile_basic_fields(authenticated_client):
    response = await authenticated_client.patch(
        "/api/v1/accounts/me/profile/",
        data={
            "first_name": "UpdatedName",
            "last_name": "UpdatedLast",
            "info": "New information here",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["first_name"] == "updatedname"
    assert data["last_name"] == "updatedlast"
    assert data["info"] == "New information here"


@pytest.mark.asyncio
async def test_update_profile_unauthorized(client):
    response = await client.patch(
        "/api/v1/accounts/me/profile/", data={"first_name": "Hacker"}
    )
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_update_profile_only_text_fields(authenticated_client):
    response = await authenticated_client.patch(
        "/api/v1/accounts/me/profile/",
        data={
            "first_name": "TextOnly",
            "last_name": "Update",
            "info": "Only text fields"
        }
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_profile_avatar_replacement(authenticated_client):
    img1 = Image.new("RGB", (100, 100), "blue")
    b1 = BytesIO()
    img1.save(b1, "JPEG")
    b1.seek(0)
    await authenticated_client.patch(
        "/api/v1/accounts/me/profile/",
        files={"avatar": ("old.jpg", b1, "image/jpeg")}
    )

    img2 = Image.new("RGB", (100, 100), "green")
    b2 = BytesIO()
    img2.save(b2, "JPEG")
    b2.seek(0)

    response = await authenticated_client.patch(
        "/api/v1/accounts/me/profile/",
        files={"avatar": ("new.jpg", b2, "image/jpeg")}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_profile_s3_error(authenticated_client, s3_storage_fake):

    img = Image.new("RGB", (100, 100), "red")
    img_bytes = BytesIO()
    img.save(img_bytes, "JPEG")
    img_bytes.seek(0)

    with patch.object(s3_storage_fake, 'upload_file', side_effect=S3FileUploadError("Fail")):
        response = await authenticated_client.patch(
            "/api/v1/accounts/me/profile/",
            files={"avatar": ("fail.jpg", img_bytes, "image/jpeg")}
        )

    assert response.status_code == 502
