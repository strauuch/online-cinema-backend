import logging
import stripe

from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy import select, delete, func, and_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.dependencies import (
    get_current_user,
    get_current_admin_user,
)
from database import get_db
from database.models.accounts import (
    UserModel,
)
from database.models.carts import CartModel, CartItemModel
from database.models.enums import OrderStatusEnum
from database.models.orders import OrderModel, OrderItemModel
from schemas.orders import (
    OrderResponseSchema,
    OrderListResponseSchema,
    AdminOrderResponseSchema,
)
from schemas.pagination import Page

router = APIRouter()
logger = logging.getLogger(__name__)


# =============================================================================
# USER ROUTES
# =============================================================================


@router.post(
    "/",
    response_model=OrderResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Order from Cart",
)
async def create_order(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> OrderResponseSchema:
    """
    Create a new order based on the current items in the user's shopping cart.
    - **Process**: Calculates total price, snapshots movie prices, and clears the cart.
    - **Transactions**: Atomic operation ensures order creation and cart clearing happen together.
    """
    current_user_id = current_user.id
    logger.info(f"User {current_user_id} is initiating order creation from cart.")

    try:
        cart_stmt = (
            select(CartModel)
            .where(CartModel.user_id == current_user_id)
            .options(selectinload(CartModel.items).selectinload(CartItemModel.movie))
        )
        result = await db.execute(cart_stmt)
        cart = result.scalar_one_or_none()

        if not cart or not cart.items:
            logger.warning(
                f"Order creation failed: User {current_user_id} has an empty cart."
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your cart is empty. Add movies before placing an order.",
            )

        total_amount = Decimal(str(sum(item.movie.price for item in cart.items)))

        new_order = OrderModel(
            user_id=current_user_id,
            total_amount=total_amount,
            status=OrderStatusEnum.PENDING,
        )
        db.add(new_order)

        await db.flush()

        for cart_item in cart.items:
            order_item = OrderItemModel(
                order_id=new_order.id,
                movie_id=cart_item.movie_id,
                price_at_order=cart_item.movie.price,
            )
            db.add(order_item)

        delete_cart_items_stmt = delete(CartItemModel).where(
            CartItemModel.cart_id == cart.id
        )
        await db.execute(delete_cart_items_stmt)

        await db.commit()

        await db.refresh(new_order, attribute_names=["items"])

        logger.info(
            f"Order {new_order.id} successfully created and cart cleared for user {current_user_id}."
        )
        return OrderResponseSchema.model_validate(new_order)

    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Database error during order creation for user {current_user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing your order.",
        )


@router.get(
    "/",
    response_model=Page[OrderListResponseSchema],
    summary="Get Paginated User Order History",
)
async def get_orders_history(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Page[OrderListResponseSchema]:
    """
    Retrieve a paginated history of orders for the authenticated user.
    - **page**: Current page number (starts from 1).
    - **size**: Number of orders per page (max 100).
    - **Returns**: A Page object containing orders, total count, and pagination metadata.
    """
    current_user_id = current_user.id
    logger.info(
        f"Fetching paginated order history for user {current_user_id} (Page: {page}, Size: {size})."
    )

    try:
        count_stmt = (
            select(func.count())
            .select_from(OrderModel)
            .where(OrderModel.user_id == current_user_id)
        )
        total_count_result = await db.execute(count_stmt)
        total_count = total_count_result.scalar() or 0

        offset = (page - 1) * size
        stmt = (
            select(OrderModel)
            .where(OrderModel.user_id == current_user_id)
            .options(selectinload(OrderModel.items).selectinload(OrderItemModel.movie))
            .order_by(OrderModel.created_at.desc())
            .offset(offset)
            .limit(size)
        )

        result = await db.execute(stmt)
        orders = result.scalars().all()

        logger.info(
            f"Retrieved {len(orders)} orders for user {current_user_id}. Total: {total_count}."
        )

        return Page(
            items=[OrderListResponseSchema.model_validate(order) for order in orders],
            total=total_count,
            page=page,
            size=size,
            total_pages=(total_count + size - 1) // size if total_count > 0 else 0,
        )

    except Exception as e:
        logger.error(
            f"Error fetching paginated orders for user {current_user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve order history.",
        )


@router.get(
    "/{order_id}",
    response_model=OrderListResponseSchema,
    summary="Get Specific Order Details",
)
async def get_order_details(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> OrderListResponseSchema:
    """
    Get detailed information about a specific order by its ID.
    - **Validation**: Ensures the order exists and belongs to the current user.
    - **Details**: Includes the list of movies and the exact price at the time of purchase.
    """
    current_user_id = current_user.id
    logger.info(f"User {current_user_id} is requesting details for order {order_id}.")

    try:
        stmt = (
            select(OrderModel)
            .where(OrderModel.id == order_id, OrderModel.user_id == current_user_id)
            .options(selectinload(OrderModel.items).selectinload(OrderItemModel.movie))
        )
        result = await db.execute(stmt)
        order = result.scalar_one_or_none()

        if not order:
            logger.warning(
                f"Order {order_id} not found or access denied for user {current_user_id}."
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Order not found."
            )

        logger.info(
            f"Successfully retrieved details for order {order_id} for user {current_user_id}."
        )
        return OrderListResponseSchema.model_validate(order)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error retrieving order {order_id} for user {current_user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while fetching order details.",
        )


@router.post(
    "/{order_id}/cancel",
    response_model=OrderResponseSchema,
    summary="Cancel Pending Order",
)
async def cancel_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> OrderResponseSchema:
    """
    Cancel an existing order if it is still in PENDING status.
    - **Ownership**: User can only cancel their own orders.
    - **Status Check**: Only orders with 'pending' status can be canceled.
    - **Effect**: Changes status to 'canceled'. Items remain in the order record for history.
    """
    current_user_id = current_user.id
    logger.info(f"User {current_user_id} requested cancellation for order {order_id}.")

    try:
        stmt = (
            select(OrderModel)
            .where(OrderModel.id == order_id, OrderModel.user_id == current_user_id)
            .options(selectinload(OrderModel.items).selectinload(OrderItemModel.movie))
        )
        result = await db.execute(stmt)
        order = result.scalar_one_or_none()

        if not order:
            logger.warning(
                f"Cancellation failed: Order {order_id} not found for user {current_user_id}."
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Order not found."
            )

        if order.status != OrderStatusEnum.PENDING:
            logger.warning(
                f"User {current_user_id} tried to cancel order {order_id} with status {order.status}."
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot cancel an order that is already {order.status.value}.",
            )

        try:
            active_sessions = stripe.checkout.Session.list(
                limit=3, customer_details={"email": current_user.email}
            )

            for session in active_sessions.data:
                if (
                    session.metadata.get("order_id") == str(order_id)
                    and session.status == "open"
                ):
                    logger.warning(
                        f"User {current_user_id} tried to cancel order {order_id} with active Stripe session."
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="You have an active payment session open. Please complete or expire it before canceling.",
                    )
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error during cancellation check: {e}")

        order.status = OrderStatusEnum.CANCELED

        await db.commit()
        await db.refresh(order)

        logger.info(
            f"Order {order_id} successfully cancelled by user {current_user_id}."
        )

        return OrderResponseSchema.model_validate(order)

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Database error during order {order_id} cancellation: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel the order.",
        )


# =============================================================================
# ADMIN ROUTES
# =============================================================================


@router.get(
    "/",
    response_model=Page[AdminOrderResponseSchema],
    summary="Get All Orders with Filters (Paginated) [Admin]",
)
async def admin_get_all_orders(
    user_id: Optional[int] = Query(None, description="Filter by User ID"),
    order_status: Optional[OrderStatusEnum] = Query(
        None, description="Filter by Order Status"
    ),
    date_from: Optional[date] = Query(
        None, description="Filter from date (YYYY-MM-DD)"
    ),
    date_to: Optional[date] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: UserModel = Depends(get_current_admin_user),
) -> Page[AdminOrderResponseSchema]:
    """
    Retrieve all orders across the platform with administrative filters.
    - **Filters**: User, Status, and Date Range.
    - **Pagination**: Standard limit/offset logic.
    - **Access**: Strictly restricted to ADMIN group.
    """
    logger.info(
        f"Admin {admin.email} is fetching all orders with filters: "
        f"user_id={user_id}, status={order_status}, range={date_from} to {date_to}"
    )

    try:
        query = select(OrderModel).options(
            selectinload(OrderModel.items).selectinload(OrderItemModel.movie),
            selectinload(OrderModel.user),
        )

        filters = []
        if user_id:
            filters.append(OrderModel.user_id == user_id)
        if order_status:
            filters.append(OrderModel.status == order_status)
        if date_from:
            dt_from = datetime.combine(date_from, time.min)
            filters.append(OrderModel.created_at >= dt_from)
        if date_to:
            dt_to = datetime.combine(date_to, time.max)
            filters.append(OrderModel.created_at <= dt_to)

        if filters:
            query = query.where(and_(*filters))

        count_stmt = select(func.count()).select_from(OrderModel)
        if filters:
            count_stmt = count_stmt.where(and_(*filters))

        total_count = await db.scalar(count_stmt) or 0

        offset = (page - 1) * size
        stmt = query.order_by(OrderModel.created_at.desc()).offset(offset).limit(size)
        result = await db.execute(stmt)
        orders = result.scalars().all()

        total_pages = (total_count + size - 1) // size if total_count > 0 else 0

        logger.info(f"Admin request processed. Found {total_count} total orders.")

        return Page(
            items=[AdminOrderResponseSchema.model_validate(order) for order in orders],
            total=total_count,
            page=page,
            size=size,
            total_pages=total_pages,
        )

    except Exception as e:
        logger.error(f"Error in admin_get_all_orders: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during order retrieval.",
        )
