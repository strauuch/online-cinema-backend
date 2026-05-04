import logging
import uuid

from datetime import datetime, timezone
from typing import cast
from fastapi import APIRouter, Depends, status, HTTPException, BackgroundTasks, Query
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, delete, func
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
from schemas.pagination import Page
from security.interfaces import JWTAuthManagerInterface
from storages.interfaces import S3StorageInterface

router = APIRouter()

logger = logging.getLogger(__name__)

# =============================================================================
# USER ROUTES
# =============================================================================


@router.post(
    "/register/",
    response_model=UserRegistrationResponseSchema,
    summary="User Registration",
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"description": "Conflict - User with this email already exists."},
        500: {
            "description": "Internal Server Error - An error occurred during user creation.",
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
    Register a new user and send an activation email.
    - **Conflict (409)**: Email already registered.
    - **Background Task**: Activation link delivery.
    """
    logger.info(f"Registering new user with email: {user_data.email}")
    stmt = select(UserModel).where(UserModel.email == user_data.email)
    result = await db.execute(stmt)
    existing_user = result.scalars().first()
    if existing_user:
        logger.warning(
            f"Registration conflict: email {user_data.email} is already taken"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with this email {user_data.email} already exists.",
        )

    stmt = select(UserGroupModel).where(UserGroupModel.name == UserGroupEnum.USER)
    result = await db.execute(stmt)
    user_group = result.scalars().first()

    if not user_group:
        logger.error("Critical: Default USER group is missing in the database")
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
        logger.info(
            f"User created successfully: ID {new_user.id}, Email {new_user.email}"
        )

    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Failed to create user {user_data.email} due to DB error: {str(e)}",
            exc_info=True,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during user creation.",
        ) from e

    logger.info(f"Enqueued activation email for: {new_user.email}")

    background_tasks.add_task(
        email_sender.send_activation_email, new_user.email, settings.activation_link
    )

    return UserRegistrationResponseSchema.model_validate(new_user)


@router.post(
    "/activate/",
    response_model=MessageResponseSchema,
    summary="Activate User Account",
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": "Bad Request - The activation token is invalid or expired or the user account is already active.",
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
    Activate a user account using email and token.
    - **Success**: Account activated and profile initialized.
    - **Error (400)**: Token invalids, expired, or an account already active.
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
            logger.warning(
                f"Activation failed: token expired for user {activation_data.email}"
            )
        else:
            logger.warning(
                f"Activation failed: invalid token/email combination for {activation_data.email}"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired activation token.",
        )

    user = token_record.user
    if user.is_active:
        logger.info(f"Activation skipped: account {user.id} is already active")
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

    logger.info(
        f"User {user.id} successfully activated their account and profile created. Enqueued welcome email for {activation_data.email}"
    )

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
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": "Bad Request - User account is already active.",
        },
        500: {
            "description": "Internal Server Error - Database error.",
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
    Regenerate and resend activation token.
    - **Logic**: Deletes any existing tokens before creating a new one.
    - **Validation**: Only for inactive accounts.
    """
    logger.info(f"Resend activation token requested for email: {data.email}")
    stmt = select(UserModel).filter_by(email=data.email)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user:
        logger.info(f"Resend token failed: email {data.email} not found in database")
        return MessageResponseSchema(
            message="If your email is registered, you will receive a new activation link."
        )

    if user.is_active:
        logger.warning(f"Resend token failed: user {user.id} is already active")
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
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"DB error during token regeneration for user {user.id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the request.",
        )

    logger.info(f"New activation token generated and enqueued for user {user.id}")
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
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": "Bad Request - Invalid old password or weak new password.",
        },
    },
)
async def change_password(
    data: PasswordChangeRequestSchema,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> MessageResponseSchema:
    """
    Update password for the currently authenticated user.
    - **Security**: Verifies old password.
    - **Validation**: New password must be different and meet strength requirements.
    """
    logger.info(f"Password change initiated for user {current_user.id}")

    current_user_id = current_user.id

    if not current_user.verify_password(data.old_password):
        logger.warning(
            f"Failed password change for user {current_user_id}: invalid old password"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid old password.",
        )

    if data.old_password == data.new_password:
        logger.info(
            f"Password change rejected for user {current_user_id}: new password matches old one"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from the old one.",
        )

    try:
        current_user.password = data.new_password
        await db.commit()
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"DB error during password update for user {current_user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating the password.",
        )

    logger.info(f"Password successfully changed for user {current_user_id}")
    return MessageResponseSchema(message="Password changed successfully.")


