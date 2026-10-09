"""Operator commands: create a user, or verify the audit chain.

Usage (inside the API container):
    python -m app.cli create-user --email E --display-name N --role R [--role R2 ...]
    python -m app.cli verify-audit

The password comes from TAXRESEARCH_PASSWORD if set, otherwise it is prompted for twice.
"""

import argparse
import asyncio
import getpass
import logging
import os
import sys
from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit import verify_chain_with_count
from app.db import get_engine
from app.models import Role, UserRole
from app.routers.admin_users import AccountError, create_user_with_roles

MIN_PASSWORD_LENGTH = 12
PASSWORD_ENV_VAR = "TAXRESEARCH_PASSWORD"


class CliError(Exception):
    """A usage error that should be shown to the operator without a traceback."""


def _read_password() -> str:
    """Return the password from the environment, or prompt for it twice."""
    password = os.environ.get(PASSWORD_ENV_VAR)
    if not password:
        first = getpass.getpass("Password: ")
        second = getpass.getpass("Repeat password: ")
        if first != second:
            raise CliError("Passwords do not match")
        password = first
    if len(password) < MIN_PASSWORD_LENGTH:
        raise CliError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    return password


async def _with_session[T](work: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run ``work`` in a session on the app's engine, then dispose the engine."""
    engine = get_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            return await work(session)
    finally:
        await engine.dispose()


async def _create_user(
    session: AsyncSession,
    *,
    email: str,
    display_name: str,
    roles: list[str],
    password: str,
) -> int:
    try:
        user = await create_user_with_roles(
            session,
            email=email,
            display_name=display_name,
            password=password,
            role_codes=roles,
            actor=None,
            ctx=None,
            via="cli",
        )
        await session.commit()
    except AccountError as exc:
        await session.rollback()
        print(f"error: {exc.detail}", file=sys.stderr)
        return 1
    print(f"created user {user.email} ({user.id}) with roles: {', '.join(sorted(set(roles)))}")
    return 0


async def _verify_audit(session: AsyncSession) -> int:
    bad_seq, count = await verify_chain_with_count(session)
    if bad_seq is None:
        print(f"audit chain OK ({count} rows)")
        return 0
    print(f"audit chain BROKEN at seq {bad_seq}")
    return 1


async def _ensure_admin(session: AsyncSession) -> int:
    """Ensure the first platform_admin user exists.

    Reads ADMIN_EMAIL, ADMIN_PASSWORD, and optional ADMIN_DISPLAY_NAME from environment.
    If either email or password is unset, skips silently.
    If a platform_admin already exists, skips silently.
    Otherwise creates the user and sets role to platform_admin.
    """
    admin_email = os.environ.get("ADMIN_EMAIL", "").strip()
    admin_password = os.environ.get("ADMIN_PASSWORD", "").strip()
    admin_display_name = os.environ.get("ADMIN_DISPLAY_NAME", "").strip() or "Administrator"

    # If credentials are not set, skip silently
    if not admin_email or not admin_password:
        print("Skipped: ADMIN_EMAIL and ADMIN_PASSWORD not set")
        return 0

    # Check password length
    if len(admin_password) < MIN_PASSWORD_LENGTH:
        print(
            f"error: ADMIN_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters",
            file=sys.stderr,
        )
        return 2

    # Check if a platform_admin user already exists
    try:
        # Query for the platform_admin role
        role_result = await session.execute(select(Role).where(Role.code == "platform_admin"))
        admin_role = role_result.scalar_one_or_none()

        if admin_role:
            # Check if any user has this role
            existing_result = await session.execute(
                select(UserRole).where(UserRole.role_id == admin_role.id).limit(1)
            )
            if existing_result.scalar_one_or_none():
                print("admin exists")
                return 0
    except Exception as exc:
        # If the query fails (e.g., table doesn't exist), we'll try to create anyway
        logging.getLogger().debug(f"Could not check for existing admin: {exc}")

    # Create the user with platform_admin role
    try:
        user = await create_user_with_roles(
            session,
            email=admin_email,
            display_name=admin_display_name,
            password=admin_password,
            role_codes=["platform_admin"],
            actor=None,
            ctx=None,
            via="cli",
        )
        await session.commit()
        print(f"created admin user {user.email} ({user.id})")
        return 0
    except AccountError as exc:
        await session.rollback()
        print(f"error: {exc.detail}", file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="TaxResearch operator tools",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-user", help="create a local user with roles")
    create.add_argument("--email", required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument(
        "--role",
        dest="roles",
        action="append",
        required=True,
        help="role code; repeat for more roles",
    )

    commands.add_parser("verify-audit", help="verify the audit log hash chain")
    commands.add_parser(
        "ensure-admin",
        help="create the first admin user from ADMIN_EMAIL, ADMIN_PASSWORD env vars",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "create-user":
            if "@" not in args.email:
                raise CliError("Email must contain '@'")
            password = _read_password()
            return asyncio.run(
                _with_session(
                    lambda session: _create_user(
                        session,
                        email=args.email,
                        display_name=args.display_name,
                        roles=args.roles,
                        password=password,
                    )
                )
            )
        if args.command == "ensure-admin":
            return asyncio.run(_with_session(_ensure_admin))
        return asyncio.run(_with_session(_verify_audit))
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
