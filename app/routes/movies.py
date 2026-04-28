from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from database import get_db
from database.models.movies import (
    MovieModel,
    GenreModel,
    StarModel,
    DirectorModel,
    movie_genres,
)
from schemas.movies import (
    MovieShortResponseSchema,
    MovieDetailResponseSchema,
    GenreWithCountSchema,
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
        if not q:
            stmt = stmt.join(MovieModel.genres)
        stmt = stmt.where(GenreModel.id == genre_id)

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

    total_pages = (total_count + size - 1) // size

    return Page(
        items=movies, total=total_count, page=page, size=size, total_pages=total_pages
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
            joinedload(MovieModel.genres),
            joinedload(MovieModel.stars),
            joinedload(MovieModel.directors),
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
