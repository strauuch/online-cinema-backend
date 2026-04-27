from datetime import datetime, timezone
from typing import cast

from fastapi import APIRouter, Depends, status, HTTPException, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from core.config import Settings
from core.dependencies import (
    get_jwt_auth_manager,
    get_settings,
    get_accounts_email_notificator,
    get_current_user,
    get_s3_storage_client,
    get_current_admin_user,
)
from database import get_db
from database.models.accounts import (
    UserModel,
    UserGroupModel,
    UserGroupEnum,
    ActivationTokenModel,
    PasswordResetTokenModel,
    RefreshTokenModel,
    UserProfileModel,
)
from exceptions.security import BaseSecurityError
from notifications import EmailSenderInterface
from schemas.accounts import (
    UserRegistrationRequestSchema,
    UserRegistrationResponseSchema,
    MessageResponseSchema,
    UserActivationRequestSchema,
    PasswordResetRequestSchema,
    PasswordResetCompleteRequestSchema,
    UserLoginResponseSchema,
    TokenRefreshRequestSchema,
    TokenRefreshResponseSchema,
    PasswordChangeRequestSchema,
    ProfileResponseSchema,
    ProfileUpdateRequestSchema,
    UserMeResponseSchema,
    AdminUserListResponseSchema,
    AdminUserUpdateResponseSchema,
    AdminUserUpdateRequestSchema,
    AdminUserDetailResponseSchema,
    UserActivationResendRequestSchema,
)
from security.interfaces import JWTAuthManagerInterface
from storages.interfaces import S3StorageInterface

router = APIRouter()


@router.post(
    "/register/",
    response_model=UserRegistrationResponseSchema,
    summary="User Registration",
    description="Register a new user with an email and password.",
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {
            "description": "Conflict - User with this email already exists.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "A user with this email test@example.com already exists."
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error - An error occurred during user creation.",
            "content": {
                "application/json": {
                    "example": {"detail": "An error occurred during user creation."}
                }
            },
        },
    },
)
async def register_user(
    user_data: UserRegistrationRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> UserRegistrationResponseSchema:
    """
    Endpoint for user registration.
    """
    stmt = select(UserModel).where(UserModel.email == user_data.email)
    result = await db.execute(stmt)
    existing_user = result.scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with this email {user_data.email} already exists.",
        )

    stmt = select(UserGroupModel).where(UserGroupModel.name == UserGroupEnum.USER)
    result = await db.execute(stmt)
    user_group = result.scalars().first()
    if not user_group:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Default user group not found.",
        )

    try:
        new_user = UserModel.create(
            email=str(user_data.email),
            raw_password=user_data.password,
            group_id=user_group.id,
        )
        db.add(new_user)
        await db.flush()

        activation_token = ActivationTokenModel(user_id=new_user.id)
        db.add(activation_token)

        await db.commit()
        await db.refresh(new_user)
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during user creation.",
        ) from e

    background_tasks.add_task(
        email_sender.send_activation_email, new_user.email, settings.activation_link
    )

    return UserRegistrationResponseSchema.model_validate(new_user)


@router.post(
    "/activate/",
    response_model=MessageResponseSchema,
    summary="Activate User Account",
    description="Activate a user's account using their email and activation token.",
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": "Bad Request - The activation token is invalid or expired, "
            "or the user account is already active.",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token": {
                            "summary": "Invalid Token",
                            "value": {"detail": "Invalid or expired activation token."},
                        },
                        "already_active": {
                            "summary": "Account Already Active",
                            "value": {"detail": "User account is already active."},
                        },
                    }
                }
            },
        },
    },
)
async def activate_account(
    activation_data: UserActivationRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> MessageResponseSchema:
    """
    Endpoint to activate a user's account.
    """
    stmt = (
        select(ActivationTokenModel)
        .options(joinedload(ActivationTokenModel.user))
        .join(UserModel)
        .where(
            UserModel.email == activation_data.email,
            ActivationTokenModel.token == activation_data.token,
        )
    )
    result = await db.execute(stmt)
    token_record = result.scalars().first()

    now_utc = datetime.now(timezone.utc)
    if (
        not token_record
        or cast(datetime, token_record.expires_at).replace(tzinfo=timezone.utc)
        < now_utc
    ):
        if token_record:
            await db.delete(token_record)
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired activation token.",
        )

    user = token_record.user
    if user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is already active.",
        )

    user.is_active = True
    await db.delete(token_record)
    await db.flush()

    new_profile = UserProfileModel(user_id=user.id)
    db.add(new_profile)

    await db.commit()

    background_tasks.add_task(
        email_sender.send_activation_complete_email,
        str(activation_data.email),
        settings.login_link,
    )

    return MessageResponseSchema(message="User account activated successfully.")


