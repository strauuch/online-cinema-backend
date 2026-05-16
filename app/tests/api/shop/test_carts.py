import pytest
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database.models.carts import CartModel, CartItemModel
from app.database.models.orders import OrderModel, OrderItemModel
from app.database.models.enums import OrderStatusEnum

BASE = "/api/v1/cart"
ADMIN_BASE = "/api/v1/cart/admin/carts"


# ==============================================================================
# Helpers
# ==============================================================================


async def get_or_create_cart(db_session, user_id: int) -> CartModel:
    cart = await db_session.scalar(
        select(CartModel).where(CartModel.user_id == user_id)
    )
    if not cart:
        cart = CartModel(user_id=user_id)
        db_session.add(cart)
        await db_session.commit()
        await db_session.refresh(cart)
    return cart


# ==============================================================================
# GET / — Get user cart
# ==============================================================================


@pytest.mark.asyncio
async def test_get_cart_success(authenticated_client, db_session):
    await get_or_create_cart(db_session, authenticated_client.user.id)

    response = await authenticated_client.get(f"{BASE}/")

    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert "items" in data
    assert "total_price" in data


@pytest.mark.asyncio
async def test_get_cart_empty(authenticated_client, db_session):
    await get_or_create_cart(db_session, authenticated_client.user.id)

    response = await authenticated_client.get(f"{BASE}/")

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert Decimal(data["total_price"]) == Decimal("0.00")


@pytest.mark.asyncio
async def test_get_cart_with_items(authenticated_client, db_session, movie_factory):
    cart = await get_or_create_cart(db_session, authenticated_client.user.id)
    movie = await movie_factory.create_movie(price=Decimal("9.99"))
    db_session.add(CartItemModel(cart_id=cart.id, movie_id=movie.id))
    await db_session.commit()

    response = await authenticated_client.get(f"{BASE}/")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert Decimal(data["total_price"]) == Decimal("9.99")


@pytest.mark.asyncio
async def test_get_cart_requires_auth(client):
    response = await client.get(f"{BASE}/")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_cart_total_sums_all_items(authenticated_client, db_session, movie_factory):
    cart = await get_or_create_cart(db_session, authenticated_client.user.id)
    m1 = await movie_factory.create_movie(price=Decimal("5.00"))
    m2 = await movie_factory.create_movie(price=Decimal("7.50"))
    db_session.add(CartItemModel(cart_id=cart.id, movie_id=m1.id))
    db_session.add(CartItemModel(cart_id=cart.id, movie_id=m2.id))
    await db_session.commit()

    response = await authenticated_client.get(f"{BASE}/")

    assert response.status_code == 200
    assert Decimal(response.json()["total_price"]) == Decimal("12.50")


@pytest.mark.asyncio
async def test_get_cart_db_error(authenticated_client, db_session, monkeypatch):
    await get_or_create_cart(db_session, authenticated_client.user.id)

    async def fake_execute(*args, **kwargs):
        raise SQLAlchemyError("DB failure")

    monkeypatch.setattr(db_session, "execute", fake_execute)

    response = await authenticated_client.get(f"{BASE}/")

    assert response.status_code == 500


# ==============================================================================
# POST /add/{movie_id} — Add movie to cart
# ==============================================================================


@pytest.mark.asyncio
async def test_add_to_cart_success(authenticated_client, db_session, movie_factory):
    await get_or_create_cart(db_session, authenticated_client.user.id)
    movie = await movie_factory.create_movie()

    response = await authenticated_client.post(f"{BASE}/add/{movie.id}")

    assert response.status_code == 201
    data = response.json()
    assert data["movie_id"] == movie.id
    assert "cart_id" in data

    cart = await get_or_create_cart(db_session, authenticated_client.user.id)
    item = await db_session.scalar(
        select(CartItemModel).where(
            CartItemModel.cart_id == cart.id,
            CartItemModel.movie_id == movie.id,
        )
    )
    assert item is not None


