import os
import uuid
from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

#: Point the suite at a scratch database. `JARVIS_TEST_DATABASE_URL` takes
#: precedence so a developer whose local role or password differs from the
#: documented default can run the tests without editing (and accidentally
#: committing) this file.
#:
#: The database is created and dropped table-by-table on every test, so it must
#: never be the development database.
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get("JARVIS_TEST_DATABASE_URL")
    or "postgresql+asyncpg://jarvis:jarvis_dev_password@localhost:5432/jarvis_test",
)

#: Ignore backend/.env entirely. A developer's real API key or a different
#: ATS_MODEL must not change what the suite asserts — tests that care about
#: model configuration set it explicitly.
os.environ["JARVIS_ENV_FILE"] = "tests/.nonexistent.env"
os.environ.pop("GOOGLE_API_KEY", None)

#: Pinned so token signing is deterministic within a run and the "no secret
#: configured" warning stays out of the test output.
os.environ.setdefault(
    "JWT_SECRET_KEY", "test-only-signing-key-padded-to-the-32-byte-minimum"
)
#: Whoever registers with this address is promoted to admin — the same
#: bootstrap path an operator uses, exercised rather than bypassed.
ADMIN_EMAIL = "admin@example.com"
os.environ.setdefault("BOOTSTRAP_ADMIN_EMAIL", ADMIN_EMAIL)

from app.core import throttle  # noqa: E402
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

#: Long enough to clear `min_password_length` without any test having to know
#: what that setting currently is.
TEST_PASSWORD = "correct-horse-battery-staple"


@pytest_asyncio.fixture(autouse=True)
async def prepare_database() -> AsyncGenerator[None, None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all, tables=_TEST_TABLES)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all, tables=_TEST_TABLES)


@pytest.fixture(autouse=True)
def reset_throttle() -> None:
    """Clear the sign-in limiter between tests.

    It is process-global by design, so without this the suite's own fixtures
    exhaust the registration budget — every test after the first few would fail
    at sign-up with a 429 that has nothing to do with what it is testing.
    """
    throttle.reset_all()


async def _get_test_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_session_maker() as session:
        yield session


app.dependency_overrides[get_session] = _get_test_session


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """An unauthenticated client — used to assert that endpoints demand a token."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


SignIn = Callable[..., Coroutine[Any, Any, AsyncClient]]


@pytest_asyncio.fixture
async def sign_in() -> AsyncGenerator[SignIn, None]:
    """Register an account and hand back a client that carries its bearer token.

    Tests go through the real `/auth/register` and `/auth/login` endpoints
    rather than minting a token directly, so the sign-up path is covered by
    every test that needs a user, and a break in it cannot hide behind a
    fixture shortcut.
    """
    clients: list[AsyncClient] = []

    async def _sign_in(email: str, full_name: str = "Test User") -> AsyncClient:
        transport = ASGITransport(app=app)
        ac = AsyncClient(transport=transport, base_url="http://test")
        registered = await ac.post(
            "/api/v1/auth/register",
            json={"full_name": full_name, "email": email, "password": TEST_PASSWORD},
        )
        assert registered.status_code == 201, registered.text
        token = await ac.post(
            "/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD}
        )
        assert token.status_code == 200, token.text
        ac.headers["Authorization"] = f"Bearer {token.json()['access_token']}"
        clients.append(ac)
        return ac

    yield _sign_in

    for ac in clients:
        await ac.aclose()


@pytest_asyncio.fixture
async def user_client(sign_in: SignIn) -> AsyncClient:
    return await sign_in("user@example.com", "Test User")


@pytest_asyncio.fixture
async def other_client(sign_in: SignIn) -> AsyncClient:
    """A second, unrelated account — the other side of every isolation test."""
    return await sign_in("other@example.com", "Other User")


@pytest_asyncio.fixture
async def admin_client(sign_in: SignIn) -> AsyncClient:
    return await sign_in(ADMIN_EMAIL, "Admin User")


#: A resume that parses and compiles, for tests that need one to exist rather
#: than to test how one is made.
SAMPLE_TEX = r"""\documentclass{article}
\usepackage{enumitem}
\begin{document}
\section{Experience}
\textbf{Engineer}, Acme \hfill 2021 -- Present
\begin{itemize}
    \item Built a data pipeline in Python.
    \item Ran the on-call rotation.
\end{itemize}
\end{document}
"""

MakeResume = Callable[..., Coroutine[Any, Any, str]]


@pytest_asyncio.fixture
async def make_resume() -> MakeResume:
    """Insert a resume straight into the database and hand back its id.

    Deliberately not `POST /resumes/upload`. That route spends a model call and
    runs the LaTeX engine, which is exactly right when the upload path is what
    is being tested and pure cost everywhere else — scope tests need a resume to
    exist, not a resume to be *built*. `tests/test_reviews.py` covers the real
    route.
    """

    async def _make(client: AsyncClient, title: str = "Master", content: str | None = None) -> str:
        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200, me.text
        from app.models.resume import Resume

        async with test_session_maker() as session:
            resume = Resume(
                user_id=uuid.UUID(me.json()["id"]),
                title=title,
                content=content or SAMPLE_TEX,
                version_label="Master",
            )
            session.add(resume)
            await session.commit()
            return str(resume.id)

    return _make
