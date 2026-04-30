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
    sort_by: str = Query("year", pattern="^(year|price|imdb|popularity)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
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
    movies = list(result.scalars().all())

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
        raise HTTPException(status_code=404, detail="Not in favorites")

    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error")

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
        rating = MovieRatingModel(
            user_id=current_user.id, movie_id=movie_id, score=rating_data.score
        )
        db.add(rating)
        message = "Movie rated"

    try:
        await db.flush()

        await update_movie_rating_stats(movie_id, db)

        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
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
    """
    Delete a user's rating for a specific movie.
    """
    movie_id = await get_movie_id_by_uuid(movie_uuid, db)

    stmt = (
        delete(MovieRatingModel)
        .where(
            MovieRatingModel.user_id == current_user.id,
            MovieRatingModel.movie_id == movie_id,
        )
        .returning(MovieRatingModel.id)
    )

    result = await db.execute(stmt)
    deleted_id = result.scalar_one_or_none()

    if deleted_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rating not found for this movie.",
        )

    try:
        await update_movie_rating_stats(movie_id, db)
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
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

    parent_comment = None
    if comment_data.parent_id:
        parent_comment = await db.get(MovieCommentModel, comment_data.parent_id)

        if not parent_comment or parent_comment.movie_id != movie_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent comment not found or belongs to another movie",
            )

    new_comment = MovieCommentModel(
        user_id=current_user.id,
        movie_id=movie_id,
        text=comment_data.text,
        parent_id=comment_data.parent_id,
    )
    db.add(new_comment)

    if parent_comment and parent_comment.user_id != current_user.id:
        notification = NotificationModel(
            user_id=parent_comment.user_id,
            notification_type=NotificationType.COMMENT_REPLY,
            content=f"User {current_user.email} replied to your comment",
            link_to_id=str(movie_uuid),
        )
        db.add(notification)

    await db.commit()
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
    """
    Update comment text.
    - **Ownership**: Only the author can edit the comment.
    """
    stmt = (
        select(MovieCommentModel)
        .options(joinedload(MovieCommentModel.user))
        .where(MovieCommentModel.id == comment_id)
    )
    result = await db.execute(stmt)
    comment = result.scalars().first()

    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found."
        )

    if comment.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only edit your own comments.",
        )

    comment.text = comment_data.text

    try:
        await db.commit()
        await db.refresh(comment)
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error."
        )

    return comment


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
        .returning(NotificationModel.id)
    )

    result = await db.execute(stmt)
    updated_id = result.scalar_one_or_none()

    if updated_id is None:
        raise HTTPException(status_code=404, detail="Notification not found")

    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error")

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
        .options(
            joinedload(MovieCommentModel.user), selectinload(MovieCommentModel.likes)
        )
        .where(MovieCommentModel.movie_id == movie_id)
        .order_by(MovieCommentModel.created_at.desc())
    )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count = await db.scalar(count_stmt) or 0

    offset = (page - 1) * size
    result = await db.execute(stmt.limit(size).offset(offset))
    comments = list(result.scalars().all())

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
    stmt = (
        select(MovieCommentModel)
        .options(joinedload(MovieCommentModel.movie))
        .where(MovieCommentModel.id == comment_id)
    )
    comment = (await db.execute(stmt)).scalar_one_or_none()

    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    like_stmt = select(CommentLikeModel).where(
        CommentLikeModel.user_id == current_user.id,
        CommentLikeModel.comment_id == comment_id,
    )
    existing_like = await db.scalar(like_stmt)

    if existing_like:
        await db.delete(existing_like)
        await db.commit()
        return {"message": "Like removed"}

    db.add(CommentLikeModel(user_id=current_user.id, comment_id=comment_id))

    if comment.user_id != current_user.id:
        notification = NotificationModel(
            user_id=comment.user_id,
            notification_type=NotificationType.COMMENT_LIKE,
            content=f"User {current_user.email} liked your comment",
            link_to_id=str(comment.movie.uuid),
        )
        db.add(notification)

    await db.commit()
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
    """
    Create a unique genre. Raises 400 if the name already exists.
    """
    new_genre = GenreModel(name=genre_data.name)
    db.add(new_genre)
    try:
        await db.commit()
        await db.refresh(new_genre)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Genre with this name already exists.",
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
    """
    Update genre name. Validates uniqueness and existence.
    """
    genre = await db.get(GenreModel, genre_id)
    if not genre:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Genre not found."
        )

    if genre_data.name:
        genre.name = genre_data.name

    try:
        await db.commit()
        await db.refresh(genre)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Genre with this name already exists.",
        )
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
    """
    Delete a genre. Movie associations are removed automatically via CASCADE.
    """
    genre = await db.get(GenreModel, genre_id)
    if not genre:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Genre not found."
        )

    try:
        await db.delete(genre)
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
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
    """
    Create a new movie record with associations.
    - **Validation**: Checks if certification, genres, stars, and directors exist.
    - **Constraints**: Ensures name/year/time uniqueness.
    - **Security**: Restricted to staff (Admin/Moderator).
    """
    cert = await db.get(CertificationModel, movie_data.certification_id)
    if not cert:
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
        raise HTTPException(
            status_code=400, detail="One or more genre IDs are invalid."
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
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Movie with this name, year and duration already exists.",
        )
    except SQLAlchemyError:
        await db.rollback()
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
    """
    Update an existing movie.
    - **Partial Update**: Only fields provided in the request body will be changed.
    - **Relationships**: If genre_ids/star_ids/director_ids are provided, the entire relationship is replaced.
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
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Some IDs in {field_name} are invalid.",
                )
            setattr(movie, attr_name, list(found_objs))

    if movie_data.certification_id is not None:
        cert = await db.get(CertificationModel, movie_data.certification_id)
        if not cert:
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
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Update failed: Unique constraint violation (name/year/time).",
        )
    except SQLAlchemyError:
        await db.rollback()
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
    """
    Delete a movie by its UUID.
    - **Cascade**: Automatically deletes related favorites, ratings, and comments due to model configuration.
    - **Security**: Only Admins and Moderators can perform this.
    """
    stmt = select(MovieModel).where(MovieModel.uuid == movie_uuid)
    result = await db.execute(stmt)
    movie = result.scalars().first()

    if not movie:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found."
        )

    try:
        await db.delete(movie)
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
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
    """
    Delete a comment.
    - **Users**: Can delete only their own.
    - **Staff**: Can delete any comment (logic for notification can be added here).
    """
    stmt = select(MovieCommentModel).where(MovieCommentModel.id == comment_id)
    result = await db.execute(stmt)
    comment = result.scalars().first()

    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found."
        )

    is_owner = comment.user_id == current_user.id
    is_staff = current_user.group.name in [UserGroupEnum.ADMIN, UserGroupEnum.MODERATOR]

    if not (is_owner or is_staff):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this comment.",
        )

    if is_staff and not is_owner:
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
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error")

    return None


@router.get(
    "/stars/",
    response_model=list[StarReadSchema],
    status_code=status.HTTP_200_OK,
    summary="[Admin] Get All Stars",
    description="Get a simple list of stars for management purposes.",
)
async def get_stars(
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns all stars ordered by name.
    """
    stmt = select(StarModel).order_by(StarModel.name)
    result = await db.execute(stmt)
    return result.scalars().all()


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
    """
    Add a new star. Name must be unique.
    """
    new_star = StarModel(name=star_data.name)
    db.add(new_star)
    try:
        await db.commit()
        await db.refresh(new_star)
    except IntegrityError:
        await db.rollback()
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
    """
    Rename a star. Checks for name collisions.
    """
    star = await db.get(StarModel, star_id)
    if not star:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Star not found."
        )

    if star_data.name:
        star.name = star_data.name

    try:
        await db.commit()
        await db.refresh(star)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Another star already has this name.",
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
    """
    Permanently remove a star. Movie links will be severed (CASCADE).
    """
    star = await db.get(StarModel, star_id)
    if not star:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Star not found."
        )

    try:
        await db.delete(star)
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error during deletion.",
        )
    return None


