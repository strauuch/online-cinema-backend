import logging

from decimal import Decimal
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.database.models.accounts import UserModel
from app.database.models.carts import CartModel, CartItemModel
from app.database.models.enums import OrderStatusEnum
from app.database.models.movies import MovieModel
from app.database.models.orders import OrderItemModel, OrderModel
from app.schemas.carts import (
    CartResponseSchema,
    CartItemAddedSchema,
    CartItemRemovedSchema,
    CartClearSchema,
)
from app.core.dependencies import get_current_user, get_current_admin_user

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get(
    "/",
    response_model=CartResponseSchema,
    summary="Get User Cart",
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Unauthorized - User not logged in"},
        500: {"description": "Internal Server Error - Database issues"},
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
    current_user_id = current_user.id
    logger.info(f"User {current_user_id} requested their cart contents.")

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
    current_user_id = current_user.id
    logger.info(
        f"User {current_user_id} is attempting to add movie {movie_id} to cart."
    )

    try:
        movie_stmt = select(MovieModel.id).where(
            MovieModel.id == movie_id, MovieModel.is_deleted == False
        )
        movie_exists = await db.scalar(movie_stmt)
        if not movie_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Movie with ID {movie_id} not found.",
            )

        purchase_stmt = (
            select(OrderItemModel.id)
            .join(OrderModel, OrderItemModel.order_id == OrderModel.id)
            .where(
                OrderModel.user_id == current_user_id,
                OrderItemModel.movie_id == movie_id,
                OrderModel.status == OrderStatusEnum.PAID,
            )
        )
        already_purchased = await db.scalar(purchase_stmt)

        if already_purchased:
            logger.warning(
                f"User {current_user_id} tried to add already owned movie {movie_id}."
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already purchased this movie. Check your library.",
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


@router.delete(
    "/item/{movie_id}",
    response_model=CartItemRemovedSchema,
    summary="Remove Movie from Cart",
    status_code=status.HTTP_200_OK,
    responses={
        404: {"description": "Not Found - Movie not in cart."},
        401: {"description": "Unauthorized - User not logged in."},
    },
)
async def remove_from_cart(
    movie_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> CartItemRemovedSchema:
    """
    Remove a specific movie from the current user's shopping cart.
    - **Validation**: Checks if the item actually exists in the user's cart.
    """
    current_user_id = current_user.id
    logger.info(f"User {current_user_id} is removing movie {movie_id} from cart.")

    try:
        cart_stmt = select(CartModel.id).where(CartModel.user_id == current_user_id)
        cart_id = await db.scalar(cart_stmt)

        if not cart_id:
            logger.error(f"Cart missing for user {current_user_id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User cart not found.",
            )

        item_stmt = select(CartItemModel).where(
            CartItemModel.cart_id == cart_id, CartItemModel.movie_id == movie_id
        )
        result = await db.execute(item_stmt)
        cart_item = result.scalar_one_or_none()

        if not cart_item:
            logger.warning(
                f"User {current_user_id} tried to remove non-existent item {movie_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This movie is not in your cart.",
            )

        await db.delete(cart_item)
        await db.commit()

        logger.info(
            f"Movie {movie_id} removed from cart {cart_id} for user {current_user_id}."
        )
        return CartItemRemovedSchema(
            message="Movie removed from cart successfully.", movie_id=movie_id
        )

    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"DB error while removing item from cart: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while removing the item from the cart.",
        )


@router.delete(
    "/clear",
    response_model=CartClearSchema,
    summary="Clear Entire Cart",
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Unauthorized - User not logged in."},
        500: {"description": "Internal Server Error - Database issues."},
    },
)
async def clear_cart(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> CartClearSchema:
    """
    Remove all items from the current user's shopping cart.
    - **Logic**: Finds the user's cart and deletes all associated CartItem records.
    """
    current_user_id = current_user.id
    logger.info(f"User {current_user_id} is clearing their shopping cart.")

    try:
        cart_stmt = select(CartModel.id).where(CartModel.user_id == current_user_id)
        cart_id = await db.scalar(cart_stmt)

        if not cart_id:
            logger.error(f"Cart missing for user {current_user_id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User cart not found.",
            )

        delete_stmt = delete(CartItemModel).where(CartItemModel.cart_id == cart_id)
        await db.execute(delete_stmt)

        await db.commit()

        logger.info(f"Cart {cart_id} for user {current_user_id} has been cleared.")
        return CartClearSchema(message="All items have been removed from your cart.")

    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"DB error while clearing cart for user {current_user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while clearing the cart.",
        )


@router.get(
    "/admin/carts/{user_id}",
    response_model=CartResponseSchema,
    summary="Get Specific User's Cart [Admin]",
    responses={
        403: {"description": "Forbidden - Admin access required."},
        404: {"description": "Not Found - User or cart does not exist."},
    },
)
async def get_user_cart_admin(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user: UserModel = Depends(get_current_admin_user),
) -> CartResponseSchema:
    """
    Allows an administrator to view the contents of any user's cart.
    """
    logger.info(f"Admin {admin_user.id} is viewing cart for user {user_id}")

    try:
        stmt = (
            select(CartModel)
            .where(CartModel.user_id == user_id)
            .options(selectinload(CartModel.items).selectinload(CartItemModel.movie))
        )

        result = await db.execute(stmt)
        cart = result.scalar_one_or_none()

        if not cart:
            logger.warning(
                f"Admin tried to access non-existent cart for user {user_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Cart for user {user_id} not found.",
            )

        calculated_total = Decimal(str(sum(item.movie.price for item in cart.items)))

        return CartResponseSchema(
            id=cart.id,
            user_id=cart.user_id,
            items=cart.items,
            total_price=calculated_total,
        )

    except SQLAlchemyError as e:
        logger.error(f"DB error in admin cart access: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while fetching the user's cart.",
        )
