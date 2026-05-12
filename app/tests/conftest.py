import os
import uuid
import pytest
import pytest_asyncio

from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.dependencies import get_accounts_email_notificator, get_s3_storage_client
from app.main import app
from app.database import Base, get_db
from app.core.dependencies import get_settings
from app.tests.doubles.stubs.emails import StubEmailSender
from app.tests.doubles.fakes.storage import FakeS3Storage
from app.tests.factories.user import UserFactory
from app.database.models.accounts import UserGroupModel
from app.database.models.enums import UserGroupEnum
from app.tests.factories.movie import MovieFactory

TEST_DB_URL = "sqlite+aiosqlite:///./test_accounts.db"

test_engine = create_async_engine(TEST_DB_URL, echo=False, future=True)
TestingSessionLocal = sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest.fixture(scope="function")
def s3_storage_fake():
    return FakeS3Storage()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()
    if os.path.exists("test_accounts.db"):
        os.remove("test_accounts.db")


@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with TestingSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def client(db_session, s3_storage_fake):
    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_accounts_email_notificator] = lambda: StubEmailSender()
    app.dependency_overrides[get_s3_storage_client] = lambda: s3_storage_fake

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def user_factory(db_session):
    return UserFactory(db_session)


@pytest_asyncio.fixture
async def jwt_manager():
    from app.security.token_manager import JWTAuthManager

    settings = get_settings()
    return JWTAuthManager(
        secret_key_access=settings.SECRET_KEY_ACCESS,
        secret_key_refresh=settings.SECRET_KEY_REFRESH,
        algorithm=settings.JWT_SIGNING_ALGORITHM,
    )


@pytest_asyncio.fixture(scope="function")
async def authenticated_client(client, user_factory, jwt_manager):
    unique_email = f"user_{uuid.uuid4()}@test.com"

    user = await user_factory.create_active_user(email=unique_email)

    access_token = jwt_manager.create_access_token({"user_id": user.id})

    client.headers["Authorization"] = f"Bearer {access_token}"

    return client


@pytest_asyncio.fixture(scope="function")
async def admin_client(client, user_factory, jwt_manager):
    unique_email = f"admin_{uuid.uuid4()}@test.com"
    admin = await user_factory.create_admin_user(email=unique_email)

    access_token = jwt_manager.create_access_token({"user_id": admin.id})
    client.headers["Authorization"] = f"Bearer {access_token}"
    return client


@pytest_asyncio.fixture
async def movie_factory(db_session):
    return MovieFactory(db_session)