@router.post(
    "/activate/resend/",
    response_model=MessageResponseSchema,
    summary="Resend Activation Token",
    description="Deletes any existing activation token for the user and sends a new one.",
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": "Bad Request - User account is already active.",
            "content": {
                "application/json": {
                    "example": {"detail": "User account is already active."}
                }
            },
        },
        500: {
            "description": "Internal Server Error - Database error.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "An error occurred during token regeneration."
                    }
                }
            },
        },
    },
)
async def resend_activation_token(
    data: UserActivationResendRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> MessageResponseSchema:
    """
    Endpoint to resend the activation token.
    """
    stmt = select(UserModel).filter_by(email=data.email)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user:
        return MessageResponseSchema(
            message="If your email is registered, you will receive a new activation link."
        )

    if user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is already active.",
        )

    try:
        await db.execute(
            delete(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id)
        )

        new_token = ActivationTokenModel(user_id=cast(int, user.id))
        db.add(new_token)

        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the request.",
        )

    background_tasks.add_task(
        email_sender.send_activation_email, user.email, settings.activation_link
    )

    return MessageResponseSchema(
        message="If your email is registered, you will receive a new activation link."
    )


@router.post(
    "/password-change/",
    response_model=MessageResponseSchema,
    summary="Change User Password",
    description="Change the password for an authenticated user by verifying the old password.",
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": "Bad Request - Invalid old password or weak new password.",
            "content": {
                "application/json": {"example": {"detail": "Invalid old password."}}
            },
        },
    },
)
async def change_password(
    data: PasswordChangeRequestSchema,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> MessageResponseSchema:
    """
    Endpoint to change the user's password.

    The new password is automatically validated by the schema
    using accounts_validators.validate_password_strength.
    """
    if not current_user.verify_password(data.old_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid old password.",
        )

    if data.old_password == data.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from the old one.",
        )

    try:
        current_user.password = data.new_password
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating the password.",
        )

    return MessageResponseSchema(message="Password changed successfully.")


@router.post(
    "/password-reset/request/",
    response_model=MessageResponseSchema,
    summary="Request Password Reset Token",
    description=(
        "Allows a user to request a password reset token. If the user exists and is active, "
        "a new token will be generated and any existing tokens will be invalidated."
    ),
    status_code=status.HTTP_200_OK,
)
async def request_password_reset_token(
    data: PasswordResetRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> MessageResponseSchema:
    """
    Endpoint to request a password reset token.
    """
    stmt = select(UserModel).filter_by(email=data.email)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user or not user.is_active:
        return MessageResponseSchema(
            message="If you are registered, you will receive an email with instructions."
        )

    await db.execute(
        delete(PasswordResetTokenModel).where(
            PasswordResetTokenModel.user_id == user.id
        )
    )

    reset_token = PasswordResetTokenModel(user_id=cast(int, user.id))
    db.add(reset_token)
    await db.commit()

    background_tasks.add_task(
        email_sender.send_password_reset_email,
        str(data.email),
        settings.password_reset_link,
    )

    return MessageResponseSchema(
        message="If you are registered, you will receive an email with instructions."
    )


@router.post(
    "/reset-password/complete/",
    response_model=MessageResponseSchema,
    summary="Reset User Password",
    description="Reset a user's password if a valid token is provided.",
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": (
                "Bad Request - The provided email or token is invalid, "
                "the token has expired, or the user account is not active."
            ),
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_email_or_token": {
                            "summary": "Invalid Email or Token",
                            "value": {"detail": "Invalid email or token."},
                        },
                        "expired_token": {
                            "summary": "Expired Token",
                            "value": {"detail": "Invalid email or token."},
                        },
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error - An error occurred while resetting the password.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "An error occurred while resetting the password."
                    }
                }
            },
        },
    },
)
async def reset_password(
    data: PasswordResetCompleteRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> MessageResponseSchema:
    """
    Endpoint for resetting a user's password.
    """
    stmt = select(UserModel).filter_by(email=data.email)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email or token."
        )

    stmt = select(PasswordResetTokenModel).filter_by(user_id=user.id)
    result = await db.execute(stmt)
    token_record = result.scalars().first()

    if not token_record or token_record.token != data.token:
        if token_record:
            await db.delete(token_record)
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email or token."
        )

    expires_at = cast(datetime, token_record.expires_at).replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        await db.delete(token_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email or token."
        )

    try:
        user.password = data.password
        await db.delete(token_record)
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while resetting the password.",
        )

    background_tasks.add_task(
        email_sender.send_password_reset_complete_email,
        str(data.email),
        settings.login_link,
    )

    return MessageResponseSchema(message="Password reset successfully.")