@router.post(
    "/password-reset/request/",
    response_model=MessageResponseSchema,
    summary="Request Password Reset Token",
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
    Allows a user to request a password reset token. If the user exists and is active, a new token will be generated and any existing tokens will be invalidated..
    - **Privacy**: Returns a success message even if the user doesn't exist.
    - **Restriction**: Works only for active accounts.
    """
    logger.info(f"Password reset requested for email: {data.email}")
    stmt = select(UserModel).filter_by(email=data.email)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user or not user.is_active:
        logger.info(f"Reset request ignored: email {data.email} not found or inactive")
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
    logger.debug(f"Generated new reset token for user {user.id}")
    await db.commit()

    logger.info(f"Reset token successfully saved for user {user.id}")

    logger.info(f"Enqueuing reset email to {data.email}")
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
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": (
                "Bad Request - The provided email or token is invalid, "
                "the token has expired, or the user account is not active."
            )
        },
        500: {
            "description": "Internal Server Error - An error occurred while resetting the password.",
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
    Set a new password using a valid reset token.
    - **Validation**: Token must match and be within the expiration period.
    - **Success**: Token is deleted after use.
    """
    logger.info(f"Attempting password reset completion for email: {data.email}")
    stmt = select(UserModel).filter_by(email=data.email)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user or not user.is_active:
        logger.warning(f"Reset failed: user {data.email} not found or inactive")
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
            logger.warning(
                f"Reset failed: invalid token provided for user {user.id}. Token deleted."
            )
        else:
            logger.warning(f"Reset failed: no token found in DB for user {user.id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email or token."
        )

    expires_at = cast(datetime, token_record.expires_at).replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        await db.delete(token_record)
        await db.commit()
        logger.warning(f"Reset failed: token expired for user {user.id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email or token."
        )

    try:
        user.password = data.password
        await db.delete(token_record)
        await db.commit()
        logger.info(f"Password successfully reset for user {user.id}. Token consumed.")
    except SQLAlchemyError:
        await db.rollback()
        logger.error(
            f"Critical error during password reset for user {user.id}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while resetting the password.",
        )

    logger.info(f"Enqueuing password reset confirmation email to {data.email}")
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
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {
            "description": "Unauthorized - Invalid email or password.",
        },
        403: {
            "description": "Forbidden - User account is not activated.",
        },
        500: {
            "description": "Internal Server Error - An error occurred while processing the request.",
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
    Authenticate user and return JWT tokens.
    - **Auto-resend**: Triggers a new activation email if account is inactive and token expired.
    - **Response**: Returns Access and Refresh tokens.
    """
    email = form_data.username
    password = form_data.password

    logger.info(f"Login attempt for user: {email}")
    stmt = select(UserModel).filter_by(email=email)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user or not user.verify_password(password):
        logger.warning(f"Failed login attempt: invalid credentials for email {email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not user.is_active:
        logger.info(f"Login blocked: Account {user.id} is not active")
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
                logger.info(
                    f"Activation token regenerated and enqueued for inactive user {user.id}"
                )

                background_tasks.add_task(
                    email_sender.send_activation_email,
                    user.email,
                    settings.activation_link,
                )

                detail_msg = "Account not activated. A new activation link has been sent to your email."
            except SQLAlchemyError:
                await db.rollback()
                logger.error(
                    f"DB error during activation token regeneration for user {user.id}",
                    exc_info=True,
                )
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
        logger.debug(f"Storing new refresh token in DB for user {user.id}")
    except SQLAlchemyError:
        await db.rollback()
        logger.error(f"Failed to save refresh token for user {user.id}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the request.",
        )

    jwt_access_token = jwt_manager.create_access_token({"user_id": user.id})
    logger.info(f"User {user.id} logged in successfully. Tokens issued.")

    return UserLoginResponseSchema(
        access_token=jwt_access_token,
        refresh_token=jwt_refresh_token,
    )


@router.post(
    "/logout/",
    response_model=MessageResponseSchema,
    summary="User Logout",
    status_code=status.HTTP_200_OK,
    responses={
        401: {
            "description": "Unauthorized - Invalid refresh token.",
        },
        500: {
            "description": "Internal Server Error - An error occurred during logout.",
        },
    },
)
async def logout_user(
    token_data: TokenRefreshRequestSchema,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> MessageResponseSchema:
    """
    Log out the user by revoking their refresh token.
    - **Action**: Deletes the specific RefreshToken record from the database.
    """
    logger.info(f"Logout initiated for user {current_user.id}")

    current_user_id = current_user.id

    stmt = select(RefreshTokenModel).filter_by(
        token=token_data.refresh_token, user_id=current_user_id
    )
    result = await db.execute(stmt)
    refresh_token_record = result.scalars().first()

    if not refresh_token_record:
        logger.warning(
            f"Logout failed: Refresh token not found or ownership mismatch for user {current_user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found or doesn't belong to this user.",
        )

    try:
        await db.delete(refresh_token_record)
        await db.commit()
        logger.info(f"User {current_user_id} logged out successfully. Session revoked.")
    except SQLAlchemyError:
        await db.rollback()
        logger.error(
            f"DB error during logout for user {current_user_id}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the request.",
        )

    return MessageResponseSchema(message="Successfully logged out.")


@router.post(
    "/refresh/",
    response_model=TokenRefreshResponseSchema,
    summary="Refresh Access Token",
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": "Bad Request - The provided refresh token is invalid or expired.",
        },
        401: {
            "description": "Unauthorized - Refresh token not found.",
        },
        404: {
            "description": "Not Found - The user associated with the token does not exist.",
        },
    },
)
async def refresh_access_token(
    token_data: TokenRefreshRequestSchema,
    db: AsyncSession = Depends(get_db),
    jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
) -> TokenRefreshResponseSchema:
    """
    Issue a new access token using a valid refresh token.
    - **Security**: Validates token existence in DB and JWT integrity.
    """
    logger.debug("Access token refresh requested")
    try:
        decoded_token = jwt_manager.decode_refresh_token(token_data.refresh_token)
        user_id = decoded_token.get("user_id")
    except BaseSecurityError as error:
        logger.warning(f"JWT Refresh failed: {str(error)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        )

    stmt = select(RefreshTokenModel).filter_by(token=token_data.refresh_token)
    result = await db.execute(stmt)
    refresh_token_record = result.scalars().first()
    if not refresh_token_record:
        logger.warning(
            f"Refresh failed: Token not found in database (possibly revoked or reused)"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found.",
        )

    stmt = select(UserModel).filter_by(id=user_id)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user:
        logger.error(
            f"Refresh failed: Token valid, but user {user_id} does not exist in DB"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    new_access_token = jwt_manager.create_access_token({"user_id": user_id})
    logger.info(f"Access token successfully refreshed for user {user_id}")

    return TokenRefreshResponseSchema(access_token=new_access_token)


@router.get(
    "/me/",
    response_model=UserMeResponseSchema,
    summary="Get current user info",
    responses={
        401: {"description": "Unauthorized - Invalid or missing access token."},
    },
)
async def get_me(
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    s3_client: S3StorageInterface = Depends(get_s3_storage_client),
) -> UserMeResponseSchema:
    """
    Retrieve current user's full data.
    - **Inclusions**: Group details, profile info, and S3 avatar URL.
    """
    logger.debug(f"Fetching profile data for user {current_user.id}")
    await db.refresh(current_user, ["profile"])

    avatar_url = ""
    if current_user.profile and current_user.profile.avatar:
        logger.debug(f"Generating S3 URL for user {current_user.id} avatar")
        avatar_url = await s3_client.get_file_url(current_user.profile.avatar)

    logger.debug(f"Profile data successfully retrieved for user {current_user.id}")

    response = UserMeResponseSchema.model_validate(current_user)

    if response.profile:
        response.profile.avatar = avatar_url

    return response


@router.patch(
    "/me/profile/",
    response_model=ProfileResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Update User Profile",
    responses={
        401: {"description": "Unauthorized."},
        502: {"description": "Bad Gateway - Failed to upload avatar to storage."},
        500: {"description": "Internal Server Error - Database update failed."},
    },
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
    Create or update user profile information.
    - **Avatar**: Handles file upload to S3 storage.
    - **Storage**: Updates existing profile or creates a new one if missing.
    """
    logger.info(f"User {current_user.id} initiated profile update")

    await db.refresh(current_user, ["profile"])
    profile = current_user.profile
    current_user_id = current_user.id

    if not profile:
        logger.info(f"Creating missing profile record for user {current_user_id}")
        profile = UserProfileModel(user_id=current_user_id)
        db.add(profile)

    if profile_data.avatar and profile_data.avatar.filename:
        old_avatar_path = profile.avatar

        file_ext = profile_data.avatar.filename.split(".")[-1]
        unique_filename = f"{uuid.uuid4()}.{file_ext}"
        new_avatar_path = f"avatars/user_{current_user_id}/{unique_filename}"

        try:
            content = await profile_data.avatar.read()
            logger.info(
                f"User {current_user_id} uploading new avatar: {profile_data.avatar.filename}"
            )
            await s3_client.upload_file(file_name=new_avatar_path, file_data=content)
            profile.avatar = new_avatar_path

            if old_avatar_path:
                try:
                    await s3_client.delete_file(old_avatar_path)
                except Exception as e:
                    logger.error(f"Failed to delete old avatar {old_avatar_path}: {e}")
        except Exception:
            logger.error(f"S3 upload failed for user {current_user_id}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to upload avatar.",
            )

    data_to_update = profile_data.model_dump(exclude_unset=True, exclude={"avatar"})

    logger.debug(
        f"Updating fields {list(data_to_update.keys())} for user {current_user_id}"
    )
    for key, value in data_to_update.items():
        setattr(profile, key, value)

    try:
        await db.commit()
        await db.refresh(profile)
    except SQLAlchemyError:
        await db.rollback()
        logger.error(
            f"Failed to save profile changes for user {current_user_id} in DB",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error."
        )

    avatar_url = ""
    if profile.avatar:
        avatar_url = await s3_client.get_file_url(profile.avatar)

    result = ProfileResponseSchema.model_validate(profile)
    result.avatar = avatar_url

    logger.info(f"Profile updated successfully for user {current_user_id}")
    return result


# =============================================================================
# ADMIN ROUTES
# =============================================================================


@router.get(
    "/admin/users/",
    response_model=Page[AdminUserListResponseSchema],
    summary="List all users (Paginated) [Admin]",
    responses={
        401: {"description": "Unauthorized."},
        403: {"description": "Forbidden - Admin privileges required."},
    },
)
async def list_users(
    page: int = Query(1, ge=1, description="Current page number"),
    size: int = Query(10, ge=1, le=100, description="Items per page"),
    email_query: str | None = None,
    group_id: int | None = None,
    is_active: bool | None = None,
    current_user: UserModel = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    [Admin] Get a paginated list of users.
    - **Filters**: Email (ILike), Group ID, and Active status.
    - **Access**: Strictly for users with Admin group.
    """
    logger.info(
        f"Admin {current_user.id} requested user list (page={page}, size={size})"
    )

    try:
        stmt = select(UserModel).options(joinedload(UserModel.group))

        if email_query:
            logger.debug(f"Applying email filter: {email_query}")
            stmt = stmt.where(UserModel.email.ilike(f"%{email_query}%"))

        if group_id:
            logger.debug(f"Filtering by group_id: {group_id}")
            stmt = stmt.where(UserModel.group_id == group_id)

        if is_active is not None:
            logger.debug(f"Filtering by is_active status: {is_active}")
            stmt = stmt.where(UserModel.is_active == is_active)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_count = await db.scalar(count_stmt) or 0

        stmt = (
                stmt.order_by(UserModel.id)
                .limit(size)
                .offset((page - 1) * size)
            )

        result = await db.execute(stmt)

        users = result.scalars().all()
        logger.info(f"Admin {current_user.id} retrieved {len(users)} users (Total: {total_count})")

        return Page(
                items=users,
                total=total_count,
                page=page,
                size=size,
                total_pages=(total_count + size - 1) // size if total_count > 0 else 0,
            )
    except SQLAlchemyError as e:
        logger.error(f"Database error in admin list_users: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error occurred while fetching user list."
        )


@router.get(
    "/admin/users/{user_id}/",
    response_model=AdminUserDetailResponseSchema,
    summary="Update user status or group [Admin]",
    responses={
        401: {"description": "Unauthorized."},
        403: {"description": "Forbidden."},
        404: {"description": "User not found."},
        500: {"description": "Database error."},
    },
)
async def get_user(
    user_id: int,
    current_user: UserModel = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    [Admin] Fetch detailed information for a specific user.
    - **Includes**: Relations with Group and Profile.
    - **Error (404)**: User does not exist.
    """
    logger.info(
        f"Admin {current_user.id} requested detailed view for user_id: {user_id}"
    )
    stmt = (
        select(UserModel)
        .options(joinedload(UserModel.group), joinedload(UserModel.profile))
        .where(UserModel.id == user_id)
    )

    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user:
        logger.warning(
            f"Admin {current_user.id} tried to access non-existent user_id: {user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    logger.info(
        f"User details for ID {user_id} successfully sent to Admin {current_user.id}"
    )

    return AdminUserDetailResponseSchema.model_validate(user)


@router.patch(
    "/admin/users/{user_id}/",
    response_model=AdminUserUpdateResponseSchema,
    summary="Get user details  [Admin]",
    responses={
        401: {"description": "Unauthorized - Missing or invalid token."},
        403: {"description": "Forbidden - Admin access only."},
        404: {"description": "User not found."},
    },
)
async def admin_update_user(
    user_id: int,
    data: AdminUserUpdateRequestSchema,
    current_user: UserModel = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    [Admin] Update user account status or group.
    - **Fields**: Supports partial updates (patching) for 'is_active' and 'group_id'.
    """
    logger.info(f"Admin {current_user.id} is patching user {user_id}")

    current_user_id = current_user.id

    user = await db.get(UserModel, user_id)
    if not user:
        logger.warning(
            f"Admin {current_user_id} attempted to update non-existent user {user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    update_data = data.model_dump(exclude_unset=True)
    logger.debug(
        f"Admin {current_user_id} update payload for user {user_id}: {update_data}"
    )
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
        logger.error(
            f"Failed to update user {user_id} by admin {current_user_id} due to DB error",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error"
        )

    logger.info(
        f"Admin {current_user_id} successfully updated user {user_id}. Fields: {list(update_data.keys())}"
    )

    return AdminUserUpdateResponseSchema.model_validate(user)
