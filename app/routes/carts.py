import logging
from decimal import Decimal
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from database.models.accounts import UserModel
from database.models.carts import CartModel, CartItemModel
from database.models.movies import MovieModel
from schemas.carts import CartResponseSchema
from core.dependencies import get_current_user

router = APIRouter(prefix="/cart", tags=["Shopping Cart"])
logger = logging.getLogger(__name__)


@router.get(
    "/",
    response_model=CartResponseSchema,
    summary="Get User Cart",
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Unauthorized - User not logged in."},
        500: {"description": "Internal Server Error - Database issues."},
    },
)
async def get_cart(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> CartResponseSchema:
    """
    Retrieve the current authenticated user's shopping cart.
    - **Content**: Detailed list of movies (name, price, year, genres).
    - **Calculations**: Automatically computes the total price of all items.
    """
    logger.info(f"User {current_user.id} requested their cart contents.")

    try:
        stmt = (
            select(CartModel)
            .where(CartModel.user_id == current_user.id)
            .options(
                selectinload(CartModel.items)
                .selectinload(CartItemModel.movie)
                .selectinload(MovieModel.genres)
            )
        )
        result = await db.execute(stmt)
        cart = result.scalar_one_or_none()

        if not cart:
            logger.error(f"Integrity error: Cart missing for user {current_user.id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User cart was not initialized properly.",
            )

        total_sum = Decimal("0.00")
        if cart.items:
            for item in cart.items:
                total_sum += item.movie.price
                item.movie.genres = [genre.name for genre in item.movie.genres]

        return CartResponseSchema(
            id=cart.id, user_id=cart.user_id, items=cart.items, total_price=total_sum
        )

    except SQLAlchemyError as e:
        logger.error(
            f"Database error while fetching cart for user {current_user.id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while retrieving your cart.",
        )
