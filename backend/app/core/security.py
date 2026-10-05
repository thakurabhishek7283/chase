"""Password hashing and JWT issuance.

Deliberately free of FastAPI and SQLModel imports: this is a pure crypto seam
that can be unit-tested without a request or a database. `app/deps.py` is where
tokens meet HTTP.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

from app.core.config import get_settings

TokenType = Literal["access", "refresh"]

#: Argon2id at the library's defaults — the current password-hashing
#: recommendation, and unlike bcrypt it has no silent 72-byte truncation.
_hasher = PasswordHasher()


class TokenError(Exception):
    """A token was malformed, expired, or not the type the caller expected."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Check a password, returning False rather than raising on a bad hash.

    Rows migrated from before authentication existed carry a deliberately
    invalid placeholder hash. Argon2 raises on those, and the desired behaviour
    is "this account cannot log in until it resets", not a 500.
    """
    try:
        return _hasher.verify(hashed, password)
    except (Argon2Error, ValueError, TypeError):
        return False


def needs_rehash(hashed: str) -> bool:
    """True when a stored hash predates the current Argon2 parameters."""
    try:
        return _hasher.check_needs_rehash(hashed)
    except (Argon2Error, ValueError, TypeError):
        return False


def _encode(
    subject: uuid.UUID,
    token_type: TokenType,
    expires_in: timedelta,
    **claims: Any,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_in,
        # A unique id per token, so individual tokens can be denylisted later
        # without changing the format.
        "jti": secrets.token_urlsafe(12),
        **claims,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, *, expires_in: timedelta | None = None) -> str:
    """Short-lived request credential.

    Carries the subject and nothing else. Embedding the role here was tempting
    — it reads like it saves a query — but the request path loads the user row
    regardless, to check `is_active` and to compare ownership. A role claim
    would therefore buy nothing while creating a second, staler answer to
    "is this user an admin?" that outlives a demotion until the token expires.
    """
    settings = get_settings()
    return _encode(
        user_id,
        "access",
        expires_in or timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(user_id: uuid.UUID, token_version: int) -> tuple[str, str, datetime]:
    """Long-lived token, redeemable only while it matches the user's version.

    `token_version` revokes every session at once — the right response to a
    password change. Individual revocation and replay detection need the `jti`
    and expiry returned alongside the token, which the caller records in
    `refresh_tokens`.
    """
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    jti = secrets.token_urlsafe(12)
    token = _encode(
        user_id,
        "refresh",
        timedelta(days=settings.refresh_token_expire_days),
        ver=token_version,
        jti=jti,
    )
    return token, jti, expires_at


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Verify a token's signature, expiry, and *type*.

    The type check is load-bearing, not defensive tidiness. Both token kinds are
    signed with the same key, so without it a refresh token — which lives for
    weeks and is stored on the client — would authenticate ordinary API calls,
    quietly erasing the point of a short access-token lifetime.
    """
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError as exc:
        raise TokenError("Token is invalid or has expired.") from exc

    if payload.get("type") != expected_type:
        raise TokenError(f"Expected a {expected_type} token.")
    return payload


def subject_of(payload: dict[str, Any]) -> uuid.UUID:
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError, TypeError) as exc:
        raise TokenError("Token carries no usable subject.") from exc


def jti_of(payload: dict[str, Any]) -> str:
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti:
        raise TokenError("Token carries no usable id.")
    return jti