@router.get(
    "/directors/",
    response_model=list[DirectorReadSchema],
    status_code=status.HTTP_200_OK,
    summary="[Admin] Get All Directors",
    description="Get a list of all directors for database management.",
)
async def get_directors(
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns a full list of directors ordered alphabetically.
    """
    stmt = select(DirectorModel).order_by(DirectorModel.name)
    result = await db.execute(stmt)
    return result.scalars().all()


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
    """
    Add a new director. Name must be unique.
    """
    new_director = DirectorModel(name=director_data.name)
    db.add(new_director)
    try:
        await db.commit()
        await db.refresh(new_director)
    except IntegrityError:
        await db.rollback()
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
    """
    Update director's name.
    """
    director = await db.get(DirectorModel, director_id)
    if not director:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Director not found."
        )

    if director_data.name:
        director.name = director_data.name

    try:
        await db.commit()
        await db.refresh(director)
    except IntegrityError:
        await db.rollback()
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
    """
    Delete a director from the catalog.
    """
    director = await db.get(DirectorModel, director_id)
    if not director:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Director not found."
        )

    try:
        await db.delete(director)
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete director.",
        )
    return None


@router.get(
    "/certifications/",
    response_model=list[CertificationReadSchema],
    status_code=status.HTTP_200_OK,
    summary="[Admin] Get All Certifications",
)
async def list_certifications(
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns a list of all movie certifications (age ratings).
    """
    stmt = select(CertificationModel).order_by(CertificationModel.name)
    result = await db.execute(stmt)
    return result.scalars().all()


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
    """
    Add a new age rating certification (e.g., '18+').
    """
    new_cert = CertificationModel(name=cert_data.name)
    db.add(new_cert)
    try:
        await db.commit()
        await db.refresh(new_cert)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Certification with this name already exists.",
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
    """
    Update the name of an existing certification.
    """
    cert = await db.get(CertificationModel, cert_id)
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Certification not found."
        )

    if cert_data.name:
        cert.name = cert_data.name

    try:
        await db.commit()
        await db.refresh(cert)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conflict: This certification name is already taken.",
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
    """
    Remove a certification.
    Warning: This may fail if movies are still linked to this certification.
    """
    cert = await db.get(CertificationModel, cert_id)
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Certification not found."
        )

    try:
        await db.delete(cert)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete: this certification is currently assigned to movies.",
        )
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred.",
        )
    return None
