import logging

from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy import select, func, or_, delete, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from core.dependencies import (
    get_current_user,
    get_current_staff_user,
    update_movie_rating_stats,
)
from database import get_db
from database.models.accounts import UserModel
from database.models.enums import NotificationType, UserGroupEnum
from database.models.movies import (
    MovieModel,
    GenreModel,
    StarModel,
    DirectorModel,
    movie_genres,
    MovieFavoriteModel,
    MovieVoteModel,
    MovieRatingModel,
    MovieCommentModel,
    NotificationModel,
    CommentLikeModel,
    CertificationModel,
)
from schemas.accounts import MessageResponseSchema
from schemas.movies import (
    MovieShortResponseSchema,
    MovieDetailResponseSchema,
    GenreWithCountSchema,
    RatingCreateSchema,
    VoteCreateSchema,
    CommentCreateSchema,
    NotificationReadSchema,
    CommentReadSchema,
    MovieCreateSchema,
    MovieUpdateSchema,
    CommentUpdateSchema,
    GenreReadSchema,
    GenreCreateSchema,
    GenreUpdateSchema,
    StarReadSchema,
    StarCreateSchema,
    StarUpdateSchema,
    DirectorReadSchema,
    DirectorCreateSchema,
    DirectorUpdateSchema,
    CertificationReadSchema,
    CertificationCreateSchema,
    CertificationUpdateSchema,
)
from schemas.pagination import Page

router = APIRouter(prefix="/movies", tags=["Movies"])

logger = logging.getLogger(__name__)


async def get_movie_id_by_uuid(movie_uuid: UUID, db: AsyncSession) -> int:
    """Resolves a public Movie UUID to an internal database Integer ID."""
    stmt = select(MovieModel.id).where(MovieModel.uuid == movie_uuid)
    result = await db.execute(stmt)
    movie_id = result.scalar_one_or_none()
    if not movie_id:
        logger.warning(f"Movie lookup failed: UUID {movie_uuid} not found in database")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found"
        )
    logger.debug(f"Resolved UUID {movie_uuid} to internal ID {movie_id}")

    return movie_id


# =============================================================================
# USER ROUTES
# =============================================================================


@router.get(
    "/genres/",
    response_model=Page[GenreWithCountSchema],
    status_code=status.HTTP_200_OK,
    summary="Get All Genres (Paginated)",
    description=(
        "Retrieve a paginated list of genres available in the catalog. "
        "Each genre includes a `movie_count` showing how many movies are associated with it."
    ),
)
async def list_genres(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="Current page number"),
    size: int = Query(10, ge=1, le=100, description="Items per page"),
) -> Page[GenreWithCountSchema]:
    """Retrieves all genres with the total count of movies associated with each."""
    logger.debug("Fetching all genres with movie counts")

    stmt = (
        select(
            GenreModel.id,
            GenreModel.name,
            func.count(movie_genres.c.movie_id).label("movie_count"),
        )
        .join(movie_genres, isouter=True)
        .group_by(GenreModel.id, GenreModel.name)
        .order_by(func.count(movie_genres.c.movie_id).desc())
    )

    try:
        count_stmt = select(func.count()).select_from(GenreModel)
        total_count = await db.scalar(count_stmt) or 0

        offset = (page - 1) * size
        result = await db.execute(stmt.limit(size).offset(offset))
        genres = result.all()

        logger.info(f"Found {total_count} total genres, returning {len(genres)} for page {page}")
    except SQLAlchemyError as e:
        logger.error(f"Failed to fetch genres with counts: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Database error during genre aggregation"
        )

    return Page(
        items=genres,
        total=total_count,
        page=page,
        size=size,
        total_pages=(total_count + size - 1) // size if total_count > 0 else 0,
    )


