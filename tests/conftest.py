import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import api.metering.collector as _metering
import api.webhooks.service as _webhooks
from api.db.base import Base
from api.db.session import get_db
from api.main import app

TEST_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/arc_test",
)


@pytest_asyncio.fixture
async def test_engine():
    # NullPool: no connection reuse across event loops — safe for function-scoped tests
    engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    test_session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Patch every module that bypasses get_db and calls AsyncSessionLocal directly
    original_webhooks = _webhooks.AsyncSessionLocal
    original_metering = _metering.AsyncSessionLocal
    _webhooks.AsyncSessionLocal = test_session_factory
    _metering.AsyncSessionLocal = test_session_factory

    yield engine

    _webhooks.AsyncSessionLocal = original_webhooks
    _metering.AsyncSessionLocal = original_metering
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    with patch("api.instances.router.get_k8s_client") as mock_k8s:
        mock_k8s.return_value = MagicMock()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def mock_provisioner():
    with patch("api.instances.service.provisioner") as mock:
        mock.provision_instance = AsyncMock()
        mock.deprovision_instance = AsyncMock()
        mock.get_statefulset_ready = AsyncMock(return_value=True)
        mock.get_service_endpoint = AsyncMock(return_value=("127.0.0.1", 30432))
        mock.rotate_password = AsyncMock()
        yield mock
