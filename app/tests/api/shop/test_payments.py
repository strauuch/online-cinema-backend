import json
import pytest
import hashlib
import hmac
import time
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from unittest.mock import patch, MagicMock, AsyncMock

from app.database.models.carts import CartModel
from app.database.models.orders import OrderModel, OrderItemModel
from app.database.models.payments import PaymentModel, PaymentItemModel
from app.database.models.enums import OrderStatusEnum, PaymentStatusEnum

BASE = "/api/v1/payment"


# ==============================================================================
# Helpers
# ==============================================================================


async def create_order(
    db_session, user_id: int, movie, status=OrderStatusEnum.PENDING
) -> OrderModel:
    order = OrderModel(user_id=user_id, status=status, total_amount=movie.price)
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItemModel(order_id=order.id, movie_id=movie.id, price_at_order=movie.price)
    )
    await db_session.commit()
    await db_session.refresh(order, ["items"])
    return order


async def create_payment(db_session, user_id: int, order: OrderModel) -> PaymentModel:
    payment = PaymentModel(
        user_id=user_id,
        order_id=order.id,
        status=PaymentStatusEnum.SUCCESSFUL,
        amount=order.total_amount,
        external_payment_id="test_session_abc",
    )
    db_session.add(payment)
    await db_session.flush()

    item = await db_session.scalar(
        select(OrderItemModel).where(OrderItemModel.order_id == order.id)
    )
    if item:
        db_session.add(
            PaymentItemModel(
                payment_id=payment.id,
                order_item_id=item.id,
                price_at_payment=item.price_at_order,
            )
        )
    await db_session.commit()
    await db_session.refresh(payment)
    return payment


def build_stripe_webhook_payload(
    event_type: str,
    order_id: int,
    amount_cents: int,
    session_id: str = "cs_test_abc123",
) -> dict:
    return {
        "type": event_type,
        "data": {
            "object": {
                "id": session_id,
                "amount_total": amount_cents,
                "metadata": {"order_id": str(order_id)},
                "status": "complete",
            }
        },
    }


# ==============================================================================
# POST /create-session/{order_id} — Create Stripe checkout session
# ==============================================================================


@pytest.mark.asyncio
async def test_create_payment_session_success(
    authenticated_client, db_session, movie_factory
):
    movie = await movie_factory.create_movie(price=Decimal("9.99"))
    order = await create_order(db_session, authenticated_client.user.id, movie)

    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/pay/test"
    mock_session.id = "cs_test_abc"

    with patch("stripe.checkout.Session.create", return_value=mock_session):
        response = await authenticated_client.post(f"{BASE}/create-session/{order.id}")

    assert response.status_code == 201
    data = response.json()
    assert "checkout_url" in data
    assert "session_id" in data
    assert data["checkout_url"] == "https://checkout.stripe.com/pay/test"


@pytest.mark.asyncio
async def test_create_payment_session_order_not_found(authenticated_client):
    with patch("stripe.checkout.Session.create"):
        response = await authenticated_client.post(f"{BASE}/create-session/99999")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_payment_session_order_not_pending(
    authenticated_client, db_session, movie_factory
):
    movie = await movie_factory.create_movie()
    order = await create_order(
        db_session, authenticated_client.user.id, movie, status=OrderStatusEnum.PAID
    )

    with patch("stripe.checkout.Session.create"):
        response = await authenticated_client.post(f"{BASE}/create-session/{order.id}")

    assert response.status_code == 400
    assert "status" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_payment_session_other_user_order(
    authenticated_client, db_session, movie_factory, user_factory
):
    other_user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    order = await create_order(db_session, other_user.id, movie)

    with patch("stripe.checkout.Session.create"):
        response = await authenticated_client.post(f"{BASE}/create-session/{order.id}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_payment_session_stripe_error(
    authenticated_client, db_session, movie_factory
):
    import stripe as stripe_module

    movie = await movie_factory.create_movie()
    order = await create_order(db_session, authenticated_client.user.id, movie)

    with patch(
        "stripe.checkout.Session.create",
        side_effect=stripe_module.error.StripeError("Stripe unavailable"),
    ):
        response = await authenticated_client.post(f"{BASE}/create-session/{order.id}")

    assert response.status_code == 502
    assert "payment provider" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_payment_session_requires_auth(
    client, db_session, movie_factory, user_factory
):
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    order = await create_order(db_session, user.id, movie)

    response = await client.post(f"{BASE}/create-session/{order.id}")

    assert response.status_code == 401


# ==============================================================================
# GET /history — Get user payment history
# ==============================================================================


