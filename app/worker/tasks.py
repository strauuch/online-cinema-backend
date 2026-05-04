import logging

from datetime import datetime, timezone
from sqlalchemy.orm import sessionmaker
from sqlalchemy import delete

from worker.celery_app import celery_app
from database.engine import sync_postgresql_engine
from database.models.accounts import (
    ActivationTokenModel,
    PasswordResetTokenModel,
    RefreshTokenModel,
)

SessionLocal = sessionmaker(bind=sync_postgresql_engine)

logger = logging.getLogger(__name__)


@celery_app.task
def cleanup_expired_tokens():
    """
    Periodic task to clean up expired tokens.
    """
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        stmt_act = (
            delete(ActivationTokenModel)
            .where(ActivationTokenModel.expires_at < now)
            .returning(ActivationTokenModel.id)
        )
        stmt_pwd = (
            delete(PasswordResetTokenModel)
            .where(PasswordResetTokenModel.expires_at < now)
            .returning(PasswordResetTokenModel.id)
        )
        stmt_ref = (
            delete(RefreshTokenModel)
            .where(RefreshTokenModel.expires_at < now)
            .returning(RefreshTokenModel.id)
        )

        deleted_act = db.execute(stmt_act).all()
        deleted_pwd = db.execute(stmt_pwd).all()
        deleted_ref = db.execute(stmt_ref).all()

        db.commit()

        logger.info(
            f"Cleanup completed. Deleted counts: "
            f"Activation: {len(deleted_act)}, "
            f"PasswordReset: {len(deleted_pwd)}, "
            f"Refresh: {len(deleted_ref)}"
        )
        return "Tokens cleanup successful."

    except Exception as e:
        db.rollback()
        logger.error(f"Critical error during token cleanup: {str(e)}", exc_info=True)
        raise e
    finally:
        db.close()
