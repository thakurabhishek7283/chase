"""Registration, sign-in, token refresh, and self-service account management."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    jti_of,
    needs_rehash,
    subject_of,
    verify_password,
)
from app.core.throttle import login_keys, login_limiter, register_limiter, throttle_enabled
from app.crud import audit as audit_crud
from app.crud import session as session_crud
from app.crud import user as crud
from app.deps import CurrentUser, SessionDep
from app.models.user import User
from app.schemas.auth import (
    EmailChangeRequest,
    LoginRequest,
    PasswordChangeRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
)
from app.schemas.user import UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

#: One message for "no such email" and for "wrong password". Distinguishing
#: them turns the login form into an oracle for which addresses hold accounts.
_BAD_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Incorrect email or password.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _too_many(retry_after: int, what: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many {what}. Try again in {retry_after} seconds.",
        headers={"Retry-After": str(retry_after)},
    )


async def _issue(
    session: AsyncSession,
    user: User,
    *,
    family_id: uuid.UUID | None = None,
) -> TokenPair:
    """Mint an access/refresh pair and record the refresh token.

    `family_id` continues an existing sign-in (rotation); omitting it starts a
    new one. The caller commits — the row and whatever prompted it must land
    together.
    """
    settings = get_settings()
    refresh, jti, expires_at = create_refresh_token(user.id, user.token_version)
    if family_id is None:
        await session_crud.start_family(session, jti=jti, user_id=user.id, expires_at=expires_at)
    else:
        await session_crud.continue_family(
            session, jti=jti, user_id=user.id, family_id=family_id, expires_at=expires_at
        )
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


async def _authenticate(session: AsyncSession, request: Request, email: str, password: str) -> User:
    """Check credentials, with the rate limiter wrapped around the whole path.

    The limiter is consulted before any work is done and charged only on
    failure, so a user signing in correctly never pays for someone else's
    guesses against the same address beyond the initial check.
    """
    settings = get_settings()
    keys = login_keys(audit_crud.client_ip(request), email)
    throttled = throttle_enabled()

    if throttled:
        for key in keys:
            wait = login_limiter.retry_after(
                key,
                window=settings.login_attempt_window_seconds,
                limit=settings.login_max_attempts,
            )
            if wait:
                raise _too_many(wait, "failed sign-in attempts")

    def _failed() -> HTTPException:
        if throttled:
            for key in keys:
                login_limiter.register_failure(
                    key,
                    window=settings.login_attempt_window_seconds,
                    limit=settings.login_max_attempts,
                    lockout=settings.login_lockout_seconds,
                )
        return _BAD_CREDENTIALS

    user = await crud.get_user_by_email(session, email)
    if user is None:
        # Hash anyway. Returning early on an unknown address makes the response
        # measurably faster than a wrong password, which leaks account
        # existence through timing alone.
        verify_password(password, "$argon2id$v=19$m=65536,t=3,p=4$invalid$invalid")
        raise _failed()
    if not verify_password(password, user.hashed_password):
        raise _failed()
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated.",
        )

    if throttled:
        for key in keys:
            login_limiter.clear(key)

    # The one moment the plaintext is in hand and already known to be correct,
    # so it is the only moment a stored hash can be upgraded to current Argon2
    # parameters without asking the user for anything.
    if needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(password)
        session.add(user)

    return user


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, session: SessionDep, request: Request) -> UserRead:
    """Create an account.

    The 409 below is an account-existence oracle, and an unavoidable one: with
    no email delivery in this deployment there is no way to say "check your
    inbox" and mean it, and silently succeeding on a duplicate would leave the
    real owner unable to explain why their password stopped working. It is rate
    limited instead of hidden — see `register_max_attempts`.
    """
    settings = get_settings()
    if throttle_enabled():
        key = f"ip:{audit_crud.client_ip(request)}"
        wait = register_limiter.retry_after(
            key,
            window=settings.register_attempt_window_seconds,
            limit=settings.register_max_attempts,
        )
        if wait:
            raise _too_many(wait, "registrations from this address")
        register_limiter.register_failure(
            key,
            window=settings.register_attempt_window_seconds,
            limit=settings.register_max_attempts,
            lockout=settings.register_attempt_window_seconds,
        )

    if await crud.get_user_by_email(session, data.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )
    user = await crud.create_user(
        session,
        UserCreate(full_name=data.full_name, email=data.email, password=data.password),
    )
    return UserRead.model_validate(user)


@router.post("/login", response_model=TokenPair)
async def login(data: LoginRequest, session: SessionDep, request: Request) -> TokenPair:
    """JSON sign-in — the endpoint the Angular client uses."""
    user = await _authenticate(session, request, data.email, data.password)
    pair = await _issue(session, user)
    await session.commit()
    return pair


@router.post("/token", response_model=TokenPair)
async def login_form(
    session: SessionDep,
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> TokenPair:
    """Form sign-in, so Swagger UI's *Authorize* button works.

    So much of this API is exercised through `/docs` that losing that button to
    a JSON-only login would be a real cost. `username` is the email address.
    """
    user = await _authenticate(session, request, form.username, form.password)
    pair = await _issue(session, user)
    await session.commit()
    return pair


@router.post("/refresh", response_model=TokenPair)
async def refresh(data: RefreshRequest, session: SessionDep) -> TokenPair:
    """Redeem a refresh token, rotating it for a fresh one.

    Each token is single-use. Presenting one that has already been redeemed
    means it exists in two places, so the whole family — every token descended
    from that sign-in — is revoked rather than guessing which holder is
    legitimate.
    """
    _revoked = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Session has been revoked. Sign in again.",
    )

    try:
        payload = decode_token(data.refresh_token, "refresh")
        user_id = subject_of(payload)
        jti = jti_of(payload)
    except TokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    record = await session_crud.get(session, jti)
    if record is None:
        # Signed correctly but unknown to us: either issued before this table
        # existed, or already swept after expiry. Neither is redeemable.
        raise _revoked

    if record.used_at is not None or record.revoked_at is not None:
        # Replay. Whoever holds the family now, at least one holder is not the
        # person who signed in, so nobody keeps it.
        await session_crud.revoke_family(session, record.family_id, "reuse-detected")
        await session.commit()
        raise _revoked

    if not record.is_live or record.user_id != user_id:
        raise _revoked

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token is no longer valid."
        )
    # The version check is what makes a password change or a deactivation
    # actually evict existing sessions.
    if payload.get("ver") != user.token_version:
        raise _revoked

    session_crud.mark_used(record)
    pair = await _issue(session, user, family_id=record.family_id)
    await session.commit()
    return pair


@router.get("/me", response_model=UserRead)
async def read_me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.patch("/me", response_model=UserRead)
async def update_me(data: EmailChangeRequest, session: SessionDep, user: CurrentUser) -> UserRead:
    """Edit the caller's own profile.

    Changing `email` changes the identity this account signs in with, so that
    one field costs a password. Everything else here is a preference.
    """
    if data.email is not None and crud.normalize_email(data.email) != user.email:
        if not data.current_password or not verify_password(
            data.current_password, user.hashed_password
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Changing the sign-in email requires the current password.",
            )
        existing = await crud.get_user_by_email(session, data.email)
        if existing is not None and existing.id != user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with that email already exists.",
            )
    return UserRead.model_validate(await crud.update_user(session, user, data.as_user_update()))


@router.post("/me/password", response_model=TokenPair)
async def change_password(
    data: PasswordChangeRequest, session: SessionDep, user: CurrentUser
) -> TokenPair:
    """Change the password, then hand back a fresh pair.

    The change revokes every outstanding refresh token, including the caller's
    own — reissuing here is what keeps that from logging the user out of the
    session they just used to fix their password.
    """
    if not verify_password(data.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Current password is incorrect."
        )
    updated = await crud.set_password(session, user, data.new_password)
    await session_crud.revoke_all_for_user(session, updated.id, "password-change")
    pair = await _issue(session, updated)
    await session.commit()
    return pair


@router.post("/me/logout-everywhere", status_code=status.HTTP_204_NO_CONTENT)
async def logout_everywhere(session: SessionDep, user: CurrentUser) -> None:
    """Invalidate every refresh token for this account.

    Access tokens are stateless and stay valid until they expire — which is
    what bounds `ACCESS_TOKEN_EXPIRE_MINUTES` to a small number.
    """
    user.token_version += 1
    session.add(user)
    await session_crud.revoke_all_for_user(session, user.id, "logout")
    await session.commit()