@router.post(
    "/login/",
    response_model=UserLoginResponseSchema,
    summary="User Login",
    description="Authenticate a user and return access and refresh tokens.",
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {
            "description": "Unauthorized - Invalid email or password.",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid email or password."}
                }
            },
        },
        403: {
            "description": "Forbidden - User account is not activated.",
            "content": {
                "application/json": {
                    "example": {"detail": "User account is not activated."}
                }
            },
        },
        500: {
            "description": "Internal Server Error - An error occurred while processing the request.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "An error occurred while processing the request."
                    }
                }
            },
        },
    },
)
async def login_user(
    background_tasks: BackgroundTasks,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
    jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
) -> UserLoginResponseSchema:
    """
    Endpoint for user login.
    If the account is not active, checks for a valid token and resends if necessary.
    """
    email = form_data.username
    password = form_data.password

    stmt = select(UserModel).filter_by(email=email)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user or not user.verify_password(password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not user.is_active:
        stmt = select(ActivationTokenModel).where(
            ActivationTokenModel.user_id == user.id
        )
        result = await db.execute(stmt)
        token_record = result.scalars().first()

        now = datetime.now(timezone.utc)

        if (
            not token_record
            or cast(datetime, token_record.expires_at).replace(tzinfo=timezone.utc)
            < now
        ):
            try:
                if token_record:
                    await db.delete(token_record)

                new_token = ActivationTokenModel(user_id=cast(int, user.id))
                db.add(new_token)
                await db.commit()

                background_tasks.add_task(
                    email_sender.send_activation_email,
                    user.email,
                    settings.activation_link,
                )

                detail_msg = "Account not activated. A new activation link has been sent to your email."
            except SQLAlchemyError:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Database error while regenerating token.",
                )
        else:
            detail_msg = "Account not activated. Please check your email for the activation link."

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail_msg,
        )

    jwt_refresh_token = jwt_manager.create_refresh_token({"user_id": user.id})

    try:
        refresh_token = RefreshTokenModel.create(
            user_id=user.id,
            days_valid=settings.LOGIN_TIME_DAYS,
            token=jwt_refresh_token,
        )
        db.add(refresh_token)
        await db.flush()
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the request.",
        )

    jwt_access_token = jwt_manager.create_access_token({"user_id": user.id})
    return UserLoginResponseSchema(
        access_token=jwt_access_token,
        refresh_token=jwt_refresh_token,
    )


@router.post(
    "/logout/",
    response_model=MessageResponseSchema,
    summary="User Logout",
    description="Revoke the user's refresh token, effectively logging them out.",
    status_code=status.HTTP_200_OK,
    responses={
        401: {
            "description": "Unauthorized - Invalid refresh token.",
            "content": {
                "application/json": {"example": {"detail": "Refresh token not found."}}
            },
        },
        500: {
            "description": "Internal Server Error - An error occurred during logout.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "An error occurred while processing the request."
                    }
                }
            },
        },
    },
)
async def logout_user(
    token_data: TokenRefreshRequestSchema,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> MessageResponseSchema:
    """
    Endpoint for user logout.
    """
    stmt = select(RefreshTokenModel).filter_by(
        token=token_data.refresh_token, user_id=current_user.id
    )
    result = await db.execute(stmt)
    refresh_token_record = result.scalars().first()

    if not refresh_token_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found or doesn't belong to this user.",
        )

    try:
        await db.delete(refresh_token_record)
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the request.",
        )

    return MessageResponseSchema(message="Successfully logged out.")


@router.post(
    "/refresh/",
    response_model=TokenRefreshResponseSchema,
    summary="Refresh Access Token",
    description="Refresh the access token using a valid refresh token.",
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": "Bad Request - The provided refresh token is invalid or expired.",
            "content": {
                "application/json": {"example": {"detail": "Token has expired."}}
            },
        },
        401: {
            "description": "Unauthorized - Refresh token not found.",
            "content": {
                "application/json": {"example": {"detail": "Refresh token not found."}}
            },
        },
        404: {
            "description": "Not Found - The user associated with the token does not exist.",
            "content": {"application/json": {"example": {"detail": "User not found."}}},
        },
    },
)
async def refresh_access_token(
    token_data: TokenRefreshRequestSchema,
    db: AsyncSession = Depends(get_db),
    jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
) -> TokenRefreshResponseSchema:
    """
    Endpoint to refresh an access token.
    """
    try:
        decoded_token = jwt_manager.decode_refresh_token(token_data.refresh_token)
        user_id = decoded_token.get("user_id")
    except BaseSecurityError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        )

    stmt = select(RefreshTokenModel).filter_by(token=token_data.refresh_token)
    result = await db.execute(stmt)
    refresh_token_record = result.scalars().first()
    if not refresh_token_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found.",
        )

    stmt = select(UserModel).filter_by(id=user_id)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    new_access_token = jwt_manager.create_access_token({"user_id": user_id})

    return TokenRefreshResponseSchema(access_token=new_access_token)


