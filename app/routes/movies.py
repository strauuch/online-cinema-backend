from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy import select, func, or_, delete, and_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from core.dependencies import get_current_user
from database import get_db
from database.models.accounts import UserModel
from database.models.enums import NotificationType
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
)
from schemas.pagination import Page

router = APIRouter(prefix="/movies", tags=["Movies"])


async def get_movie_id_by_uuid(movie_uuid: UUID, db: AsyncSession) -> int:
    stmt = select(MovieModel.id).where(MovieModel.uuid == movie_uuid)
    result = await db.execute(stmt)
    movie_id = result.scalar_one_or_none()
    if not movie_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found"
        )
    return movie_id


# =============================================================================
# USER ROUTES
# =============================================================================


@router.get(
    "/genres/",
    response_model=List[GenreWithCountSchema],
    status_code=status.HTTP_200_OK,
    summary="Get All Genres",
    description=(
        "Retrieve a complete list of genres available in the catalog. "
        "Each genre includes a `movie_count` showing how many movies are associated with it. "
    ),
)
async def list_genres(
    db: AsyncSession = Depends(get_db),
):
    """
    Returns all genres with the count of movies in each.
    - **Logic**: Performs a LEFT OUTER JOIN on the movies_genres link table.
    - **Grouping**: Groups by Genre ID to aggregate the count.
    - **Sorting**: Most populated genres appear first.
    """
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
    result = await db.execute(stmt)
    return result.all()


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
    sort_by: str = Query("year", regex="^(year|price|imdb|popularity)$"),
    order: str = Query("desc", regex="^(asc|desc)$"),
    only_favorites: bool = Query(False),
    current_user: Optional[UserModel] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page[MovieShortResponseSchema]:
    """
    Main catalog endpoint:
    - **Pagination**: Calculates total items and pages.
    - **Search**: Multi-column search with ILIKE.
    - **Filtering**: Year, IMDb, and Genre support.
    - **Sorting**: Maps 'popularity' to 'votes' internally.
    """

    stmt = select(MovieModel).options(selectinload(MovieModel.genres))

    if only_favorites:
        if not current_user:
            raise HTTPException(status_code=401, detail="Log in to see favorites")
        stmt = stmt.join(MovieFavoriteModel).where(
            MovieFavoriteModel.user_id == current_user.id
        )

    if q:
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
        stmt = stmt.where(MovieModel.year == year)
    if min_imdb:
        stmt = stmt.where(MovieModel.imdb >= min_imdb)
    if genre_id:
        stmt = (
            stmt.join(movie_genres)
            .where(movie_genres.c.genre_id == genre_id)
            .distinct()
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count = await db.scalar(count_stmt) or 0

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
    movies = result.scalars().all()

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
    Fetches a single movie by its public UUID.
    - **Joined Loads**: Optimized to fetch genres, stars, directors, and certification in one go.
    """
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with provided UUID not found",
        )

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
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = select(MovieFavoriteModel).where(
        MovieFavoriteModel.user_id == current_user.id,
        MovieFavoriteModel.movie_id == movie_id,
    )
    existing = await db.scalar(stmt)
    if existing:
        return {"message": "Movie is already in favorites"}

    new_favorite = MovieFavoriteModel(user_id=current_user.id, movie_id=movie_id)
    db.add(new_favorite)
    await db.commit()
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
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = delete(MovieFavoriteModel).where(
        MovieFavoriteModel.user_id == current_user.id,
        MovieFavoriteModel.movie_id == movie_id,
    )
    result = await db.execute(stmt)
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Movie was not in your favorites")

    return {"message": "Movie removed from favorites"}


@router.post(
    "/{movie_uuid}/rate/",
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
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = select(MovieRatingModel).where(
        MovieRatingModel.user_id == current_user.id,
        MovieRatingModel.movie_id == movie_id,
    )
    rating = (await db.execute(stmt)).scalar_one_or_none()

    if rating:
        rating.score = rating_data.score
        message = "Rating updated"
    else:
        db.add(
            MovieRatingModel(
                user_id=current_user.id, movie_id=movie_id, score=rating_data.score
            )
        )
        message = "Movie rated"

    await db.commit()
    return {"message": message}


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
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = select(MovieVoteModel).where(
        MovieVoteModel.user_id == current_user.id, MovieVoteModel.movie_id == movie_id
    )
    existing_vote = (await db.execute(stmt)).scalar_one_or_none()

    if not existing_vote:
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
        existing_vote.is_like = vote_data.is_like
        message = "Vote updated"

    await db.commit()
    return {"message": message}


@router.post("/{movie_uuid}/comments/", status_code=status.HTTP_201_CREATED)
async def add_comment(
    movie_uuid: UUID,
    comment_data: CommentCreateSchema,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    new_comment = MovieCommentModel(
        user_id=current_user.id,
        movie_id=movie_id,
        text=comment_data.text,
        parent_id=comment_data.parent_id,
    )
    db.add(new_comment)
    await db.flush()

    if comment_data.parent_id:
        parent_comment = await db.get(MovieCommentModel, comment_data.parent_id)
        if (
            parent_comment
            and parent_comment.user_id != current_user.id
            and parent_comment.movie_id == movie_id
        ):
            notification = NotificationModel(
                user_id=parent_comment.user_id,
                notification_type=NotificationType.COMMENT_REPLY,
                content=f"User {current_user.email} replied to your comment",
                link_to_id=str(movie_uuid),
            )
            db.add(notification)

    await db.commit()
    return {"message": "Comment added successfully"}


@router.get("/notifications/", response_model=List[NotificationReadSchema])
async def get_my_notifications(
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(NotificationModel)
        .where(NotificationModel.user_id == current_user.id)
        .order_by(NotificationModel.created_at.desc())
    )

    result = await db.execute(stmt)
    return result.scalars().all()


@router.patch("/notifications/{notif_id}/read/")
async def mark_as_read(
    notif_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        update(NotificationModel)
        .where(
            NotificationModel.id == notif_id,
            NotificationModel.user_id == current_user.id,
        )
        .values(is_read=True)
    )

    result = await db.execute(stmt)
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Notification not found")

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
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = (
        select(MovieCommentModel)
        .options(joinedload(MovieCommentModel.user))
        .where(MovieCommentModel.movie_id == movie_id)
        .order_by(MovieCommentModel.created_at.desc())
    )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count = await db.scalar(count_stmt) or 0

    offset = (page - 1) * size
    result = await db.execute(stmt.limit(size).offset(offset))
    comments = result.scalars().all()

    return Page(
        items=comments,
        total=total_count,
        page=page,
        size=size,
        total_pages=(total_count + size - 1) // size if total_count > 0 else 0,
    )
