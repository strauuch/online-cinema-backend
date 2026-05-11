import datetime
import uuid
import pytest

from io import BytesIO
from PIL import Image
from unittest.mock import AsyncMock, patch
from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.accounts import (
    UserModel,
    ActivationTokenModel,
    UserProfileModel,
    UserGroupModel,
    UserGroupEnum,
    RefreshTokenModel,
    PasswordResetTokenModel,
)
from app.exceptions.storage import S3FileUploadError
from app.database.models.carts import CartModel
from app.routes.accounts import router as accounts_router, register_user


async def ensure_user_group(db_session):
    group = await db_session.scalar(
        select(UserGroupModel).where(UserGroupModel.name == UserGroupEnum.USER)
    )
    if not group:
        group = UserGroupModel(name=UserGroupEnum.USER)
        db_session.add(group)
        await db_session.commit()


@pytest.mark.asyncio
async def test_register_user_success(client, db_session):
    await ensure_user_group(db_session)
    unique_email = f"{uuid.uuid4()}@example.com"

    payload = {
        "email": unique_email,
        "password": "StrongPassword123!",
    }

    response = await client.post("/api/v1/accounts/register/", json=payload)
    assert response.status_code == 201
    response_data = response.json()
    assert response_data["email"] == payload["email"]
    assert "id" in response_data

    user = await db_session.scalar(
        select(UserModel).where(UserModel.email == payload["email"])
    )
    assert user is not None
    assert user.is_active is False

    profile = await db_session.scalar(
        select(UserProfileModel).where(UserProfileModel.user_id == user.id)
    )
    assert profile is not None

    cart = await db_session.scalar(
        select(CartModel).where(CartModel.user_id == user.id)
    )
    assert cart is not None

    token = await db_session.scalar(
        select(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id)
    )
    assert token is not None


@pytest.mark.asyncio
async def test_register_duplicate_email(client, db_session):
    await ensure_user_group(db_session)

    unique_email = f"{uuid.uuid4()}@example.com"
    payload = {
        "email": unique_email,
        "password": "StrongPassword123!",
    }

    await client.post("/api/v1/accounts/register/", json=payload)

    response = await client.post("/api/v1/accounts/register/", json=payload)
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_password, expected_error",
    [
        ("short", "at least 8 characters"),
        ("NoDigitHere!", "at least one digit"),
        ("nodigitspecial123!", "at least one uppercase letter"),
        ("NOLOWERCASE123!", "at least one lower letter"),
    ],
)
async def test_register_weak_password(client, invalid_password, expected_error):
    unique_email = f"{uuid.uuid4()}@example.com"
    payload = {
        "email": unique_email,
        "password": invalid_password,
    }

    response = await client.post("/api/v1/accounts/register/", json=payload)
    assert response.status_code == 422
    assert expected_error in str(response.json())