@router.get(
    "/me/",
    response_model=UserMeResponseSchema,
    summary="Get current user info",
)
async def get_me(
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    s3_client: S3StorageInterface = Depends(get_s3_storage_client),
) -> UserMeResponseSchema:

    await db.refresh(current_user, ["profile"])

    avatar_url = ""
    if current_user.profile and current_user.profile.avatar:
        avatar_url = await s3_client.get_file_url(current_user.profile.avatar)

    response = UserMeResponseSchema.model_validate(current_user)

    if response.profile:
        response.profile.avatar = avatar_url

    return response


@router.patch(
    "/me/profile/",
    response_model=ProfileResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Update User Profile",
    description="Update a personal profile with an avatar. Only for authenticated users without an existing profile.",
)
async def update_profile(
    profile_data: ProfileUpdateRequestSchema = Depends(
        ProfileUpdateRequestSchema.as_form
    ),
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    s3_client: S3StorageInterface = Depends(get_s3_storage_client),
) -> ProfileResponseSchema:
    """
    Endpoint to update a profile for the current authenticated user.
    """

    await db.refresh(current_user, ["profile"])
    profile = current_user.profile

    if not profile:
        profile = UserProfileModel(user_id=current_user.id)
        db.add(profile)

    if profile_data.avatar and profile_data.avatar.filename:
        avatar_path = f"avatars/user_{current_user.id}/{profile_data.avatar.filename}"
        try:
            content = await profile_data.avatar.read()
            await s3_client.upload_file(file_name=avatar_path, file_data=content)
            profile.avatar = avatar_path
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to upload avatar.",
            )

    data_to_update = profile_data.model_dump(exclude_unset=True, exclude={"avatar"})

    for key, value in data_to_update.items():
        setattr(profile, key, value)

    try:
        await db.commit()
        await db.refresh(profile)
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error."
        )

    avatar_url = ""
    if profile.avatar:
        avatar_url = await s3_client.get_file_url(profile.avatar)

    result = ProfileResponseSchema.model_validate(profile)
    result.avatar = avatar_url
    return result


# =============================================================================
# ADMIN ROUTES
# =============================================================================


@router.get(
    "/admin/users/",
    response_model=list[AdminUserListResponseSchema],
    summary="Admin: List all users",
)
async def list_users(
    limit: int = 10,
    offset: int = 0,
    email_query: str | None = None,
    group_id: int | None = None,
    is_active: bool | None = None,
    current_user: UserModel = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(UserModel)
        .options(joinedload(UserModel.group))
    )

    if email_query:
        stmt = stmt.where(UserModel.email.ilike(f"%{email_query}%"))

    if group_id:
        stmt = stmt.where(UserModel.group_id == group_id)

    if is_active is not None:
        stmt = stmt.where(UserModel.is_active == is_active)

    stmt = stmt.limit(limit).offset(offset).order_by(UserModel.id)

    result = await db.execute(stmt)
    return result.scalars().all()


@router.get(
    "/admin/users/{user_id}/",
    response_model=AdminUserDetailResponseSchema,
    summary="Admin: Get user details",
)
async def get_user(
    user_id: int,
    current_user: UserModel = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(UserModel)
        .options(joinedload(UserModel.group), joinedload(UserModel.profile))
        .where(UserModel.id == user_id)
    )

    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    return AdminUserDetailResponseSchema.model_validate(user)


@router.patch(
    "/admin/users/{user_id}/",
    response_model=AdminUserUpdateResponseSchema,
    summary="Admin: Update user status or group",
)
async def admin_update_user(
    user_id: int,
    data: AdminUserUpdateRequestSchema,
    current_user: UserModel = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(UserModel, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user, key, value)

    try:
        await db.commit()
        stmt = (
            select(UserModel)
            .options(joinedload(UserModel.group))
            .where(UserModel.id == user.id)
        )
        result = await db.execute(stmt)
        user = result.scalar_one()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error"
        )

    return AdminUserUpdateResponseSchema.model_validate(user)