@pytest.mark.asyncio
async def test_get_payment_history_success(
    authenticated_client, db_session, movie_factory
):
    movie = await movie_factory.create_movie()
    order = await create_order(
        db_session, authenticated_client.user.id, movie, status=OrderStatusEnum.PAID
    )
    await create_payment(db_session, authenticated_client.user.id, order)

    response = await authenticated_client.get(f"{BASE}/history")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_get_payment_history_empty(authenticated_client):
    response = await authenticated_client.get(f"{BASE}/history")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_get_payment_history_pagination(
    authenticated_client, db_session, movie_factory
):
    movie = await movie_factory.create_movie()
    for _ in range(5):
        order = await create_order(
            db_session, authenticated_client.user.id, movie, status=OrderStatusEnum.PAID
        )
        await create_payment(db_session, authenticated_client.user.id, order)

    response = await authenticated_client.get(f"{BASE}/history?page=1&size=3")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 3
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_get_payment_history_only_own(
    authenticated_client, db_session, movie_factory, user_factory
):
    other_user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    order = await create_order(
        db_session, other_user.id, movie, status=OrderStatusEnum.PAID
    )
    await create_payment(db_session, other_user.id, order)

    response = await authenticated_client.get(f"{BASE}/history")

    assert response.status_code == 200
    assert response.json()["total"] == 0


@pytest.mark.asyncio
async def test_get_payment_history_response_shape(
    authenticated_client, db_session, movie_factory
):
    movie = await movie_factory.create_movie()
    order = await create_order(
        db_session, authenticated_client.user.id, movie, status=OrderStatusEnum.PAID
    )
    await create_payment(db_session, authenticated_client.user.id, order)

    response = await authenticated_client.get(f"{BASE}/history")

    item = response.json()["items"][0]
    for field in ("id", "status", "amount", "created_at"):
        assert field in item, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_get_payment_history_requires_auth(client):
    response = await client.get(f"{BASE}/history")

    assert response.status_code == 401


# ==============================================================================
# GET /admin/payments/ — Admin view of all payments
# ==============================================================================


@pytest.mark.asyncio
async def test_admin_get_all_payments_success(
    admin_client, db_session, movie_factory, user_factory
):
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    order = await create_order(db_session, user.id, movie, status=OrderStatusEnum.PAID)
    await create_payment(db_session, user.id, order)

    response = await admin_client.get(f"{BASE}/admin/payments/")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_admin_get_all_payments_filter_by_user(
    admin_client, db_session, movie_factory, user_factory
):
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    order = await create_order(db_session, user.id, movie, status=OrderStatusEnum.PAID)
    await create_payment(db_session, user.id, order)

    response = await admin_client.get(f"{BASE}/admin/payments/?user_id={user.id}")

    assert response.status_code == 200
    data = response.json()
    assert all(item["user"]["id"] == user.id for item in data["items"])


@pytest.mark.asyncio
async def test_admin_get_all_payments_filter_by_status(
    admin_client, db_session, movie_factory, user_factory
):
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    order = await create_order(db_session, user.id, movie, status=OrderStatusEnum.PAID)
    await create_payment(db_session, user.id, order)

    response = await admin_client.get(f"{BASE}/admin/payments/?status=successful")

    assert response.status_code == 200
    data = response.json()
    assert all(
        item["status"] == PaymentStatusEnum.SUCCESSFUL.value for item in data["items"]
    )


@pytest.mark.asyncio
async def test_admin_get_all_payments_filter_by_date_range(
    admin_client, db_session, movie_factory, user_factory
):
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    order = await create_order(db_session, user.id, movie, status=OrderStatusEnum.PAID)
    await create_payment(db_session, user.id, order)

    response = await admin_client.get(
        f"{BASE}/admin/payments/?date_from=2020-01-01&date_to=2099-12-31"
    )

    assert response.status_code == 200
    assert response.json()["total"] >= 1


@pytest.mark.asyncio
async def test_admin_get_all_payments_pagination(
    admin_client, db_session, movie_factory, user_factory
):
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    for _ in range(5):
        order = await create_order(
            db_session, user.id, movie, status=OrderStatusEnum.PAID
        )
        await create_payment(db_session, user.id, order)

    response = await admin_client.get(f"{BASE}/admin/payments/?page=1&size=3")

    assert response.status_code == 200
    assert len(response.json()["items"]) <= 3


@pytest.mark.asyncio
async def test_admin_get_all_payments_unauthorized(client):
    response = await client.get(f"{BASE}/admin/payments/")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_get_all_payments_forbidden_regular_user(authenticated_client):
    response = await authenticated_client.get(f"{BASE}/admin/payments/")

    assert response.status_code == 403


# ==============================================================================
# POST /webhook — Stripe webhook
# ==============================================================================


def make_stripe_event(
    event_type: str, order_id: int, amount_cents: int, session_id: str = "cs_test_abc"
) -> dict:
    return {
        "type": event_type,
        "data": {
            "object": {
                "id": session_id,
                "amount_total": amount_cents,
                "metadata": {"order_id": str(order_id)},
                "status": "complete",
            }
        },
    }


