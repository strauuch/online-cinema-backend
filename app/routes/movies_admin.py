import logging

from uuid import UUID
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from core.dependencies import (
    get_current_staff_user,
)
from database import get_db
from database.models.accounts import UserModel
from database.models.movies import (
    MovieModel,
    GenreModel,
    StarModel,
    DirectorModel,
    CertificationModel,
)
from schemas.movies import (
    MovieDetailResponseSchema,
    MovieCreateSchema,
    MovieUpdateSchema,
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

router = APIRouter(dependencies=[Depends(get_current_staff_user)])

logger = logging.getLogger(__name__)


@router.post(
    "/genres/",
    response_model=GenreReadSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create genre [Moderator | Admin]",
)
async def create_genre(
    genre_data: GenreCreateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Creates a new unique genre in the database. Restricted to staff users."""
    logger.info(
        f"Staff user {current_user.id} is creating a new genre: '{genre_data.name}'"
    )

    current_user_id = current_user.id

    new_genre = GenreModel(name=genre_data.name)
    db.add(new_genre)

    try:
        await db.commit()
        await db.refresh(new_genre)
        logger.info(
            f"Genre '{new_genre.name}' (ID: {new_genre.id}) successfully created by user {current_user_id}"
        )
    except IntegrityError as e:
        await db.rollback()
        logger.warning(
            f"Genre creation failed: Name '{genre_data.name}' already exists. (User: {current_user_id})"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Genre with this name already exists.",
        )
    except Exception as e:
        await db.rollback()
        logger.error(
            f"Unexpected error during genre creation by user {current_user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred.",
        )

    return new_genre


@router.patch(
    "/genres/{genre_id}/",
    response_model=GenreReadSchema,
    status_code=status.HTTP_200_OK,
    summary="Update genre [Moderator | Admin]",
)
async def update_genre(
    genre_id: int,
    genre_data: GenreUpdateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Updates the name of an existing genre, ensuring the new name remains unique."""
    logger.debug(
        f"Staff user {current_user.id} initiated update for genre_id: {genre_id}"
    )

    current_user_id = current_user.id

    genre = await db.get(GenreModel, genre_id)
    if not genre:
        logger.warning(
            f"Genre update failed: ID {genre_id} not found (User: {current_user_id})"
        )
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
            f"Genre {genre_id} updated by staff {current_user_id}: "
            f"'{old_name}' -> '{new_name}'"
        )
    except IntegrityError:
        await db.rollback()
        logger.warning(
            f"Conflict: Staff {current_user_id} tried to rename genre {genre_id} "
            f"to existing name '{new_name}'"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Genre with this name already exists.",
        )
    except Exception as e:
        await db.rollback()
        logger.error(
            f"Error updating genre {genre_id} by user {current_user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error."
        )

    return genre


@router.delete(
    "/genres/{genre_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete genre [Moderator | Admin]",
)
async def delete_genre(
    genre_id: int,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently deletes a genre by ID. Movie-genre associations are cleaned via cascade."""
    logger.info(
        f"Staff user {current_user.id} is attempting to delete genre ID: {genre_id}"
    )

    current_user_id = current_user.id

    genre = await db.get(GenreModel, genre_id)
    if not genre:
        logger.warning(
            f"Delete failed: Genre ID {genre_id} not found. (User: {current_user_id})"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Genre not found."
        )

    try:
        logger.debug(f"Deleting genre object: {genre.name} (ID: {genre_id})")
        await db.delete(genre)
        await db.commit()
        logger.info(
            f"Genre ID {genre_id} successfully deleted by staff user {current_user_id}"
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Database error during genre {genre_id} deletion by user {current_user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete genre.",
        )
    return None


@router.get(
    "/stars/",
    response_model=Page[StarReadSchema],
    status_code=status.HTTP_200_OK,
    summary="Get all actors (Paginated) [Moderator | Admin]",
)
async def get_stars(
    page: int = Query(1, ge=1, description="Current page number"),
    size: int = Query(10, ge=1, le=100, description="Items per page"),
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns a paginated list of all actors (stars) ordered alphabetically by name."""
    logger.info(
        f"Staff user {current_user.id} requested stars list. Page: {page}, Size: {size}"
    )

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

        logger.info(
            f"Returning {len(stars)} stars (Total: {total_count}) to staff {current_user.id}"
        )
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
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching stars.",
        )


@router.post(
    "/stars/",
    response_model=StarReadSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create actor [Moderator | Admin]",
)
async def create_star(
    star_data: StarCreateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Adds a new actor to the database. Ensures the name is unique."""
    logger.info(f"Staff user {current_user.id} creating star: '{star_data.name}'")

    current_user_id = current_user.id

    new_star = StarModel(name=star_data.name)
    db.add(new_star)

    try:
        await db.commit()
        await db.refresh(new_star)
        logger.info(
            f"Star created: '{new_star.name}' (ID: {new_star.id}) by user {current_user_id}"
        )
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
    summary="Update actor [Moderator | Admin]",
)
async def update_star(
    star_id: int,
    star_data: StarUpdateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Updates an actor's name after validating it doesn't conflict with existing records."""
    logger.debug(f"User {current_user.id} updating star {star_id}")

    current_user_id = current_user.id

    star = await db.get(StarModel, star_id)
    if not star:
        logger.warning(f"Star {star_id} not found for update by user {current_user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Star not found."
        )

    old_name = star.name
    if star_data.name:
        star.name = star_data.name

    try:
        await db.commit()
        await db.refresh(star)
        logger.info(
            f"Star {star_id} updated by {current_user_id}: '{old_name}' -> '{star.name}'"
        )
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
    summary="Delete actor [Moderator | Admin]",
)
async def delete_star(
    star_id: int,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently deletes an actor record and severs all movie associations."""
    logger.info(
        f"Staff user {current_user.id} initiated deletion for star ID: {star_id}"
    )

    current_user_id = current_user.id

    star = await db.get(StarModel, star_id)
    if not star:
        logger.warning(
            f"Star ID {star_id} not found for deletion by user {current_user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Star not found."
        )

    try:
        star_name = star.name
        logger.debug(f"Deleting star object: {star_name}")

        await db.delete(star)
        await db.commit()

        logger.info(
            f"Star '{star_name}' (ID: {star_id}) deleted by user {current_user_id}"
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Database error while deleting star {star_id}: {str(e)}", exc_info=True
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
    summary="Get all directors (Paginated) [Moderator | Admin]",
)
async def get_directors(
    page: int = Query(1, ge=1, description="Current page number"),
    size: int = Query(10, ge=1, le=100, description="Items per page"),
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieves a paginated list of directors for administrative management."""
    logger.info(
        f"Staff user {current_user.id} fetching directors. Page: {page}, Size: {size}"
    )

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
            detail="Database error occurred while fetching directors.",
        )


@router.post(
    "/directors/",
    response_model=DirectorReadSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create director [Moderator | Admin]",
)
async def create_director(
    director_data: DirectorCreateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Creates a new director record. Raises a conflict error if the name already exists."""
    logger.info(
        f"Staff user {current_user.id} initiated director creation: '{director_data.name}'"
    )

    current_user_id = current_user.id

    new_director = DirectorModel(name=director_data.name)
    db.add(new_director)

    try:
        await db.commit()
        await db.refresh(new_director)
        logger.info(
            f"Director '{new_director.name}' (ID: {new_director.id}) created by user {current_user_id}"
        )
    except IntegrityError:
        await db.rollback()
        logger.warning(
            f"Conflict: Director '{director_data.name}' already exists in the database"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This director already exists in the database.",
        )
    return new_director


@router.patch(
    "/directors/{director_id}/",
    response_model=DirectorReadSchema,
    status_code=status.HTTP_200_OK,
    summary="Update director [Moderator | Admin]",
)
async def update_director(
    director_id: int,
    director_data: DirectorUpdateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Renames an existing director and performs a uniqueness check on the new name."""
    logger.debug(f"User {current_user.id} requested update for director {director_id}")

    current_user_id = current_user.id

    director = await db.get(DirectorModel, director_id)
    if not director:
        logger.warning(
            f"Update failed: Director {director_id} not found (User: {current_user_id})"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Director not found."
        )

    old_name = director.name
    if director_data.name:
        director.name = director_data.name

    try:
        await db.commit()
        await db.refresh(director)
        logger.info(
            f"Director {director_id} updated by staff {current_user_id}: '{old_name}' -> '{director.name}'"
        )
    except IntegrityError:
        await db.rollback()
        logger.warning(
            f"Conflict: Name '{director_data.name}' already exists (Update aborted for ID {director_id}) by user {current_user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conflict: Another director with this name already exists.",
        )
    return director


@router.delete(
    "/directors/{director_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete director [Moderator | Admin]",
)
async def delete_director(
    director_id: int,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Removes a director from the catalog by their internal ID."""
    logger.info(
        f"Staff user {current_user.id} initiated deletion for director ID: {director_id}"
    )

    current_user_id = current_user.id

    director = await db.get(DirectorModel, director_id)
    if not director:
        logger.warning(
            f"Director ID {director_id} not found for deletion by user {current_user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Director not found."
        )

    try:
        director_name = director.name
        logger.debug(f"Deleting director object: {director_name}")

        await db.delete(director)
        await db.commit()

        logger.info(
            f"Director '{director_name}' (ID: {director_id}) deleted by user {current_user_id}"
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Database error during director {director_id} deletion: {str(e)}",
            exc_info=True,
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
    summary="Get all certifications (Paginated) [Moderator | Admin]",
)
async def list_certifications(
    page: int = Query(1, ge=1, description="Current page number"),
    size: int = Query(10, ge=1, le=100, description="Items per page"),
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
) -> Page[CertificationReadSchema]:
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
        logger.error(
            f"Error fetching certifications for user {current_user.id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching certifications.",
        )


@router.post(
    "/certifications/",
    response_model=CertificationReadSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create certification [Moderator | Admin]",
)
async def create_certification(
    cert_data: CertificationCreateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Registers a new age certification (e.g., 'PG-13', '18+') in the system."""
    logger.info(
        f"Staff user {current_user.id} is creating a new certification: '{cert_data.name}'"
    )

    current_user_id = current_user.id

    new_cert = CertificationModel(name=cert_data.name)
    db.add(new_cert)
    try:
        await db.commit()
        await db.refresh(new_cert)
        logger.info(
            f"Certification '{new_cert.name}' (ID: {new_cert.id}) created by user {current_user_id}"
        )
    except IntegrityError:
        await db.rollback()
        logger.warning(
            f"Conflict: Certification '{cert_data.name}' already exists (User: {current_user_id})"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Certification with this name already exists.",
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Database error during certification creation: {str(e)}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal database error occurred.",
        )
    return new_cert


@router.patch(
    "/certifications/{cert_id}/",
    response_model=CertificationReadSchema,
    status_code=status.HTTP_200_OK,
    summary="Update certification [Moderator | Admin]",
)
async def update_certification(
    cert_id: int,
    cert_data: CertificationUpdateSchema,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Modifies the name of an existing age rating certification."""
    logger.debug(f"User {current_user.id} requested update for certification {cert_id}")

    current_user_id = current_user.id

    cert = await db.get(CertificationModel, cert_id)
    if not cert:
        logger.warning(
            f"Certification {cert_id} not found for update by user {current_user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Certification not found."
        )

    old_name = cert.name
    if cert_data.name:
        cert.name = cert_data.name

    try:
        await db.commit()
        await db.refresh(cert)
        logger.info(
            f"Certification {cert_id} updated by {current_user_id}: '{old_name}' -> '{cert.name}'"
        )
    except IntegrityError:
        await db.rollback()
        logger.warning(
            f"Update conflict: Certification name '{cert_data.name}' is already taken"
        )
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
    summary="Delete certification [Moderator | Admin]",
)
async def delete_certification(
    cert_id: int,
    current_user: UserModel = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Deletes a certification record.

    **Restriction:**
    * The deletion will fail with a **400 Bad Request** if any movies are currently assigned to this certification.
    * You must reassign or delete the associated movies before removing the certification.
    """
    logger.info(
        f"Staff user {current_user.id} is attempting to delete certification ID: {cert_id}"
    )

    current_user_id = current_user.id

    cert = await db.get(CertificationModel, cert_id)
    if not cert:
        logger.warning(
            f"Certification {cert_id} not found for deletion by user {current_user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Certification not found."
        )

    cert_name = cert.name

    try:
        await db.delete(cert)
        await db.commit()
        logger.info(
            f"Certification '{cert_name}' (ID: {cert_id}) successfully deleted by staff {current_user_id}"
        )
    except IntegrityError:
        await db.rollback()
        logger.warning(
            f"Delete aborted: Certification '{cert_name}' (ID: {cert_id}) is linked to existing movies. "
            f"Action by user {current_user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete: this certification is currently assigned to movies.",
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Critical database error during certification {cert_id} deletion: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred.",
        )
    return None


@router.post(
    "/",
    response_model=MovieDetailResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create movie [Moderator | Admin]",
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
    Creates a new movie record and validates all related entity IDs.

    **Validation Logic:**
    * **IDs Check**: Verifies that `certification_id`, `genre_ids`, `star_ids`, and `director_ids` exist in the database.
    * **Unique Constraint**: Prevents creation of a movie with the same name, year, and duration.
    * **Relationships**: Automatically links the movie to provided genres, actors, and directors.
    """
    logger.info(f"Staff user {current_user.id} is creating movie: '{movie_data.name}'")

    current_user_id = current_user.id

    cert = await db.get(CertificationModel, movie_data.certification_id)
    if not cert:
        logger.warning(
            f"Movie creation failed: Certification {movie_data.certification_id} not found"
        )
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
        logger.warning(
            f"Creation failed: User {current_user_id} provided invalid genre IDs"
        )
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
        logger.info(
            f"Movie '{new_movie.name}' (ID: {new_movie.id}) successfully created by user {current_user_id}"
        )
    except IntegrityError:
        await db.rollback()
        logger.warning(
            f"Conflict: Movie '{movie_data.name}' ({movie_data.year}) already exists in DB"
        )
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
    summary="Update movie details [Moderator | Admin]",
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
    Partially updates movie details and manages relationships.

    **Behavior for lists (genres, stars, directors):**
    * If a list of IDs is provided, it **completely replaces** the existing associations.
    * To clear a list, send an empty array `[]`.
    * If the field is omitted, the current associations remain unchanged.
    """
    logger.info(
        f"Staff user {current_user.id} initiated update for movie UUID: {movie_uuid}"
    )

    current_user_id = current_user.id

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
        logger.warning(
            f"Update failed: Movie with UUID {movie_uuid} not found (User: {current_user_id})"
        )
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
                logger.warning(
                    f"User {current_user_id} provided invalid IDs in {field_name}"
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Some IDs in {field_name} are invalid.",
                )
            setattr(movie, attr_name, list(found_objs))

    if movie_data.certification_id is not None:
        cert = await db.get(CertificationModel, movie_data.certification_id)
        if not cert:
            logger.warning(
                f"Invalid certification_id {movie_data.certification_id} provided by user {current_user_id}"
            )
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
        logger.info(
            f"Movie {movie_uuid} ('{movie.name}') successfully updated by staff {current_user_id}"
        )
    except IntegrityError:
        await db.rollback()
        logger.warning(
            f"IntegrityError: Update of movie {movie_uuid} violates unique constraints"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Update failed: Unique constraint violation (name/year/time).",
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Critical DB error during movie {movie_uuid} update: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error during update.",
        )

    return movie


@router.delete(
    "/{movie_uuid}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete movie [Moderator | Admin]",
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
    logger.info(
        f"Staff user {current_user.id} is attempting to delete movie UUID: {movie_uuid}"
    )

    current_user_id = current_user.id

    stmt = select(MovieModel).where(MovieModel.uuid == movie_uuid)
    result = await db.execute(stmt)
    movie = result.scalars().first()

    if not movie:
        logger.warning(
            f"Delete failed: Movie {movie_uuid} not found (User: {current_user_id})"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found."
        )

    try:
        movie_name = movie.name
        logger.debug(f"Processing deletion of movie '{movie_name}'")

        await db.delete(movie)
        await db.commit()

        logger.info(
            f"Movie '{movie_name}' (UUID: {movie_uuid}) successfully deleted by staff {current_user_id}"
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Database error during deletion of movie {movie_uuid} by user {current_user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete the movie from the database.",
        )

    return None