@router.get(
    "/",
    response_model=Page[MovieShortResponseSchema],
    status_code=status.HTTP_200_OK,
    summary="Browse and Filter Movie Catalog",
    description=(
        "Get a paginated list of movies with advanced filtering, searching, and sorting. "
        "Search covers title, description, stars, and directors."
    ),
    responses={
        200: {"description": "Paginated list of movies returned successfully."},
        400: {"description": "Invalid sorting attribute or filter parameters."},
    },
)
async def list_movies(
    page: int = Query(1, ge=1, description="Current page number"),
    size: int = Query(10, ge=1, le=100, description="Items per page"),
    q: Optional[str] = Query(
        None, min_length=2, description="Search query (title, desc, stars, directors)"
    ),
    year: Optional[int] = Query(None, description="Filter by release year"),
    min_imdb: Optional[float] = Query(
        None, ge=0, le=10, description="Minimum IMDb rating"
    ),
    genre_id: Optional[int] = Query(None, description="Filter by genre ID"),
    sort_by: str = Query("year", pattern="^(year|price|imdb|popularity)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    only_favorites: bool = Query(False),
    current_user: Optional[UserModel] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page[MovieShortResponseSchema]:
    """Provides a paginated list of movies with multi-criteria filtering and full-text search."""
    logger.info(
        f"Movie list requested. Page: {page}, Size: {size}, Query: '{q}', Sort: {sort_by} {order}"
    )

    stmt = select(MovieModel).options(selectinload(MovieModel.genres))

    if only_favorites:
        if not current_user:
            logger.debug("Unauthorized access attempt to favorites list")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Log in to see favorites",
            )
        logger.debug(f"Filtering favorites for user_id: {current_user.id}")
        stmt = stmt.join(MovieFavoriteModel).where(
            MovieFavoriteModel.user_id == current_user.id
        )

    if q:
        logger.debug(f"Applying text search filter with query: '{q}'")
        stmt = stmt.join(MovieModel.stars, isouter=True).join(
            MovieModel.directors, isouter=True
        )
        search_filter = or_(
            MovieModel.name.ilike(f"%{q}%"),
            MovieModel.description.ilike(f"%{q}%"),
            StarModel.name.ilike(f"%{q}%"),
            DirectorModel.name.ilike(f"%{q}%"),
        )
        stmt = stmt.where(search_filter).distinct()

    if year:
        logger.debug(f"Filtering by year: {year}")
        stmt = stmt.where(MovieModel.year == year)
    if min_imdb:
        logger.debug(f"Filtering by min_imdb: {min_imdb}")
        stmt = stmt.where(MovieModel.imdb >= min_imdb)
    if genre_id:
        logger.debug(f"Filtering by genre_id: {genre_id}")
        stmt = (
            stmt.join(movie_genres)
            .where(movie_genres.c.genre_id == genre_id)
            .distinct()
        )

    try:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_count = await db.scalar(count_stmt) or 0

        logger.info(f"Movie search found {total_count} total items")

        sort_mapping = {
            "popularity": MovieModel.votes,
            "year": MovieModel.year,
            "price": MovieModel.price,
            "imdb": MovieModel.imdb,
        }
        column = sort_mapping.get(sort_by, MovieModel.year)
        stmt = stmt.order_by(column.desc() if order == "desc" else column.asc())

        offset = (page - 1) * size
        result = await db.execute(stmt.limit(size).offset(offset))
        movies = list(result.scalars().all())

        logger.info(
            f"Search successful. Found {total_count} total, returning {len(movies)} items"
        )
    except SQLAlchemyError as e:
        logger.error(f"Database error in list_movies: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Search operation failed",
        )

    return Page(
        items=movies,
        total=total_count,
        page=page,
        size=size,
        total_pages=(total_count + size - 1) // size,
    )


@router.get(
    "/{movie_uuid}/",
    response_model=MovieDetailResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Get Movie Details",
    description="Retrieve comprehensive information about a movie, including cast, directors, and certification.",
    responses={
        200: {"description": "Movie details found."},
        404: {"description": "Movie not found."},
    },
)
async def get_movie_detail(
    movie_uuid: UUID, db: AsyncSession = Depends(get_db)
) -> MovieDetailResponseSchema:
    """
    Retrieves full information about a specific movie by its public UUID.
    """
    logger.info(f"Fetching movie details for UUID: {movie_uuid}")

    stmt = (
        select(MovieModel)
        .options(
            selectinload(MovieModel.genres),
            selectinload(MovieModel.stars),
            selectinload(MovieModel.directors),
            joinedload(MovieModel.certification),
        )
        .where(MovieModel.uuid == movie_uuid)
    )

    try:
        result = await db.execute(stmt)
        movie = result.scalars().first()
    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching movie {movie_uuid}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while fetching movie details"
        )

    if not movie:
        logger.warning(f"Movie not found for UUID: {movie_uuid}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with provided UUID not found",
        )

    logger.debug(f"Movie details for '{movie.name}' (ID: {movie.id}) successfully retrieved")

    return movie


@router.post(
    "/{movie_uuid}/favorite/",
    status_code=status.HTTP_201_CREATED,
    response_model=MessageResponseSchema,
    summary="Add Movie to Favorites",
)
async def add_favorite(
    movie_uuid: UUID,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Adds a movie to the user's personal favorites list."""
    logger.debug(f"User {current_user.id} attempting to add movie {movie_uuid} to favorites")
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = select(MovieFavoriteModel).where(
        MovieFavoriteModel.user_id == current_user.id,
        MovieFavoriteModel.movie_id == movie_id,
    )
    existing = await db.scalar(stmt)
    if existing:
        logger.info(f"User {current_user.id} already has movie {movie_uuid} in favorites")
        return {"message": "Movie is already in favorites"}

    try:
        new_favorite = MovieFavoriteModel(user_id=current_user.id, movie_id=movie_id)
        db.add(new_favorite)
        await db.commit()
        logger.info(f"Successfully added movie {movie_uuid} to favorites for user {current_user.id}")
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"DB Error while adding favorite for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error")

    return {"message": "Movie added to favorites"}


@router.delete(
    "/{movie_uuid}/favorite/",
    status_code=status.HTTP_200_OK,
    response_model=MessageResponseSchema,
    summary="Remove Movie from Favorites",
)
async def remove_favorite(
    movie_uuid: UUID,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Removes a movie from the user's personal favorites list."""
    logger.debug(f"Process 'remove_favorite' started for user {current_user.id}, movie {movie_uuid}")
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = (
        delete(MovieFavoriteModel)
        .where(
            MovieFavoriteModel.user_id == current_user.id,
            MovieFavoriteModel.movie_id == movie_id,
        )
        .returning(MovieFavoriteModel.movie_id)
    )

    result = await db.execute(stmt)
    deleted_id = result.scalar_one_or_none()

    if deleted_id is None:
        logger.warning(f"Deletion failed: movie {movie_uuid} not in user {current_user.id} favorites")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not in favorites"
        )

    try:
        await db.commit()
        logger.info(f"User {current_user.id} successfully removed movie {movie_uuid} from favorites")
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"DB Error while removing favorite for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error"
        )

    return {"message": "Movie removed from favorites"}


