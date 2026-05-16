import pytest
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from unittest.mock import patch, MagicMock

from app.database.models.carts import CartModel, CartItemModel
from app.database.models.orders import OrderModel, OrderItemModel
from app.database.models.enums import OrderStatusEnum

BASE = "/api/v1/order"
ADMIN_BASE = "/api/v1/order/admin/"


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


async def add_movie_to_cart(db_session, cart: CartModel, movie) -> CartItemModel:
    item = CartItemModel(cart_id=cart.id, movie_id=movie.id)
    db_session.add(item)
    await db_session.commit()
    return item


async def create_order_for_user(db_session, user_id: int, movie, status=OrderStatusEnum.PENDING) -> OrderModel:
    order = OrderModel(
        user_id=user_id,
        status=status,
        total_amount=movie.price,
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItemModel(order_id=order.id, movie_id=movie.id, price_at_order=movie.price)
    )
    await db_session.commit()
    await db_session.refresh(order)
    return order


# ==============================================================================
# POST / — Create order from cart
# ==============================================================================


@pytest.mark.asyncio
async def test_create_order_success(authenticated_client, db_session, movie_factory):
    cart = await get_or_create_cart(db_session, authenticated_client.user.id)
    movie = await movie_factory.create_movie(price=Decimal("14.99"))
    await add_movie_to_cart(db_session, cart, movie)

    response = await authenticated_client.post(f"{BASE}/")

    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert Decimal(data["total_amount"]) == Decimal("14.99")
    assert data["status"] == OrderStatusEnum.PENDING.value


@pytest.mark.asyncio
async def test_create_order_clears_cart(authenticated_client, db_session, movie_factory):
    cart = await get_or_create_cart(db_session, authenticated_client.user.id)
    movie = await movie_factory.create_movie()
    await add_movie_to_cart(db_session, cart, movie)

    await authenticated_client.post(f"{BASE}/")

    items = (
        await db_session.execute(
            select(CartItemModel).where(CartItemModel.cart_id == cart.id)
        )
    ).scalars().all()
    assert items == []


@pytest.mark.asyncio
async def test_create_order_persists_to_db(authenticated_client, db_session, movie_factory):
    cart = await get_or_create_cart(db_session, authenticated_client.user.id)
    movie = await movie_factory.create_movie()
    await add_movie_to_cart(db_session, cart, movie)

    response = await authenticated_client.post(f"{BASE}/")

    order_id = response.json()["id"]
    order = await db_session.scalar(select(OrderModel).where(OrderModel.id == order_id))
    assert order is not None
    assert order.user_id == authenticated_client.user.id


@pytest.mark.asyncio
async def test_create_order_snapshots_item_prices(authenticated_client, db_session, movie_factory):
    cart = await get_or_create_cart(db_session, authenticated_client.user.id)
    movie = await movie_factory.create_movie(price=Decimal("19.99"))
    await add_movie_to_cart(db_session, cart, movie)

    response = await authenticated_client.post(f"{BASE}/")

    order_id = response.json()["id"]
    item = await db_session.scalar(
        select(OrderItemModel).where(OrderItemModel.order_id == order_id)
    )
    assert item is not None
    assert item.price_at_order == Decimal("19.99")


@pytest.mark.asyncio
async def test_create_order_empty_cart_returns_400(authenticated_client, db_session):
    await get_or_create_cart(db_session, authenticated_client.user.id)

    response = await authenticated_client.post(f"{BASE}/")

    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_order_multiple_items(authenticated_client, db_session, movie_factory):
    cart = await get_or_create_cart(db_session, authenticated_client.user.id)
    m1 = await movie_factory.create_movie(price=Decimal("5.00"))
    m2 = await movie_factory.create_movie(price=Decimal("10.00"))
    await add_movie_to_cart(db_session, cart, m1)
    await add_movie_to_cart(db_session, cart, m2)

    response = await authenticated_client.post(f"{BASE}/")

    assert response.status_code == 201
    assert Decimal(response.json()["total_amount"]) == Decimal("15.00")


