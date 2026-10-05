"""Authentication, user scoping, and the moderation lifecycle.

The scoping tests are written from the attacker's side: each one holds a valid
token for account A and reaches for a resource belonging to account B. That is
the shape of the bug this phase exists to prevent, so it is the shape the tests
take.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.core.security import (
    TokenError,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from tests.conftest import TEST_PASSWORD, MakeResume

# --- the crypto seam ---------------------------------------------------------


def test_password_round_trips() -> None:
    hashed = hash_password("a-perfectly-fine-passphrase")
    assert hashed != "a-perfectly-fine-passphrase"
    assert verify_password("a-perfectly-fine-passphrase", hashed)
    assert not verify_password("something-else-entirely", hashed)


def test_the_migration_placeholder_hash_can_never_authenticate() -> None:
    """Rows migrated from before auth carry an unusable hash.

    Argon2 raises on it rather than returning False, so this asserts the
    exception is caught — otherwise every legacy account would 500 on login
    instead of simply being locked out.
    """
    for attempt in ("", "!locked-no-password-set", "password", TEST_PASSWORD):
        assert not verify_password(attempt, "!locked-no-password-set")


def test_a_refresh_token_is_not_decodable_as_an_access_token() -> None:
    import uuid

    token, jti, expires_at = create_refresh_token(uuid.uuid4(), 0)
    assert decode_token(token, "refresh")["type"] == "refresh"
    # The jti handed back is the one inside the token — the caller stores it as
    # the row key, so a mismatch would make every rotation look like a replay.
    assert decode_token(token, "refresh")["jti"] == jti
    assert expires_at > datetime.now(UTC)
    with pytest.raises(TokenError):
        decode_token(token, "access")


# --- registration and sign-in ------------------------------------------------


async def test_register_then_login(client: AsyncClient) -> None:
    registered = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Ada", "email": "ada@example.com", "password": TEST_PASSWORD},
    )
    assert registered.status_code == 201
    body = registered.json()
    assert body["role"] == "user"
    # The digest must never appear on the wire.
    assert "hashed_password" not in body
    assert "password" not in body

    token = await client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": TEST_PASSWORD}
    )
    assert token.status_code == 200
    assert token.json()["token_type"] == "bearer"
    assert token.json()["access_token"]


async def test_login_is_case_insensitive_on_email(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Ada", "email": "Ada@Example.COM", "password": TEST_PASSWORD},
    )
    token = await client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": TEST_PASSWORD}
    )
    assert token.status_code == 200


async def test_duplicate_registration_is_rejected(client: AsyncClient) -> None:
    payload = {"full_name": "Ada", "email": "dup@example.com", "password": TEST_PASSWORD}
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


async def test_short_password_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Ada", "email": "short@example.com", "password": "abc"},
    )
    assert response.status_code == 422


async def test_wrong_password_and_unknown_email_are_indistinguishable(
    client: AsyncClient,
) -> None:
    """The login form must not double as an account-enumeration oracle."""
    await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Ada", "email": "real@example.com", "password": TEST_PASSWORD},
    )
    wrong_password = await client.post(
        "/api/v1/auth/login", json={"email": "real@example.com", "password": "wrong-password-x"}
    )
    unknown_email = await client.post(
        "/api/v1/auth/login", json={"email": "ghost@example.com", "password": TEST_PASSWORD}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


async def test_bootstrap_email_becomes_admin(admin_client: AsyncClient) -> None:
    me = await admin_client.get("/api/v1/auth/me")
    assert me.json()["role"] == "admin"


async def test_role_cannot_be_set_at_registration(client: AsyncClient) -> None:
    """`role` is not a field on the wire — an extra key must not promote."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Sneaky",
            "email": "sneaky@example.com",
            "password": TEST_PASSWORD,
            "role": "admin",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == "user"


# --- tokens ------------------------------------------------------------------


