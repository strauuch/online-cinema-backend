import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from core.dependencies import get_accounts_email_notificator, get_s3_storage_client
from main import app
from database import Base, get_db
from core.config import settings as get_settings
from tests.doubles.stubs.emails import StubEmailSender
from tests.doubles.fakes.storage import FakeS3Storage
from tests.factories.user import UserFactory

TEST_DB_URL = "sqlite+aiosqlite:///./test_accounts.db"

test_engine = create_async_engine(TEST_DB_URL, echo=False, future=True)
TestingSessionLocal = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with TestingSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_accounts_email_notificator] = lambda: StubEmailSender()
    app.dependency_overrides[get_s3_storage_client] = lambda: FakeS3Storage()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
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