@router.post(
    "/{movie_uuid}/rating/",
    response_model=MessageResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Rate a movie",
    description="Set or update a 10-point scale rating for a movie.",
)
async def rate_movie(
    movie_uuid: UUID,
    rating_data: RatingCreateSchema,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sets or updates a numerical rating (1-10) for a movie and updates global stats."""
    logger.debug(f"User {current_user.id} rating movie {movie_uuid} with score {rating_data.score}")
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = select(MovieRatingModel).where(
        MovieRatingModel.user_id == current_user.id,
        MovieRatingModel.movie_id == movie_id,
    )
    rating = (await db.execute(stmt)).scalar_one_or_none()

    if rating:
        old_score = rating.score
        rating.score = rating_data.score
        message = "Rating updated"
        logger.info(f"User {current_user.id} changing score for movie {movie_id} from {old_score} to {rating_data.score}")
    else:
        rating = MovieRatingModel(
            user_id=current_user.id, movie_id=movie_id, score=rating_data.score
        )
        db.add(rating)
        message = "Movie rated"
        logger.info(f"User {current_user.id} set new rating for movie {movie_id}: {rating_data.score}")

    try:
        await db.flush()

        logger.debug(f"Triggering stats update for movie_id: {movie_id}")
        await update_movie_rating_stats(movie_id, db)

        await db.commit()
        logger.info(f"Successfully committed rating and stats update for movie {movie_id}")
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Rating operation failed for user {current_user.id}, movie {movie_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error"
        )

    return {"message": message}


@router.delete(
    "/{movie_uuid}/rating/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Movie Rating",
    description="Allows a user to remove their previously set rating for a movie.",
    responses={
        204: {"description": "Rating removed successfully."},
        401: {"description": "Unauthorized."},
        404: {"description": "Not Found - Movie or rating not found."},
    },
)
async def remove_movie_rating(
    movie_uuid: UUID,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deletes the user's rating for a movie and triggers a global stats recalculation."""
    logger.debug(f"Initiating rating removal for user {current_user.id} on movie {movie_uuid}")
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = (
        delete(MovieRatingModel)
        .where(
            MovieRatingModel.user_id == current_user.id,
            MovieRatingModel.movie_id == movie_id,
        )
        .returning(MovieRatingModel.user_id)
    )

    result = await db.execute(stmt)
    deleted_id = result.scalar_one_or_none()

    if deleted_id is None:
        logger.warning(f"User {current_user.id} attempted to delete non-existent rating for movie {movie_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rating not found for this movie.",
        )

    try:
        logger.debug(f"Updating stats for movie {movie_id} after rating deletion")
        await update_movie_rating_stats(movie_id, db)
        await db.commit()
        logger.info(f"Rating removed and stats recalculated for movie {movie_id} by user {current_user.id}")
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Failed to complete rating removal for user {current_user.id} (movie {movie_id}): {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error"
        )

    return None


@router.post(
    "/{movie_uuid}/vote/",
    response_model=MessageResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Like or Dislike a movie",
    description="Submit a like (true) or dislike (false). Updates existing vote if found.",
)
async def vote_movie(
    movie_uuid: UUID,
    vote_data: VoteCreateSchema,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Casts or updates a binary vote (like/dislike) for a movie."""
    logger.debug(f"User {current_user.id} is voting for movie {movie_uuid} (is_like={vote_data.is_like})")
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = select(MovieVoteModel).where(
        MovieVoteModel.user_id == current_user.id, MovieVoteModel.movie_id == movie_id
    )
    existing_vote = (await db.execute(stmt)).scalar_one_or_none()

    try:
        if not existing_vote:
            logger.info(f"User {current_user.id} cast a new vote for movie {movie_id}. Total votes counter incremented.")
            db.add(
                MovieVoteModel(
                    user_id=current_user.id, movie_id=movie_id, is_like=vote_data.is_like
                )
            )
            update_stmt = (
                update(MovieModel)
                .where(MovieModel.id == movie_id)
                .values(votes=MovieModel.votes + 1)
            )
            await db.execute(update_stmt)
            message = "Vote cast"
        else:
            logger.info(f"Updating existing vote for movie {movie_id} by user {current_user.id} to {vote_data.is_like}")
            existing_vote.is_like = vote_data.is_like
            message = "Vote updated"

        await db.commit()
        logger.info(f"Vote successfully committed for user {current_user.id}, movie {movie_id}")
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Database error while voting on movie {movie_id} by user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing your vote."
        )

    return {"message": message}


@router.post("/{movie_uuid}/comments/", status_code=status.HTTP_201_CREATED)
async def add_comment(
    movie_uuid: UUID,
    comment_data: CommentCreateSchema,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Posts a new comment or a reply to an existing comment for a specific movie."""
    logger.info(f"User {current_user.id} is adding a comment to movie {movie_uuid}")
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    parent_comment = None
    if comment_data.parent_id:
        parent_comment = await db.get(MovieCommentModel, comment_data.parent_id)

        if not parent_comment or parent_comment.movie_id != movie_id:
            logger.warning(f"Comment failed: User {current_user.id} provided invalid parent_id {comment_data.parent_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent comment not found or belongs to another movie",
            )

    try:
        new_comment = MovieCommentModel(
            user_id=current_user.id,
            movie_id=movie_id,
            text=comment_data.text,
            parent_id=comment_data.parent_id,
        )
        db.add(new_comment)

        if parent_comment and parent_comment.user_id != current_user.id:
            logger.debug(f"Creating reply notification for user {parent_comment.user_id} triggered by user {current_user.id}")
            notification = NotificationModel(
                user_id=parent_comment.user_id,
                notification_type=NotificationType.COMMENT_REPLY,
                content=f"User {current_user.email} replied to your comment",
                link_to_id=str(movie_uuid),
            )
            db.add(notification)

        await db.commit()
        logger.info(f"Comment successfully added by user {current_user.id} to movie {movie_id}")
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"DB error while adding comment for user {current_user.id}: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while saving your comment."
        )

    return {"message": "Comment added successfully"}


@router.patch(
    "/comments/{comment_id}/",
    response_model=CommentReadSchema,
    status_code=status.HTTP_200_OK,
    summary="Update Own Comment",
    description="Allows a user to edit their own comment text.",
    responses={
        403: {"description": "Forbidden - Not your comment."},
        404: {"description": "Not Found - Comment not found."},
    },
)
async def update_my_comment(
    comment_id: int,
    comment_data: CommentUpdateSchema,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edits the text content of a comment owned by the current user."""
    logger.debug(f"User {current_user.id} is attempting to update comment {comment_id}")
    stmt = (
        select(MovieCommentModel)
        .options(joinedload(MovieCommentModel.user))
        .where(MovieCommentModel.id == comment_id)
    )
    result = await db.execute(stmt)
    comment = result.scalars().first()

    if not comment:
        logger.warning(f"Comment update failed: comment {comment_id} not found for user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found."
        )

    if comment.user_id != current_user.id:
        logger.warning(f"Access denied: User {current_user.id} tried to edit comment {comment_id} owned by user {comment.user_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only edit your own comments.",
        )

    comment.text = comment_data.text

    try:
        await db.commit()
        await db.refresh(comment)
        logger.info(f"User {current_user.id} successfully updated comment {comment_id}")
    except SQLAlchemyError:
        await db.rollback()
        logger.error(f"DB error during comment {comment_id} update by user {current_user.id}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error."
        )

    return comment


@router.get("/notifications/", response_model=List[NotificationReadSchema])
async def get_my_notifications(
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieves a list of all notifications for the authenticated user."""
    logger.debug(f"User {current_user.id} requested notifications list")
    stmt = (
        select(NotificationModel)
        .where(NotificationModel.user_id == current_user.id)
        .order_by(NotificationModel.created_at.desc())
    )

    result = await db.execute(stmt)
    logger.debug(f"Retrieved notifications for user {current_user.id}")
    return result.scalars().all()


@router.patch("/notifications/{notif_id}/read/")
async def mark_as_read(
    notif_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Marks a specific notification as read, validating ownership first."""
    logger.debug(f"User {current_user.id} marking notification {notif_id} as read")
    stmt = (
        update(NotificationModel)
        .where(
            NotificationModel.id == notif_id,
            NotificationModel.user_id == current_user.id,
        )
        .values(is_read=True)
        .returning(NotificationModel.id)
    )

    result = await db.execute(stmt)
    updated_id = result.scalar_one_or_none()

    if updated_id is None:
        logger.warning(f"Notification {notif_id} not found or not owned by user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        )

    try:
        await db.commit()
        logger.info(f"Notification {notif_id} successfully marked as read for user {current_user.id}")
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Error marking notification {notif_id} as read: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error"
        )

    return {"message": "Marked as read"}


@router.get(
    "/{movie_uuid}/comments/",
    response_model=Page[CommentReadSchema],
    status_code=status.HTTP_200_OK,
)
async def list_movie_comments(
    movie_uuid: UUID,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Returns a paginated list of comments for a specific movie, including likes and user info."""
    logger.debug(f"Fetching comments for movie {movie_uuid} (page={page}, size={size})")
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = (
        select(MovieCommentModel)
        .options(
            joinedload(MovieCommentModel.user), selectinload(MovieCommentModel.likes)
        )
        .where(MovieCommentModel.movie_id == movie_id)
        .order_by(MovieCommentModel.created_at.desc())
    )

    try:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_count = await db.scalar(count_stmt) or 0

        logger.info(f"Movie {movie_id} has {total_count} total comments")

        offset = (page - 1) * size
        result = await db.execute(stmt.limit(size).offset(offset))
        comments = list(result.scalars().all())

        logger.debug(f"Page {page} of comments for movie {movie_id} retrieved successfully")
    except SQLAlchemyError as e:
        logger.error(
            f"Database error while listing comments for movie {movie_id}: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving comments"
        )

    return Page(
        items=comments,
        total=total_count,
        page=page,
        size=size,
        total_pages=(total_count + size - 1) // size if total_count > 0 else 0,
    )


@router.post("/comments/{comment_id}/like/", response_model=MessageResponseSchema)
async def like_comment(
    comment_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Toggles a like on a comment and notifies the author if it's a new like."""
    logger.debug(f"User {current_user.id} toggling like on comment {comment_id}")
    stmt = (
        select(MovieCommentModel)
        .options(joinedload(MovieCommentModel.movie))
        .where(MovieCommentModel.id == comment_id)
    )
    comment = (await db.execute(stmt)).scalar_one_or_none()

    if not comment:
        logger.warning(f"Like failed: Comment {comment_id} not found for user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found"
        )

    like_stmt = select(CommentLikeModel).where(
        CommentLikeModel.user_id == current_user.id,
        CommentLikeModel.comment_id == comment_id,
    )
    existing_like = await db.scalar(like_stmt)

    try:
        if existing_like:
            await db.delete(existing_like)
            await db.commit()
            logger.info(f"User {current_user.id} unliked comment {comment_id}")
            return {"message": "Like removed"}

        db.add(CommentLikeModel(user_id=current_user.id, comment_id=comment_id))

        if comment.user_id != current_user.id:
            logger.debug(f"Creating like notification for author {comment.user_id}")
            notification = NotificationModel(
                user_id=comment.user_id,
                notification_type=NotificationType.COMMENT_LIKE,
                content=f"User {current_user.email} liked your comment",
                link_to_id=str(comment.movie.uuid),
            )

            db.add(notification)
        await db.commit()

        logger.info(f"User {current_user.id} liked comment {comment_id} (Author: {comment.user_id})")
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Database error during like toggle for user {current_user.id} on comment {comment_id}: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error"
        )

    return {"message": "Comment liked"}


# =============================================================================
# MODERATOR AND ADMIN ROUTES
# =============================================================================


@router.post(
    "/genres/",
    response_model=GenreReadSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Genre",
    description="Add a new genre to the database. Restricted to staff.",
)
async def create_genre(
    genre_data: GenreCreateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Creates a new unique genre in the database. Restricted to staff users."""
    logger.info(f"Staff user {current_user.id} is creating a new genre: '{genre_data.name}'")
    new_genre = GenreModel(name=genre_data.name)
    db.add(new_genre)

    try:
        await db.commit()
        await db.refresh(new_genre)
        logger.info(f"Genre '{new_genre.name}' (ID: {new_genre.id}) successfully created by user {current_user.id}")
    except IntegrityError as e:
        await db.rollback()
        logger.warning(f"Genre creation failed: Name '{genre_data.name}' already exists. (User: {current_user.id})")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Genre with this name already exists.",
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"Unexpected error during genre creation by user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred."
        )

    return new_genre


@router.patch(
    "/genres/{genre_id}/",
    response_model=GenreReadSchema,
    status_code=status.HTTP_200_OK,
    summary="Update Genre",
)
async def update_genre(
    genre_id: int,
    genre_data: GenreUpdateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Updates the name of an existing genre, ensuring the new name remains unique."""
    logger.debug(f"Staff user {current_user.id} initiated update for genre_id: {genre_id}")
    genre = await db.get(GenreModel, genre_id)
    if not genre:
        logger.warning(f"Genre update failed: ID {genre_id} not found (User: {current_user.id})")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Genre not found."
        )

    old_name = genre.name
    new_name = genre_data.name

    if new_name:
        genre.name = new_name

    try:
        await db.commit()
        await db.refresh(genre)
        logger.info(
            f"Genre {genre_id} updated by staff {current_user.id}: "
            f"'{old_name}' -> '{new_name}'"
        )
    except IntegrityError:
        await db.rollback()
        logger.warning(
            f"Conflict: Staff {current_user.id} tried to rename genre {genre_id} "
            f"to existing name '{new_name}'"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Genre with this name already exists.",
        )
    except Exception as e:
        await db.rollback()
        logger.error(
            f"Error updating genre {genre_id} by user {current_user.id}: {str(e)}",
            exc_info=True
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error.")

    return genre


@router.delete(
    "/genres//{genre_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Genre",
)
async def delete_genre(
    genre_id: int,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently deletes a genre by ID. Movie-genre associations are cleaned via cascade."""
    logger.info(f"Staff user {current_user.id} is attempting to delete genre ID: {genre_id}")
    genre = await db.get(GenreModel, genre_id)
    if not genre:
        logger.warning(f"Delete failed: Genre ID {genre_id} not found. (User: {current_user.id})")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Genre not found."
        )

    try:
        logger.debug(f"Deleting genre object: {genre.name} (ID: {genre_id})")
        await db.delete(genre)
        await db.commit()
        logger.info(f"Genre ID {genre_id} successfully deleted by staff user {current_user.id}")
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Database error during genre {genre_id} deletion by user {current_user.id}: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete genre.",
        )
    return None


@router.post(
    "/",
    response_model=MovieDetailResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create New Movie",
    description="Add a new movie to the catalog. Only Admins and Moderators can perform this action.",
    responses={
        400: {
            "description": "Bad Request - Integrity constraint violation or missing relations."
        },
        401: {"description": "Unauthorized."},
        403: {"description": "Forbidden - Insufficient permissions."},
        500: {"description": "Internal Server Error - Database failure."},
    },
)
async def create_movie(
    movie_data: MovieCreateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
) -> MovieModel:
    """Creates a new movie record and validates all related entity IDs (genres, stars, etc.)."""
    logger.info(f"Staff user {current_user.id} is creating movie: '{movie_data.name}'")

    cert = await db.get(CertificationModel, movie_data.certification_id)
    if not cert:
        logger.warning(f"Movie creation failed: Certification {movie_data.certification_id} not found")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Certification with id {movie_data.certification_id} not found.",
        )

    genres_stmt = select(GenreModel).where(GenreModel.id.in_(movie_data.genre_ids))
    stars_stmt = select(StarModel).where(StarModel.id.in_(movie_data.star_ids))
    directors_stmt = select(DirectorModel).where(
        DirectorModel.id.in_(movie_data.director_ids)
    )

    genres = (await db.execute(genres_stmt)).scalars().all()
    stars = (await db.execute(stars_stmt)).scalars().all()
    directors = (await db.execute(directors_stmt)).scalars().all()

    if len(genres) != len(movie_data.genre_ids):
        logger.warning(f"Creation failed: User {current_user.id} provided invalid genre IDs")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more genre IDs are invalid.",
        )

    movie_fields = movie_data.model_dump(
        exclude={"genre_ids", "star_ids", "director_ids"}
    )
    new_movie = MovieModel(**movie_fields)

    new_movie.genres = list(genres)
    new_movie.stars = list(stars)
    new_movie.directors = list(directors)

    db.add(new_movie)

    try:
        await db.flush()
        await db.commit()
        await db.refresh(new_movie, ["genres", "stars", "directors", "certification"])
        logger.info(f"Movie '{new_movie.name}' (ID: {new_movie.id}) successfully created by user {current_user.id}")
    except IntegrityError:
        await db.rollback()
        logger.warning(f"Conflict: Movie '{movie_data.name}' ({movie_data.year}) already exists in DB")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Movie with this name, year and duration already exists.",
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Database error during movie creation: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while creating the movie.",
        )

    return new_movie


@router.patch(
    "/{movie_uuid}/",
    response_model=MovieDetailResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Update Movie Details",
    description="Partially update movie information, including relationships. Only staff can perform this.",
    responses={
        400: {"description": "Bad Request - Invalid data or constraint violation."},
        401: {"description": "Unauthorized."},
        403: {"description": "Forbidden - Staff access required."},
        404: {"description": "Not Found - Movie not found."},
        500: {"description": "Internal Server Error."},
    },
)
async def update_movie(
    movie_uuid: UUID,
    movie_data: MovieUpdateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
) -> MovieModel:
    """Partially updates movie details and replaces specific relationships if IDs are provided."""
    logger.info(f"Staff user {current_user.id} initiated update for movie UUID: {movie_uuid}")

    stmt = (
        select(MovieModel)
        .options(
            selectinload(MovieModel.genres),
            selectinload(MovieModel.stars),
            selectinload(MovieModel.directors),
            joinedload(MovieModel.certification),
        )
        .where(MovieModel.uuid == movie_uuid)
    )
    result = await db.execute(stmt)
    movie = result.scalars().first()

    if not movie:
        logger.warning(f"Update failed: Movie with UUID {movie_uuid} not found (User: {current_user.id})")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found."
        )

    relationship_configs = [
        ("genre_ids", GenreModel, "genres"),
        ("star_ids", StarModel, "stars"),
        ("director_ids", DirectorModel, "directors"),
    ]

    for field_name, model_cls, attr_name in relationship_configs:
        ids = getattr(movie_data, field_name)
        if ids is not None:
            if not ids:
                setattr(movie, attr_name, [])
                continue

            objs_stmt = select(model_cls).where(model_cls.id.in_(ids))
            found_objs = (await db.execute(objs_stmt)).scalars().all()

            if len(found_objs) != len(ids):
                logger.warning(f"User {current_user.id} provided invalid IDs in {field_name}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Some IDs in {field_name} are invalid.",
                )
            setattr(movie, attr_name, list(found_objs))

    if movie_data.certification_id is not None:
        cert = await db.get(CertificationModel, movie_data.certification_id)
        if not cert:
            logger.warning(f"Invalid certification_id {movie_data.certification_id} provided by user {current_user.id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid certification_id.",
            )
        movie.certification_id = movie_data.certification_id

    update_data = movie_data.model_dump(
        exclude_unset=True,
        exclude={"genre_ids", "star_ids", "director_ids", "certification_id"},
    )

    for key, value in update_data.items():
        setattr(movie, key, value)

    try:
        await db.commit()
        await db.refresh(movie, ["genres", "stars", "directors", "certification"])
        logger.info(f"Movie {movie_uuid} ('{movie.name}') successfully updated by staff {current_user.id}")
    except IntegrityError:
        await db.rollback()
        logger.warning(f"IntegrityError: Update of movie {movie_uuid} violates unique constraints")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Update failed: Unique constraint violation (name/year/time).",
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Critical DB error during movie {movie_uuid} update: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error during update.",
        )

    return movie


@router.delete(
    "/{movie_uuid}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Movie",
    description="Permanently remove a movie and all its associated data (ratings, comments, etc.).",
    responses={
        204: {"description": "Movie deleted successfully."},
        401: {"description": "Unauthorized."},
        403: {"description": "Forbidden - Staff access required."},
        404: {"description": "Not Found - Movie not found."},
        500: {"description": "Internal Server Error."},
    },
)
async def delete_movie(
    movie_uuid: UUID,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Removes a movie by UUID, automatically clearing related ratings, comments, and favorites."""
    logger.info(f"Staff user {current_user.id} is attempting to delete movie UUID: {movie_uuid}")

    stmt = select(MovieModel).where(MovieModel.uuid == movie_uuid)
    result = await db.execute(stmt)
    movie = result.scalars().first()

    if not movie:
        logger.warning(f"Delete failed: Movie {movie_uuid} not found (User: {current_user.id})")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found."
        )

    try:
        movie_name = movie.name
        logger.debug(f"Processing deletion of movie '{movie_name}'")

        await db.delete(movie)
        await db.commit()

        logger.info(f"Movie '{movie_name}' (UUID: {movie_uuid}) successfully deleted by staff {current_user.id}")
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Database error during deletion of movie {movie_uuid} by user {current_user.id}: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete the movie from the database.",
        )

    return None


@router.delete(
    "/comments/{comment_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Comment",
    description="Users can delete their own comments. Staff can delete any comment.",
    responses={
        204: {"description": "Deleted successfully."},
        403: {"description": "Forbidden - Access denied."},
        404: {"description": "Not Found."},
    },
)
async def delete_comment(
    comment_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deletes a comment. Owners can delete their own; staff can delete any and notify the user."""
    logger.debug(f"User {current_user.id} initiated deletion of comment {comment_id}")

    stmt = select(MovieCommentModel).where(MovieCommentModel.id == comment_id)
    result = await db.execute(stmt)
    comment = result.scalars().first()

    if not comment:
        logger.warning(f"Comment {comment_id} not found for deletion by user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found."
        )

    is_owner = comment.user_id == current_user.id
    is_staff = current_user.group.name in [UserGroupEnum.ADMIN, UserGroupEnum.MODERATOR]

    if not (is_owner or is_staff):
        logger.warning(
                f"Security: User {current_user.id} blocked from deleting comment {comment_id} (Owner: {comment.user_id})"
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this comment.",
        )

    if is_staff and not is_owner:
        logger.info(f"Moderation action: Staff {current_user.id} is deleting comment {comment_id} by user {comment.user_id}")
        logger.debug(f"Sending moderation notification to user {comment.user_id}")
        notification = NotificationModel(
            user_id=comment.user_id,
            notification_type=NotificationType.SYSTEM,
            content="Your comment was removed by a moderator.",
            link_to_id=None,
        )
        db.add(notification)

    try:
        await db.delete(comment)
        await db.commit()
        logger.info(f"Comment {comment_id} successfully deleted by user {current_user.id}")
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Failed to delete comment {comment_id} for user {current_user.id}: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error"
        )

    return None


@router.get(
    "/stars/",
    response_model=Page[StarReadSchema],
    status_code=status.HTTP_200_OK,
    summary="[Admin] Get All Stars",
    description="Get a simple list of stars for management purposes.",
)
async def get_stars(
    page: int = Query(1, ge=1, description="Current page number"),
    size: int = Query(10, ge=1, le=100, description="Items per page"),
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns a paginated list of all actors (stars) ordered alphabetically by name."""
    logger.info(f"Staff user {current_user.id} requested stars list. Page: {page}, Size: {size}")

    try:
        count_stmt = select(func.count()).select_from(StarModel)
        total_count = await db.scalar(count_stmt) or 0

        stmt = (
            select(StarModel)
            .order_by(StarModel.name)
            .limit(size)
            .offset((page - 1) * size)
        )
        result = await db.execute(stmt)
        stars = list(result.scalars().all())

        logger.info(f"Returning {len(stars)} stars (Total: {total_count}) to staff {current_user.id}")
        return Page(
            items=stars,
            total=total_count,
            page=page,
            size=size,
            total_pages=(total_count + size - 1) // size if total_count > 0 else 0,
        )
    except SQLAlchemyError as e:
        logger.error(
            f"Failed to fetch stars list for staff {current_user.id}: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching stars."
        )


@router.post(
    "/stars/",
    response_model=StarReadSchema,
    status_code=status.HTTP_201_CREATED,
    summary="[Admin] Create Star",
)
async def create_star(
    star_data: StarCreateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Adds a new actor to the database. Ensures the name is unique."""
    logger.info(f"Staff user {current_user.id} creating star: '{star_data.name}'")

    new_star = StarModel(name=star_data.name)
    db.add(new_star)

    try:
        await db.commit()
        await db.refresh(new_star)
        logger.info(f"Star created: '{new_star.name}' (ID: {new_star.id})")
    except IntegrityError:
        await db.rollback()
        logger.warning(f"Conflict: Star '{star_data.name}' already exists")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="This star already exists."
        )
    return new_star


@router.patch(
    "/stars/{star_id}/",
    response_model=StarReadSchema,
    status_code=status.HTTP_200_OK,
    summary="[Admin] Update Star",
)
async def update_star(
    star_id: int,
    star_data: StarUpdateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Updates an actor's name after validating it doesn't conflict with existing records."""
    logger.debug(f"User {current_user.id} updating star {star_id}")

    star = await db.get(StarModel, star_id)
    if not star:
        logger.warning(f"Star {star_id} not found for update by user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Star not found."
        )

    old_name = star.name
    if star_data.name:
        star.name = star_data.name

    try:
        await db.commit()
        await db.refresh(star)
        logger.info(f"Star {star_id} updated by {current_user.id}: '{old_name}' -> '{star.name}'")
    except IntegrityError:
        await db.rollback()
        logger.warning(f"Update conflict: Name '{star_data.name}' already taken")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Another star already has this name.",
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Error updating star {star_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error during update.",
        )

    return star


@router.delete(
    "/stars/{star_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="[Admin] Delete Star",
)
async def delete_star(
    star_id: int,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently deletes an actor record and severs all movie associations."""
    logger.info(f"Staff user {current_user.id} initiated deletion for star ID: {star_id}")

    star = await db.get(StarModel, star_id)
    if not star:
        logger.warning(f"Star ID {star_id} not found for deletion by user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Star not found."
        )

    try:
        star_name = star.name
        logger.debug(f"Deleting star object: {star_name}")

        await db.delete(star)
        await db.commit()

        logger.info(f"Star '{star_name}' (ID: {star_id}) deleted by user {current_user.id}")
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Database error while deleting star {star_id}: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error during deletion.",
        )
    return None


@router.get(
    "/directors/",
    response_model=Page[DirectorReadSchema],
    status_code=status.HTTP_200_OK,
    summary="[Admin] Get All Directors (Paginated)",
    description="Get a list of all directors for database management.",
)
async def get_directors(
    page: int = Query(1, ge=1, description="Current page number"),
    size: int = Query(10, ge=1, le=100, description="Items per page"),
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieves a paginated list of directors for administrative management."""
    logger.info(f"Staff user {current_user.id} fetching directors. Page: {page}, Size: {size}")

    try:
        count_stmt = select(func.count()).select_from(DirectorModel)
        total_count = await db.scalar(count_stmt) or 0

        stmt = (
            select(DirectorModel)
            .order_by(DirectorModel.name)
            .limit(size)
            .offset((page - 1) * size)
        )

        result = await db.execute(stmt)
        directors = list(result.scalars().all())

        logger.info(f"Returning {len(directors)} directors (Total: {total_count})")

        return Page(
            items=directors,
            total=total_count,
            page=page,
            size=size,
            total_pages=(total_count + size - 1) // size if total_count > 0 else 0,
        )
    except SQLAlchemyError as e:
        logger.error(f"Error fetching directors: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching directors."
        )


@router.post(
    "/directors/",
    response_model=DirectorReadSchema,
    status_code=status.HTTP_201_CREATED,
    summary="[Admin] Create Director",
)
async def create_director(
    director_data: DirectorCreateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Creates a new director record. Raises a conflict error if the name already exists."""
    logger.info(f"Staff user {current_user.id} initiated director creation: '{director_data.name}'")

    new_director = DirectorModel(name=director_data.name)
    db.add(new_director)

    try:
        await db.commit()
        await db.refresh(new_director)
        logger.info(f"Director '{new_director.name}' (ID: {new_director.id}) created by user {current_user.id}")
    except IntegrityError:
        await db.rollback()
        logger.warning(f"Conflict: Director '{director_data.name}' already exists in the database")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This director already exists in the database.",
        )
    return new_director


@router.patch(
    "/directors/{director_id}/",
    response_model=DirectorReadSchema,
    status_code=status.HTTP_200_OK,
    summary="[Admin] Update Director",
)
async def update_director(
    director_id: int,
    director_data: DirectorUpdateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Renames an existing director and performs a uniqueness check on the new name."""
    logger.debug(f"User {current_user.id} requested update for director {director_id}")

    director = await db.get(DirectorModel, director_id)
    if not director:
        logger.warning(f"Update failed: Director {director_id} not found (User: {current_user.id})")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Director not found."
        )

    old_name = director.name
    if director_data.name:
        director.name = director_data.name

    try:
        await db.commit()
        await db.refresh(director)
        logger.info(f"Director {director_id} updated by staff {current_user.id}: '{old_name}' -> '{director.name}'")
    except IntegrityError:
        await db.rollback()
        logger.warning(f"Conflict: Name '{director_data.name}' already exists (Update aborted for ID {director_id})")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conflict: Another director with this name already exists.",
        )
    return director


@router.delete(
    "/directors/{director_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="[Admin] Delete Director",
)
async def delete_director(
    director_id: int,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Removes a director from the catalog by their internal ID."""
    logger.info(f"Staff user {current_user.id} initiated deletion for director ID: {director_id}")

    director = await db.get(DirectorModel, director_id)
    if not director:
        logger.warning(f"Director ID {director_id} not found for deletion by user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Director not found."
        )

    try:
        director_name = director.name
        logger.debug(f"Deleting director object: {director_name}")

        await db.delete(director)
        await db.commit()

        logger.info(f"Director '{director_name}' (ID: {director_id}) deleted by user {current_user.id}")
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Database error during director {director_id} deletion: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete director.",
        )
    return None


@router.get(
    "/certifications/",
    response_model=Page[CertificationReadSchema],
    status_code=status.HTTP_200_OK,
    summary="[Admin] Get All Certifications (Paginated)",
)
async def list_certifications(
    page: int = Query(1, ge=1, description="Current page number"),
    size: int = Query(10, ge=1, le=100, description="Items per page"),
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
)-> Page[CertificationReadSchema]:
    """Provides a paginated list of available age ratings and certifications."""
    logger.debug(f"User {current_user.id} is fetching certifications list")

    try:
        count_stmt = select(func.count()).select_from(CertificationModel)
        total_count = await db.scalar(count_stmt) or 0

        stmt = (
            select(CertificationModel)
            .order_by(CertificationModel.name)
            .limit(size)
            .offset((page - 1) * size)
        )

        result = await db.execute(stmt)
        certs = list(result.scalars().all())

        logger.info(f"Returning {len(certs)} certifications (Total: {total_count})")

        return Page(
            items=certs,
            total=total_count,
            page=page,
            size=size,
            total_pages=(total_count + size - 1) // size if total_count > 0 else 0,
        )

    except SQLAlchemyError as e:
        logger.error(f"Error fetching certifications for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching certifications."
        )


@router.post(
    "/certifications/",
    response_model=CertificationReadSchema,
    status_code=status.HTTP_201_CREATED,
    summary="[Admin] Create Certification",
)
async def create_certification(
    cert_data: CertificationCreateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Registers a new age certification (e.g., 'PG-13', '18+') in the system."""
    logger.info(f"Staff user {current_user.id} is creating a new certification: '{cert_data.name}'")

    new_cert = CertificationModel(name=cert_data.name)
    db.add(new_cert)
    try:
        await db.commit()
        await db.refresh(new_cert)
        logger.info(f"Certification '{new_cert.name}' (ID: {new_cert.id}) created by user {current_user.id}")
    except IntegrityError:
        await db.rollback()
        logger.warning(f"Conflict: Certification '{cert_data.name}' already exists (User: {current_user.id})")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Certification with this name already exists.",
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Database error during certification creation: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal database error occurred."
        )
    return new_cert


@router.patch(
    "/certifications/{cert_id}/",
    response_model=CertificationReadSchema,
    status_code=status.HTTP_200_OK,
    summary="[Admin] Update Certification",
)
async def update_certification(
    cert_id: int,
    cert_data: CertificationUpdateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Modifies the name of an existing age rating certification."""
    logger.debug(f"User {current_user.id} requested update for certification {cert_id}")
    cert = await db.get(CertificationModel, cert_id)
    if not cert:
        logger.warning(f"Certification {cert_id} not found for update by user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Certification not found."
        )

    old_name = cert.name
    if cert_data.name:
        cert.name = cert_data.name

    try:
        await db.commit()
        await db.refresh(cert)
        logger.info(f"Certification {cert_id} updated by {current_user.id}: '{old_name}' -> '{cert.name}'")
    except IntegrityError:
        await db.rollback()
        logger.warning(f"Update conflict: Certification name '{cert_data.name}' is already taken")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conflict: This certification name is already taken.",
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Error updating certification {cert_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error during update.",
        )
    return cert


@router.delete(
    "/certifications/{cert_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="[Admin] Delete Certification",
)
async def delete_certification(
    cert_id: int,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Deletes a certification, provided no movies are currently linked to it."""
    logger.info(f"Staff user {current_user.id} is attempting to delete certification ID: {cert_id}")
    cert = await db.get(CertificationModel, cert_id)
    if not cert:
        logger.warning(f"Certification {cert_id} not found for deletion by user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Certification not found."
        )

    cert_name = cert.name

    try:
        await db.delete(cert)
        await db.commit()
        logger.info(f"Certification '{cert_name}' (ID: {cert_id}) successfully deleted by staff {current_user.id}")
    except IntegrityError:
        await db.rollback()
        logger.warning(
            f"Delete aborted: Certification '{cert_name}' (ID: {cert_id}) is linked to existing movies. "
            f"Action by user {current_user.id}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete: this certification is currently assigned to movies.",
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Critical database error during certification {cert_id} deletion: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred.",
        )
    return None