async def test_protected_endpoint_requires_a_token(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/resumes")).status_code == 401
    assert (await client.get("/api/v1/companies")).status_code == 401
    assert (await client.get("/api/v1/job-profiles")).status_code == 401


async def test_garbage_token_is_rejected(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/resumes", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


async def test_refresh_token_is_not_accepted_as_an_access_token(client: AsyncClient) -> None:
    """The `type` claim check, from the outside.

    Both tokens are signed with the same key, so only the type check stands
    between a weeks-long credential and ordinary API access.
    """
    await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Ada", "email": "typed@example.com", "password": TEST_PASSWORD},
    )
    tokens = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "typed@example.com", "password": TEST_PASSWORD},
        )
    ).json()

    response = await client.get(
        "/api/v1/resumes", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
    )
    assert response.status_code == 401


async def test_refresh_issues_a_new_pair(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Ada", "email": "refresh@example.com", "password": TEST_PASSWORD},
    )
    tokens = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "refresh@example.com", "password": TEST_PASSWORD},
        )
    ).json()

    refreshed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]


async def test_password_change_revokes_old_refresh_tokens(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Ada", "email": "rotate@example.com", "password": TEST_PASSWORD},
    )
    tokens = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "rotate@example.com", "password": TEST_PASSWORD},
        )
    ).json()

    changed = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": TEST_PASSWORD, "new_password": "a-brand-new-passphrase"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert changed.status_code == 200

    stale = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert stale.status_code == 401
    assert "revoked" in stale.json()["detail"].lower()

    # The pair handed back by the change itself still works.
    fresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": changed.json()["refresh_token"]}
    )
    assert fresh.status_code == 200


async def test_wrong_current_password_blocks_the_change(user_client: AsyncClient) -> None:
    response = await user_client.post(
        "/api/v1/auth/me/password",
        json={"current_password": "not-the-password", "new_password": "another-good-passphrase"},
    )
    assert response.status_code == 403


# --- private data is owner-scoped -------------------------------------------


async def test_resume_is_owned_by_its_creator(
    user_client: AsyncClient, make_resume: MakeResume
) -> None:
    resume_id = await make_resume(user_client)
    me = await user_client.get("/api/v1/auth/me")
    fetched = await user_client.get(f"/api/v1/resumes/{resume_id}")
    assert fetched.status_code == 200
    assert fetched.json()["user_id"] == me.json()["id"]


async def test_resume_listing_never_crosses_accounts(
    user_client: AsyncClient, other_client: AsyncClient, make_resume: MakeResume
) -> None:
    await make_resume(user_client, "Mine")
    await make_resume(other_client, "Theirs")

    mine = await user_client.get("/api/v1/resumes")
    assert [r["title"] for r in mine.json()] == ["Mine"]


@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("get", ""),
        ("get", "/versions"),
        ("get", "/outline"),
        ("get", "/tex"),
        ("get", "/pdf"),
        ("get", "/reviews"),
        ("delete", ""),
    ],
)
async def test_every_resume_route_refuses_another_users_id(
    user_client: AsyncClient,
    other_client: AsyncClient,
    make_resume: MakeResume,
    method: str,
    suffix: str,
) -> None:
    """The whole resume surface, not just the obvious read."""
    victim_id = await make_resume(other_client, "Private")

    call = getattr(user_client, method)
    response = await call(f"/api/v1/resumes/{victim_id}{suffix}")

    assert response.status_code == 404, f"{method.upper()} {suffix or '/'} leaked"


async def test_not_even_an_admin_can_read_a_users_resume(
    admin_client: AsyncClient, user_client: AsyncClient, make_resume: MakeResume
) -> None:
    """The one rule with no administrative override.

    Moderation covers public data; a resume is not moderation surface. There is
    no path through the API that reads one as anybody but its owner, so "an
    admin read this document" is not a thing that can quietly happen.
    """
    resume_id = await make_resume(user_client, "Private")
    assert (await admin_client.get(f"/api/v1/resumes/{resume_id}")).status_code == 404


