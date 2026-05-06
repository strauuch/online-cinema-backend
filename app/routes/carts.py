import logging
from decimal import Decimal
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from database.models.accounts import UserModel
from database.models.carts import CartModel, CartItemModel
from database.models.movies import MovieModel
from schemas.carts import CartResponseSchema, CartItemAddedSchema
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

    current_user_id = current_user.id

    try:
        stmt = (
            select(CartModel)
            .where(CartModel.user_id == current_user_id)
            .options(
                selectinload(CartModel.items)
                .selectinload(CartItemModel.movie)
                .selectinload(MovieModel.genres)
            )
        )
        result = await db.execute(stmt)
        cart = result.scalar_one_or_none()

        if not cart:
            logger.error(f"Integrity error: Cart missing for user {current_user_id}")
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
            f"Database error while fetching cart for user {current_user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while retrieving your cart.",
        )


@router.post(
    "/add/{movie_id}",
    response_model=CartItemAddedSchema,
    summary="Add Movie to Cart",
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {
            "description": "Bad Request - Movie already purchased or already in cart."
        },
        404: {"description": "Not Found - Movie does not exist."},
        401: {"description": "Unauthorized - User not logged in."},
    },
)
async def add_to_cart(
    movie_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> CartItemAddedSchema:
    """
    Add a movie to the current user's shopping cart.
    - **Validation**: Checks if the movie exists.
    - **Purchase Check**: (Placeholder) Checks if the movie was already bought.
    - **Duplicate Check**: Prevents adding the same movie twice.
    """
    logger.info(
        f"User {current_user.id} is attempting to add movie {movie_id} to cart."
    )

    current_user_id = current_user.id

    try:
        movie_stmt = select(MovieModel.id).where(MovieModel.id == movie_id)
        movie_exists = await db.scalar(movie_stmt)
        if not movie_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Movie with ID {movie_id} not found.",
            )

        is_already_purchased = False
        if is_already_purchased:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already purchased this movie. Repeat purchases are not allowed.",
            )

        cart_stmt = select(CartModel.id).where(CartModel.user_id == current_user_id)
        cart_id = await db.scalar(cart_stmt)

        new_item = CartItemModel(cart_id=cart_id, movie_id=movie_id)
        db.add(new_item)

        await db.commit()

        logger.info(
            f"Movie {movie_id} successfully added to cart {cart_id} for user {current_user_id}."
        )
        return CartItemAddedSchema(
            message="Movie added to cart successfully.",
            movie_id=movie_id,
            cart_id=cart_id,
        )

    except IntegrityError:
        await db.rollback()
        logger.warning(
            f"User {current_user_id} tried to add duplicate movie {movie_id} to cart."
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This movie is already in your cart.",
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Database error while adding to cart: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while adding the item to the cart.",
        )
