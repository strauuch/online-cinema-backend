import uuid
import pytest
from datetime import datetime
from sqlalchemy import select, insert
from sqlalchemy.exc import SQLAlchemyError

from app.database.models.movies import (
    GenreModel,
    StarModel,
    DirectorModel,
    CertificationModel,
)

# ====================== POST /genres/ ======================


@pytest.mark.asyncio
async def test_create_genre_success(admin_client, db_session):
    payload = {"name": "Horror"}

    response = await admin_client.post("/api/v1/admin/movies/genres/", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Horror"

    genre = await db_session.scalar(
        select(GenreModel).where(GenreModel.name == "Horror")
    )
    assert genre is not None


@pytest.mark.asyncio
async def test_create_genre_validation_error(admin_client):
    response = await admin_client.post(
        "/api/v1/admin/movies/genres/", json={"name": ""}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_genre_unauthorized(client):
    response = await client.post("/api/v1/admin/movies/genres/", json={"name": "Test"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_genre_forbidden_regular_user(authenticated_client):
    response = await authenticated_client.post(
        "/api/v1/admin/movies/genres/", json={"name": "Forbidden"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_genre_internal_server_error(
    admin_client, monkeypatch, db_session
):
    async def fake_commit(*args, **kwargs):
        raise Exception("Simulated unexpected error")

    monkeypatch.setattr(db_session, "commit", fake_commit)

    response = await admin_client.post(
        "/api/v1/admin/movies/genres/", json={"name": "CrashTest"}
    )

    assert response.status_code == 500
    assert "internal error" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_genre_duplicate(admin_client, db_session):
    db_session.add(GenreModel(name="DuplicateGenre"))
    await db_session.commit()

    response = await admin_client.post(
        "/api/v1/admin/movies/genres/", json={"name": "DuplicateGenre"}
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"].lower()


# ====================== PATCH /genres/{genre_id}/ ======================


@pytest.mark.asyncio
async def test_update_genre_success(admin_client, movie_factory, db_session):
    genre = await movie_factory.create_genre("OldGenre")

    response = await admin_client.patch(
        f"/api/v1/admin/movies/genres/{genre.id}/", json={"name": "NewGenre"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "NewGenre"

    await db_session.refresh(genre)
    assert genre.name == "NewGenre"


@pytest.mark.asyncio
async def test_update_genre_not_found(admin_client):
    response = await admin_client.patch(
        "/api/v1/admin/movies/genres/99999/", json={"name": "NotExist"}
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_genre_validation_error(admin_client, movie_factory):
    genre = await movie_factory.create_genre("TestGenre")

    response = await admin_client.patch(
        f"/api/v1/admin/movies/genres/{genre.id}/", json={"name": ""}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_genre_unauthorized(client, movie_factory):
    genre = await movie_factory.create_genre("Unauthorized")

    response = await client.patch(
        f"/api/v1/admin/movies/genres/{genre.id}/", json={"name": "ShouldFail"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_genre_forbidden_regular_user(authenticated_client, movie_factory):
    genre = await movie_factory.create_genre("Forbidden")

    response = await authenticated_client.patch(
        f"/api/v1/admin/movies/genres/{genre.id}/", json={"name": "ShouldFail"}
    )
    assert response.status_code == 403


# ====================== DELETE /genres/{genre_id}/ ======================


@pytest.mark.asyncio
async def test_delete_genre_success(admin_client, movie_factory, db_session):
    genre = await movie_factory.create_genre("ToBeDeleted")

    response = await admin_client.delete(f"/api/v1/admin/movies/genres/{genre.id}/")

    assert response.status_code == 204

    deleted = await db_session.scalar(
        select(GenreModel).where(GenreModel.id == genre.id)
    )
    assert deleted is None


@pytest.mark.asyncio
async def test_delete_genre_not_found(admin_client):
    response = await admin_client.delete("/api/v1/admin/movies/genres/99999/")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_genre_unauthorized(client, movie_factory):
    genre = await movie_factory.create_genre("UnauthorizedDelete")

    response = await client.delete(f"/api/v1/admin/movies/genres/{genre.id}/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_genre_forbidden_regular_user(authenticated_client, movie_factory):
    genre = await movie_factory.create_genre("ForbiddenDelete")

    response = await authenticated_client.delete(
        f"/api/v1/admin/movies/genres/{genre.id}/"
    )
    assert response.status_code == 403


# ====================== GET /stars/ ======================


@pytest.mark.asyncio
async def test_get_stars_list_success(admin_client, movie_factory):
    await movie_factory.create_movie(stars=["Leonardo DiCaprio", "Tom Hardy"])

    response = await admin_client.get("/api/v1/admin/movies/stars/")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert len(data["items"]) > 0


@pytest.mark.asyncio
async def test_get_stars_pagination(admin_client, movie_factory):
    for i in range(15):
        await movie_factory.create_movie(stars=[f"Star {i}"])

    response = await admin_client.get("/api/v1/admin/movies/stars/?page=1&size=5")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 5
    assert data["page"] == 1
    assert data["size"] == 5


@pytest.mark.asyncio
async def test_get_stars_unauthorized(client):
    response = await client.get("/api/v1/admin/movies/stars/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_stars_forbidden_regular_user(authenticated_client):
    response = await authenticated_client.get("/api/v1/admin/movies/stars/")
    assert response.status_code == 403


# ====================== POST /stars/ ======================


@pytest.mark.asyncio
async def test_create_star_success(admin_client, db_session):
    payload = {"name": "Brad Pitt"}

    response = await admin_client.post("/api/v1/admin/movies/stars/", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Brad Pitt"

    star = await db_session.scalar(
        select(StarModel).where(StarModel.name == "Brad Pitt")
    )
    assert star is not None


@pytest.mark.asyncio
async def test_create_star_duplicate(admin_client, movie_factory):
    await movie_factory.create_movie(stars=["Tom Hanks"])

    response = await admin_client.post(
        "/api/v1/admin/movies/stars/", json={"name": "Tom Hanks"}
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_star_validation_error(admin_client):
    response = await admin_client.post("/api/v1/admin/movies/stars/", json={"name": ""})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_star_unauthorized(client):
    response = await client.post(
        "/api/v1/admin/movies/stars/", json={"name": "Unauthorized"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_star_forbidden_regular_user(authenticated_client):
    response = await authenticated_client.post(
        "/api/v1/admin/movies/stars/", json={"name": "Forbidden"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_star_success(admin_client, db_session):
    payload = {"name": "Brad Pitt"}

    response = await admin_client.post("/api/v1/admin/movies/stars/", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Brad Pitt"

    star = await db_session.scalar(
        select(StarModel).where(StarModel.name == "Brad Pitt")
    )
    assert star is not None


@pytest.mark.asyncio
async def test_create_star_duplicate(admin_client, movie_factory):
    await movie_factory.create_movie(stars=["Tom Hanks"])

    response = await admin_client.post(
        "/api/v1/admin/movies/stars/", json={"name": "Tom Hanks"}
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_star_validation_error(admin_client):
    response = await admin_client.post("/api/v1/admin/movies/stars/", json={"name": ""})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_star_unauthorized(client):
    response = await client.post(
        "/api/v1/admin/movies/stars/", json={"name": "Unauthorized"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_star_forbidden_regular_user(authenticated_client):
    response = await authenticated_client.post(
        "/api/v1/admin/movies/stars/", json={"name": "Forbidden"}
    )
    assert response.status_code == 403


# ====================== PATCH /stars/{star_id}/ ======================


@pytest.mark.asyncio
async def test_update_star_success(admin_client, movie_factory, db_session):
    await movie_factory.create_movie(stars=["Old Star Name"])
    star = await db_session.scalar(
        select(StarModel).where(StarModel.name == "Old Star Name")
    )

    response = await admin_client.patch(
        f"/api/v1/admin/movies/stars/{star.id}/", json={"name": "New Star Name"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Star Name"

    await db_session.refresh(star)
    assert star.name == "New Star Name"


@pytest.mark.asyncio
async def test_update_star_not_found(admin_client):
    response = await admin_client.patch(
        "/api/v1/admin/movies/stars/99999/", json={"name": "NotExist"}
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_star_duplicate_name(admin_client, movie_factory, db_session):
    await movie_factory.create_movie(stars=["Existing Star"])
    await movie_factory.create_movie(stars=["Another Star"])

    star_to_update = await db_session.scalar(
        select(StarModel).where(StarModel.name == "Another Star")
    )

    response = await admin_client.patch(
        f"/api/v1/admin/movies/stars/{star_to_update.id}/",
        json={"name": "Existing Star"},
    )

    assert response.status_code == 400
    assert "already" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_star_validation_error(admin_client, movie_factory, db_session):
    await movie_factory.create_movie(stars=["Validation Test"])

    star = await db_session.scalar(
        select(StarModel).where(StarModel.name == "Validation Test")
    )

    response = await admin_client.patch(
        f"/api/v1/admin/movies/stars/{star.id}/", json={"name": ""}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_star_unauthorized(client, movie_factory, db_session):
    await movie_factory.create_movie(stars=["Unauthorized Update"])

    star = await db_session.scalar(
        select(StarModel).where(StarModel.name == "Unauthorized Update")
    )

    response = await client.patch(
        f"/api/v1/admin/movies/stars/{star.id}/", json={"name": "Should Fail"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_star_forbidden_regular_user(
    authenticated_client, movie_factory, db_session
):
    await movie_factory.create_movie(stars=["Forbidden Update"])

    star = await db_session.scalar(
        select(StarModel).where(StarModel.name == "Forbidden Update")
    )

    response = await authenticated_client.patch(
        f"/api/v1/admin/movies/stars/{star.id}/", json={"name": "Should Fail"}
    )
    assert response.status_code == 403


# ====================== DELETE /stars/{star_id}/ ======================


@pytest.mark.asyncio
async def test_delete_star_success(admin_client, movie_factory, db_session):
    await movie_factory.create_movie(stars=["Star To Delete"])
    star = await db_session.scalar(
        select(StarModel).where(StarModel.name == "Star To Delete")
    )

    response = await admin_client.delete(f"/api/v1/admin/movies/stars/{star.id}/")

    assert response.status_code == 204

    deleted = await db_session.scalar(select(StarModel).where(StarModel.id == star.id))
    assert deleted is None


@pytest.mark.asyncio
async def test_delete_star_not_found(admin_client):
    response = await admin_client.delete("/api/v1/admin/movies/stars/99999/")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_star_unauthorized(client, movie_factory, db_session):
    await movie_factory.create_movie(stars=["Unauthorized Delete"])

    star = await db_session.scalar(
        select(StarModel).where(StarModel.name == "Unauthorized Delete")
    )

    response = await client.delete(f"/api/v1/admin/movies/stars/{star.id}/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_star_forbidden_regular_user(
    authenticated_client, movie_factory, db_session
):
    await movie_factory.create_movie(stars=["Forbidden Delete"])

    star = await db_session.scalar(
        select(StarModel).where(StarModel.name == "Forbidden Delete")
    )

    response = await authenticated_client.delete(
        f"/api/v1/admin/movies/stars/{star.id}/"
    )
    assert response.status_code == 403


# ====================== GET /directors/ ======================


@pytest.mark.asyncio
async def test_get_directors_list_success(admin_client, movie_factory):
    await movie_factory.create_movie(
        directors=["Christopher Nolan", "Denis Villeneuve"]
    )

    response = await admin_client.get("/api/v1/admin/movies/directors/")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert len(data["items"]) > 0


@pytest.mark.asyncio
async def test_get_directors_pagination(admin_client, movie_factory):
    for i in range(12):
        await movie_factory.create_movie(directors=[f"Director Pagination {i}"])

    response = await admin_client.get("/api/v1/admin/movies/directors/?page=1&size=4")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 4
    assert data["page"] == 1
    assert data["size"] == 4


@pytest.mark.asyncio
async def test_get_directors_unauthorized(client):
    response = await client.get("/api/v1/admin/movies/directors/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_directors_forbidden_regular_user(authenticated_client):
    response = await authenticated_client.get("/api/v1/admin/movies/directors/")
    assert response.status_code == 403


# ====================== POST /directors/ ======================


@pytest.mark.asyncio
async def test_create_director_success(admin_client, db_session):
    payload = {"name": "Martin Scorsese"}

    response = await admin_client.post("/api/v1/admin/movies/directors/", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Martin Scorsese"

    director = await db_session.scalar(
        select(DirectorModel).where(DirectorModel.name == "Martin Scorsese")
    )
    assert director is not None


@pytest.mark.asyncio
async def test_create_director_duplicate(admin_client, movie_factory):
    await movie_factory.create_movie(directors=["Quentin Tarantino"])

    response = await admin_client.post(
        "/api/v1/admin/movies/directors/", json={"name": "Quentin Tarantino"}
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_director_validation_error(admin_client):
    response = await admin_client.post(
        "/api/v1/admin/movies/directors/", json={"name": ""}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_director_unauthorized(client):
    response = await client.post(
        "/api/v1/admin/movies/directors/", json={"name": "Unauthorized Director"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_director_forbidden_regular_user(authenticated_client):
    response = await authenticated_client.post(
        "/api/v1/admin/movies/directors/", json={"name": "Forbidden Director"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_director_internal_error(admin_client, monkeypatch, db_session):
    async def fake_commit(*args, **kwargs):
        raise Exception("Simulated unexpected error")

    monkeypatch.setattr(db_session, "commit", fake_commit)

    response = await admin_client.post(
        "/api/v1/admin/movies/directors/", json={"name": "CrashTest Director"}
    )

    assert response.status_code == 500
    assert "internal error" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_director_duplicate(admin_client, db_session):
    db_session.add(DirectorModel(name="Duplicate Director"))
    await db_session.commit()

    response = await admin_client.post(
        "/api/v1/admin/movies/directors/", json={"name": "Duplicate Director"}
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"].lower()


# ====================== PATCH /directors/{director_id}/ ======================


@pytest.mark.asyncio
async def test_update_director_success(admin_client, movie_factory, db_session):
    await movie_factory.create_movie(directors=["Old Director Name"])
    director = await db_session.scalar(
        select(DirectorModel).where(DirectorModel.name == "Old Director Name")
    )

    response = await admin_client.patch(
        f"/api/v1/admin/movies/directors/{director.id}/",
        json={"name": "New Director Name"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Director Name"

    await db_session.refresh(director)
    assert director.name == "New Director Name"


@pytest.mark.asyncio
async def test_update_director_not_found(admin_client):
    response = await admin_client.patch(
        "/api/v1/admin/movies/directors/99999/", json={"name": "NotExist"}
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_director_duplicate_name(admin_client, movie_factory, db_session):
    await movie_factory.create_movie(directors=["Existing Director"])
    await movie_factory.create_movie(directors=["Another Director"])

    director_to_update = await db_session.scalar(
        select(DirectorModel).where(DirectorModel.name == "Another Director")
    )

    response = await admin_client.patch(
        f"/api/v1/admin/movies/directors/{director_to_update.id}/",
        json={"name": "Existing Director"},
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_director_validation_error(
    admin_client, movie_factory, db_session
):
    await movie_factory.create_movie(directors=["Validation Director"])

    director = await db_session.scalar(
        select(DirectorModel).where(DirectorModel.name == "Validation Director")
    )

    response = await admin_client.patch(
        f"/api/v1/admin/movies/directors/{director.id}/", json={"name": ""}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_director_unauthorized(client, movie_factory, db_session):
    await movie_factory.create_movie(directors=["Unauthorized Director Update"])

    director = await db_session.scalar(
        select(DirectorModel).where(
            DirectorModel.name == "Unauthorized Director Update"
        )
    )

    response = await client.patch(
        f"/api/v1/admin/movies/directors/{director.id}/", json={"name": "Should Fail"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_director_forbidden_regular_user(
    authenticated_client, movie_factory, db_session
):
    await movie_factory.create_movie(directors=["Forbidden Director Update"])

    director = await db_session.scalar(
        select(DirectorModel).where(DirectorModel.name == "Forbidden Director Update")
    )

    response = await authenticated_client.patch(
        f"/api/v1/admin/movies/directors/{director.id}/", json={"name": "Should Fail"}
    )
    assert response.status_code == 403


# ====================== DELETE /directors/{director_id}/ ======================


@pytest.mark.asyncio
async def test_delete_director_success(admin_client, movie_factory, db_session):
    await movie_factory.create_movie(directors=["Director To Delete"])
    director = await db_session.scalar(
        select(DirectorModel).where(DirectorModel.name == "Director To Delete")
    )

    response = await admin_client.delete(
        f"/api/v1/admin/movies/directors/{director.id}/"
    )

    assert response.status_code == 204

    deleted = await db_session.scalar(
        select(DirectorModel).where(DirectorModel.id == director.id)
    )
    assert deleted is None


@pytest.mark.asyncio
async def test_delete_director_not_found(admin_client):
    response = await admin_client.delete("/api/v1/admin/movies/directors/99999/")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_director_unauthorized(client, movie_factory, db_session):
    await movie_factory.create_movie(directors=["Unauthorized Director Delete"])

    director = await db_session.scalar(
        select(DirectorModel).where(
            DirectorModel.name == "Unauthorized Director Delete"
        )
    )

    response = await client.delete(f"/api/v1/admin/movies/directors/{director.id}/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_director_forbidden_regular_user(
    authenticated_client, movie_factory, db_session
):
    await movie_factory.create_movie(directors=["Forbidden Director Delete"])

    director = await db_session.scalar(
        select(DirectorModel).where(DirectorModel.name == "Forbidden Director Delete")
    )

    response = await authenticated_client.delete(
        f"/api/v1/admin/movies/directors/{director.id}/"
    )
    assert response.status_code == 403


# ====================== GET /certifications/ ======================


@pytest.mark.asyncio
async def test_get_certifications_list_success(admin_client, movie_factory):
    await movie_factory.create_movie()

    response = await admin_client.get("/api/v1/admin/movies/certifications/")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert len(data["items"]) > 0


@pytest.mark.asyncio
async def test_get_certifications_pagination(admin_client, movie_factory, db_session):
    for i in range(10):
        cert = CertificationModel(name=f"Certification Test {i}")
        db_session.add(cert)
    await db_session.commit()

    response = await admin_client.get(
        "/api/v1/admin/movies/certifications/?page=1&size=5"
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 5
    assert data["page"] == 1
    assert data["size"] == 5


@pytest.mark.asyncio
async def test_get_certifications_unauthorized(client):
    response = await client.get("/api/v1/admin/movies/certifications/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_certifications_forbidden_regular_user(authenticated_client):
    response = await authenticated_client.get("/api/v1/admin/movies/certifications/")
    assert response.status_code == 403


# ====================== POST /certifications/ ======================


@pytest.mark.asyncio
async def test_create_certification_success(admin_client, db_session):
    payload = {"name": "PG-18"}

    response = await admin_client.post(
        "/api/v1/admin/movies/certifications/", json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "PG-18"

    cert = await db_session.scalar(
        select(CertificationModel).where(CertificationModel.name == "PG-18")
    )
    assert cert is not None


@pytest.mark.asyncio
async def test_create_certification_duplicate(admin_client, db_session):
    duplicate_name = "DuplicateCert12345"

    existing = CertificationModel(name=duplicate_name)
    db_session.add(existing)
    await db_session.commit()

    response = await admin_client.post(
        "/api/v1/admin/movies/certifications/", json={"name": duplicate_name}
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_certification_validation_error(admin_client):
    response = await admin_client.post(
        "/api/v1/admin/movies/certifications/", json={"name": ""}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_certification_unauthorized(client):
    response = await client.post(
        "/api/v1/admin/movies/certifications/", json={"name": "Unauthorized Cert"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_certification_forbidden_regular_user(authenticated_client):
    response = await authenticated_client.post(
        "/api/v1/admin/movies/certifications/", json={"name": "Forbidden Cert"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_certification_internal_error(
    admin_client, monkeypatch, db_session
):
    async def fake_commit(*args, **kwargs):
        raise Exception("Simulated unexpected error")

    monkeypatch.setattr(db_session, "commit", fake_commit)

    response = await admin_client.post(
        "/api/v1/admin/movies/certifications/", json={"name": "CrashTest Cert"}
    )

    assert response.status_code == 500
    assert "internal database error occurred." in response.json()["detail"].lower()


# ====================== PATCH /certifications/{cert_id}/ ======================


@pytest.mark.asyncio
async def test_update_certification_success(admin_client, db_session):
    cert = CertificationModel(name="Old Rating")
    db_session.add(cert)
    await db_session.commit()

    response = await admin_client.patch(
        f"/api/v1/admin/movies/certifications/{cert.id}/", json={"name": "New Rating"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Rating"

    await db_session.refresh(cert)
    assert cert.name == "New Rating"


@pytest.mark.asyncio
async def test_update_certification_not_found(admin_client):
    response = await admin_client.patch(
        "/api/v1/admin/movies/certifications/99999/", json={"name": "NotExist"}
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_certification_duplicate_name(admin_client, db_session):
    cert1 = CertificationModel(name="Existing Cert")
    cert2 = CertificationModel(name="ToBeUpdated")
    db_session.add_all([cert1, cert2])
    await db_session.commit()

    response = await admin_client.patch(
        f"/api/v1/admin/movies/certifications/{cert2.id}/",
        json={"name": "Existing Cert"},
    )

    assert response.status_code == 400
    assert "already taken" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_certification_validation_error(admin_client, db_session):
    cert = CertificationModel(name="Validation Test")
    db_session.add(cert)
    await db_session.commit()

    response = await admin_client.patch(
        f"/api/v1/admin/movies/certifications/{cert.id}/", json={"name": ""}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_certification_unauthorized(client, db_session):
    cert = CertificationModel(name="Unauthorized Update")
    db_session.add(cert)
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/admin/movies/certifications/{cert.id}/", json={"name": "Should Fail"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_certification_forbidden_regular_user(
    authenticated_client, db_session
):
    cert = CertificationModel(name="Forbidden Update")
    db_session.add(cert)
    await db_session.commit()

    response = await authenticated_client.patch(
        f"/api/v1/admin/movies/certifications/{cert.id}/", json={"name": "Should Fail"}
    )
    assert response.status_code == 403


# ====================== DELETE /certifications/{cert_id}/ ======================


@pytest.mark.asyncio
async def test_delete_certification_success(admin_client, db_session):
    cert = CertificationModel(name="ToBeDeletedCert")
    db_session.add(cert)
    await db_session.commit()

    response = await admin_client.delete(
        f"/api/v1/admin/movies/certifications/{cert.id}/"
    )

    assert response.status_code == 204

    deleted = await db_session.scalar(
        select(CertificationModel).where(CertificationModel.id == cert.id)
    )
    assert deleted is None


@pytest.mark.asyncio
async def test_delete_certification_not_found(admin_client):
    response = await admin_client.delete("/api/v1/admin/movies/certifications/99999/")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_certification_with_movies(admin_client, movie_factory, db_session):
    cert = CertificationModel(name="UsedCert")
    db_session.add(cert)
    await db_session.commit()
    await db_session.refresh(cert)

    movie = await movie_factory.create_movie()

    movie.certification_id = cert.id
    await db_session.commit()

    response = await admin_client.delete(
        f"/api/v1/admin/movies/certifications/{cert.id}/"
    )

    assert response.status_code == 400
    detail = response.json()["detail"].lower()
    assert any(phrase in detail for phrase in [
        "assigned to movies",
        "cannot delete",
        "linked to existing movies"
    ])


@pytest.mark.asyncio
async def test_delete_certification_unauthorized(client, db_session):
    cert = CertificationModel(name="Unauthorized Delete Cert")
    db_session.add(cert)
    await db_session.commit()

    response = await client.delete(f"/api/v1/admin/movies/certifications/{cert.id}/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_certification_forbidden_regular_user(
    authenticated_client, db_session
):
    cert = CertificationModel(name="Forbidden Delete Cert")
    db_session.add(cert)
    await db_session.commit()

    response = await authenticated_client.delete(
        f"/api/v1/admin/movies/certifications/{cert.id}/"
    )
    assert response.status_code == 403

# ====================== POST / (create movie) ======================

@pytest.mark.asyncio
async def test_create_movie_success(admin_client, movie_factory, db_session):
    genre = await movie_factory.create_genre(f"Action_{uuid.uuid4().hex[:6]}")
    star = await db_session.scalar(select(StarModel).limit(1))
    director = await db_session.scalar(select(DirectorModel).limit(1))
    cert = await db_session.scalar(select(CertificationModel).limit(1))

    payload = {
        "name": f"Inception Test {uuid.uuid4().hex[:8]}",
        "year": 2010,
        "time": 148,
        "imdb": 8.8,
        "description": "A thief who steals corporate secrets through dream-sharing technology.",
        "price": "12.99",
        "certification_id": cert.id,
        "genre_ids": [genre.id],
        "star_ids": [star.id],
        "director_ids": [director.id],
        "votes": 2000000
    }

    response = await admin_client.post("/api/v1/admin/movies/", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert payload["name"] in data["name"]
    assert data["year"] == 2010
    assert len(data["genres"]) == 1
    assert len(data["stars"]) >= 1
    assert len(data["directors"]) >= 1


@pytest.mark.asyncio
async def test_create_movie_invalid_certification(admin_client, movie_factory, db_session):
    genre = await movie_factory.create_genre(f"Drama_{uuid.uuid4().hex[:6]}")
    star = await db_session.scalar(select(StarModel).limit(1))
    director = await db_session.scalar(select(DirectorModel).limit(1))

    payload = {
        "name": f"Invalid Cert Movie {uuid.uuid4().hex[:8]}",
        "year": 2023,
        "time": 120,
        "imdb": 7.5,
        "description": "Test description",
        "price": "9.99",
        "certification_id": 99999,
        "genre_ids": [genre.id],
        "star_ids": [star.id],
        "director_ids": [director.id]
    }

    response = await admin_client.post("/api/v1/admin/movies/", json=payload)
    assert response.status_code == 400
    assert "certification" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_movie_invalid_genre_ids(admin_client, movie_factory, db_session):

    cert = await db_session.scalar(select(CertificationModel).limit(1))
    star = await db_session.scalar(select(StarModel).limit(1))
    director = await db_session.scalar(select(DirectorModel).limit(1))

    payload = {
        "name": f"Invalid Genre Movie {uuid.uuid4().hex[:8]}",
        "year": 2023,
        "time": 130,
        "imdb": 7.0,
        "description": "Test description",
        "price": "10.00",
        "certification_id": cert.id,
        "genre_ids": [99999],
        "star_ids": [star.id],
        "director_ids": [director.id]
    }

    response = await admin_client.post("/api/v1/admin/movies/", json=payload)
    assert response.status_code == 400
    assert "genre" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_movie_duplicate(admin_client, movie_factory, db_session):
    unique_name = f"Duplicate Movie {uuid.uuid4().hex[:8]}"

    await movie_factory.create_movie(name=unique_name, year=2025, time=120)

    genre = await movie_factory.create_genre(f"Thriller_{uuid.uuid4().hex[:6]}")
    star = await db_session.scalar(select(StarModel).limit(1))
    director = await db_session.scalar(select(DirectorModel).limit(1))
    cert = await db_session.scalar(select(CertificationModel).limit(1))

    payload = {
        "name": unique_name,
        "year": 2025,
        "time": 120,
        "imdb": 8.0,
        "description": "Test duplicate",
        "price": "15.00",
        "certification_id": cert.id,
        "genre_ids": [genre.id],
        "star_ids": [star.id],
        "director_ids": [director.id],
        "votes": 500
    }

    response = await admin_client.post("/api/v1/admin/movies/", json=payload)
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_movie_validation_error(admin_client):
    payload = {"name": ""}
    response = await admin_client.post("/api/v1/admin/movies/", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_movie_unauthorized(client):
    payload = {
        "name": "Test Unauthorized",
        "year": 2023,
        "time": 120,
        "imdb": 7.0,
        "description": "x",
        "price": "10",
        "certification_id": 1,
        "genre_ids": [1],
        "star_ids": [1],
        "director_ids": [1]
    }
    response = await client.post("/api/v1/admin/movies/", json=payload)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_movie_forbidden_regular_user(authenticated_client):
    payload = {
        "name": "Test Forbidden",
        "year": 2023,
        "time": 120,
        "imdb": 7.0,
        "description": "x",
        "price": "10",
        "certification_id": 1,
        "genre_ids": [1],
        "star_ids": [1],
        "director_ids": [1]
    }
    response = await authenticated_client.post("/api/v1/admin/movies/", json=payload)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_movie_internal_error(admin_client, monkeypatch, movie_factory, db_session):

    async def fake_flush(*args, **kwargs):
        raise SQLAlchemyError("Simulated DB crash")

    monkeypatch.setattr(db_session, "flush", fake_flush)

    genre = await movie_factory.create_genre(f"CrashGenre_{uuid.uuid4().hex[:6]}")
    star = await db_session.scalar(select(StarModel).limit(1))
    director = await db_session.scalar(select(DirectorModel).limit(1))
    cert = await db_session.scalar(select(CertificationModel).limit(1))

    payload = {
        "name": f"Crash Movie {uuid.uuid4().hex[:8]}",
        "year": 2024,
        "time": 120,
        "imdb": 7.5,
        "description": "Test crash",
        "price": "10.00",
        "certification_id": cert.id,
        "genre_ids": [genre.id],
        "star_ids": [star.id],
        "director_ids": [director.id]
    }

    response = await admin_client.post("/api/v1/admin/movies/", json=payload)
    assert response.status_code == 500
    assert "database error" in response.json()["detail"].lower()

@pytest.mark.asyncio
async def test_create_movie_with_meta_score_and_gross(admin_client, movie_factory, db_session):
    genre = await movie_factory.create_genre(f"MetaTest_{uuid.uuid4().hex[:6]}")
    star = await db_session.scalar(select(StarModel).limit(1))
    director = await db_session.scalar(select(DirectorModel).limit(1))
    cert = await db_session.scalar(select(CertificationModel).limit(1))

    payload = {
        "name": f"Meta Gross Movie {uuid.uuid4().hex[:8]}",
        "year": 2024,
        "time": 142,
        "imdb": 8.2,
        "description": "Test movie with meta and gross fields",
        "price": "15.99",
        "certification_id": cert.id,
        "genre_ids": [genre.id],
        "star_ids": [star.id],
        "director_ids": [director.id],
        "meta_score": 82,
        "gross": 285000000,
        "votes": 1250000
    }

    response = await admin_client.post("/api/v1/admin/movies/", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["meta_score"] == 82
    assert data["gross"] == 285000000
    assert data["name"] == payload["name"]


@pytest.mark.asyncio
async def test_create_movie_invalid_star_ids(admin_client, movie_factory, db_session):
    genre = await movie_factory.create_genre()
    cert = await db_session.scalar(select(CertificationModel).limit(1))
    director = await db_session.scalar(select(DirectorModel).limit(1))

    payload = {
        "name": f"Invalid Stars {uuid.uuid4().hex[:8]}",
        "year": 2023,
        "time": 125,
        "imdb": 7.8,
        "description": "Test invalid stars",
        "price": "12.50",
        "certification_id": cert.id,
        "genre_ids": [genre.id],
        "star_ids": [99999, 88888],
        "director_ids": [director.id]
    }

    response = await admin_client.post("/api/v1/admin/movies/", json=payload)
    assert response.status_code == 400
    assert "star" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_movie_invalid_director_ids(admin_client, movie_factory, db_session):
    genre = await movie_factory.create_genre()
    cert = await db_session.scalar(select(CertificationModel).limit(1))
    star = await db_session.scalar(select(StarModel).limit(1))

    payload = {
        "name": f"Invalid Directors {uuid.uuid4().hex[:8]}",
        "year": 2023,
        "time": 130,
        "imdb": 7.5,
        "description": "Test invalid directors",
        "price": "11.99",
        "certification_id": cert.id,
        "genre_ids": [genre.id],
        "star_ids": [star.id],
        "director_ids": [99999]
    }

    response = await admin_client.post("/api/v1/admin/movies/", json=payload)
    assert response.status_code == 400
    assert "director" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_movie_validation_errors(admin_client):
    payload = {
        "name": "Validation Movie",
        "year": 1800,
        "time": 350,
        "imdb": 10.5,
        "description": "short",
        "price": "-10.00",
        "certification_id": 1,
        "genre_ids": [1],
        "star_ids": [1],
        "director_ids": [1]
    }

    response = await admin_client.post("/api/v1/admin/movies/", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_movie_empty_genre_ids(admin_client, movie_factory, db_session):
    cert = await db_session.scalar(select(CertificationModel).limit(1))
    star = await db_session.scalar(select(StarModel).limit(1))
    director = await db_session.scalar(select(DirectorModel).limit(1))

    payload = {
        "name": f"Empty Genres {uuid.uuid4().hex[:8]}",
        "year": 2024,
        "time": 110,
        "imdb": 6.8,
        "description": "Movie without genres",
        "price": "9.99",
        "certification_id": cert.id,
        "genre_ids": [],
        "star_ids": [star.id],
        "director_ids": [director.id]
    }

    response = await admin_client.post("/api/v1/admin/movies/", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_movie_internal_error_flush(admin_client, monkeypatch, movie_factory, db_session):
    async def fake_flush(*args, **kwargs):
        raise SQLAlchemyError("Simulated flush error")

    monkeypatch.setattr(db_session, "flush", fake_flush)

    genre = await movie_factory.create_genre()
    star = await db_session.scalar(select(StarModel).limit(1))
    director = await db_session.scalar(select(DirectorModel).limit(1))
    cert = await db_session.scalar(select(CertificationModel).limit(1))

    payload = {
        "name": f"Crash Movie {uuid.uuid4().hex[:8]}",
        "year": 2024,
        "time": 120,
        "imdb": 7.5,
        "description": "This will cause internal error",
        "price": "10.99",
        "certification_id": cert.id,
        "genre_ids": [genre.id],
        "star_ids": [star.id],
        "director_ids": [director.id]
    }

    response = await admin_client.post("/api/v1/admin/movies/", json=payload)

    assert response.status_code == 500
    assert "database error" in response.json()["detail"].lower()

# ====================== GET /deleted/ ======================

@pytest.mark.asyncio
async def test_list_deleted_movies_success(admin_client, movie_factory, db_session):

    movie = await movie_factory.create_movie(name="Active Movie")
    deleted_movie = await movie_factory.create_movie(name="Deleted Movie")

    deleted_movie.is_deleted = True
    deleted_movie.deleted_at = datetime.utcnow()
    await db_session.commit()

    response = await admin_client.get("/api/v1/admin/movies/deleted/")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1

    deleted_names = [item["name"] for item in data["items"]]
    assert "Deleted Movie" in deleted_names
    assert any(item["is_deleted"] is True for item in data["items"])


@pytest.mark.asyncio
async def test_list_deleted_movies_pagination(admin_client, movie_factory, db_session):

    for i in range(12):
        movie = await movie_factory.create_movie(name=f"Deleted Movie {i}")
        movie.is_deleted = True
        movie.deleted_at = datetime.utcnow()

    await db_session.commit()

    response = await admin_client.get("/api/v1/admin/movies/deleted/?page=1&size=5")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 5
    assert data["page"] == 1
    assert data["size"] == 5
    assert data["total"] >= 12


@pytest.mark.asyncio
async def test_list_deleted_movies_empty(admin_client, db_session):
    from sqlalchemy import text

    await db_session.execute(text("UPDATE movies SET is_deleted = FALSE, deleted_at = NULL"))
    await db_session.commit()
    response = await admin_client.get("/api/v1/admin/movies/deleted/")

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_list_deleted_movies_unauthorized(client):
    response = await client.get("/api/v1/admin/movies/deleted/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_deleted_movies_forbidden_regular_user(authenticated_client):
    response = await authenticated_client.get("/api/v1/admin/movies/deleted/")
    assert response.status_code == 403

# ====================== PATCH /{movie_uuid}/ ======================


@pytest.mark.asyncio
async def test_update_movie_success(admin_client, movie_factory, db_session):
    movie = await movie_factory.create_movie(
        name="Original Movie",
        year=2020,
        time=120,
        description="Original description"
    )

    payload = {
        "name": "Updated Movie Title",
        "year": 2023,
        "description": "New updated description that is long enough",
        "meta_score": 85,
        "gross": 150000000
    }

    response = await admin_client.patch(
        f"/api/v1/admin/movies/{movie.uuid}/", json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Movie Title"
    assert data["year"] == 2023
    assert data["description"] == payload["description"]
    assert data["meta_score"] == 85
    assert data["gross"] == 150000000


@pytest.mark.asyncio
async def test_update_movie_relationships(admin_client, movie_factory, db_session):
    movie = await movie_factory.create_movie()

    new_genre = await movie_factory.create_genre("New Action")
    new_star = await movie_factory.create_genre("New Star")
    star = await db_session.scalar(select(StarModel).limit(1))
    director = await db_session.scalar(select(DirectorModel).limit(1))
    new_genre2 = await movie_factory.create_genre("Thriller Updated")

    payload = {
        "genre_ids": [new_genre.id, new_genre2.id],
        "star_ids": [star.id],
        "director_ids": [director.id],
        "certification_id": 1
    }

    response = await admin_client.patch(
        f"/api/v1/admin/movies/{movie.uuid}/", json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["genres"]) == 2
    assert len(data["stars"]) >= 1
    assert len(data["directors"]) >= 1


@pytest.mark.asyncio
async def test_update_movie_clear_relationships(admin_client, movie_factory, db_session):
    movie = await movie_factory.create_movie()

    payload = {
        "genre_ids": [],
        "star_ids": [],
        "director_ids": []
    }

    response = await admin_client.patch(
        f"/api/v1/admin/movies/{movie.uuid}/", json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["genres"]) == 0
    assert len(data["stars"]) == 0
    assert len(data["directors"]) == 0


@pytest.mark.asyncio
async def test_update_movie_invalid_genre_ids(admin_client, movie_factory, db_session):
    movie = await movie_factory.create_movie()

    payload = {
        "genre_ids": [99999, 88888],
        "description": "Test invalid genres"
    }

    response = await admin_client.patch(
        f"/api/v1/admin/movies/{movie.uuid}/", json=payload
    )
    assert response.status_code == 400
    assert "genre" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_movie_invalid_star_ids(admin_client, movie_factory, db_session):
    movie = await movie_factory.create_movie()

    payload = {"star_ids": [99999]}

    response = await admin_client.patch(
        f"/api/v1/admin/movies/{movie.uuid}/", json=payload
    )
    assert response.status_code == 400
    assert "star" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_movie_invalid_director_ids(admin_client, movie_factory, db_session):
    movie = await movie_factory.create_movie()

    payload = {"director_ids": [99999]}

    response = await admin_client.patch(
        f"/api/v1/admin/movies/{movie.uuid}/", json=payload
    )
    assert response.status_code == 400
    assert "director" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_movie_invalid_certification(admin_client, movie_factory, db_session):
    movie = await movie_factory.create_movie()

    payload = {"certification_id": 99999}

    response = await admin_client.patch(
        f"/api/v1/admin/movies/{movie.uuid}/", json=payload
    )
    assert response.status_code == 400
    assert "certification" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_movie_not_found(admin_client):
    fake_uuid = str(uuid.uuid4())
    payload = {"name": "Not Exists"}

    response = await admin_client.patch(
        f"/api/v1/admin/movies/{fake_uuid}/", json=payload
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_movie_validation_error(admin_client, movie_factory, db_session):
    movie = await movie_factory.create_movie()

    payload = {
        "year": 1800,
        "imdb": 11.0,
        "description": "short",
        "price": -5.0
    }

    response = await admin_client.patch(
        f"/api/v1/admin/movies/{movie.uuid}/", json=payload
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_movie_duplicate_unique_constraint(admin_client, movie_factory, db_session):
    await movie_factory.create_movie(name="Existing Movie", year=2025, time=130)
    movie_to_update = await movie_factory.create_movie(name="To Update", year=2024, time=120)

    payload = {
        "name": "Existing Movie",
        "year": 2025,
        "time": 130
    }

    response = await admin_client.patch(
        f"/api/v1/admin/movies/{movie_to_update.uuid}/", json=payload
    )
    assert response.status_code == 400
    assert "unique" in response.json()["detail"].lower() or "already" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_movie_unauthorized(client, movie_factory, db_session):
    movie = await movie_factory.create_movie()
    payload = {"name": "Should Fail"}

    response = await client.patch(
        f"/api/v1/admin/movies/{movie.uuid}/", json=payload
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_movie_forbidden_regular_user(authenticated_client, movie_factory, db_session):
    movie = await movie_factory.create_movie()
    payload = {"name": "Should Fail"}

    response = await authenticated_client.patch(
        f"/api/v1/admin/movies/{movie.uuid}/", json=payload
    )
    assert response.status_code == 403
