# Online Cinema API

REST API for a digital cinema platform — user accounts, movie catalogue, cart, orders, and Stripe payments.

---

## Tech Stack

| Layer | Tools |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2 |
| Database | PostgreSQL 16, SQLAlchemy 2 (async), Alembic, asyncpg |
| Queue / Cache | Celery, Celery-Beat, Redis 7 |
| Storage | MinIO (S3-compatible), aioboto3 |
| Payments | Stripe |
| Email | aiosmtplib, Jinja2, MailHog (local) |
| Infrastructure | Docker, Docker Compose, Poetry |
| CI/CD | GitHub Actions, Flake8, Black, Pytest |

---

## Features

**Auth & Users**
- JWT access + refresh token pair; secure logout revokes the refresh token
- Email activation link on registration (24h TTL, resendable)
- Password reset via email token
- Three roles: `User`, `Moderator`, `Admin`

**Movie Catalog**
- CRUD for movies, genres, actors, directors (Moderator+)
- Filtering by year / IMDb rating, sorting by price / date / popularity
- Full-text search across title, description, actor, director
- Likes/dislikes, 10-point ratings, favorites, nested comments

**Cart & Orders**
- One cart per user; duplicate and re-purchase prevention
- Order total recalculated at payment time to handle price changes
- Moderators cannot delete a movie that is purchased or in any active cart

**Payments**
- Stripe Checkout session per order
- Webhook validation automatically updates order and payment status
- Payment history with statuses: `successful`, `canceled`, `refunded`

**Background Tasks**
- Celery-Beat periodically purges expired activation and password reset tokens
- Email notifications for comment replies and likes

**Docs**
- Swagger UI and Redoc — accessible to authenticated admins/moderators only

---

## Prerequisites

- Docker & Docker Compose
- Stripe account (Secret Key + Webhook Signing Secret; test mode is fine)

---

## Getting Started

```bash
# 1. Clone
git clone <your-repository-url>
cd online-cinema-backend

# 2. Configure environment
cp .env.sample .env
# fill in .env with your values

# 3. Build and start
docker compose up --build

# 4. Run migrations
docker compose exec app alembic upgrade head
```

API is available at `http://localhost:8000`.

---

## API Docs

Requires authentication with Admin or Moderator role.

- Swagger UI: `http://localhost:8000/docs`
- Redoc: `http://localhost:8000/redoc`

---

## Running Tests

```bash
docker compose exec app pytest --cov=app
```

## Live Demo

The API is deployed on AWS EC2 and available at:

| Interface | URL |
|---|---|
| Swagger UI | http://3.123.207.169:8000/docs |
| Redoc | http://3.123.207.169:8000/redoc |

> Authentication with Admin or Moderator credentials required to access the docs.

---

## Project Directory Structure
```bash
.
├── .dockerignore
├── .env
├── .env.sample
├── .flake8
├── .gitignore
├── Dockerfile
├── README.md
├── alembic.ini
├── celerybeat-schedule
├── docker-compose.yml
├── poetry.lock
├── pyproject.toml
├── .github/
│   └── workflows/
│       ├── cd.yml
│       └── ci.yml
├── commands/
│   ├── deploy.sh
│   └── entrypoint.sh
└── app/
    ├── main.py
    ├── manage.py
    ├── core/
    │   ├── __init__.py
    │   ├── config.py
    │   └── dependencies.py
    ├── database/
    │   ├── __init__.py
    │   ├── engine.py
    │   ├── migrations/
    │   │   ├── README
    │   │   ├── env.py
    │   │   ├── script.py.mako
    │   │   ├── __init__.py
    │   │   └── versions/
    │   ├── models/
    │   │   ├── __init__.py
    │   │   ├── accounts.py
    │   │   ├── base.py
    │   │   ├── carts.py
    │   │   ├── enums.py
    │   │   ├── movies.py
    │   │   ├── orders.py
    │   │   └── payments.py
    │   └── validators/
    │       ├── __init__.py
    │       ├── accounts_validators.py
    │       └── movies_validators.py
    ├── exceptions/
    │   ├── __init__.py
    │   ├── email.py
    │   ├── security.py
    │   └── storage.py
    ├── notifications/
    │   ├── __init__.py
    │   ├── emails.py
    │   ├── interfaces.py
    │   └── templates/
    ├── routes/
    │   ├── __init__.py
    │   ├── accounts.py
    │   ├── carts.py
    │   ├── movies_admin.py
    │   ├── movies_user.py
    │   ├── orders.py
    │   └── payments.py
    ├── schemas/
    │   ├── __init__.py
    │   ├── accounts.py
    │   ├── carts.py
    │   ├── movies.py
    │   ├── orders.py
    │   ├── pagination.py
    │   └── payments.py
    ├── scripts/
    │   ├── __init__.py
    │   ├── base.py
    │   └── seed_users.py
    ├── security/
    │   ├── __init__.py
    │   ├── interfaces.py
    │   ├── passwords.py
    │   ├── token_manager.py
    │   └── utils.py
    ├── storages/
    │   ├── __init__.py
    │   ├── interfaces.py
    │   └── s3.py
    ├── tests/
    │   ├── __init__.py
    │   ├── conftest.py
    │   ├── test_security.py
    │   ├── test_validators.py
    │   ├── doubles/
    │   ├── factories/
    │   └── api/
    │       ├── __init__.py
    │       ├── accounts/
    │       │   ├── __init__.py
    │       │   └── test_accounts.py
    │       ├── movies/
    │       │   ├── __init__.py
    │       │   ├── test_admin_movies.py
    │       │   └── test_user_movies.py
    │       └── shop/
    │           ├── __init__.py
    │           ├── test_carts.py
    │           ├── test_orders.py
    │           └── test_payments.py
    └── worker/
        ├── __init__.py
        ├── celery_app.py
        └── tasks.py
```