@pytest.mark.asyncio
async def test_add_to_cart_movie_not_found(authenticated_client, db_session):
    await get_or_create_cart(db_session, authenticated_client.user.id)

    response = await authenticated_client.post(f"{BASE}/add/99999")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_add_to_cart_duplicate_returns_400(
    authenticated_client, db_session, movie_factory
):
    await get_or_create_cart(db_session, authenticated_client.user.id)
    movie = await movie_factory.create_movie()

    await authenticated_client.post(f"{BASE}/add/{movie.id}")
    response = await authenticated_client.post(f"{BASE}/add/{movie.id}")

    assert response.status_code == 400
    assert "already" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_add_to_cart_already_purchased(
    authenticated_client, db_session, movie_factory
):
    await get_or_create_cart(db_session, authenticated_client.user.id)
    movie = await movie_factory.create_movie()

    order = OrderModel(
        user_id=authenticated_client.user.id,
        status=OrderStatusEnum.PAID,
        total_amount=movie.price,
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItemModel(
            order_id=order.id, movie_id=movie.id, price_at_order=movie.price
        )
    )
    await db_session.commit()

    response = await authenticated_client.post(f"{BASE}/add/{movie.id}")

    assert response.status_code == 400
    assert "purchased" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_add_to_cart_requires_auth(client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await client.post(f"{BASE}/add/{movie.id}")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_add_to_cart_deleted_movie(authenticated_client, db_session, movie_factory):
    await get_or_create_cart(db_session, authenticated_client.user.id)
    movie = await movie_factory.create_movie()
    movie.is_deleted = True
    await db_session.commit()

    response = await authenticated_client.post(f"{BASE}/add/{movie.id}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_add_to_cart_db_error(authenticated_client, db_session, movie_factory, monkeypatch):
    await get_or_create_cart(db_session, authenticated_client.user.id)
    movie = await movie_factory.create_movie()

    async def fake_commit(*args, **kwargs):
        raise SQLAlchemyError("DB failure")

    monkeypatch.setattr(db_session, "commit", fake_commit)

    response = await authenticated_client.post(f"{BASE}/add/{movie.id}")

    assert response.status_code == 500


# ==============================================================================
# DELETE /item/{movie_id} — Remove movie from cart
# ==============================================================================


@pytest.mark.asyncio
async def test_remove_from_cart_success(authenticated_client, db_session, movie_factory):
    cart = await get_or_create_cart(db_session, authenticated_client.user.id)
    movie = await movie_factory.create_movie()
    db_session.add(CartItemModel(cart_id=cart.id, movie_id=movie.id))
    await db_session.commit()

    response = await authenticated_client.delete(f"{BASE}/item/{movie.id}")

    assert response.status_code == 200
    assert "removed" in response.json()["message"].lower()

    item = await db_session.scalar(
        select(CartItemModel).where(
            CartItemModel.cart_id == cart.id,
            CartItemModel.movie_id == movie.id,
        )
    )
    assert item is None


@pytest.mark.asyncio
async def test_remove_from_cart_not_in_cart(authenticated_client, db_session, movie_factory):
    await get_or_create_cart(db_session, authenticated_client.user.id)
    movie = await movie_factory.create_movie()

    response = await authenticated_client.delete(f"{BASE}/item/{movie.id}")

    assert response.status_code == 404
    assert "not in your cart" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_remove_from_cart_requires_auth(client, movie_factory):
    movie = await movie_factory.create_movie()

    response = await client.delete(f"{BASE}/item/{movie.id}")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_remove_from_cart_db_error(
    authenticated_client, db_session, movie_factory, monkeypatch
):
    cart = await get_or_create_cart(db_session, authenticated_client.user.id)
    movie = await movie_factory.create_movie()
    db_session.add(CartItemModel(cart_id=cart.id, movie_id=movie.id))
    await db_session.commit()

    async def fake_commit(*args, **kwargs):
        raise SQLAlchemyError("DB failure")

    monkeypatch.setattr(db_session, "commit", fake_commit)

    response = await authenticated_client.delete(f"{BASE}/item/{movie.id}")

    assert response.status_code == 500


# ==============================================================================
# DELETE /clear — Clear entire cart
# ==============================================================================


@pytest.mark.asyncio
async def test_clear_cart_success(authenticated_client, db_session, movie_factory):
    cart = await get_or_create_cart(db_session, authenticated_client.user.id)
    m1 = await movie_factory.create_movie()
    m2 = await movie_factory.create_movie()
    db_session.add(CartItemModel(cart_id=cart.id, movie_id=m1.id))
    db_session.add(CartItemModel(cart_id=cart.id, movie_id=m2.id))
    await db_session.commit()

    response = await authenticated_client.delete(f"{BASE}/clear")

    assert response.status_code == 200
    assert "removed" in response.json()["message"].lower()

    items = (
        await db_session.execute(
            select(CartItemModel).where(CartItemModel.cart_id == cart.id)
        )
    ).scalars().all()
    assert items == []


@pytest.mark.asyncio
async def test_clear_cart_already_empty(authenticated_client, db_session):
    await get_or_create_cart(db_session, authenticated_client.user.id)

    response = await authenticated_client.delete(f"{BASE}/clear")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_clear_cart_requires_auth(client):
    response = await client.delete(f"{BASE}/clear")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_clear_cart_db_error(authenticated_client, db_session, monkeypatch):
    await get_or_create_cart(db_session, authenticated_client.user.id)

    async def fake_commit(*args, **kwargs):
        raise SQLAlchemyError("DB failure")

    monkeypatch.setattr(db_session, "commit", fake_commit)

    response = await authenticated_client.delete(f"{BASE}/clear")

    assert response.status_code == 500


# ==============================================================================
# GET /admin/carts/{user_id} — Admin view of any user's cart
# ==============================================================================


@pytest.mark.asyncio
async def test_admin_get_user_cart_success(admin_client, db_session, user_factory, movie_factory):
    user = await user_factory.create_active_user()
    cart = await get_or_create_cart(db_session, user.id)
    movie = await movie_factory.create_movie()
    db_session.add(CartItemModel(cart_id=cart.id, movie_id=movie.id))
    await db_session.commit()

    response = await admin_client.get(f"{ADMIN_BASE}/{user.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == user.id
    assert len(data["items"]) == 1


@pytest.mark.asyncio
async def test_admin_get_user_cart_not_found(admin_client):
    response = await admin_client.get(f"{ADMIN_BASE}/99999")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_admin_get_user_cart_unauthorized(client, user_factory, db_session):
    user = await user_factory.create_active_user()
    await get_or_create_cart(db_session, user.id)

    response = await client.get(f"{ADMIN_BASE}/{user.id}")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_get_user_cart_forbidden_regular_user(
    authenticated_client, user_factory, db_session
):
    user = await user_factory.create_active_user()
    await get_or_create_cart(db_session, user.id)

    response = await authenticated_client.get(f"{ADMIN_BASE}/{user.id}")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_get_user_cart_empty(admin_client, user_factory, db_session):
    user = await user_factory.create_active_user()
    await get_or_create_cart(db_session, user.id)

    response = await admin_client.get(f"{ADMIN_BASE}/{user.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert Decimal(data["total_price"]) == Decimal("0.00")
