import logging

from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload

from database.models.accounts import UserModel, UserGroupEnum
from database.models.movies import MovieRatingModel, MovieModel
from exceptions.security import TokenExpiredError, InvalidTokenError
from notifications import EmailSenderInterface, EmailSender
from security.interfaces import JWTAuthManagerInterface
from security.token_manager import JWTAuthManager
from storages.s3 import S3StorageInterface, S3StorageClient
from core.config import settings
from database import get_db

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/accounts/login/", auto_error=False
)

logger = logging.getLogger(__name__)


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
    """
    try:
        payload = jwt_manager.decode_access_token(token)
        logger.info(f"Token decoded for user_id: {payload.get('user_id')}")
    except TokenExpiredError:
        logger.warning("Authentication failed: Token expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired."
        )
    except (InvalidTokenError, Exception):
        logger.error(
            "Authentication failed: Invalid token or unexpected error", exc_info=True
        )
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
        logger.warning(f"Authentication failed: User with ID {user_id} not found in DB")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )

    if not user.is_active:
        logger.warning(f"Access denied: User {user.email} is inactive")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not activated.",
        )

    return user


async def get_current_admin_user(
    current_user: UserModel = Depends(get_current_user),
) -> UserModel:
    """
    Dependency to ensure the current authenticated user is an administrator.
    """
    if current_user.group.name != UserGroupEnum.ADMIN:
        logger.warning(
            f"Unauthorized admin access attempt by user: {current_user.email}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return current_user


async def get_current_staff_user(
    current_user: UserModel = Depends(get_current_user),
) -> UserModel:
    """
    Dependency to ensure the current authenticated user is either an Admin or a Moderator.
    """
    if current_user.group.name not in [UserGroupEnum.ADMIN, UserGroupEnum.MODERATOR]:
        logger.warning(
            f"Unauthorized staff access attempt by user: {current_user.email}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff access required (Admin or Moderator).",
        )
    return current_user


async def get_current_user_optional(
    token: str = Depends(oauth2_scheme),
    jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
    db: AsyncSession = Depends(get_db),
) -> Optional[UserModel]:
    """
    Optional dependency: returns UserModel if the token is valid, otherwise returns None without raising an exception.
    """
    if not token:
        return None

    try:
        payload = jwt_manager.decode_access_token(token)
        user_id = payload.get("user_id")
        if not user_id:
            return None
        stmt = (
            select(UserModel)
            .where(UserModel.id == user_id)
            .options(joinedload(UserModel.group))
        )
        user = await db.scalar(stmt)

        if user and user.is_active:
            return user

    except Exception:
        return None

    return None


async def update_movie_rating_stats(movie_id: int, db: AsyncSession):
    """
    Recalculates the average rating and number of ratings for a movie.
    """
    stmt = select(
        func.avg(MovieRatingModel.score).label("avg_score"),
        func.count(MovieRatingModel.movie_id).label("total_count"),
    ).where(MovieRatingModel.movie_id == movie_id)
    result = await db.execute(stmt)
    stats = result.one_or_none()
    logger.info(f"Recalculating stats for movie_id {movie_id}. Found stats: {stats}")

    movie = await db.get(MovieModel, movie_id)
    if movie and stats:
        movie.rating_avg = round(float(stats.avg_score or 0.0), 1)
        movie.rating_count = int(stats.total_count or 0)
        logger.info(
            f"Movie {movie_id} stats updated: avg={movie.rating_avg}, count={movie.rating_count}"
        )
    else:
        logger.warning(f"Failed to update stats: Movie {movie_id} not found")
