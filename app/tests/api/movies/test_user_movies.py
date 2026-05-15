import uuid
import pytest
from datetime import datetime
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database.models.movies import (
    MovieFavoriteModel,
    MovieRatingModel,
    MovieVoteModel,
    MovieCommentModel,
    NotificationModel,
    CommentLikeModel,
    GenreModel,
)
from app.database.models.enums import NotificationType


BASE = "/api/v1/movies"


# ==============================================================================
# GET /
# ==============================================================================


@pytest.mark.asyncio
async def test_list_movies_returns_paginated_response(client, movie_factory):
    await movie_factory.create_movie()

    response = await client.get(f"{BASE}/")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "size" in data
    assert "total_pages" in data


@pytest.mark.asyncio
async def test_list_movies_accessible_without_auth(client, movie_factory):
    """GET / is a public endpoint — no token required."""
    await movie_factory.create_movie()

    response = await client.get(f"{BASE}/")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_movies_pagination_size(client, movie_factory):
    for _ in range(12):
        await movie_factory.create_movie()

    response = await client.get(f"{BASE}/?page=1&size=5")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 5
    assert data["page"] == 1
    assert data["size"] == 5


@pytest.mark.asyncio
async def test_list_movies_second_page(client, movie_factory):
    for _ in range(12):
        await movie_factory.create_movie()

    response = await client.get(f"{BASE}/?page=2&size=5")

    assert response.status_code == 200
    data = response.json()
    assert data["page"] == 2
    assert len(data["items"]) <= 5


@pytest.mark.asyncio
async def test_list_movies_filter_by_year(client, movie_factory):
    target_year = 1999
    await movie_factory.create_movie(name=f"OldMovie_{uuid.uuid4().hex[:6]}", year=target_year)
    await movie_factory.create_movie(name=f"NewMovie_{uuid.uuid4().hex[:6]}", year=2024)

    response = await client.get(f"{BASE}/?year={target_year}")

    assert response.status_code == 200
    data = response.json()
    assert all(item["year"] == target_year for item in data["items"])


@pytest.mark.asyncio
async def test_list_movies_filter_by_min_imdb(client, movie_factory):
    await movie_factory.create_movie(name=f"HighRated_{uuid.uuid4().hex[:6]}", imdb=9.0)
    await movie_factory.create_movie(name=f"LowRated_{uuid.uuid4().hex[:6]}", imdb=4.0)

    response = await client.get(f"{BASE}/?min_imdb=8.0")

    assert response.status_code == 200
    data = response.json()
    assert all(item["imdb"] >= 8.0 for item in data["items"])


