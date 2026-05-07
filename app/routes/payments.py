import logging
from typing import Optional

import stripe
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, Query

from core.dependencies import get_current_user, get_current_admin_user
from database import get_db
from database.models.accounts import UserModel
from database.models.enums import OrderStatusEnum, PaymentStatusEnum
from database.models.orders import OrderModel, OrderItemModel
from database.models.payments import PaymentModel, PaymentItemModel
from core.config import settings
from schemas.pagination import Page
from schemas.payments import PaymentResponseSchema, AdminPaymentResponseSchema

router = APIRouter()
logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY


# =============================================================================
# USER ROUTES
# =============================================================================


async def finalize_successful_order(db: AsyncSession, order_id: int, external_id: str):
    """
    Business logic to finalize an order after successful payment.
    Updates order status and creates payment records.
    """
    stmt = (
        select(OrderModel)
        .where(OrderModel.id == order_id)
        .options(selectinload(OrderModel.items))
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order or order.status != OrderStatusEnum.PENDING:
        return

    order.status = OrderStatusEnum.PAID

    new_payment = PaymentModel(
        user_id=order.user_id,
        order_id=order.id,
        status=PaymentStatusEnum.SUCCESSFUL,
        amount=order.total_amount,
        external_payment_id=external_id,
    )
    db.add(new_payment)
    await db.flush()

    for item in order.items:
        payment_item = PaymentItemModel(
            payment_id=new_payment.id,
            order_item_id=item.id,
            price_at_payment=item.price_at_order,
        )
        db.add(payment_item)

    await db.commit()
    logger.info(f"Order {order_id} finalized as PAID with payment {new_payment.id}")


@router.post(
    "/create-session/{order_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Create Stripe Checkout Session",
)
async def create_payment_session(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """Creates a Stripe session and returns the URL for the frontend redirect."""
    current_user_id = current_user.id

    try:
        stmt = (
            select(OrderModel)
            .where(OrderModel.id == order_id, OrderModel.user_id == current_user_id)
            .options(selectinload(OrderModel.items).selectinload(OrderItemModel.movie))
        )
        result = await db.execute(stmt)
        order = result.scalar_one_or_none()

        if not order:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Order not found.")

        if order.status != OrderStatusEnum.PENDING:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Order status is {order.status.value}, cannot pay.",
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
        logger.error(f"Stripe error: {str(e)}")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Stripe API error.")
    except Exception as e:
        logger.error(f"Payment session error: {str(e)}", exc_info=True)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server error."
        )


@router.get("/verify/{session_id}", summary="Verify Payment")
async def verify_payment(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """Endpoint for frontend to call after redirect from Stripe."""
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        order_id = int(session.metadata["order_id"])

        if session.payment_status == "paid":
            await finalize_successful_order(db, order_id, session.id)
            return {"status": "paid", "order_id": order_id}

        return {"status": session.payment_status, "order_id": order_id}

    except Exception as e:
        logger.error(f"Verification error: {str(e)}")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Verification failed.")


@router.get(
    "/history",
    response_model=Page[PaymentResponseSchema],
    summary="Get User Payment History",
)
async def get_payment_history(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Page[PaymentResponseSchema]:
    """
    Retrieve a paginated list of all payments made by the current user.
    """
    try:
        # 1. Count total
        count_stmt = (
            select(func.count())
            .select_from(PaymentModel)
            .where(PaymentModel.user_id == current_user.id)
        )
        total_count = await db.scalar(count_stmt) or 0

        # 2. Fetch data
        offset = (page - 1) * size
        stmt = (
            select(PaymentModel)
            .where(PaymentModel.user_id == current_user.id)
            .order_by(PaymentModel.created_at.desc())
            .offset(offset)
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
        logger.error(f"Error fetching payment history: {str(e)}")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch history."
        )


# =============================================================================
# ADMIN ROUTES
# =============================================================================


@router.get(
    "/admin/payments/",
    response_model=Page[AdminPaymentResponseSchema],
    summary="Admin: View All Transactions",
)
async def admin_get_all_payments(
    user_id: Optional[int] = Query(None),
    status_filter: Optional[PaymentStatusEnum] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: UserModel = Depends(get_current_admin_user),
) -> Page[AdminPaymentResponseSchema]:
    """
    Administrative view of all transactions in the system.
    """
    try:
        # 1. Base query with user info
        query = select(PaymentModel).options(selectinload(PaymentModel.user))

        # 2. Filters
        filters = []
        if user_id:
            filters.append(PaymentModel.user_id == user_id)
        if status_filter:
            filters.append(PaymentModel.status == status_filter)

        if filters:
            query = query.where(and_(*filters))

        # 3. Count total
        count_stmt = select(func.count()).select_from(PaymentModel)
        if filters:
            count_stmt = count_stmt.where(and_(*filters))
        total_count = await db.scalar(count_stmt) or 0

        # 4. Results
        offset = (page - 1) * size
        stmt = query.order_by(PaymentModel.created_at.desc()).offset(offset).limit(size)
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
        logger.error(f"Admin payment fetch error: {str(e)}")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error."
        )
