import logging
import stripe

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, status, HTTPException, Request, Query
from sqlalchemy import select, func, and_, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.dependencies import get_current_user, get_current_admin_user
from database import get_db
from database.models.accounts import UserModel
from database.models.enums import OrderStatusEnum, PaymentStatusEnum
from database.models.orders import OrderModel, OrderItemModel
from database.models.payments import PaymentModel, PaymentItemModel
from core.config import settings
from schemas.pagination import Page
from schemas.payments import PaymentResponseSchema, AdminPaymentResponseSchema
from worker.tasks import send_payment_confirmation_task

router = APIRouter()
logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY


async def finalize_payment(
    db: AsyncSession, order_id: int, session_id: str, amount_total_cents: int
) -> bool:
    """
    Finalize order by updating the status to PAID and creating payment records.
    Validates that Stripe amount matches the order total in the database.
    Ensures a consistent financial history by snapshotting payment items.
    """
    stmt = (
        select(OrderModel)
        .where(OrderModel.id == order_id)
        .options(selectinload(OrderModel.items), selectinload(OrderModel.user))
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order or order.status != OrderStatusEnum.PENDING:
        logger.warning(
            f"Finalization skipped: Order {order_id} not found or status is not PENDING."
        )
        return False

    if int(order.total_amount * 100) != amount_total_cents:
        logger.error(
            f"CRITICAL: Amount mismatch for order {order_id}! "
            f"DB: {order.total_amount}, Stripe: {amount_total_cents / 100}"
        )
        return False

    order.status = OrderStatusEnum.PAID

    new_payment = PaymentModel(
        user_id=order.user_id,
        order_id=order.id,
        status=PaymentStatusEnum.SUCCESSFUL,
        amount=order.total_amount,
        external_payment_id=session_id,
    )
    db.add(new_payment)
    await db.flush()

    for item in order.items:
        db.add(
            PaymentItemModel(
                payment_id=new_payment.id,
                order_item_id=item.id,
                price_at_payment=item.price_at_order,
            )
        )

    await db.commit()
    logger.info(
        f"Successfully finalized payment for order {order_id}. Transaction: {session_id}"
    )
    send_payment_confirmation_task.delay(
        user_email=order.user.email, order_id=order.id, amount=str(order.total_amount)
    )

    logger.info(f"Order {order_id} finalized and confirmation email enqueued.")
    return True


# =============================================================================
# USER ROUTES
# =============================================================================


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Handles asynchronous Stripe events via webhooks.
    Verifies event integrity and triggers order finalization on successful payment.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.error(f"Webhook signature verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature"
        )

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        order_id_str = session.get("metadata", {}).get("order_id")

        if order_id_str:
            try:
                await finalize_payment(
                    db, int(order_id_str), session["id"], session["amount_total"]
                )
            except Exception as e:
                logger.error(
                    f"Error finalizing payment from webhook: {e}", exc_info=True
                )
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    if event["type"] == "checkout.session.async_payment_failed":
        session = event["data"]["object"]
        order_id_str = session.get("metadata", {}).get("order_id")

        if order_id_str:
            try:
                stmt = select(OrderModel).where(OrderModel.id == int(order_id_str))
                result = await db.execute(stmt)
                order = result.scalar_one_or_none()

                if order and order.status == OrderStatusEnum.PENDING:
                    order.status = OrderStatusEnum.CANCELED
                    await db.commit()
                    logger.warning(
                        f"Payment failed for order {order_id_str}. Status set to CANCELED."
                    )
            except Exception as e:
                await db.rollback()
                logger.error(f"Failed to cancel order {order_id_str} via webhook: {e}")
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return {"status": "success"}


@router.post("/create-session/{order_id}", status_code=status.HTTP_201_CREATED)
async def create_payment_session(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """
    Initializes a Stripe Checkout session for a specific pending order.
    Validates order ownership and converts line items for the Stripe API.
    """
    try:
        stmt = (
            select(OrderModel)
            .where(OrderModel.id == order_id, OrderModel.user_id == current_user.id)
            .options(selectinload(OrderModel.items).selectinload(OrderItemModel.movie))
        )
        result = await db.execute(stmt)
        order = result.scalar_one_or_none()

        if not order:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Order not found")

        if order.status != OrderStatusEnum.PENDING:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Payment unavailable for order in {order.status.value} status",
            )

        if not order.items:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="Order has no items"
            )

        line_items = [
            {
                "price_data": {
                    "currency": settings.STRIPE_CURRENCY,
                    "product_data": {"name": item.movie.name},
                    "unit_amount": int(item.price_at_order * 100),
                },
                "quantity": 1,
            }
            for item in order.items
        ]

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=line_items,
            mode="payment",
            success_url=settings.PAYMENT_SUCCESS_URL,
            cancel_url=settings.PAYMENT_CANCEL_URL,
            metadata={"order_id": str(order.id)},
        )

        return {"checkout_url": session.url, "session_id": session.id}

    except stripe.error.StripeError as e:
        logger.error(f"Stripe API error for order {order_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Payment provider error"
        )
    except Exception as e:
        logger.error(
            f"Internal error creating session for order {order_id}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server error"
        )


@router.get("/history", response_model=Page[PaymentResponseSchema])
async def get_payment_history(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """
    Retrieve a paginated list of the current user's transaction history.
    Includes detailed snapshots of purchased items for each payment record.
    """
    try:
        base_stmt = select(PaymentModel).where(PaymentModel.user_id == current_user.id)

        total_count = (
            await db.scalar(select(func.count()).select_from(base_stmt.subquery())) or 0
        )

        stmt = (
            base_stmt.options(selectinload(PaymentModel.items))
            .order_by(PaymentModel.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await db.execute(stmt)
        payments_list = result.scalars().all()

        return Page(
            items=[PaymentResponseSchema.model_validate(p) for p in payments_list],
            total=total_count,
            page=page,
            size=size,
            total_pages=(total_count + size - 1) // size if total_count > 0 else 0,
        )
    except Exception as e:
        logger.error(
            f"Failed to fetch payment history for user {current_user.id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve history.",
        )


# =============================================================================
# ADMIN ROUTES
# =============================================================================


@router.get("/admin/payments/", response_model=Page[AdminPaymentResponseSchema])
async def admin_get_all_payments(
    user_id: Optional[int] = Query(None),
    status_filter: Optional[PaymentStatusEnum] = Query(None, alias="status"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: UserModel = Depends(get_current_admin_user),
):
    """
    Provide administrative access to all system transactions with advanced filtering.
    Supports filtering by user ID, payment status, and creation date ranges.
    """
    try:
        query = select(PaymentModel).options(
            selectinload(PaymentModel.user), selectinload(PaymentModel.items)
        )

        filters = []
        if user_id:
            filters.append(PaymentModel.user_id == user_id)
        if status_filter:
            filters.append(PaymentModel.status == status_filter)
        if date_from:
            filters.append(cast(PaymentModel.created_at, Date) >= date_from)
        if date_to:
            filters.append(cast(PaymentModel.created_at, Date) <= date_to)

        if filters:
            query = query.where(and_(*filters))

        total_count = (
            await db.scalar(select(func.count()).select_from(query.subquery())) or 0
        )

        stmt = (
            query.order_by(PaymentModel.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await db.execute(stmt)
        payments_list = result.scalars().all()

        return Page(
            items=[AdminPaymentResponseSchema.model_validate(p) for p in payments_list],
            total=total_count,
            page=page,
            size=size,
            total_pages=(total_count + size - 1) // size if total_count > 0 else 0,
        )
    except Exception as e:
        logger.error(f"Admin payment fetch failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error.",
        )
