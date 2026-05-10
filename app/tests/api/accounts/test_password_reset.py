import pytest

from sqlalchemy import select

from app.database.models.accounts import UserModel, PasswordResetTokenModel


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