@pytest.mark.asyncio
async def test_create_order_requires_auth(client):
    response = await client.post(f"{BASE}/")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_order_db_error(authenticated_client, db_session, movie_factory, monkeypatch):
    cart = await get_or_create_cart(db_session, authenticated_client.user.id)
    movie = await movie_factory.create_movie()
    await add_movie_to_cart(db_session, cart, movie)

    async def fake_commit(*args, **kwargs):
        raise SQLAlchemyError("DB failure")

    monkeypatch.setattr(db_session, "commit", fake_commit)

    response = await authenticated_client.post(f"{BASE}/")

    assert response.status_code == 500


# ==============================================================================
# GET / — Get paginated order history
# ==============================================================================


@pytest.mark.asyncio
async def test_get_order_history_success(authenticated_client, db_session, movie_factory):
    movie = await movie_factory.create_movie()
    await create_order_for_user(db_session, authenticated_client.user.id, movie)

    response = await authenticated_client.get(f"{BASE}/")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_get_order_history_empty(authenticated_client, db_session):
    response = await authenticated_client.get(f"{BASE}/")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_get_order_history_pagination(authenticated_client, db_session, movie_factory):
    movie = await movie_factory.create_movie()
    for _ in range(5):
        await create_order_for_user(db_session, authenticated_client.user.id, movie)

    response = await authenticated_client.get(f"{BASE}/?page=1&size=3")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 3
    assert data["page"] == 1
    assert data["size"] == 3


@pytest.mark.asyncio
async def test_get_order_history_only_own_orders(
    authenticated_client, db_session, movie_factory, user_factory
):
    other_user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    await create_order_for_user(db_session, other_user.id, movie)

    response = await authenticated_client.get(f"{BASE}/")

    assert response.status_code == 200
    assert response.json()["total"] == 0


@pytest.mark.asyncio
async def test_get_order_history_requires_auth(client):
    response = await client.get(f"{BASE}/")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_order_history_response_shape(authenticated_client, db_session, movie_factory):
    movie = await movie_factory.create_movie()
    await create_order_for_user(db_session, authenticated_client.user.id, movie)

    response = await authenticated_client.get(f"{BASE}/")

    item = response.json()["items"][0]
    for field in ("id", "status", "total_amount", "created_at", "items"):
        assert field in item, f"Missing field: {field}"


# ==============================================================================
# GET /{order_id} — Get specific order details
# ==============================================================================