async def test_starting_a_review_on_another_users_resume_is_refused(
    user_client: AsyncClient, other_client: AsyncClient, make_resume: MakeResume
) -> None:
    victim_id = await make_resume(other_client, "Private")
    response = await user_client.post(
        f"/api/v1/resumes/{victim_id}/reviews",
        json={"job_profile_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert response.status_code in (404, 503)


# --- public data: moderation and deduplication -------------------------------


async def test_user_submission_is_pending_and_admin_submission_is_not(
    user_client: AsyncClient, admin_client: AsyncClient
) -> None:
    proposed = await user_client.post("/api/v1/companies", json={"name": "Hooli"})
    assert proposed.status_code == 201
    assert proposed.json()["status"] == "pending"

    by_admin = await admin_client.post("/api/v1/companies", json={"name": "Pied Piper"})
    assert by_admin.json()["status"] == "approved"


async def test_pending_company_is_usable_by_its_contributor_only(
    user_client: AsyncClient, other_client: AsyncClient
) -> None:
    """The core of the moderation policy: review must not block your own work."""
    company_id = (
        await user_client.post("/api/v1/companies", json={"name": "Stealth Startup"})
    ).json()["id"]

    assert (await user_client.get(f"/api/v1/companies/{company_id}")).status_code == 200
    assert [c["name"] for c in (await user_client.get("/api/v1/companies")).json()] == [
        "Stealth Startup"
    ]

    assert (await other_client.get(f"/api/v1/companies/{company_id}")).status_code == 404
    assert (await other_client.get("/api/v1/companies")).json() == []


async def test_approval_publishes_to_everyone(
    user_client: AsyncClient, other_client: AsyncClient, admin_client: AsyncClient
) -> None:
    company_id = (await user_client.post("/api/v1/companies", json={"name": "Umbrella"})).json()[
        "id"
    ]
    assert (await other_client.get(f"/api/v1/companies/{company_id}")).status_code == 404

    approved = await admin_client.post(f"/api/v1/companies/{company_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    assert (await other_client.get(f"/api/v1/companies/{company_id}")).status_code == 200


async def test_rejection_records_a_reason_the_contributor_can_read(
    user_client: AsyncClient, admin_client: AsyncClient
) -> None:
    company_id = (
        await user_client.post("/api/v1/companies", json={"name": "Not A Company"})
    ).json()["id"]
    rejected = await admin_client.post(
        f"/api/v1/companies/{company_id}/reject", json={"reason": "Not a real employer."}
    )
    assert rejected.status_code == 200

    seen = await user_client.get(f"/api/v1/companies/{company_id}")
    assert seen.status_code == 200
    assert seen.json()["rejection_reason"] == "Not a real employer."


async def test_moderation_endpoints_are_admin_only(user_client: AsyncClient) -> None:
    company_id = (
        await user_client.post("/api/v1/companies", json={"name": "Self Approve Inc"})
    ).json()["id"]
    assert (await user_client.post(f"/api/v1/companies/{company_id}/approve")).status_code == 403
    assert (await user_client.delete(f"/api/v1/companies/{company_id}")).status_code == 403


async def test_approved_company_is_no_longer_contributor_editable(
    user_client: AsyncClient, admin_client: AsyncClient
) -> None:
    company_id = (await user_client.post("/api/v1/companies", json={"name": "Shared Co"})).json()[
        "id"
    ]
    # Editable while pending — that is the review conversation.
    assert (
        await user_client.patch(f"/api/v1/companies/{company_id}", json={"industry": "Retail"})
    ).status_code == 200

    await admin_client.post(f"/api/v1/companies/{company_id}/approve")

    # Once shared, one user's edit would rewrite it for everyone.
    blocked = await user_client.patch(
        f"/api/v1/companies/{company_id}", json={"industry": "Defence"}
    )
    assert blocked.status_code == 403


@pytest.mark.parametrize(
    "duplicate_name",
    ["Acme Inc", "acme", "ACME, Inc.", "Acme  Incorporated", "Acme-Inc"],
)
async def test_company_duplicates_are_refused_across_spellings(
    admin_client: AsyncClient, duplicate_name: str
) -> None:
    assert (await admin_client.post("/api/v1/companies", json={"name": "Acme"})).status_code == 201

    clash = await admin_client.post("/api/v1/companies", json={"name": duplicate_name})
    assert clash.status_code == 409, f"{duplicate_name!r} slipped past the slug"
    # The existing row rides along so the client can offer it.
    assert clash.json()["detail"]["existing"]["name"] == "Acme"


async def test_company_lookup_finds_the_row_before_submitting(
    admin_client: AsyncClient,
) -> None:
    await admin_client.post("/api/v1/companies", json={"name": "Globex Corporation"})
    found = await admin_client.get("/api/v1/companies/lookup", params={"name": "globex"})
    assert found.status_code == 200
    assert found.json()["name"] == "Globex Corporation"

    missing = await admin_client.get("/api/v1/companies/lookup", params={"name": "Nothing Here"})
    assert missing.status_code == 200
    assert missing.json() is None


async def test_job_profile_is_keyed_by_company_and_requisition_id(
    admin_client: AsyncClient,
) -> None:
    company_id = (await admin_client.post("/api/v1/companies", json={"name": "Keyed Co"})).json()[
        "id"
    ]
    payload = {
        "company_id": company_id,
        "external_job_id": "REQ-1234",
        "position_title": "Backend Engineer",
        "description": "Build and operate backend APIs in Python.",
    }
    assert (await admin_client.post("/api/v1/job-profiles", json=payload)).status_code == 201

    # Same requisition id, different title — still the same posting.
    clash = await admin_client.post(
        "/api/v1/job-profiles", json={**payload, "position_title": "Senior Backend Engineer"}
    )
    assert clash.status_code == 409

    # A different requisition id at the same company is a different posting.
    other = await admin_client.post(
        "/api/v1/job-profiles", json={**payload, "external_job_id": "REQ-9999"}
    )
    assert other.status_code == 201


async def test_job_profiles_without_a_requisition_id_fall_back_to_title_and_location(
    admin_client: AsyncClient,
) -> None:
    """The NULL case — where a plain UNIQUE would have admitted everything."""
    company_id = (
        await admin_client.post("/api/v1/companies", json={"name": "Fallback Co"})
    ).json()["id"]
    payload = {
        "company_id": company_id,
        "position_title": "Data Engineer",
        "description": "Build and maintain batch and streaming data pipelines.",
        "location": "Remote",
    }
    assert (await admin_client.post("/api/v1/job-profiles", json=payload)).status_code == 201

    # Case and spacing differences must not create a second row.
    clash = await admin_client.post(
        "/api/v1/job-profiles", json={**payload, "position_title": "data engineer"}
    )
    assert clash.status_code == 409

    # A genuinely different location is a genuinely different posting.
    berlin = await admin_client.post("/api/v1/job-profiles", json={**payload, "location": "Berlin"})
    assert berlin.status_code == 201


async def test_job_profile_cannot_attach_to_an_invisible_company(
    user_client: AsyncClient, other_client: AsyncClient
) -> None:
    hidden_id = (
        await other_client.post("/api/v1/companies", json={"name": "Someone Elses Draft"})
    ).json()["id"]

    response = await user_client.post(
        "/api/v1/job-profiles",
        json={
            "company_id": hidden_id,
            "position_title": "Engineer",
            "description": "General engineering work on the core product.",
        },
    )
    assert response.status_code == 404


# --- admin user management ---------------------------------------------------


# --- keeping junk out of the shared tables -----------------------------------


async def test_rejecting_a_company_releases_its_name(
    user_client: AsyncClient, other_client: AsyncClient, admin_client: AsyncClient
) -> None:
    """The whole point of rejecting junk: the real company can still be added.

    A unique index over every row would let one bad submission claim "Google"
    permanently — and the next contributor would get a 409 pointing at a row
    they cannot see.
    """
    junk = await user_client.post("/api/v1/companies", json={"name": "Google"})
    assert junk.status_code == 201
    await admin_client.post(
        f"/api/v1/companies/{junk.json()['id']}/reject", json={"reason": "Junk entry."}
    )

    real = await other_client.post(
        "/api/v1/companies", json={"name": "Google", "industry": "Software"}
    )
    assert real.status_code == 201, real.text
    assert real.json()["slug"] == "google"


async def test_rejecting_a_posting_releases_its_requisition_id(
    user_client: AsyncClient, other_client: AsyncClient, admin_client: AsyncClient
) -> None:
    company_id = (await admin_client.post("/api/v1/companies", json={"name": "Reissue Co"})).json()[
        "id"
    ]
    payload = {
        "company_id": company_id,
        "external_job_id": "REQ-77",
        "position_title": "Engineer",
        "description": "A description long enough to pass the minimum length rule.",
    }
    junk = await user_client.post("/api/v1/job-profiles", json=payload)
    assert junk.status_code == 201
    await admin_client.post(
        f"/api/v1/job-profiles/{junk.json()['id']}/reject", json={"reason": "Not real."}
    )

    assert (await other_client.post("/api/v1/job-profiles", json=payload)).status_code == 201


async def test_pending_submissions_are_capped_per_user(
    user_client: AsyncClient, monkeypatch
) -> None:
    """Moderation judges quality; the quota is what bounds volume."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_pending_submissions_per_user", 3)

    for n in range(3):
        created = await user_client.post("/api/v1/companies", json={"name": f"Filler {n}"})
        assert created.status_code == 201

    blocked = await user_client.post("/api/v1/companies", json={"name": "One Too Many"})
    assert blocked.status_code == 429
    assert "awaiting review" in blocked.json()["detail"]


async def test_approval_frees_quota(
    user_client: AsyncClient, admin_client: AsyncClient, monkeypatch
) -> None:
    """A good-faith contributor is never blocked for long."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_pending_submissions_per_user", 1)

    first = await user_client.post("/api/v1/companies", json={"name": "First Co"})
    assert first.status_code == 201
    assert (
        await user_client.post("/api/v1/companies", json={"name": "Second Co"})
    ).status_code == 429

    await admin_client.post(f"/api/v1/companies/{first.json()['id']}/approve")
    assert (
        await user_client.post("/api/v1/companies", json={"name": "Second Co"})
    ).status_code == 201


async def test_admins_are_exempt_from_the_quota(admin_client: AsyncClient, monkeypatch) -> None:
    """Their submissions are approved on creation, so they are never pending."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_pending_submissions_per_user", 1)

    for n in range(3):
        assert (
            await admin_client.post("/api/v1/companies", json={"name": f"Admin Co {n}"})
        ).status_code == 201


@pytest.mark.parametrize(
    "name",
    ["", " ", "x", "!!!", "aaaaaaaaaa", "123"],
)
async def test_obvious_junk_company_names_are_refused(user_client: AsyncClient, name: str) -> None:
    response = await user_client.post("/api/v1/companies", json={"name": name})
    assert response.status_code == 422, f"{name!r} was accepted"


async def test_a_stub_job_description_is_refused(admin_client: AsyncClient) -> None:
    """Too short to score against a resume is too short to store."""
    company_id = (await admin_client.post("/api/v1/companies", json={"name": "Stub Co"})).json()[
        "id"
    ]
    response = await admin_client.post(
        "/api/v1/job-profiles",
        json={"company_id": company_id, "position_title": "Engineer", "description": "job"},
    )
    assert response.status_code == 422


async def test_blank_requisition_id_is_stored_as_null(admin_client: AsyncClient) -> None:
    """Otherwise "" becomes a distinct key and defeats the fallback index."""
    company_id = (
        await admin_client.post("/api/v1/companies", json={"name": "Blank Id Co"})
    ).json()["id"]
    payload = {
        "company_id": company_id,
        "external_job_id": "   ",
        "position_title": "Engineer",
        "description": "A description long enough to pass the minimum length rule.",
    }
    created = await admin_client.post("/api/v1/job-profiles", json=payload)
    assert created.status_code == 201
    assert created.json()["external_job_id"] is None

    # And the title+location fallback now catches the duplicate.
    assert (await admin_client.post("/api/v1/job-profiles", json=payload)).status_code == 409


async def test_purge_removes_rejected_rows_and_is_admin_only(
    user_client: AsyncClient, admin_client: AsyncClient
) -> None:
    junk = await user_client.post("/api/v1/companies", json={"name": "Purge Me"})
    await admin_client.post(
        f"/api/v1/companies/{junk.json()['id']}/reject", json={"reason": "Junk."}
    )

    assert (await user_client.post("/api/v1/admin/purge-rejected")).status_code == 403

    # retention_days=0 makes everything already rejected eligible.
    purged = await admin_client.post("/api/v1/admin/purge-rejected?retention_days=0")
    assert purged.status_code == 200
    assert purged.json()["companies_deleted"] == 1

    assert (await user_client.get(f"/api/v1/companies/{junk.json()['id']}")).status_code == 404


async def test_user_listing_is_admin_only(
    user_client: AsyncClient, admin_client: AsyncClient
) -> None:
    assert (await user_client.get("/api/v1/users")).status_code == 403
    assert (await admin_client.get("/api/v1/users")).status_code == 200


async def test_user_cannot_read_another_users_record(
    user_client: AsyncClient, other_client: AsyncClient
) -> None:
    victim_id = (await other_client.get("/api/v1/auth/me")).json()["id"]
    assert (await user_client.get(f"/api/v1/users/{victim_id}")).status_code == 404


async def test_admin_can_promote_and_deactivate(
    admin_client: AsyncClient, user_client: AsyncClient
) -> None:
    target_id = (await user_client.get("/api/v1/auth/me")).json()["id"]

    promoted = await admin_client.patch(f"/api/v1/users/{target_id}/role", json={"role": "admin"})
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"

    deactivated = await admin_client.patch(
        f"/api/v1/users/{target_id}/active", json={"is_active": False}
    )
    assert deactivated.status_code == 200
    # Existing sessions must stop working immediately.
    assert (await user_client.get("/api/v1/auth/me")).status_code == 401


async def test_last_admin_cannot_be_demoted(admin_client: AsyncClient) -> None:
    """Otherwise the moderation queue becomes permanently unreachable."""
    admin_id = (await admin_client.get("/api/v1/auth/me")).json()["id"]
    response = await admin_client.patch(f"/api/v1/users/{admin_id}/role", json={"role": "user"})
    assert response.status_code == 409


async def test_moderator_role_and_moderation_permissions(
    admin_client: AsyncClient, user_client: AsyncClient, other_client: AsyncClient
) -> None:
    """Moderators can approve and reject public items, but cannot alter user roles."""
    # 1. Promote other_client user to moderator
    mod_id = (await other_client.get("/api/v1/auth/me")).json()["id"]
    mod_promoted = await admin_client.patch(
        f"/api/v1/users/{mod_id}/role", json={"role": "moderator"}
    )
    assert mod_promoted.status_code == 200
    assert mod_promoted.json()["role"] == "moderator"

    # 2. User proposes a company
    company_id = (
        await user_client.post("/api/v1/companies", json={"name": "Mod Review Co"})
    ).json()["id"]

    # 3. General user cannot approve/reject
    assert (await user_client.post(f"/api/v1/companies/{company_id}/approve")).status_code == 403

    # 4. Moderator can approve company
    approved = await other_client.post(f"/api/v1/companies/{company_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    # 5. Moderator cannot perform admin-only role changes
    user_id = (await user_client.get("/api/v1/auth/me")).json()["id"]
    role_change = await other_client.patch(f"/api/v1/users/{user_id}/role", json={"role": "admin"})
    assert role_change.status_code == 403
