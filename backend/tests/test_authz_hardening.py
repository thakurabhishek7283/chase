"""Regression tests for the authorization audit.

Every test here corresponds to a behaviour that was once wrong, and each is
written from the attacker's side. A passing suite means the specific mistake
cannot come back silently.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlmodel import col, select

from app.core import throttle
from app.core.config import get_settings
from app.models.audit import AuditLog
from app.models.session import RefreshToken
#: Aliased on import: pytest tries to *collect* a module-level name starting
#: with `test_`, and warns when it turns out to be a sessionmaker.
from tests.conftest import TEST_PASSWORD, MakeResume
from tests.conftest import test_session_maker as session_maker

pytestmark = pytest.mark.anyio


async def audit_actions(action: str | None = None) -> list[AuditLog]:
    async with session_maker() as session:
        query = select(AuditLog).order_by(col(AuditLog.created_at))
        if action is not None:
            query = query.where(AuditLog.action == action)
        return list((await session.exec(query)).all())


async def me(client: AsyncClient) -> dict:
    return (await client.get("/api/v1/auth/me")).json()


# --- refresh tokens: single use, with replay treated as theft ----------------


async def test_refreshing_rotates_the_token(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"full_name": "R", "email": "rotate@example.com", "password": TEST_PASSWORD},
    )
    first = (
        await client.post(
            "/api/v1/auth/login", json={"email": "rotate@example.com", "password": TEST_PASSWORD}
        )
    ).json()

    second = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert second.status_code == 200
    assert second.json()["refresh_token"] != first["refresh_token"]

    # The new one works.
    third = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": second.json()["refresh_token"]}
    )
    assert third.status_code == 200


async def test_replaying_a_refresh_token_revokes_the_whole_family(
    client: AsyncClient,
) -> None:
    """Two parties holding one token is theft; the server cannot tell which is which."""
    await client.post(
        "/api/v1/auth/register",
        json={"full_name": "R", "email": "replay@example.com", "password": TEST_PASSWORD},
    )
    stolen = (
        await client.post(
            "/api/v1/auth/login", json={"email": "replay@example.com", "password": TEST_PASSWORD}
        )
    ).json()["refresh_token"]

    legitimate = (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
    ).json()["refresh_token"]

    # The thief redeems the copy they took.
    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
    assert replay.status_code == 401
    assert "revoked" in replay.json()["detail"]

    # And the legitimate holder's newer token dies with it, rather than the
    # session quietly continuing in the attacker's hands.
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": legitimate})
    ).status_code == 401

    async with session_maker() as session:
        rows = (await session.exec(select(RefreshToken))).all()
    assert {row.revoked_reason for row in rows} == {"reuse-detected"}


async def test_a_refresh_token_unknown_to_the_server_is_refused(
    client: AsyncClient, user_client: AsyncClient
) -> None:
    """Correctly signed but with no row — pre-rotation tokens, or swept ones."""
    from app.core.security import create_refresh_token

    user_id = uuid.UUID((await me(user_client))["id"])
    forged, _jti, _exp = create_refresh_token(user_id, 0)

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": forged})
    assert response.status_code == 401


async def test_logout_everywhere_closes_the_session_rows(
    user_client: AsyncClient,
) -> None:
    await user_client.post("/api/v1/auth/me/logout-everywhere")
    async with session_maker() as session:
        rows = (await session.exec(select(RefreshToken))).all()
    assert rows and all(row.revoked_at is not None for row in rows)


# --- throttling ---------------------------------------------------------------


async def test_repeated_bad_passwords_start_being_refused(client: AsyncClient) -> None:
    settings = get_settings()
    await client.post(
        "/api/v1/auth/register",
        json={"full_name": "B", "email": "brute@example.com", "password": TEST_PASSWORD},
    )

    codes = [
        (
            await client.post(
                "/api/v1/auth/login",
                json={"email": "brute@example.com", "password": f"wrong-{i}"},
            )
        ).status_code
        for i in range(settings.login_max_attempts + 2)
    ]

    assert codes[0] == 401, "the first attempt must be judged on the password"
    assert 429 in codes, "unlimited guessing was the bug"
    # Even the right password is refused while the lockout stands, or the
    # limiter would be trivially bypassed by whoever eventually guesses it.
    locked_out = await client.post(
        "/api/v1/auth/login", json={"email": "brute@example.com", "password": TEST_PASSWORD}
    )
    assert locked_out.status_code == 429
    assert "Retry-After" in locked_out.headers


async def test_a_successful_sign_in_clears_the_count(client: AsyncClient) -> None:
    """A user who mistypes then succeeds must not be locked out by later typos."""
    settings = get_settings()
    await client.post(
        "/api/v1/auth/register",
        json={"full_name": "T", "email": "typo@example.com", "password": TEST_PASSWORD},
    )
    for _ in range(settings.login_max_attempts - 1):
        await client.post(
            "/api/v1/auth/login", json={"email": "typo@example.com", "password": "nope"}
        )

    good = await client.post(
        "/api/v1/auth/login", json={"email": "typo@example.com", "password": TEST_PASSWORD}
    )
    assert good.status_code == 200

    # Budget is back: another near-full run of failures still ends in 401, not 429.
    after = await client.post(
        "/api/v1/auth/login", json={"email": "typo@example.com", "password": "nope"}
    )
    assert after.status_code == 401


async def test_registration_is_capped_per_address(client: AsyncClient) -> None:
    settings = get_settings()
    codes = []
    for i in range(settings.register_max_attempts + 2):
        codes.append(
            (
                await client.post(
                    "/api/v1/auth/register",
                    json={
                        "full_name": "Flood",
                        "email": f"flood{i}@example.com",
                        "password": TEST_PASSWORD,
                    },
                )
            ).status_code
        )
    assert codes[0] == 201
    assert 429 in codes


async def test_the_throttle_can_be_switched_off(client: AsyncClient, monkeypatch) -> None:
    """Load tests need an escape hatch; deployments should never use it."""
    monkeypatch.setattr(get_settings(), "login_throttle_enabled", False)
    throttle.reset_all()
    await client.post(
        "/api/v1/auth/register",
        json={"full_name": "N", "email": "nothrottle@example.com", "password": TEST_PASSWORD},
    )
    codes = [
        (
            await client.post(
                "/api/v1/auth/login",
                json={"email": "nothrottle@example.com", "password": "wrong"},
            )
        ).status_code
        for _ in range(get_settings().login_max_attempts + 3)
    ]
    assert set(codes) == {401}


# --- career goals are not moderation business --------------------------------


async def test_job_matches_are_refused_even_to_admins(
    admin_client: AsyncClient, user_client: AsyncClient
) -> None:
    """The docstring always said self-only; the guard said self-or-admin."""
    user_id = (await me(user_client))["id"]
    await user_client.patch("/api/v1/auth/me", json={"career_goals": "somewhere else"})

    response = await admin_client.get(f"/api/v1/users/{user_id}/job-matches")
    # 404, not 403 — consistent with how every other private resource answers.
    assert response.status_code == 404


# --- changing the sign-in address costs a password ---------------------------


async def test_changing_email_without_the_password_is_refused(
    user_client: AsyncClient,
) -> None:
    response = await user_client.patch(
        "/api/v1/auth/me", json={"email": "hijacked@example.com"}
    )
    assert response.status_code == 403
    assert (await me(user_client))["email"] == "user@example.com"


async def test_changing_email_with_the_password_succeeds(user_client: AsyncClient) -> None:
    response = await user_client.patch(
        "/api/v1/auth/me",
        json={"email": "moved@example.com", "current_password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "moved@example.com"


async def test_an_ordinary_profile_edit_needs_no_password(user_client: AsyncClient) -> None:
    """The password is the price of moving the *identity*, not of editing a title."""
    response = await user_client.patch(
        "/api/v1/auth/me", json={"current_title": "Staff Engineer"}
    )
    assert response.status_code == 200
    assert response.json()["current_title"] == "Staff Engineer"


async def test_current_password_is_never_written_to_the_user(
    user_client: AsyncClient,
) -> None:
    """`current_password` is an auth input, not a profile field."""
    response = await user_client.patch(
        "/api/v1/auth/me",
        json={"full_name": "Renamed", "current_password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    assert "current_password" not in response.json()
    # Still signs in with the original password — nothing was overwritten.
    assert (
        await user_client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": TEST_PASSWORD},
        )
    ).status_code == 200


# --- the audit trail ----------------------------------------------------------


async def test_role_changes_are_recorded_with_both_ends(
    admin_client: AsyncClient, user_client: AsyncClient
) -> None:
    user_id = (await me(user_client))["id"]
    await admin_client.patch(f"/api/v1/users/{user_id}/role", json={"role": "moderator"})

    entries = await audit_actions("user.role_change")
    assert len(entries) == 1
    assert entries[0].detail == {"from": "user", "to": "moderator"}
    assert entries[0].target_email == "user@example.com"
    assert entries[0].actor_email == "admin@example.com"


async def test_deactivation_is_recorded_and_cuts_sessions(
    admin_client: AsyncClient, user_client: AsyncClient
) -> None:
    user_id = (await me(user_client))["id"]
    await admin_client.patch(f"/api/v1/users/{user_id}/active", json={"is_active": False})

    assert [e.action for e in await audit_actions("user.deactivate")] == ["user.deactivate"]
    async with session_maker() as session:
        rows = (
            await session.exec(
                select(RefreshToken).where(RefreshToken.user_id == uuid.UUID(user_id))
            )
        ).all()
    assert rows and all(row.revoked_reason == "deactivated" for row in rows)


async def test_the_audit_entry_survives_deleting_the_account_it_describes(
    admin_client: AsyncClient, sign_in
) -> None:
    """An audit log that is cascaded away with its subject explains nothing."""
    doomed = await sign_in("doomed@example.com", "Doomed User")
    doomed_id = (await me(doomed))["id"]

    assert (await admin_client.delete(f"/api/v1/users/{doomed_id}")).status_code == 204

    entries = await audit_actions("user.delete")
    assert len(entries) == 1
    assert entries[0].target_email == "doomed@example.com"
    assert str(entries[0].target_user_id) == doomed_id


async def test_deleting_an_account_that_owns_data_is_refused_not_a_500(
    admin_client: AsyncClient, user_client: AsyncClient, make_resume: MakeResume
) -> None:
    """The FK that protects the history has to be explained, not leaked.

    `resumes.user_id` is deliberately RESTRICT, so this delete cannot succeed —
    but it used to reach `commit()` and come back as a 500 with the constraint
    name in it, which reads as a server bug rather than as the refusal it is.
    """
    user_id = (await me(user_client))["id"]
    await make_resume(user_client, "Kept")

    response = await admin_client.delete(f"/api/v1/users/{user_id}")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "1 resume" in detail
    assert "active" in detail  # points at the operation that does work

    # Refused outright, not half-applied: the account is intact, and no audit
    # entry claims a delete that never happened.
    assert (await admin_client.get(f"/api/v1/users/{user_id}")).status_code == 200
    assert await audit_actions("user.delete") == []


async def test_purging_is_recorded(admin_client: AsyncClient) -> None:
    assert (await admin_client.post("/api/v1/admin/purge-rejected")).status_code == 200
    entries = await audit_actions("moderation.purge")
    assert len(entries) == 1
    assert entries[0].detail["retention_days"] == get_settings().rejected_retention_days


async def test_ordinary_activity_is_not_audited(
    user_client: AsyncClient, make_resume: MakeResume
) -> None:
    """A log that records everything is a log nobody reads."""
    await make_resume(user_client, "CV")
    await user_client.patch("/api/v1/auth/me", json={"current_title": "Engineer"})
    assert await audit_actions() == []
