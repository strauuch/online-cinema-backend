import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, status, HTTPException

from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.dependencies import (
    get_current_user,
)
from database import get_db
from database.models.accounts import (
    UserModel,
)
from database.models.carts import CartModel, CartItemModel
from database.models.enums import OrderStatusEnum
from database.models.orders import OrderModel, OrderItemModel
from schemas.orders import OrderResponseSchema

router = APIRouter()
logger = logging.getLogger(__name__)


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