@pytest.mark.asyncio
async def test_register_missing_user_group(client, db_session, monkeypatch):
    from sqlalchemy.engine import Result
    from unittest.mock import AsyncMock

    unique_email = f"{uuid.uuid4()}@example.com"
    mock_result = AsyncMock(spec=Result)
    mock_result.scalars.return_value.first.return_value = None

    original_execute = db_session.execute

    async def mock_execute(stmt, *args, **kwargs):
        if "usergroupmodel" in str(stmt).lower() or "user_group" in str(stmt).lower():
            return mock_result
        return await original_execute(stmt, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", mock_execute)

    payload = {"email": unique_email, "password": "StrongTestPass123!"}
    response = await client.post("/api/v1/accounts/register/", json=payload)

    assert response.status_code == 500
    assert "Default user group not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_register_db_error(client, db_session, monkeypatch):
    await ensure_user_group(db_session)
    unique_email = f"{uuid.uuid4()}@example.com"

    async def fake_flush(*args, **kwargs):
        raise SQLAlchemyError("DB Crash")

    monkeypatch.setattr(db_session, "flush", fake_flush)

    payload = {
        "email": unique_email,
        "password": "StrongTestPass123!",
    }

    response = await client.post("/api/v1/accounts/register/", json=payload)

    assert response.status_code == 500
    assert "An error occurred during user creation" in response.json()["detail"]


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
    unique_email = f"{uuid.uuid4()}@example.com"
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
    user = await user_factory.create_active_user()

    token = ActivationTokenModel(user_id=user.id, token="some-token")
    db_session.add(token)
    await db_session.commit()

    payload = {"email": user.email, "token": "some-token"}
    response = await client.post("/api/v1/accounts/activate/", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "User account is already active."


@pytest.mark.asyncio
async def test_activate_db_error_during_commit(
    client, user_factory, db_session, monkeypatch
):
    unique_email = f"db_err_{uuid.uuid4()}@test.com"
    user = await user_factory.create_user(email=unique_email, is_active=False)

    token_val = str(uuid.uuid4())
    token = ActivationTokenModel(user_id=user.id, token=token_val)
    db_session.add(token)
    await db_session.commit()

    async def mock_flush(*args, **kwargs):
        raise SQLAlchemyError("Activation flush crash")

    monkeypatch.setattr(db_session, "flush", mock_flush)

    payload = {"email": user.email, "token": token_val}
    response = await client.post("/api/v1/accounts/activate/", json=payload)

    assert response.status_code == 500
    assert "An error occurred during account activation" in response.json()["detail"]

    await db_session.refresh(user)
    assert user.is_active is False


@pytest.mark.asyncio
async def test_resend_activation_token(client, db_session, user_factory):
    user = await user_factory.create_user(is_active=False)

    payload = {"email": user.email}
    response = await client.post("/api/v1/accounts/activate/resend/", json=payload)

    assert response.status_code == 200
    assert "will receive a new activation link" in response.json()["message"]


@pytest.mark.asyncio
async def test_resend_for_active_user_fails(client, db_session, user_factory):
    unique_email = f"{uuid.uuid4()}@example.com"
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
        expires_at=datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=1),
    )
    db_session.add(expired_token)
    await db_session.commit()

    response = await client.post(
        "/api/v1/accounts/activate/",
        json={"email": user.email, "token": expired_token.token},
    )
    assert response.status_code == 400

    remaining = await db_session.scalar(
        select(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id)
    )
    assert remaining is None


@pytest.mark.asyncio
async def test_resend_activation_token_deletes_old_one(
    client, db_session, user_factory
):
    unique_email = f"{uuid.uuid4()}@example.com"
    user = await user_factory.create_user(email=unique_email, is_active=False)

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
    user = await user_factory.create_user(is_active=False)

    response = await client.post(
        "/api/v1/accounts/activate/",
        json={"email": user.email, "token": "non-existent-token-999"},
    )
    assert response.status_code == 400
    assert "Invalid or expired activation token." in response.json()["detail"]


@pytest.mark.asyncio
async def test_activate_user_already_active(client, user_factory, db_session):
    unique_email = f"active_{uuid.uuid4()}@test.com"
    user = await user_factory.create_active_user(email=unique_email)

    activation_uuid = uuid.uuid4()
    token = ActivationTokenModel(user_id=user.id, token=str(activation_uuid))
    db_session.add(token)
    await db_session.commit()

    response = await client.post(
        "/api/v1/accounts/activate/",
        json={"email": unique_email, "token": str(activation_uuid)},
    )

    assert response.status_code == 400
    assert "User account is already active." in response.json()["detail"]


@pytest.mark.asyncio
async def test_resend_for_nonexistent_user(client):
    unique_email = f"{uuid.uuid4()}@example.com"
    response = await client.post(
        "/api/v1/accounts/activate/resend/", json={"email": unique_email}
    )
    assert response.status_code == 200
    assert "will receive a new activation link" in response.json()["message"]