@pytest.mark.asyncio
async def test_list_movies_filter_by_genre(client, movie_factory, db_session):
    genre = await movie_factory.create_genre(f"FilterGenre_{uuid.uuid4().hex[:6]}")
    await movie_factory.create_movie(genres=[genre])

    response = await client.get(f"{BASE}/?genre_id={genre.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    for item in data["items"]:
        genre_ids = [g["id"] for g in item["genres"]]
        assert genre.id in genre_ids


@pytest.mark.asyncio
async def test_list_movies_search_by_title(client, movie_factory):
    unique_token = uuid.uuid4().hex[:10]
    await movie_factory.create_movie(name=f"UniqueTitle_{unique_token}")

    response = await client.get(f"{BASE}/?q={unique_token}")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(unique_token in item["name"] for item in data["items"])


@pytest.mark.asyncio
async def test_list_movies_search_by_star_name(client, movie_factory):
    unique_star = f"StarUnique_{uuid.uuid4().hex[:8]}"
    await movie_factory.create_movie(stars=[unique_star])

    response = await client.get(f"{BASE}/?q={unique_star}")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_list_movies_search_by_director_name(client, movie_factory):
    unique_director = f"DirUnique_{uuid.uuid4().hex[:8]}"
    await movie_factory.create_movie(directors=[unique_director])

    response = await client.get(f"{BASE}/?q={unique_director}")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_list_movies_search_too_short_query(client):
    """q parameter has a min_length=2; single char should fail validation."""
    response = await client.get(f"{BASE}/?q=a")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_movies_sort_by_year_asc(client, movie_factory):
    await movie_factory.create_movie(name=f"Old_{uuid.uuid4().hex[:6]}", year=2000)
    await movie_factory.create_movie(name=f"New_{uuid.uuid4().hex[:6]}", year=2023)

    response = await client.get(f"{BASE}/?sort_by=year&order=asc")

    assert response.status_code == 200
    items = response.json()["items"]
    years = [item["year"] for item in items]
    assert years == sorted(years)


@pytest.mark.asyncio
async def test_list_movies_sort_by_imdb_desc(client, movie_factory):
    await movie_factory.create_movie(name=f"ImdbLow_{uuid.uuid4().hex[:6]}", imdb=5.5)
    await movie_factory.create_movie(name=f"ImdbHigh_{uuid.uuid4().hex[:6]}", imdb=9.1)

    response = await client.get(f"{BASE}/?sort_by=imdb&order=desc")

    assert response.status_code == 200
    items = response.json()["items"]
    imdbs = [item["imdb"] for item in items]
    assert imdbs == sorted(imdbs, reverse=True)


@pytest.mark.asyncio
async def test_list_movies_invalid_sort_by(client):
    response = await client.get(f"{BASE}/?sort_by=invalid_field")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_movies_invalid_order(client):
    response = await client.get(f"{BASE}/?order=sideways")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_movies_only_favorites_requires_auth(client, movie_factory):
    await movie_factory.create_movie()

    response = await client.get(f"{BASE}/?only_favorites=true")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_movies_only_favorites_returns_user_favorites(
    authenticated_client, movie_factory, db_session, user_factory, jwt_manager
):
    movie = await movie_factory.create_movie()
    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    db_session.add(MovieFavoriteModel(user_id=user_id, movie_id=movie.id))
    await db_session.commit()

    response = await authenticated_client.get(f"{BASE}/?only_favorites=true")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    uuids = [item["uuid"] for item in data["items"]]
    assert str(movie.uuid) in uuids


@pytest.mark.asyncio
async def test_list_movies_only_favorites_empty_when_none_added(authenticated_client):
    response = await authenticated_client.get(f"{BASE}/?only_favorites=true")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_movies_response_shape(client, movie_factory):
    await movie_factory.create_movie()

    response = await client.get(f"{BASE}/")

    assert response.status_code == 200
    item = response.json()["items"][0]
    for field in ("id", "uuid", "name", "year", "imdb", "price", "genres", "rating_avg", "rating_count"):
        assert field in item, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_list_movies_page_validation_below_minimum(client):
    response = await client.get(f"{BASE}/?page=0")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_movies_size_validation_above_maximum(client):
    response = await client.get(f"{BASE}/?size=101")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_movies_empty_db_returns_zero_total(client):
    response = await client.get(f"{BASE}/")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["total"], int)
    assert data["total"] >= 0


# ==============================================================================
# GET /{movie_uuid}/
# ==============================================================================


