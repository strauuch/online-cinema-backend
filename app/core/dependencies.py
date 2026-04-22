import os

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from database.models.accounts import UserModel
from exceptions.security import TokenExpiredError, InvalidTokenError
from notifications import EmailSenderInterface, EmailSender
from security.interfaces import JWTAuthManagerInterface
from security.token_manager import JWTAuthManager
from storages.s3 import S3StorageInterface, S3StorageClient
from core.config import settings
from database import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/accounts/login/")


def get_settings():
    """
    Returns the application configuration settings instance.
    """
    return settings


def get_jwt_auth_manager(
    main_settings=Depends(get_settings),
) -> JWTAuthManagerInterface:
    """
    Initializes and returns a JWT authentication manager with configured secrets and algorithms.
    """
    return JWTAuthManager(
        secret_key_access=main_settings.SECRET_KEY_ACCESS,
        secret_key_refresh=main_settings.SECRET_KEY_REFRESH,
        algorithm=main_settings.JWT_SIGNING_ALGORITHM,
    )


def get_accounts_email_notificator(
    main_settings=Depends(get_settings),
) -> EmailSenderInterface:
    """
    Provides an email notification service configured for account-related operations
    (activation, password reset, etc.).
    """
    return EmailSender(
        hostname=main_settings.EMAIL_HOST,
        port=main_settings.EMAIL_PORT,
        email=main_settings.EMAIL_HOST_USER,
        password=main_settings.EMAIL_HOST_PASSWORD,
        use_tls=main_settings.EMAIL_USE_TLS,
        template_dir=main_settings.PATH_TO_EMAIL_TEMPLATES_DIR,
        activation_email_template_name=main_settings.ACTIVATION_EMAIL_TEMPLATE_NAME,
        activation_complete_email_template_name=main_settings.ACTIVATION_COMPLETE_EMAIL_TEMPLATE_NAME,
        password_email_template_name=main_settings.PASSWORD_RESET_TEMPLATE_NAME,
        password_complete_email_template_name=main_settings.PASSWORD_RESET_COMPLETE_TEMPLATE_NAME,
    )


def get_s3_storage_client(main_settings=Depends(get_settings)) -> S3StorageInterface:
    """
    Returns a client for interacting with S3-compatible storage using application settings.
    """
    return S3StorageClient(
        endpoint_url=main_settings.S3_STORAGE_ENDPOINT,
        access_key=main_settings.S3_STORAGE_ACCESS_KEY,
        secret_key=main_settings.S3_STORAGE_SECRET_KEY,
        bucket_name=main_settings.S3_BUCKET_NAME,
    )


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
    db: AsyncSession = Depends(get_db),
) -> UserModel:
    """
    Dependency to retrieve the currently authenticated user from a JWT access token.

    Extracts the token from the Authorization header, decodes it to retrieve the user ID,
    and fetches the corresponding user from the database along with their group information.
    Ensures that the user exists and their account is active.

    Args:
        token (str): The JWT access token provided in the 'Authorization' header.
        jwt_manager (JWTAuthManagerInterface): The manager responsible for decoding JWT tokens.
        db (AsyncSession): The asynchronous database session for user retrieval.

    Returns:
        UserModel: The authenticated user instance including related group data.

    Raises:
        HTTPException:
            - 401 Unauthorized if the token is expired, invalid, or missing the user ID.
            - 401 Unauthorized if the user associated with the token no longer exists.
            - 403 Forbidden if the user account is present but not activated.
    """
    try:
        payload = jwt_manager.decode_access_token(token)
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired."
        )
    except (InvalidTokenError, Exception):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token."
        )

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload."
        )

    stmt = (
        select(UserModel)
        .where(UserModel.id == user_id)
        .options(joinedload(UserModel.group))
    )
    user = await db.scalar(stmt)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not activated.",
        )

    return user
