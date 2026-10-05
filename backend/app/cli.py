"""Administrative commands that have no place in the HTTP API.

`BOOTSTRAP_ADMIN_EMAIL` only applies at registration, which leaves two gaps:
an account that already exists cannot be promoted, and a deployment whose only
admin is locked out has no way back in. Both need a hand on the server rather
than an endpoint — an HTTP route that grants admin is a route that can be
called by someone who should not be able to call it. That is also why there is
no "forgot password" endpoint: without email delivery, any such route would be
an unauthenticated way to take over an account by naming it.

**Locked out of the admin account?** This is the way back in. Run from
`backend/`, with the same `.env` the server uses:

    uv run python -m app.cli list-admins                       # who is an admin
    uv run python -m app.cli reset-password you@example.com    # prompts, no echo
    uv run python -m app.cli promote-admin  you@example.com    # existing account
    uv run python -m app.cli create-admin   you@example.com --name "Your Name"
    uv run python -m app.cli promote-moderator them@example.com

`reset-password` prompts twice without echoing, reactivates the account, and
signs every other session out. Where stdin is not a terminal it generates a
password and prints it instead — convenient in a pipeline, so do not run it
that way anywhere the output is logged.
"""

import argparse
import asyncio
import getpass
import secrets
import sys

from sqlmodel import col, select

from app.core.config import get_settings
from app.core.db import async_session_maker
from app.core.security import hash_password
from app.crud import session as session_crud
from app.crud.user import normalize_email
from app.models.user import User


async def _find(session, email: str) -> User | None:
    result = await session.exec(select(User).where(User.email == normalize_email(email)))
    return result.first()


def _read_password(confirm: bool = True) -> str:
    """Prompt without echoing, or generate one if stdin is not a terminal."""
    minimum = get_settings().min_password_length
    if not sys.stdin.isatty():
        generated = secrets.token_urlsafe(18)
        print(f"No terminal for a prompt — generated password: {generated}")
        return generated
    while True:
        password = getpass.getpass("New password: ")
        if len(password) < minimum:
            print(f"Too short — needs at least {minimum} characters.")
            continue
        if confirm and password != getpass.getpass("Confirm: "):
            print("Those did not match.")
            continue
        return password


async def promote_admin(email: str) -> int:
    async with async_session_maker() as session:
        user = await _find(session, email)
        if user is None:
            print(f"No account with email {email!r}. Register first, or use create-admin.")
            return 1
        if user.is_admin:
            print(f"{user.email} is already an admin.")
            return 0
        user.role = "admin"
        session.add(user)
        await session.commit()
        print(f"{user.email} is now an admin.")
        return 0


async def demote_admin(email: str) -> int:
    async with async_session_maker() as session:
        user = await _find(session, email)
        if user is None:
            print(f"No account with email {email!r}.")
            return 1
        others = (
            await session.exec(
                select(User).where(User.role == "admin", User.is_active, User.id != user.id)
            )
        ).all()
        if not others:
            # Same guard the API applies: an instance with no admin has an
            # unreachable moderation queue and no in-app way to appoint one.
            print("Refusing — this is the only active admin.")
            return 1
        user.role = "user"
        session.add(user)
        await session.commit()
        print(f"{user.email} is no longer an admin.")
        return 0


async def create_admin(email: str, name: str | None) -> int:
    async with async_session_maker() as session:
        if await _find(session, email) is not None:
            print(f"{email} already exists — use promote-admin instead.")
            return 1
        password = _read_password()
        user = User(
            full_name=name or email.split("@")[0],
            email=normalize_email(email),
            hashed_password=hash_password(password),
            role="admin",
        )
        session.add(user)
        await session.commit()
        print(f"Created admin {user.email}.")
        return 0


async def reset_password(email: str) -> int:
    """Set a new password out-of-band. The way back in when nobody can sign in.

    Also reactivates the account: an admin who managed to deactivate themselves
    would otherwise be able to fix their password and still be locked out.
    """
    async with async_session_maker() as session:
        user = await _find(session, email)
        if user is None:
            print(f"No account with email {email!r}.")
            return 1
        user.hashed_password = hash_password(_read_password())
        # Every existing session for this account dies with the old password.
        user.token_version += 1
        user.is_active = True
        session.add(user)
        await session_crud.revoke_all_for_user(session, user.id, "password-reset")
        await session.commit()
        print(f"Password reset for {user.email}. Other sessions were signed out.")
        return 0


async def list_admins() -> int:
    async with async_session_maker() as session:
        admins = (
            await session.exec(select(User).where(User.role == "admin").order_by(col(User.email)))
        ).all()
        if not admins:
            print("No admins. Run promote-admin or create-admin.")
            return 1
        for admin in admins:
            print(f"  {admin.email:40} {'active' if admin.is_active else 'INACTIVE'}")
        return 0


async def set_role(email: str, role: str) -> int:
    if role not in ("user", "moderator", "admin"):
        print(f"Invalid role {role!r}. Valid roles are: user, moderator, admin")
        return 1
    async with async_session_maker() as session:
        user = await _find(session, email)
        if user is None:
            print(f"No account with email {email!r}.")
            return 1
        if user.role == "admin" and role != "admin":
            others = (
                await session.exec(
                    select(User).where(User.role == "admin", User.is_active, User.id != user.id)
                )
            ).all()
            if not others:
                print("Refusing — this is the only active admin.")
                return 1
        user.role = role
        session.add(user)
        await session.commit()
        print(f"{user.email} is now role: {user.role}.")
        return 0


async def create_user_with_role(email: str, name: str | None, role: str) -> int:
    async with async_session_maker() as session:
        if await _find(session, email) is not None:
            print(f"{email} already exists — use set-role instead.")
            return 1
        password = _read_password()
        user = User(
            full_name=name or email.split("@")[0],
            email=normalize_email(email),
            hashed_password=hash_password(password),
            role=role,
        )
        session.add(user)
        await session.commit()
        print(f"Created account {user.email} with role {user.role}.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    promote = sub.add_parser("promote-admin", help="Grant admin to an existing account")
    promote.add_argument("email")

    demote = sub.add_parser("demote-admin", help="Revoke admin")
    demote.add_argument("email")

    create = sub.add_parser("create-admin", help="Create a new admin account")
    create.add_argument("email")
    create.add_argument("--name", default=None)

    promote_mod = sub.add_parser(
        "promote-moderator", help="Grant moderator role to an existing account"
    )
    promote_mod.add_argument("email")

    create_mod = sub.add_parser("create-moderator", help="Create a new moderator account")
    create_mod.add_argument("email")
    create_mod.add_argument("--name", default=None)

    reset = sub.add_parser("reset-password", help="Set a new password and revoke sessions")
    reset.add_argument("email")

    sub.add_parser("list-admins", help="Show every admin account")

    args = parser.parse_args()

    if args.command == "promote-admin":
        return asyncio.run(promote_admin(args.email))
    if args.command == "demote-admin":
        return asyncio.run(demote_admin(args.email))
    if args.command == "create-admin":
        return asyncio.run(create_admin(args.email, args.name))
    if args.command == "promote-moderator":
        return asyncio.run(set_role(args.email, "moderator"))
    if args.command == "create-moderator":
        return asyncio.run(create_user_with_role(args.email, args.name, "moderator"))
    if args.command == "reset-password":
        return asyncio.run(reset_password(args.email))
    return asyncio.run(list_admins())


if __name__ == "__main__":
    raise SystemExit(main())
