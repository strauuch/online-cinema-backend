import asyncio
import logging
import stripe

from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import sessionmaker
from sqlalchemy import delete

from app.core.config import settings
from app.database.models.enums import OrderStatusEnum, PaymentStatusEnum
from app.notifications import EmailSender
from app.worker.celery_app import celery_app
from app.database.engine import sync_postgresql_engine
from app.database.models import accounts, movies, carts, orders, payments
from app.database.models.accounts import (
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


@celery_app.task
def sync_stuck_orders():
    """
    Check Stripe for orders that are PENDING but might be paid.
    """
    db = SessionLocal()
    try:
        pending_orders = (
            db.query(orders.OrderModel)
            .filter(orders.OrderModel.status == OrderStatusEnum.PENDING)
            .all()
        )

        for order in pending_orders:
            sessions = stripe.checkout.Session.list(
                limit=100,
                created={
                    "gte": int(
                        (datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()
                    )
                },
            )
            for s in sessions.data:
                if (
                    s.metadata.get("order_id") == str(order.id)
                    and s.payment_status == "paid"
                ):
                    order.status = OrderStatusEnum.PAID

                    payment = payments.PaymentModel(
                        user_id=order.user_id,
                        order_id=order.id,
                        status=PaymentStatusEnum.SUCCESSFUL,
                        amount=order.total_amount,
                        external_payment_id=s.id,
                    )
                    db.add(payment)
                    logger.info(f"Celery: Fixed stuck order {order.id}")

        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Celery sync error: {str(e)}")
    finally:
        db.close()


@celery_app.task(name="send_payment_confirmation")
def send_payment_confirmation_task(user_email: str, order_id: int, amount: str):
    """
    Background task to send order confirmation email using the asynchronous EmailSender.
    """
    sender = EmailSender(
        hostname=settings.EMAIL_HOST,
        port=settings.EMAIL_PORT,
        email=settings.EMAIL_HOST_USER,
        password=settings.EMAIL_HOST_PASSWORD,
        use_tls=settings.EMAIL_USE_TLS,
        template_dir=settings.PATH_TO_EMAIL_TEMPLATES_DIR,
        activation_email_template_name=settings.ACTIVATION_EMAIL_TEMPLATE_NAME,
        activation_complete_email_template_name=settings.ACTIVATION_COMPLETE_EMAIL_TEMPLATE_NAME,
        password_email_template_name=settings.PASSWORD_RESET_TEMPLATE_NAME,
        password_complete_email_template_name=settings.PASSWORD_RESET_COMPLETE_TEMPLATE_NAME,
    )

    history_link = f"{settings.PAYMENT_SUCCESS_URL}"

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(
            sender.send_order_confirmation_email(
                email=user_email,
                order_id=order_id,
                amount=amount,
                history_link=history_link,
            )
        )
        return f"Confirmation sent to {user_email} for order {order_id}"
    except Exception as e:
        logger.error(f"Celery task failed for order {order_id}: {str(e)}")
        raise e