@pytest.mark.asyncio
async def test_get_order_details_success(authenticated_client, db_session, movie_factory):
    movie = await movie_factory.create_movie()
    order = await create_order_for_user(db_session, authenticated_client.user.id, movie)

    response = await authenticated_client.get(f"{BASE}/{order.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == order.id
    assert len(data["items"]) == 1


@pytest.mark.asyncio
async def test_get_order_details_not_found(authenticated_client):
    response = await authenticated_client.get(f"{BASE}/99999")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_order_details_other_user_order(
    authenticated_client, db_session, movie_factory, user_factory
):
    other_user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    order = await create_order_for_user(db_session, other_user.id, movie)

    response = await authenticated_client.get(f"{BASE}/{order.id}")

    # Treated as not found since ownership check is applied
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_order_details_requires_auth(client, db_session, movie_factory, user_factory):
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    order = await create_order_for_user(db_session, user.id, movie)

    response = await client.get(f"{BASE}/{order.id}")

    assert response.status_code == 401


# ==============================================================================
# POST /{order_id}/cancel — Cancel a pending order
# ==============================================================================


@pytest.mark.asyncio
async def test_cancel_order_success(authenticated_client, db_session, movie_factory):
    movie = await movie_factory.create_movie()
    order = await create_order_for_user(db_session, authenticated_client.user.id, movie)

    with patch("stripe.checkout.Session.list") as mock_stripe:
        mock_stripe.return_value = MagicMock(data=[])
        response = await authenticated_client.post(f"{BASE}/{order.id}/cancel")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == OrderStatusEnum.CANCELED.value

    await db_session.refresh(order)
    assert order.status == OrderStatusEnum.CANCELED


@pytest.mark.asyncio
async def test_cancel_order_not_found(authenticated_client):
    with patch("stripe.checkout.Session.list") as mock_stripe:
        mock_stripe.return_value = MagicMock(data=[])
        response = await authenticated_client.post(f"{BASE}/99999/cancel")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cancel_order_already_paid(authenticated_client, db_session, movie_factory):
    movie = await movie_factory.create_movie()
    order = await create_order_for_user(
        db_session, authenticated_client.user.id, movie, status=OrderStatusEnum.PAID
    )

    with patch("stripe.checkout.Session.list") as mock_stripe:
        mock_stripe.return_value = MagicMock(data=[])
        response = await authenticated_client.post(f"{BASE}/{order.id}/cancel")

    assert response.status_code == 400
    assert "cannot cancel" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cancel_order_already_canceled(authenticated_client, db_session, movie_factory):
    movie = await movie_factory.create_movie()
    order = await create_order_for_user(
        db_session, authenticated_client.user.id, movie, status=OrderStatusEnum.CANCELED
    )

    with patch("stripe.checkout.Session.list") as mock_stripe:
        mock_stripe.return_value = MagicMock(data=[])
        response = await authenticated_client.post(f"{BASE}/{order.id}/cancel")

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_cancel_order_other_user(
    authenticated_client, db_session, movie_factory, user_factory
):
    other_user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    order = await create_order_for_user(db_session, other_user.id, movie)

    with patch("stripe.checkout.Session.list") as mock_stripe:
        mock_stripe.return_value = MagicMock(data=[])
        response = await authenticated_client.post(f"{BASE}/{order.id}/cancel")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cancel_order_requires_auth(client, db_session, movie_factory, user_factory):
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    order = await create_order_for_user(db_session, user.id, movie)

    response = await client.post(f"{BASE}/{order.id}/cancel")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_cancel_order_db_error(
    authenticated_client, db_session, movie_factory, monkeypatch
):
    movie = await movie_factory.create_movie()
    order = await create_order_for_user(db_session, authenticated_client.user.id, movie)

    async def fake_commit(*args, **kwargs):
        raise SQLAlchemyError("DB failure")

    monkeypatch.setattr(db_session, "commit", fake_commit)

    with patch("stripe.checkout.Session.list") as mock_stripe:
        mock_stripe.return_value = MagicMock(data=[])
        response = await authenticated_client.post(f"{BASE}/{order.id}/cancel")

    assert response.status_code == 500


# ==============================================================================
# GET / (admin) — Get all orders with filters [Admin]
# ==============================================================================


@pytest.mark.asyncio
async def test_admin_get_all_orders_success(admin_client, db_session, movie_factory, user_factory):
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    await create_order_for_user(db_session, user.id, movie)

    response = await admin_client.get(f"{ADMIN_BASE}orders/")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_admin_get_all_orders_filter_by_user(
    admin_client, db_session, movie_factory, user_factory
):
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    await create_order_for_user(db_session, user.id, movie)

    response = await admin_client.get(f"{ADMIN_BASE}orders/?user_id={user.id}")

    assert response.status_code == 200
    data = response.json()
    assert all(item["user"]["id"] == user.id for item in data["items"])


@pytest.mark.asyncio
async def test_admin_get_all_orders_filter_by_status(
    admin_client, db_session, movie_factory, user_factory
):
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    await create_order_for_user(db_session, user.id, movie, status=OrderStatusEnum.PAID)
    await create_order_for_user(db_session, user.id, movie, status=OrderStatusEnum.PENDING)

    response = await admin_client.get(f"{ADMIN_BASE}orders/?order_status=paid")

    assert response.status_code == 200
    data = response.json()
    assert all(item["status"] == OrderStatusEnum.PAID.value for item in data["items"])


@pytest.mark.asyncio
async def test_admin_get_all_orders_filter_by_date_range(
    admin_client, db_session, movie_factory, user_factory
):
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    await create_order_for_user(db_session, user.id, movie)

    response = await admin_client.get(
        f"{ADMIN_BASE}orders/?date_from=2020-01-01&date_to=2099-12-31"
    )

    assert response.status_code == 200
    assert response.json()["total"] >= 1


@pytest.mark.asyncio
async def test_admin_get_all_orders_pagination(
    admin_client, db_session, movie_factory, user_factory
):
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    for _ in range(5):
        await create_order_for_user(db_session, user.id, movie)

    response = await admin_client.get(f"{ADMIN_BASE}orders/?page=1&size=3")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) <= 3


@pytest.mark.asyncio
async def test_admin_get_all_orders_unauthorized(client):
    response = await client.get(f"{ADMIN_BASE}orders/")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_get_all_orders_forbidden_regular_user(authenticated_client):
    response = await authenticated_client.get(f"{ADMIN_BASE}orders/")

    assert response.status_code == 403