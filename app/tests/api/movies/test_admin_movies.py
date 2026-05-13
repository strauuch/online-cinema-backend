import pytest
from sqlalchemy import select

from app.database.models.movies import GenreModel, StarModel, DirectorModel, CertificationModel


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
    response = await client.post(
        "/api/v1/admin/movies/genres/", json={"name": "Test"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_genre_forbidden_regular_user(authenticated_client):
    response = await authenticated_client.post(
        "/api/v1/admin/movies/genres/", json={"name": "Forbidden"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_genre_internal_server_error(admin_client, monkeypatch, db_session):
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
        "/api/v1/admin/movies/genres/",
        json={"name": "DuplicateGenre"}
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"].lower()

# ====================== PATCH /genres/{genre_id}/ ======================

@pytest.mark.asyncio
async def test_update_genre_success(admin_client, movie_factory, db_session):
    genre = await movie_factory.create_genre("OldGenre")

    response = await admin_client.patch(
        f"/api/v1/admin/movies/genres/{genre.id}/",
        json={"name": "NewGenre"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "NewGenre"

    await db_session.refresh(genre)
    assert genre.name == "NewGenre"


@pytest.mark.asyncio
async def test_update_genre_not_found(admin_client):
    response = await admin_client.patch(
        "/api/v1/admin/movies/genres/99999/",
        json={"name": "NotExist"}
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_genre_validation_error(admin_client, movie_factory):
    genre = await movie_factory.create_genre("TestGenre")

    response = await admin_client.patch(
        f"/api/v1/admin/movies/genres/{genre.id}/",
        json={"name": ""}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_genre_unauthorized(client, movie_factory):
    genre = await movie_factory.create_genre("Unauthorized")

    response = await client.patch(
        f"/api/v1/admin/movies/genres/{genre.id}/",
        json={"name": "ShouldFail"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_genre_forbidden_regular_user(authenticated_client, movie_factory):
    genre = await movie_factory.create_genre("Forbidden")

    response = await authenticated_client.patch(
        f"/api/v1/admin/movies/genres/{genre.id}/",
        json={"name": "ShouldFail"}
    )
    assert response.status_code == 403

# ====================== DELETE /genres/{genre_id}/ ======================

@pytest.mark.asyncio
async def test_delete_genre_success(admin_client, movie_factory, db_session):
    genre = await movie_factory.create_genre("ToBeDeleted")

    response = await admin_client.delete(
        f"/api/v1/admin/movies/genres/{genre.id}/"
    )

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

    response = await client.delete(
        f"/api/v1/admin/movies/genres/{genre.id}/"
    )
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
    response = await admin_client.post(
        "/api/v1/admin/movies/stars/", json={"name": ""}
    )
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
    response = await admin_client.post(
        "/api/v1/admin/movies/stars/", json={"name": ""}
    )
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
    star = await db_session.scalar(select(StarModel).where(StarModel.name == "Old Star Name"))

    response = await admin_client.patch(
        f"/api/v1/admin/movies/stars/{star.id}/",
        json={"name": "New Star Name"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Star Name"

    await db_session.refresh(star)
    assert star.name == "New Star Name"


@pytest.mark.asyncio
async def test_update_star_not_found(admin_client):
    response = await admin_client.patch(
        "/api/v1/admin/movies/stars/99999/",
        json={"name": "NotExist"}
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
        json={"name": "Existing Star"}
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
        f"/api/v1/admin/movies/stars/{star.id}/",
        json={"name": ""}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_star_unauthorized(client, movie_factory, db_session):
    await movie_factory.create_movie(stars=["Unauthorized Update"])

    star = await db_session.scalar(
        select(StarModel).where(StarModel.name == "Unauthorized Update")
    )

    response = await client.patch(
        f"/api/v1/admin/movies/stars/{star.id}/",
        json={"name": "Should Fail"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_star_forbidden_regular_user(authenticated_client, movie_factory, db_session):
    await movie_factory.create_movie(stars=["Forbidden Update"])

    star = await db_session.scalar(
        select(StarModel).where(StarModel.name == "Forbidden Update")
    )

    response = await authenticated_client.patch(
        f"/api/v1/admin/movies/stars/{star.id}/",
        json={"name": "Should Fail"}
    )
    assert response.status_code == 403

# ====================== DELETE /stars/{star_id}/ ======================

@pytest.mark.asyncio
async def test_delete_star_success(admin_client, movie_factory, db_session):
    await movie_factory.create_movie(stars=["Star To Delete"])
    star = await db_session.scalar(
        select(StarModel).where(StarModel.name == "Star To Delete")
    )

    response = await admin_client.delete(
        f"/api/v1/admin/movies/stars/{star.id}/"
    )

    assert response.status_code == 204

    deleted = await db_session.scalar(
        select(StarModel).where(StarModel.id == star.id)
    )
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
async def test_delete_star_forbidden_regular_user(authenticated_client, movie_factory, db_session):
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
    await movie_factory.create_movie(directors=["Christopher Nolan", "Denis Villeneuve"])

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
        "/api/v1/admin/movies/directors/",
        json={"name": "Duplicate Director"}
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
        json={"name": "New Director Name"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Director Name"

    await db_session.refresh(director)
    assert director.name == "New Director Name"


@pytest.mark.asyncio
async def test_update_director_not_found(admin_client):
    response = await admin_client.patch(
        "/api/v1/admin/movies/directors/99999/",
        json={"name": "NotExist"}
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
        json={"name": "Existing Director"}
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_director_validation_error(admin_client, movie_factory, db_session):
    await movie_factory.create_movie(directors=["Validation Director"])

    director = await db_session.scalar(
        select(DirectorModel).where(DirectorModel.name == "Validation Director")
    )

    response = await admin_client.patch(
        f"/api/v1/admin/movies/directors/{director.id}/",
        json={"name": ""}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_director_unauthorized(client, movie_factory, db_session):
    await movie_factory.create_movie(directors=["Unauthorized Director Update"])

    director = await db_session.scalar(
        select(DirectorModel).where(DirectorModel.name == "Unauthorized Director Update")
    )

    response = await client.patch(
        f"/api/v1/admin/movies/directors/{director.id}/",
        json={"name": "Should Fail"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_director_forbidden_regular_user(authenticated_client, movie_factory, db_session):
    await movie_factory.create_movie(directors=["Forbidden Director Update"])

    director = await db_session.scalar(
        select(DirectorModel).where(DirectorModel.name == "Forbidden Director Update")
    )

    response = await authenticated_client.patch(
        f"/api/v1/admin/movies/directors/{director.id}/",
        json={"name": "Should Fail"}
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
        select(DirectorModel).where(DirectorModel.name == "Unauthorized Director Delete")
    )

    response = await client.delete(
        f"/api/v1/admin/movies/directors/{director.id}/"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_director_forbidden_regular_user(authenticated_client, movie_factory, db_session):
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

    response = await admin_client.get("/api/v1/admin/movies/certifications/?page=1&size=5")

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
        "/api/v1/admin/movies/certifications/",
        json=payload
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
        "/api/v1/admin/movies/certifications/",
        json={"name": duplicate_name}
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_certification_validation_error(admin_client):
    response = await admin_client.post(
        "/api/v1/admin/movies/certifications/",
        json={"name": ""}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_certification_unauthorized(client):
    response = await client.post(
        "/api/v1/admin/movies/certifications/",
        json={"name": "Unauthorized Cert"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_certification_forbidden_regular_user(authenticated_client):
    response = await authenticated_client.post(
        "/api/v1/admin/movies/certifications/",
        json={"name": "Forbidden Cert"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_certification_internal_error(admin_client, monkeypatch, db_session):
    async def fake_commit(*args, **kwargs):
        raise Exception("Simulated unexpected error")

    monkeypatch.setattr(db_session, "commit", fake_commit)

    response = await admin_client.post(
        "/api/v1/admin/movies/certifications/",
        json={"name": "CrashTest Cert"}
    )

    assert response.status_code == 500
    assert "internal database error occurred." in response.json()["detail"].lower()
