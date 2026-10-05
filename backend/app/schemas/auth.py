import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.schemas.user import UserUpdate


def _check_password(value: str) -> str:
    """Length-only policy, checked against settings at validation time.

    Deliberately not a composition rule ("one upper, one digit, one symbol").
    Those push users toward `Password1!` — predictable to an attacker and
    hostile to a password manager — while length is what actually costs a
    cracker time.
    """
    minimum = get_settings().min_password_length
    if len(value) < minimum:
        raise ValueError(f"Password must be at least {minimum} characters.")
    # Bound the input so a multi-megabyte body cannot turn Argon2 into a
    # denial-of-service lever.
    if len(value) > 256:
        raise ValueError("Password must be at most 256 characters.")
    return value


Password = Annotated[str, AfterValidator(_check_password)]


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: Password


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: Password


class EmailChangeRequest(BaseModel):
    """`PATCH /auth/me` — a profile edit that may also move the sign-in address.

    A superset of `UserUpdate` with one extra field. Re-authentication is
    required for `email` and nothing else, so the password is optional here and
    checked by the route only when the address actually changes; making it
    mandatory would put a password prompt in front of editing a job title.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    current_password: str | None = None
    current_title: str | None = None
    career_goals: str | None = None
    desired_salary_min: Decimal | None = None
    desired_salary_max: Decimal | None = None
    salary_currency: str | None = None

    def as_user_update(self) -> "UserUpdate":
        """Drop `current_password` before anything reaches the model layer."""
        from app.schemas.user import UserUpdate

        return UserUpdate.model_validate(
            self.model_dump(exclude={"current_password"}, exclude_unset=True)
        )


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — the OAuth2 scheme name, not a secret
    expires_in: int


class RoleUpdateRequest(BaseModel):
    role: str = Field(pattern="^(user|moderator|admin)$")


class ActiveUpdateRequest(BaseModel):
    is_active: bool


class UserSummary(BaseModel):
    """Attribution shown alongside public data — never an email address."""

    id: uuid.UUID
    full_name: str
