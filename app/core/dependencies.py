import os

from fastapi import Depends

from notifications import EmailSenderInterface, EmailSender
from security.interfaces import JWTAuthManagerInterface
from security.token_manager import JWTAuthManager
from storages.s3 import S3StorageInterface, S3StorageClient

from core.config import settings


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