@pytest.mark.asyncio
async def test_get_movie_detail_success(client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await client.get(f"{BASE}/{movie.uuid}/")

    assert response.status_code == 200
    data = response.json()
    assert data["uuid"] == str(movie.uuid)
    assert data["name"] == movie.name


@pytest.mark.asyncio
async def test_get_movie_detail_response_shape(client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await client.get(f"{BASE}/{movie.uuid}/")

    assert response.status_code == 200
    data = response.json()
    for field in ("id", "uuid", "name", "year", "time", "imdb", "votes", "description",
                  "price", "genres", "stars", "directors", "certification"):
        assert field in data, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_get_movie_detail_not_found(client):
    fake_uuid = str(uuid.uuid4())

    response = await client.get(f"{BASE}/{fake_uuid}/")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_movie_detail_accessible_without_auth(client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await client.get(f"{BASE}/{movie.uuid}/")

    assert response.status_code == 200


# ==============================================================================
# GET /genres/
# ==============================================================================


@pytest.mark.asyncio
async def test_list_genres_success(client, movie_factory):
    await movie_factory.create_movie()

    response = await client.get(f"{BASE}/genres/")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_list_genres_accessible_without_auth(client, movie_factory):
    await movie_factory.create_movie()

    response = await client.get(f"{BASE}/genres/")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_genres_response_shape(client, movie_factory):
    await movie_factory.create_movie()

    response = await client.get(f"{BASE}/genres/")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert "id" in item
    assert "name" in item
    assert "movie_count" in item


@pytest.mark.asyncio
async def test_list_genres_pagination(client, movie_factory):
    for i in range(8):
        await movie_factory.create_genre(f"PaginationGenre_{uuid.uuid4().hex[:6]}")

    response = await client.get(f"{BASE}/genres/?page=1&size=3")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 3


@pytest.mark.asyncio
async def test_list_genres_movie_count_is_non_negative(client, movie_factory):
    await movie_factory.create_genre(f"EmptyGenre_{uuid.uuid4().hex[:6]}")

    response = await client.get(f"{BASE}/genres/")

    assert response.status_code == 200
    for item in response.json()["items"]:
        assert item["movie_count"] >= 0


# ==============================================================================
# GET /notifications/
# ==============================================================================


@pytest.mark.asyncio
async def test_get_notifications_success(authenticated_client, db_session, jwt_manager):
    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    db_session.add(NotificationModel(
        user_id=user_id,
        notification_type=NotificationType.SYSTEM,
        content="Test notification",
    ))
    await db_session.commit()

    response = await authenticated_client.get(f"{BASE}/notifications/")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_get_notifications_requires_auth(client):
    response = await client.get(f"{BASE}/notifications/")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_notifications_only_own(
    authenticated_client, user_factory, db_session, jwt_manager
):
    """User should only receive their own notifications, not other users'."""
    other_user = await user_factory.create_active_user(
        email=f"other_{uuid.uuid4()}@test.com"
    )
    db_session.add(NotificationModel(
        user_id=other_user.id,
        notification_type=NotificationType.SYSTEM,
        content="Not yours",
    ))
    await db_session.commit()

    response = await authenticated_client.get(f"{BASE}/notifications/")

    assert response.status_code == 200
    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]
    for notif in response.json():
        assert "id" in notif


@pytest.mark.asyncio
async def test_get_notifications_response_shape(authenticated_client, db_session, jwt_manager):
    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    db_session.add(NotificationModel(
        user_id=user_id,
        notification_type=NotificationType.SYSTEM,
        content="Shape test",
    ))
    await db_session.commit()

    response = await authenticated_client.get(f"{BASE}/notifications/")

    assert response.status_code == 200
    item = response.json()[0]
    for field in ("id", "notification_type", "content", "is_read", "created_at"):
        assert field in item, f"Missing field: {field}"


# ==============================================================================
# PATCH /notifications/{notif_id}/read/
# ==============================================================================


@pytest.mark.asyncio
async def test_mark_notification_as_read_success(
    authenticated_client, db_session, jwt_manager
):
    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    notif = NotificationModel(
        user_id=user_id,
        notification_type=NotificationType.SYSTEM,
        content="Mark me read",
    )
    db_session.add(notif)
    await db_session.commit()
    await db_session.refresh(notif)

    response = await authenticated_client.patch(
        f"{BASE}/notifications/{notif.id}/read/"
    )

    assert response.status_code == 200
    assert "read" in response.json()["message"].lower()

    await db_session.refresh(notif)
    assert notif.is_read is True


@pytest.mark.asyncio
async def test_mark_notification_as_read_not_found(authenticated_client):
    response = await authenticated_client.patch(f"{BASE}/notifications/99999/read/")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_mark_notification_as_read_other_user(
    authenticated_client, user_factory, db_session
):
    other_user = await user_factory.create_active_user(
        email=f"other2_{uuid.uuid4()}@test.com"
    )
    notif = NotificationModel(
        user_id=other_user.id,
        notification_type=NotificationType.SYSTEM,
        content="Not yours to read",
    )
    db_session.add(notif)
    await db_session.commit()
    await db_session.refresh(notif)

    response = await authenticated_client.patch(
        f"{BASE}/notifications/{notif.id}/read/"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_mark_notification_as_read_requires_auth(client, user_factory, db_session):
    user = await user_factory.create_active_user(
        email=f"bare_{uuid.uuid4()}@test.com"
    )
    notif = NotificationModel(
        user_id=user.id,
        notification_type=NotificationType.SYSTEM,
        content="No token",
    )
    db_session.add(notif)
    await db_session.commit()
    await db_session.refresh(notif)

    response = await client.patch(f"{BASE}/notifications/{notif.id}/read/")

    assert response.status_code == 401


# ==============================================================================
# GET /{movie_uuid}/comments/
# ==============================================================================


@pytest.mark.asyncio
async def test_list_comments_success(client, movie_factory, user_factory, comment_factory):
    other_user = await user_factory.create_active_user(
        email=f"other_{uuid.uuid4()}@test.com"
    )
    movie = await movie_factory.create_movie()
    await comment_factory.create_comment(movie_id=movie.id, user_id=other_user.id)

    response = await client.get(f"{BASE}/{movie.uuid}/comments/")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_list_comments_accessible_without_auth(client, movie_factory, user_factory, comment_factory):
    other_user = await user_factory.create_active_user(
        email=f"other_{uuid.uuid4()}@test.com"
    )
    movie = await movie_factory.create_movie()
    await comment_factory.create_comment(movie_id=movie.id, user_id=other_user.id)

    response = await client.get(f"{BASE}/{movie.uuid}/comments/")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_comments_movie_not_found(client):
    response = await client.get(f"{BASE}/{uuid.uuid4()}/comments/")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_comments_pagination(client, movie_factory, comment_factory, user_factory):
    other_user = await user_factory.create_active_user(
        email=f"other_{uuid.uuid4()}@test.com"
    )
    movie = await movie_factory.create_movie()
    for _ in range(5):
        await comment_factory.create_comment(movie_id=movie.id, user_id=other_user.id)

    response = await client.get(f"{BASE}/{movie.uuid}/comments/?page=1&size=3")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 3


@pytest.mark.asyncio
async def test_list_comments_response_shape(client, movie_factory, comment_factory):
    movie = await movie_factory.create_movie()
    await comment_factory.create_comment(movie_id=movie.id)

    response = await client.get(f"{BASE}/{movie.uuid}/comments/")

    assert response.status_code == 200
    item = response.json()["items"][0]
    for field in ("id", "user_id", "text", "created_at", "likes_count", "email"):
        assert field in item, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_list_comments_empty_movie(client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await client.get(f"{BASE}/{movie.uuid}/comments/")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []


# ==============================================================================
# POST /{movie_uuid}/comments/
# ==============================================================================


@pytest.mark.asyncio
async def test_add_comment_success(authenticated_client, movie_factory, db_session, jwt_manager):
    movie = await movie_factory.create_movie()

    response = await authenticated_client.post(
        f"{BASE}/{movie.uuid}/comments/", json={"text": "Great film!"}
    )

    assert response.status_code == 201
    assert "message" in response.json()


@pytest.mark.asyncio
async def test_add_comment_requires_auth(client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await client.post(
        f"{BASE}/{movie.uuid}/comments/", json={"text": "No token here"}
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_add_comment_movie_not_found(authenticated_client):
    response = await authenticated_client.post(
        f"{BASE}/{uuid.uuid4()}/comments/", json={"text": "Ghost movie"}
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_add_comment_validation_empty_text(authenticated_client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await authenticated_client.post(
        f"{BASE}/{movie.uuid}/comments/", json={"text": ""}
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_add_reply_comment_success(
    authenticated_client, movie_factory, comment_factory, jwt_manager, db_session
):
    movie = await movie_factory.create_movie()
    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    parent = await comment_factory.create_comment(movie_id=movie.id, user_id=user_id)

    response = await authenticated_client.post(
        f"{BASE}/{movie.uuid}/comments/",
        json={"text": "A reply", "parent_id": parent.id},
    )

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_add_reply_invalid_parent(authenticated_client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await authenticated_client.post(
        f"{BASE}/{movie.uuid}/comments/",
        json={"text": "Bad reply", "parent_id": 99999},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_add_comment_persisted_to_db(
    authenticated_client, movie_factory, db_session, jwt_manager
):
    movie = await movie_factory.create_movie()

    await authenticated_client.post(
        f"{BASE}/{movie.uuid}/comments/", json={"text": "Persisted comment"}
    )

    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    comment = await db_session.scalar(
        select(MovieCommentModel).where(
            MovieCommentModel.movie_id == movie.id,
            MovieCommentModel.user_id == user_id,
        )
    )
    assert comment is not None
    assert comment.text == "Persisted comment"


# ==============================================================================
# PATCH /comments/{comment_id}/
# ==============================================================================


@pytest.mark.asyncio
async def test_update_comment_success(
    authenticated_client, movie_factory, comment_factory, jwt_manager, db_session
):
    from app.database.models.accounts import UserModel

    movie = await movie_factory.create_movie()

    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user = await db_session.get(UserModel, payload["user_id"])

    comment = await comment_factory.create_comment(movie=movie, user=user)

    response = await authenticated_client.patch(
        f"{BASE}/comments/{comment.id}/",
        json={"text": "Updated professional text"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["text"] == "Updated professional text"
    assert data["user_id"] == user.id


@pytest.mark.asyncio
async def test_update_comment_not_owner(
    authenticated_client, movie_factory, comment_factory, user_factory
):
    movie = await movie_factory.create_movie()
    other_user = await user_factory.create_active_user(
        email=f"owner_{uuid.uuid4()}@test.com"
    )
    comment = await comment_factory.create_comment(movie_id=movie.id, user_id=other_user.id)

    response = await authenticated_client.patch(
        f"{BASE}/comments/{comment.id}/", json={"text": "Steal the comment"}
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_comment_not_found(authenticated_client):
    response = await authenticated_client.patch(
        f"{BASE}/comments/99999/", json={"text": "Does not exist"}
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_comment_requires_auth(client, movie_factory, comment_factory, user_factory):
    movie = await movie_factory.create_movie()
    user = await user_factory.create_active_user(email=f"noauth_{uuid.uuid4()}@test.com")
    comment = await comment_factory.create_comment(movie_id=movie.id, user_id=user.id)

    response = await client.patch(
        f"{BASE}/comments/{comment.id}/", json={"text": "No token"}
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_comment_validation_empty_text(
    authenticated_client, movie_factory, comment_factory, jwt_manager
):
    movie = await movie_factory.create_movie()
    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    comment = await comment_factory.create_comment(movie_id=movie.id, user_id=user_id)

    response = await authenticated_client.patch(
        f"{BASE}/comments/{comment.id}/", json={"text": ""}
    )

    assert response.status_code == 422


# ==============================================================================
# POST /comments/{comment_id}/like/
# ==============================================================================


@pytest.mark.asyncio
async def test_like_comment_success(
    authenticated_client, movie_factory, comment_factory, user_factory, db_session, jwt_manager
):
    movie = await movie_factory.create_movie()
    other_user = await user_factory.create_active_user(
        email=f"author_{uuid.uuid4()}@test.com"
    )
    comment = await comment_factory.create_comment(movie_id=movie.id, user_id=other_user.id)

    response = await authenticated_client.post(f"{BASE}/comments/{comment.id}/like/")

    assert response.status_code == 200
    assert response.json()["message"] == "Comment liked"

    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    like = await db_session.scalar(
        select(CommentLikeModel).where(
            CommentLikeModel.comment_id == comment.id,
            CommentLikeModel.user_id == user_id,
        )
    )
    assert like is not None


@pytest.mark.asyncio
async def test_unlike_comment_toggle(
    authenticated_client, movie_factory, comment_factory, user_factory, db_session, jwt_manager
):
    movie = await movie_factory.create_movie()
    other_user = await user_factory.create_active_user(
        email=f"author2_{uuid.uuid4()}@test.com"
    )
    comment = await comment_factory.create_comment(movie_id=movie.id, user_id=other_user.id)

    await authenticated_client.post(f"{BASE}/comments/{comment.id}/like/")
    response = await authenticated_client.post(f"{BASE}/comments/{comment.id}/like/")

    assert response.status_code == 200
    assert response.json()["message"] == "Like removed"

    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    like = await db_session.scalar(
        select(CommentLikeModel).where(
            CommentLikeModel.comment_id == comment.id,
            CommentLikeModel.user_id == user_id,
        )
    )
    assert like is None


@pytest.mark.asyncio
async def test_like_comment_not_found(authenticated_client):
    response = await authenticated_client.post(f"{BASE}/comments/99999/like/")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_like_comment_requires_auth(client, movie_factory, comment_factory, user_factory):
    movie = await movie_factory.create_movie()
    user = await user_factory.create_active_user(email=f"likeanon_{uuid.uuid4()}@test.com")
    comment = await comment_factory.create_comment(movie_id=movie.id, user_id=user.id)

    response = await client.post(f"{BASE}/comments/{comment.id}/like/")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_like_own_comment_no_notification(
    authenticated_client, movie_factory, comment_factory, db_session, jwt_manager
):
    movie = await movie_factory.create_movie()
    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    comment = await comment_factory.create_comment(movie_id=movie.id, user_id=user_id)

    await authenticated_client.post(f"{BASE}/comments/{comment.id}/like/")

    notif = await db_session.scalar(
        select(NotificationModel).where(
            NotificationModel.user_id == user_id,
            NotificationModel.notification_type == NotificationType.COMMENT_LIKE,
        )
    )
    assert notif is None


# ==============================================================================
# DELETE /comments/{comment_id}/
# ==============================================================================


@pytest.mark.asyncio
async def test_delete_own_comment_success(
    authenticated_client, movie_factory, comment_factory, db_session, jwt_manager
):
    movie = await movie_factory.create_movie()
    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    comment = await comment_factory.create_comment(movie_id=movie.id, user_id=user_id)

    response = await authenticated_client.delete(f"{BASE}/comments/{comment.id}/")

    assert response.status_code == 204

    deleted = await db_session.scalar(
        select(MovieCommentModel).where(MovieCommentModel.id == comment.id)
    )
    assert deleted is None


@pytest.mark.asyncio
async def test_delete_comment_forbidden_for_non_owner(
    authenticated_client, movie_factory, comment_factory, user_factory
):
    movie = await movie_factory.create_movie()
    other_user = await user_factory.create_active_user(
        email=f"otherowner_{uuid.uuid4()}@test.com"
    )
    comment = await comment_factory.create_comment(movie_id=movie.id, user_id=other_user.id)

    response = await authenticated_client.delete(f"{BASE}/comments/{comment.id}/")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_comment_by_admin(
    admin_client, movie_factory, comment_factory, user_factory, db_session
):
    movie = await movie_factory.create_movie()
    user = await user_factory.create_active_user(email=f"victim_{uuid.uuid4()}@test.com")
    comment = await comment_factory.create_comment(movie_id=movie.id, user_id=user.id)

    response = await admin_client.delete(f"{BASE}/comments/{comment.id}/")

    assert response.status_code == 204

    deleted = await db_session.scalar(
        select(MovieCommentModel).where(MovieCommentModel.id == comment.id)
    )
    assert deleted is None


@pytest.mark.asyncio
async def test_delete_comment_by_admin_sends_notification(
    admin_client, movie_factory, comment_factory, user_factory, db_session
):
    movie = await movie_factory.create_movie()
    user = await user_factory.create_active_user(email=f"notify_{uuid.uuid4()}@test.com")
    comment = await comment_factory.create_comment(movie_id=movie.id, user_id=user.id)

    await admin_client.delete(f"{BASE}/comments/{comment.id}/")

    notif = await db_session.scalar(
        select(NotificationModel).where(
            NotificationModel.user_id == user.id,
            NotificationModel.notification_type == NotificationType.SYSTEM,
        )
    )
    assert notif is not None


@pytest.mark.asyncio
async def test_delete_comment_not_found(authenticated_client):
    response = await authenticated_client.delete(f"{BASE}/comments/99999/")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_comment_requires_auth(client, movie_factory, comment_factory, user_factory):
    movie = await movie_factory.create_movie()
    user = await user_factory.create_active_user(email=f"delnoauth_{uuid.uuid4()}@test.com")
    comment = await comment_factory.create_comment(movie_id=movie.id, user_id=user.id)

    response = await client.delete(f"{BASE}/comments/{comment.id}/")

    assert response.status_code == 401


# ==============================================================================
# POST /{movie_uuid}/favorite/
# ==============================================================================


@pytest.mark.asyncio
async def test_add_favorite_success(authenticated_client, movie_factory, db_session, jwt_manager):
    movie = await movie_factory.create_movie()

    response = await authenticated_client.post(f"{BASE}/{movie.uuid}/favorite/")

    assert response.status_code == 201
    assert "favorite" in response.json()["message"].lower()

    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    fav = await db_session.scalar(
        select(MovieFavoriteModel).where(
            MovieFavoriteModel.user_id == user_id,
            MovieFavoriteModel.movie_id == movie.id,
        )
    )
    assert fav is not None


@pytest.mark.asyncio
async def test_add_favorite_idempotent(authenticated_client, movie_factory):
    movie = await movie_factory.create_movie()

    await authenticated_client.post(f"{BASE}/{movie.uuid}/favorite/")
    response = await authenticated_client.post(f"{BASE}/{movie.uuid}/favorite/")

    assert response.status_code == 201
    assert "already" in response.json()["message"].lower()


@pytest.mark.asyncio
async def test_add_favorite_movie_not_found(authenticated_client):
    response = await authenticated_client.post(f"{BASE}/{uuid.uuid4()}/favorite/")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_add_favorite_requires_auth(client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await client.post(f"{BASE}/{movie.uuid}/favorite/")

    assert response.status_code == 401


# ==============================================================================
# DELETE /{movie_uuid}/favorite/
# ==============================================================================


@pytest.mark.asyncio
async def test_remove_favorite_success(
    authenticated_client, movie_factory, db_session, jwt_manager
):
    movie = await movie_factory.create_movie()
    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    db_session.add(MovieFavoriteModel(user_id=user_id, movie_id=movie.id))
    await db_session.commit()

    response = await authenticated_client.delete(f"{BASE}/{movie.uuid}/favorite/")

    assert response.status_code == 200
    assert "removed" in response.json()["message"].lower()

    fav = await db_session.scalar(
        select(MovieFavoriteModel).where(
            MovieFavoriteModel.user_id == user_id,
            MovieFavoriteModel.movie_id == movie.id,
        )
    )
    assert fav is None


@pytest.mark.asyncio
async def test_remove_favorite_not_in_favorites(authenticated_client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await authenticated_client.delete(f"{BASE}/{movie.uuid}/favorite/")

    assert response.status_code == 404
    assert "not in favorites" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_remove_favorite_movie_not_found(authenticated_client):
    response = await authenticated_client.delete(f"{BASE}/{uuid.uuid4()}/favorite/")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_remove_favorite_requires_auth(client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await client.delete(f"{BASE}/{movie.uuid}/favorite/")

    assert response.status_code == 401


# ==============================================================================
# POST /{movie_uuid}/rating/
# ==============================================================================


@pytest.mark.asyncio
async def test_rate_movie_success(authenticated_client, movie_factory, db_session, jwt_manager):
    movie = await movie_factory.create_movie()

    response = await authenticated_client.post(
        f"{BASE}/{movie.uuid}/rating/", json={"score": 8}
    )

    assert response.status_code == 200
    assert "rated" in response.json()["message"].lower()

    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    rating = await db_session.scalar(
        select(MovieRatingModel).where(
            MovieRatingModel.user_id == user_id,
            MovieRatingModel.movie_id == movie.id,
        )
    )
    assert rating is not None
    assert rating.score == 8


@pytest.mark.asyncio
async def test_rate_movie_update_existing(
    authenticated_client, movie_factory, db_session, jwt_manager
):
    movie = await movie_factory.create_movie()

    await authenticated_client.post(
        f"{BASE}/{movie.uuid}/rating/", json={"score": 5}
    )
    response = await authenticated_client.post(
        f"{BASE}/{movie.uuid}/rating/", json={"score": 9}
    )

    assert response.status_code == 200
    assert "updated" in response.json()["message"].lower()

    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    rating = await db_session.scalar(
        select(MovieRatingModel).where(
            MovieRatingModel.user_id == user_id,
            MovieRatingModel.movie_id == movie.id,
        )
    )
    assert rating.score == 9


@pytest.mark.asyncio
async def test_rate_movie_score_out_of_range(authenticated_client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await authenticated_client.post(
        f"{BASE}/{movie.uuid}/rating/", json={"score": 11}
    )
    assert response.status_code == 422

    response = await authenticated_client.post(
        f"{BASE}/{movie.uuid}/rating/", json={"score": 0}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_rate_movie_not_found(authenticated_client):
    response = await authenticated_client.post(
        f"{BASE}/{uuid.uuid4()}/rating/", json={"score": 7}
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rate_movie_requires_auth(client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await client.post(f"{BASE}/{movie.uuid}/rating/", json={"score": 7})

    assert response.status_code == 401


# ==============================================================================
# DELETE /{movie_uuid}/rating/
# ==============================================================================


@pytest.mark.asyncio
async def test_remove_rating_success(
    authenticated_client, movie_factory, db_session, jwt_manager
):
    movie = await movie_factory.create_movie()
    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    db_session.add(MovieRatingModel(user_id=user_id, movie_id=movie.id, score=7))
    await db_session.commit()

    response = await authenticated_client.delete(f"{BASE}/{movie.uuid}/rating/")

    assert response.status_code == 204

    rating = await db_session.scalar(
        select(MovieRatingModel).where(
            MovieRatingModel.user_id == user_id,
            MovieRatingModel.movie_id == movie.id,
        )
    )
    assert rating is None


@pytest.mark.asyncio
async def test_remove_rating_not_found(authenticated_client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await authenticated_client.delete(f"{BASE}/{movie.uuid}/rating/")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_remove_rating_movie_not_found(authenticated_client):
    response = await authenticated_client.delete(f"{BASE}/{uuid.uuid4()}/rating/")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_remove_rating_requires_auth(client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await client.delete(f"{BASE}/{movie.uuid}/rating/")

    assert response.status_code == 401


# ==============================================================================
# POST /{movie_uuid}/vote/
# ==============================================================================


@pytest.mark.asyncio
async def test_vote_movie_like(authenticated_client, movie_factory, db_session, jwt_manager):
    movie = await movie_factory.create_movie()

    response = await authenticated_client.post(
        f"{BASE}/{movie.uuid}/vote/", json={"is_like": True}
    )

    assert response.status_code == 200
    assert "cast" in response.json()["message"].lower()

    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    vote = await db_session.scalar(
        select(MovieVoteModel).where(
            MovieVoteModel.user_id == user_id,
            MovieVoteModel.movie_id == movie.id,
        )
    )
    assert vote is not None
    assert vote.is_like is True


@pytest.mark.asyncio
async def test_vote_movie_dislike(authenticated_client, movie_factory, db_session, jwt_manager):
    movie = await movie_factory.create_movie()

    response = await authenticated_client.post(
        f"{BASE}/{movie.uuid}/vote/", json={"is_like": False}
    )

    assert response.status_code == 200

    token = authenticated_client.headers["Authorization"].split(" ")[1]
    payload = jwt_manager.decode_access_token(token)
    user_id = payload["user_id"]

    vote = await db_session.scalar(
        select(MovieVoteModel).where(
            MovieVoteModel.user_id == user_id,
            MovieVoteModel.movie_id == movie.id,
        )
    )
    assert vote.is_like is False


@pytest.mark.asyncio
async def test_vote_movie_increments_votes_counter(
    authenticated_client, movie_factory, db_session, jwt_manager
):
    from sqlalchemy import select as sa_select
    from app.database.models.movies import MovieModel

    movie = await movie_factory.create_movie(votes=0)
    initial_votes = movie.votes

    await authenticated_client.post(
        f"{BASE}/{movie.uuid}/vote/", json={"is_like": True}
    )

    await db_session.refresh(movie)
    assert movie.votes == initial_votes + 1


@pytest.mark.asyncio
async def test_vote_movie_update_does_not_increment_counter(
    authenticated_client, movie_factory, db_session, jwt_manager
):
    movie = await movie_factory.create_movie(votes=0)

    await authenticated_client.post(f"{BASE}/{movie.uuid}/vote/", json={"is_like": True})
    await db_session.refresh(movie)
    votes_after_first = movie.votes

    response = await authenticated_client.post(
        f"{BASE}/{movie.uuid}/vote/", json={"is_like": False}
    )
    assert response.status_code == 200
    assert "updated" in response.json()["message"].lower()

    await db_session.refresh(movie)
    assert movie.votes == votes_after_first  # no extra increment


@pytest.mark.asyncio
async def test_vote_movie_not_found(authenticated_client):
    response = await authenticated_client.post(
        f"{BASE}/{uuid.uuid4()}/vote/", json={"is_like": True}
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_vote_movie_requires_auth(client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await client.post(f"{BASE}/{movie.uuid}/vote/", json={"is_like": True})

    assert response.status_code == 401