@pytest.mark.asyncio
async def test_webhook_checkout_completed_finalizes_order(
    client, db_session, movie_factory, user_factory
):
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie(price=Decimal("9.99"))
    order = await create_order(db_session, user.id, movie)

    amount_cents = int(order.total_amount * 100)
    event = make_stripe_event("checkout.session.completed", order.id, amount_cents)

    with patch("stripe.Webhook.construct_event", return_value=event):
        with patch("app.routes.payments.send_payment_confirmation_task") as mock_task:
            mock_task.delay = MagicMock()
            response = await client.post(
                f"{BASE}/webhook",
                content=json.dumps(event),
                headers={
                    "stripe-signature": "test_sig",
                    "content-type": "application/json",
                },
            )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}

    await db_session.refresh(order)
    assert order.status == OrderStatusEnum.PAID


@pytest.mark.asyncio
async def test_webhook_payment_failed_cancels_order(
    client, db_session, movie_factory, user_factory
):
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie()
    order = await create_order(db_session, user.id, movie)

    event = make_stripe_event(
        "checkout.session.async_payment_failed", order.id, int(movie.price * 100)
    )

    with patch("stripe.Webhook.construct_event", return_value=event):
        response = await client.post(
            f"{BASE}/webhook",
            content=json.dumps(event),
            headers={
                "stripe-signature": "test_sig",
                "content-type": "application/json",
            },
        )

    assert response.status_code == 200

    await db_session.refresh(order)
    assert order.status == OrderStatusEnum.CANCELED


@pytest.mark.asyncio
async def test_webhook_invalid_signature_returns_400(client):
    import stripe as stripe_module

    with patch(
        "stripe.Webhook.construct_event",
        side_effect=stripe_module.error.SignatureVerificationError(
            "Bad sig", "sig_header"
        ),
    ):
        response = await client.post(
            f"{BASE}/webhook",
            content=b"{}",
            headers={"stripe-signature": "bad_sig", "content-type": "application/json"},
        )

    assert response.status_code == 400
    assert "signature" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_webhook_invalid_payload_returns_400(client):
    with patch(
        "stripe.Webhook.construct_event",
        side_effect=ValueError("Invalid payload"),
    ):
        response = await client.post(
            f"{BASE}/webhook",
            content=b"not-json",
            headers={"stripe-signature": "any", "content-type": "application/json"},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_webhook_unknown_event_type_returns_200(client):
    event = {"type": "some.unknown.event", "data": {"object": {}}}

    with patch("stripe.Webhook.construct_event", return_value=event):
        response = await client.post(
            f"{BASE}/webhook",
            content=json.dumps(event),
            headers={
                "stripe-signature": "test_sig",
                "content-type": "application/json",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}


@pytest.mark.asyncio
async def test_webhook_completed_amount_mismatch_does_not_pay(
    client, db_session, movie_factory, user_factory
):
    """If Stripe amount differs from DB total, order must NOT be marked PAID."""
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie(price=Decimal("9.99"))
    order = await create_order(db_session, user.id, movie)

    wrong_amount_cents = 1  # clearly wrong
    event = make_stripe_event(
        "checkout.session.completed", order.id, wrong_amount_cents
    )

    with patch("stripe.Webhook.construct_event", return_value=event):
        with patch("app.routes.payments.send_payment_confirmation_task") as mock_task:
            mock_task.delay = MagicMock()
            response = await client.post(
                f"{BASE}/webhook",
                content=json.dumps(event),
                headers={
                    "stripe-signature": "test_sig",
                    "content-type": "application/json",
                },
            )

    assert response.status_code == 200

    await db_session.refresh(order)
    assert order.status == OrderStatusEnum.PENDING


@pytest.mark.asyncio
async def test_webhook_completed_already_paid_order_is_skipped(
    client, db_session, movie_factory, user_factory
):
    user = await user_factory.create_active_user()
    movie = await movie_factory.create_movie(price=Decimal("9.99"))
    order = await create_order(db_session, user.id, movie, status=OrderStatusEnum.PAID)

    amount_cents = int(order.total_amount * 100)
    event = make_stripe_event("checkout.session.completed", order.id, amount_cents)

    with patch("stripe.Webhook.construct_event", return_value=event):
        with patch("app.routes.payments.send_payment_confirmation_task") as mock_task:
            mock_task.delay = MagicMock()
            response = await client.post(
                f"{BASE}/webhook",
                content=json.dumps(event),
                headers={
                    "stripe-signature": "test_sig",
                    "content-type": "application/json",
                },
            )

    assert response.status_code == 200
    # status unchanged — still PAID, not double-processed
    await db_session.refresh(order)
    assert order.status == OrderStatusEnum.PAID
