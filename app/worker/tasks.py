from datetime import datetime, timezone
from sqlalchemy.orm import sessionmaker
from sqlalchemy import delete

from app.worker.celery_app import celery_app
from app.database.engine import sync_postgresql_engine
from app.database.models.accounts import (
    ActivationTokenModel,
    PasswordResetTokenModel,
    RefreshTokenModel
)

SessionLocal = sessionmaker(bind=sync_postgresql_engine)

@celery_app.task
def cleanup_expired_tokens():
    """
    Periodic task to clean up expired tokens.
    """
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        db.execute(
            delete(ActivationTokenModel).where(ActivationTokenModel.expires_at < now)
        )

        db.execute(
            delete(PasswordResetTokenModel).where(PasswordResetTokenModel.expires_at < now)
        )

        db.execute(
            delete(RefreshTokenModel).where(RefreshTokenModel.expires_at < now)
        )

        db.commit()
        return "Expired tokens cleanup completed successfully."
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()