@pytest.mark.asyncio
async def test_login_success(client, db_session, user_factory, jwt_manager):
    user = await user_factory.create_active_user()

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
    user = await user_factory.create_user(is_active=False)

    response = await client.post(
        "/api/v1/accounts/login/",
        data={"username": user.email, "password": "StrongTestPass123!"},
    )

    assert response.status_code == 403
    assert "not activated" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_invalid_credentials(client):
    unique_email = f"{uuid.uuid4()}@example.com"
    response = await client.post(
        "/api/v1/accounts/login/",
        data={"username": unique_email, "password": "WrongPass123!"},
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
async def test_login_inactive_user_auto_resend_token(client, db_session, user_factory):
    user = await user_factory.create_user(is_active=False)

    response = await client.post(
        "/api/v1/accounts/login/",
        data={"username": user.email, "password": "StrongTestPass123!"},
    )
    assert response.status_code == 403
    assert "new activation link" in response.json()["detail"].lower()

    tokens = await db_session.scalars(
        select(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id)
    )
    assert len(list(tokens)) == 1


@pytest.mark.asyncio
async def test_logout_invalid_token(authenticated_client):
    response = await authenticated_client.post(
        "/api/v1/accounts/logout/", json={"refresh_token": "invalid-token"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_token_not_belonging_to_user(authenticated_client):
    resp = await authenticated_client.post(
        "/api/v1/accounts/logout/",
        json={"refresh_token": "fake-token-that-doesnt-belong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_db_error(client, db_session, user_factory, monkeypatch):
    user = await user_factory.create_active_user()

    login_resp = await client.post(
        "/api/v1/accounts/login/",
        data={"username": user.email, "password": "StrongTestPass123!"},
    )
    tokens = login_resp.json()
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    mock_commit = AsyncMock(side_effect=SQLAlchemyError("DB fail"))
    monkeypatch.setattr(db_session, "commit", mock_commit)

    response = await client.post(
        "/api/v1/accounts/logout/",
        json={"refresh_token": refresh_token},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 500


@pytest.mark.asyncio
async def test_refresh_invalid_jwt(client):
    response = await client.post(
        "/api/v1/accounts/refresh/", json={"refresh_token": "invalid.jwt.token"}
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_refresh_user_not_found(client, db_session, user_factory, jwt_manager):
    user = await user_factory.create_active_user()
    login_resp = await client.post(
        "/api/v1/accounts/login/",
        data={"username": user.email, "password": "StrongTestPass123!"},
    )
    refresh_token = login_resp.json()["refresh_token"]

    await db_session.execute(delete(UserModel).where(UserModel.id == user.id))
    await db_session.commit()

    response = await client.post(
        "/api/v1/accounts/refresh/", json={"refresh_token": refresh_token}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_refresh_token_not_in_db(client, user_factory, jwt_manager):
    user = await user_factory.create_active_user()
    refresh_token = jwt_manager.create_refresh_token({"user_id": user.id})

    response = await client.post(
        "/api/v1/accounts/refresh/", json={"refresh_token": refresh_token}
    )
    assert response.status_code == 401


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
        data={"first_name": "John", "last_name": "Doe", "info": "Updated bio"},
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

    with patch.object(
        s3_storage_fake,
        "upload_file",
        side_effect=S3FileUploadError("Simulated failure"),
    ):
        response = await authenticated_client.patch(
            "/api/v1/accounts/me/profile/",
            files={"avatar": ("fail.jpg", img_bytes, "image/jpeg")},
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
            "info": "Only text fields",
        },
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_profile_avatar_replacement(authenticated_client):
    img1 = Image.new("RGB", (100, 100), "blue")
    b1 = BytesIO()
    img1.save(b1, "JPEG")
    b1.seek(0)
    await authenticated_client.patch(
        "/api/v1/accounts/me/profile/", files={"avatar": ("old.jpg", b1, "image/jpeg")}
    )

    img2 = Image.new("RGB", (100, 100), "green")
    b2 = BytesIO()
    img2.save(b2, "JPEG")
    b2.seek(0)

    response = await authenticated_client.patch(
        "/api/v1/accounts/me/profile/", files={"avatar": ("new.jpg", b2, "image/jpeg")}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_profile_s3_error(authenticated_client, s3_storage_fake):

    img = Image.new("RGB", (100, 100), "red")
    img_bytes = BytesIO()
    img.save(img_bytes, "JPEG")
    img_bytes.seek(0)

    with patch.object(
        s3_storage_fake, "upload_file", side_effect=S3FileUploadError("Fail")
    ):
        response = await authenticated_client.patch(
            "/api/v1/accounts/me/profile/",
            files={"avatar": ("fail.jpg", img_bytes, "image/jpeg")},
        )

    assert response.status_code == 502


@pytest.mark.asyncio
async def test_get_me_with_avatar(authenticated_client, s3_storage_fake, db_session):
    response = await authenticated_client.get("/api/v1/accounts/me/")
    assert response.status_code == 200
    data = response.json()
    assert "profile" in data


@pytest.mark.asyncio
async def test_get_me_with_avatar_url(authenticated_client, s3_storage_fake):
    response = await authenticated_client.get("/api/v1/accounts/me/")
    assert response.status_code == 200
    data = response.json()
    if data.get("profile") and data["profile"].get("avatar"):
        assert data["profile"]["avatar"].startswith("http")


@pytest.mark.asyncio
async def test_update_profile_creates_new_profile(authenticated_client, db_session):
    response = await authenticated_client.patch(
        "/api/v1/accounts/me/profile/", data={"first_name": "NewProfileUser"}
    )
    assert response.status_code == 200


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


@pytest.mark.asyncio
async def test_change_password_success(authenticated_client, db_session, user_factory):
    user = await user_factory.create_active_user()

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
        json={"old_password": "WrongOld123!", "new_password": "NewPass123!"},
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
        json={"old_password": "StrongTestPass123!", "new_password": "NewPass456!"},
    )
    assert response.status_code == 500


@pytest.mark.asyncio
async def test_password_reset_full_flow(client, db_session, user_factory):
    user = await user_factory.create_active_user()

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
    unique_email = f"{uuid.uuid4()}@example.com"
    user = await user_factory.create_user(email=unique_email, is_active=False)
    resp = await client.post(
        "/api/v1/accounts/password-reset/request/", json={"email": user.email}
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_password_reset_expired_token(client, db_session, user_factory):
    unique_email = f"{uuid.uuid4()}@example.com"
    user = await user_factory.create_active_user(email=unique_email)
    token = PasswordResetTokenModel(
        user_id=user.id,
        expires_at=datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=1),
    )
    db_session.add(token)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/accounts/reset-password/complete/",
        json={"email": user.email, "token": token.token, "password": "NewPass123!"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_admin_list_users(admin_client):
    response = await admin_client.get("/api/v1/accounts/admin/users/")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_admin_get_user_detail(admin_client, user_factory):
    user = await user_factory.create_active_user()
    response = await admin_client.get(f"/api/v1/accounts/admin/users/{user.id}/")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == user.id
    assert data["email"] == user.email


@pytest.mark.asyncio
async def test_admin_update_user(admin_client, user_factory):
    user = await user_factory.create_active_user()

    response = await admin_client.patch(
        f"/api/v1/accounts/admin/users/{user.id}/",
        json={"is_active": False, "group_id": 1},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is False


@pytest.mark.asyncio
async def test_admin_update_user_is_active(admin_client, user_factory):
    user = await user_factory.create_active_user()
    response = await admin_client.patch(
        f"/api/v1/accounts/admin/users/{user.id}/", json={"is_active": False}
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


@pytest.mark.asyncio
async def test_admin_list_users_with_filters(admin_client, user_factory):
    await user_factory.create_active_user()
    response = await admin_client.get("/api/v1/accounts/admin/users/?is_active=true")
    assert response.status_code == 200
