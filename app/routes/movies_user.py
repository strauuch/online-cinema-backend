import logging

from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy import select, func, or_, delete, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from core.dependencies import (
    get_current_user,
    update_movie_rating_stats,
    get_current_user_optional,
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
    CommentUpdateSchema,
)
from schemas.pagination import Page

router = APIRouter()

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


@router.get(
    "/genres/",
    response_model=Page[GenreWithCountSchema],
    status_code=status.HTTP_200_OK,
    summary="Get all genres (Paginated)",
)
async def list_genres(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="Current page number"),
    size: int = Query(10, ge=1, le=100, description="Items per page"),
) -> Page[GenreWithCountSchema]:
    """Retrieves all genres with the total count of movies associated with each.

    The list is sorted by the number of movies in descending order, showing the most popular genres first.
    """
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

        logger.info(
            f"Found {total_count} total genres, returning {len(genres)} for page {page}"
        )
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
    "/notifications/",
    response_model=List[NotificationReadSchema],
    summary="Get notifications",
)
async def get_my_notifications(
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieves a list of all personal notifications (replies to comments, likes, etc.).
    The list is sorted by date, with the most recent notifications first.
    """
    logger.debug(f"User {current_user.id} requested notifications list")

    stmt = (
        select(NotificationModel)
        .where(NotificationModel.user_id == current_user.id)
        .order_by(NotificationModel.created_at.desc())
    )

    result = await db.execute(stmt)
    logger.debug(f"Retrieved notifications for user {current_user.id}")
    return result.scalars().all()


@router.patch(
    "/notifications/{notif_id}/read/",
    summary="Mark notification as read",
)
async def mark_as_read(
    notif_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Marks a specific notification as read.
    The user can only mark notifications that belong to their own account.
    """
    logger.debug(f"User {current_user.id} marking notification {notif_id} as read")

    current_user_id = current_user.id

    stmt = (
        update(NotificationModel)
        .where(
            NotificationModel.id == notif_id,
            NotificationModel.user_id == current_user_id,
        )
        .values(is_read=True)
        .returning(NotificationModel.id)
    )

    result = await db.execute(stmt)
    updated_id = result.scalar_one_or_none()

    if updated_id is None:
        logger.warning(
            f"Notification {notif_id} not found or not owned by user {current_user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        )

    try:
        await db.commit()
        logger.info(
            f"Notification {notif_id} successfully marked as read for user {current_user_id}"
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Error marking notification {notif_id} as read: {str(e)}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error"
        )

    return {"message": "Marked as read"}


@router.patch(
    "/comments/{comment_id}/",
    response_model=CommentReadSchema,
    status_code=status.HTTP_200_OK,
    summary="Update own comment",
)
async def update_my_comment(
    comment_id: int,
    comment_data: CommentUpdateSchema,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edits the text content of a comment owned by the current user."""
    logger.debug(f"User {current_user.id} is attempting to update comment {comment_id}")

    current_user_id = current_user.id

    stmt = (
        select(MovieCommentModel)
        .options(
            joinedload(MovieCommentModel.user), selectinload(MovieCommentModel.likes)
        )
        .where(MovieCommentModel.id == comment_id)
    )
    result = await db.execute(stmt)
    comment = result.scalars().first()

    if not comment:
        logger.warning(
            f"Comment update failed: comment {comment_id} not found for user {current_user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found."
        )

    if comment.user_id != current_user_id:
        logger.warning(
            f"Access denied: User {current_user_id} tried to edit comment {comment_id} owned by user {comment.user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only edit your own comments.",
        )

    comment.text = comment_data.text

    try:
        await db.commit()
        await db.refresh(comment)
        logger.info(f"User {current_user_id} successfully updated comment {comment_id}")
    except SQLAlchemyError:
        await db.rollback()
        logger.error(
            f"DB error during comment {comment_id} update by user {current_user_id}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error."
        )

    return comment


@router.post(
    "/comments/{comment_id}/like/",
    response_model=MessageResponseSchema,
    summary="Like or unlike a comment",
)
async def like_comment(
    comment_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Toggles a like on a comment.

    If the user hasn't liked it yet, a like is added and the author receives a notification.
    If a like already exists, it is removed.
    """
    logger.debug(f"User {current_user.id} toggling like on comment {comment_id}")

    current_user_id = current_user.id
    current_user_email = current_user.email

    stmt = (
        select(MovieCommentModel)
        .options(joinedload(MovieCommentModel.movie))
        .where(MovieCommentModel.id == comment_id)
    )
    comment = (await db.execute(stmt)).scalar_one_or_none()

    if not comment:
        logger.warning(
            f"Like failed: Comment {comment_id} not found for user {current_user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found"
        )

    like_stmt = select(CommentLikeModel).where(
        CommentLikeModel.user_id == current_user_id,
        CommentLikeModel.comment_id == comment_id,
    )
    existing_like = await db.scalar(like_stmt)

    try:
        if existing_like:
            await db.delete(existing_like)
            await db.commit()
            logger.info(f"User {current_user_id} unliked comment {comment_id}")
            return {"message": "Like removed"}

        db.add(CommentLikeModel(user_id=current_user_id, comment_id=comment_id))

        if comment.user_id != current_user_id:
            logger.debug(f"Creating like notification for author {comment.user_id}")
            notification = NotificationModel(
                user_id=comment.user_id,
                notification_type=NotificationType.COMMENT_LIKE,
                content=f"User {current_user_email} liked your comment",
                link_to_id=str(comment.movie.uuid),
            )

            db.add(notification)
        await db.commit()

        logger.info(
            f"User {current_user_id} liked comment {comment_id} (Author: {comment.user_id})"
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Database error during like toggle for user {current_user_id} on comment {comment_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error"
        )

    return {"message": "Comment liked"}


@router.delete(
    "/comments/{comment_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete comment [Owner | Admin | Moderator]",
)
async def delete_comment(
    comment_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Deletes a comment with permission checks.

    **Access Levels:**
    * **Owner**: Can delete their own comment at any time.
    * **Staff (Admin/Moderator)**: Can delete any comment.

    **Side Effects:**
    If a staff member deletes a user's comment, the user will receive a **system notification** about the moderation action.
    """
    logger.debug(f"User {current_user.id} initiated deletion of comment {comment_id}")

    current_user_id = current_user.id

    stmt = select(MovieCommentModel).where(MovieCommentModel.id == comment_id)
    result = await db.execute(stmt)
    comment = result.scalars().first()

    if not comment:
        logger.warning(
            f"Comment {comment_id} not found for deletion by user {current_user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found."
        )

    await db.refresh(current_user, ["group"])

    is_owner = comment.user_id == current_user_id
    is_staff = current_user.group.name in [UserGroupEnum.ADMIN, UserGroupEnum.MODERATOR]

    if not (is_owner or is_staff):
        logger.warning(
            f"Security: User {current_user_id} blocked from deleting comment {comment_id} (Owner: {comment.user_id})"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this comment.",
        )

    if is_staff and not is_owner:
        logger.info(
            f"Moderation action: Staff {current_user_id} is deleting comment {comment_id} by user {comment.user_id}"
        )
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
        logger.info(
            f"Comment {comment_id} successfully deleted by user {current_user_id}"
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Failed to delete comment {comment_id} for user {current_user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error"
        )

    return None


@router.get(
    "/",
    response_model=Page[MovieShortResponseSchema],
    status_code=status.HTTP_200_OK,
    summary="Browse and filter movie catalog (Paginated)",
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
    current_user: Optional[UserModel] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> Page[MovieShortResponseSchema]:
    """
    Provides a paginated list of movies with multi-criteria filtering and full-text search.

    **Search & Filtering Logic:**
    * **Full-text Search (`q`)**: Performs a case-insensitive search across movie titles, descriptions, and the names of actors (stars) and directors.
    * **Favorites**: When `only_favorites` is true, returns only movies from the user's personal list. Requires an authorization token.
    * **Categorization**: Filter by release year, genre, or set a minimum IMDb score threshold.

    **Ordering:**
    * Supports sorting by **year**, **price**, **imdb** rating, and **popularity** (based on total vote count).
    * Results are returned in descending order by default.

    **Note on Performance:**
    Uses `selectinload` for genres to optimize database queries and avoid N+1 issues.
    """
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
        total_pages=(total_count + size - 1) // size if total_count > 0 else 0,
    )


@router.get(
    "/{movie_uuid}/",
    response_model=MovieDetailResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Get movie details",
)
async def get_movie_detail(
    movie_uuid: UUID, db: AsyncSession = Depends(get_db)
) -> MovieDetailResponseSchema:
    """
    Retrieves full information about a specific movie by its public UUID.
    Includes expanded data for genres, cast (stars), directors, and age certification.
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
        logger.error(
            f"Database error while fetching movie {movie_uuid}: {str(e)}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while fetching movie details",
        )

    if not movie:
        logger.warning(f"Movie not found for UUID: {movie_uuid}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with provided UUID not found",
        )

    logger.debug(
        f"Movie details for '{movie.name}' (ID: {movie.id}) successfully retrieved"
    )

    return movie


@router.get(
    "/{movie_uuid}/comments/",
    response_model=Page[CommentReadSchema],
    status_code=status.HTTP_200_OK,
    summary="List movie comments (Paginated)",
)
async def list_movie_comments(
    movie_uuid: UUID,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns a paginated list of comments for a specific movie.
    Includes information about the authors and the list of users who liked each comment.
    """
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

        logger.debug(
            f"Page {page} of comments for movie {movie_id} retrieved successfully"
        )
    except SQLAlchemyError as e:
        logger.error(
            f"Database error while listing comments for movie {movie_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving comments",
        )

    return Page(
        items=comments,
        total=total_count,
        page=page,
        size=size,
        total_pages=(total_count + size - 1) // size if total_count > 0 else 0,
    )


@router.post(
    "/{movie_uuid}/comments/",
    status_code=status.HTTP_201_CREATED,
    summary="Add comment to movie",
)
async def add_comment(
    movie_uuid: UUID,
    comment_data: CommentCreateSchema,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Posts a new comment or a reply to an existing one.

    If the comment is a reply, the author of the parent comment will receive
    an automatic system notification.
    """
    logger.info(f"User {current_user.id} is adding a comment to movie {movie_uuid}")

    current_user_id = current_user.id
    current_user_email = current_user.email
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    parent_comment = None
    if comment_data.parent_id:
        parent_comment = await db.get(MovieCommentModel, comment_data.parent_id)

        if not parent_comment or parent_comment.movie_id != movie_id:
            logger.warning(
                f"Comment failed: User {current_user_id} provided invalid parent_id {comment_data.parent_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent comment not found or belongs to another movie",
            )

    try:
        new_comment = MovieCommentModel(
            user_id=current_user_id,
            movie_id=movie_id,
            text=comment_data.text,
            parent_id=comment_data.parent_id,
        )
        db.add(new_comment)

        if parent_comment and parent_comment.user_id != current_user_id:
            logger.debug(
                f"Creating reply notification for user {parent_comment.user_id} triggered by user {current_user_id}"
            )
            notification = NotificationModel(
                user_id=parent_comment.user_id,
                notification_type=NotificationType.COMMENT_REPLY,
                content=f"User {current_user_email} replied to your comment",
                link_to_id=str(movie_uuid),
            )
            db.add(notification)

        await db.commit()
        logger.info(
            f"Comment successfully added by user {current_user_id} to movie {movie_id}"
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"DB error while adding comment for user {current_user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while saving your comment.",
        )

    return {"message": "Comment added successfully"}


@router.post(
    "/{movie_uuid}/favorite/",
    status_code=status.HTTP_201_CREATED,
    response_model=MessageResponseSchema,
    summary="Add movie to favorites",
)
async def add_favorite(
    movie_uuid: UUID,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Adds a movie to the user's personal favorites list.
    If the movie is already in favorites, it returns a success message without creating a duplicate.
    """
    logger.debug(
        f"User {current_user.id} attempting to add movie {movie_uuid} to favorites"
    )

    current_user_id = current_user.id
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = select(MovieFavoriteModel).where(
        MovieFavoriteModel.user_id == current_user_id,
        MovieFavoriteModel.movie_id == movie_id,
    )
    existing = await db.scalar(stmt)
    if existing:
        logger.info(
            f"User {current_user_id} already has movie {movie_uuid} in favorites"
        )
        return {"message": "Movie is already in favorites"}

    try:
        new_favorite = MovieFavoriteModel(user_id=current_user_id, movie_id=movie_id)
        db.add(new_favorite)
        await db.commit()
        logger.info(
            f"Successfully added movie {movie_uuid} to favorites for user {current_user_id}"
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"DB Error while adding favorite for user {current_user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error"
        )

    return {"message": "Movie added to favorites"}


@router.delete(
    "/{movie_uuid}/favorite/",
    status_code=status.HTTP_200_OK,
    response_model=MessageResponseSchema,
    summary="Remove movie from favorites",
)
async def remove_favorite(
    movie_uuid: UUID,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Removes a movie from the user's personal favorites list."""
    logger.debug(
        f"Process 'remove_favorite' started for user {current_user.id}, movie {movie_uuid}"
    )

    current_user_id = current_user.id

    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = (
        delete(MovieFavoriteModel)
        .where(
            MovieFavoriteModel.user_id == current_user_id,
            MovieFavoriteModel.movie_id == movie_id,
        )
        .returning(MovieFavoriteModel.movie_id)
    )

    result = await db.execute(stmt)
    deleted_id = result.scalar_one_or_none()

    if deleted_id is None:
        logger.warning(
            f"Deletion failed: movie {movie_uuid} not in user {current_user_id} favorites"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not in favorites"
        )

    try:
        await db.commit()
        logger.info(
            f"User {current_user_id} successfully removed movie {movie_uuid} from favorites"
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"DB Error while removing favorite for user {current_user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error"
        )

    return {"message": "Movie removed from favorites"}


@router.post(
    "/{movie_uuid}/rating/",
    response_model=MessageResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Rate a movie",
)
async def rate_movie(
    movie_uuid: UUID,
    rating_data: RatingCreateSchema,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Sets or updates a numerical rating (1-10) for a movie.

    **Side effects:** Automatically triggers a background recalculation of the movie's
    global average rating and total review count.
    """
    logger.debug(
        f"User {current_user.id} rating movie {movie_uuid} with score {rating_data.score}"
    )

    current_user_id = current_user.id
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = select(MovieRatingModel).where(
        MovieRatingModel.user_id == current_user_id,
        MovieRatingModel.movie_id == movie_id,
    )
    rating = (await db.execute(stmt)).scalar_one_or_none()

    if rating:
        old_score = rating.score
        rating.score = rating_data.score
        message = "Rating updated"
        logger.info(
            f"User {current_user_id} changing score for movie {movie_id} from {old_score} to {rating_data.score}"
        )
    else:
        rating = MovieRatingModel(
            user_id=current_user_id, movie_id=movie_id, score=rating_data.score
        )
        db.add(rating)
        message = "Movie rated"
        logger.info(
            f"User {current_user_id} set new rating for movie {movie_id}: {rating_data.score}"
        )

    try:
        await db.flush()

        logger.debug(f"Triggering stats update for movie_id: {movie_id}")
        await update_movie_rating_stats(movie_id, db)

        await db.commit()
        logger.info(
            f"Successfully committed rating and stats update for movie {movie_id}"
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Rating operation failed for user {current_user_id}, movie {movie_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error"
        )

    return {"message": message}


@router.delete(
    "/{movie_uuid}/rating/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove movie rating",
)
async def remove_movie_rating(
    movie_uuid: UUID,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deletes the user's rating for a movie and triggers a global stats recalculation."""
    logger.debug(
        f"Initiating rating removal for user {current_user.id} on movie {movie_uuid}"
    )

    current_user_id = current_user.id
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = (
        delete(MovieRatingModel)
        .where(
            MovieRatingModel.user_id == current_user_id,
            MovieRatingModel.movie_id == movie_id,
        )
        .returning(MovieRatingModel.user_id)
    )

    result = await db.execute(stmt)
    deleted_id = result.scalar_one_or_none()

    if deleted_id is None:
        logger.warning(
            f"User {current_user_id} attempted to delete non-existent rating for movie {movie_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rating not found for this movie.",
        )

    try:
        logger.debug(f"Updating stats for movie {movie_id} after rating deletion")
        await update_movie_rating_stats(movie_id, db)
        await db.commit()
        logger.info(
            f"Rating removed and stats recalculated for movie {movie_id} by user {current_user_id}"
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Failed to complete rating removal for user {current_user_id} (movie {movie_id}): {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error"
        )

    return None


@router.post(
    "/{movie_uuid}/vote/",
    response_model=MessageResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Like or dislike a movie",
)
async def vote_movie(
    movie_uuid: UUID,
    vote_data: VoteCreateSchema,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Casts a binary vote (like/dislike) for a movie.

    Updating a vote changes the type (like to dislike), while casting a new vote
    increments the movie's global popularity counter.
    """
    logger.debug(
        f"User {current_user.id} is voting for movie {movie_uuid} (is_like={vote_data.is_like})"
    )

    current_user_id = current_user.id
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = select(MovieVoteModel).where(
        MovieVoteModel.user_id == current_user_id, MovieVoteModel.movie_id == movie_id
    )
    existing_vote = (await db.execute(stmt)).scalar_one_or_none()

    try:
        if not existing_vote:
            logger.info(
                f"User {current_user_id} cast a new vote for movie {movie_id}. Total votes counter incremented."
            )
            db.add(
                MovieVoteModel(
                    user_id=current_user_id,
                    movie_id=movie_id,
                    is_like=vote_data.is_like,
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
            logger.info(
                f"Updating existing vote for movie {movie_id} by user {current_user_id} to {vote_data.is_like}"
            )
            existing_vote.is_like = vote_data.is_like
            message = "Vote updated"

        await db.commit()
        logger.info(
            f"Vote successfully committed for user {current_user_id}, movie {movie_id}"
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Database error while voting on movie {movie_id} by user {current_user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing your vote.",
        )

    return {"message": message}
