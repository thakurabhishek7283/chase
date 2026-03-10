import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://jarvis:jarvis_dev_password@localhost:5432/jarvis_test",
)

#: Ignore backend/.env entirely. A developer's real provider key or a different
#: LLM_PROVIDER must not change what the suite asserts — tests that care about
#: provider configuration set it explicitly.
os.environ["JARVIS_ENV_FILE"] = "tests/.nonexistent.env"
for _leaked_key in ("ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
    os.environ.pop(_leaked_key, None)

from app.core.db import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import PGVECTOR_TABLES  # noqa: E402

test_engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
test_session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

#: The local Postgres used for tests has no pgvector extension, so the vector
#: table is excluded from schema creation. Semantic-search endpoints surface a
#: 503 in that state, which is the behaviour we want to preserve.
_TEST_TABLES = [
    table for name, table in SQLModel.metadata.tables.items() if name not in PGVECTOR_TABLES
]


@pytest_asyncio.fixture(autouse=True)
async def prepare_database() -> AsyncGenerator[None, None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all, tables=_TEST_TABLES)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all, tables=_TEST_TABLES)


async def _get_test_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_session_maker() as session:
        yield session


app.dependency_overrides[get_session] = _get_test_session


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
