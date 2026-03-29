import asyncio
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.db.base import Base
from api.db.session import get_db
from api.main import app

TEST_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/arc_test",
)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
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

    # Mock K8s client so tests don't need a cluster
    with patch("api.k8s.client.get_k8s_client") as mock_k8s:
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
