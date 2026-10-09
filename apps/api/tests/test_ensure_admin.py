"""ensure-admin: the first platform_admin is created once, from the environment (no database)."""

import types
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app import cli
from app.routers.admin_users import AccountError

pytestmark = pytest.mark.anyio  # the repo's conftest selects the asyncio backend

PASSWORD = "synthetic-pass-12345"


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeSession:
    """Answers the two lookups ensure-admin makes: the role, then a user holding it."""

    def __init__(self, *, role: Any, holder: Any) -> None:
        self._answers = [role, holder]
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def execute(self, _statement: Any) -> _Result:
        return _Result(self._answers.pop(0) if self._answers else None)


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for name in ("ADMIN_EMAIL", "ADMIN_PASSWORD", "ADMIN_DISPLAY_NAME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def _created_user() -> Any:
    return types.SimpleNamespace(email="admin@example.test", id=uuid4())


async def test_skipped_without_email_or_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(monkeypatch, ADMIN_EMAIL="admin@example.test")
    create = AsyncMock()
    monkeypatch.setattr(cli, "create_user_with_roles", create)
    code = await cli._ensure_admin(FakeSession(role=None, holder=None))  # type: ignore[arg-type]
    assert code == 0
    assert "Skipped" in capsys.readouterr().out
    create.assert_not_awaited()


async def test_short_password_is_refused_and_not_echoed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(monkeypatch, ADMIN_EMAIL="admin@example.test", ADMIN_PASSWORD="short-pw")
    create = AsyncMock()
    monkeypatch.setattr(cli, "create_user_with_roles", create)
    code = await cli._ensure_admin(FakeSession(role=None, holder=None))  # type: ignore[arg-type]
    captured = capsys.readouterr()
    assert code == 2
    assert "short-pw" not in captured.out + captured.err
    create.assert_not_awaited()


async def test_existing_admin_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(monkeypatch, ADMIN_EMAIL="admin@example.test", ADMIN_PASSWORD=PASSWORD)
    create = AsyncMock()
    monkeypatch.setattr(cli, "create_user_with_roles", create)
    session = FakeSession(role=types.SimpleNamespace(id=uuid4()), holder=object())
    code = await cli._ensure_admin(session)  # type: ignore[arg-type]
    assert code == 0
    assert "admin exists" in capsys.readouterr().out
    create.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_creates_the_first_admin_with_the_default_display_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(monkeypatch, ADMIN_EMAIL="admin@example.test", ADMIN_PASSWORD=PASSWORD)
    create = AsyncMock(return_value=_created_user())
    monkeypatch.setattr(cli, "create_user_with_roles", create)
    session = FakeSession(role=types.SimpleNamespace(id=uuid4()), holder=None)
    code = await cli._ensure_admin(session)  # type: ignore[arg-type]
    assert code == 0
    create.assert_awaited_once()
    kwargs = create.await_args.kwargs  # type: ignore[union-attr]
    assert kwargs["role_codes"] == ["platform_admin"]
    assert kwargs["display_name"] == "Administrator"
    assert kwargs["email"] == "admin@example.test"
    session.commit.assert_awaited_once()
    captured = capsys.readouterr()
    assert PASSWORD not in captured.out + captured.err


async def test_empty_display_name_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(
        monkeypatch,
        ADMIN_EMAIL="admin@example.test",
        ADMIN_PASSWORD=PASSWORD,
        ADMIN_DISPLAY_NAME="",
    )
    create = AsyncMock(return_value=_created_user())
    monkeypatch.setattr(cli, "create_user_with_roles", create)
    await cli._ensure_admin(FakeSession(role=None, holder=None))  # type: ignore[arg-type]
    assert create.await_args.kwargs["display_name"] == "Administrator"  # type: ignore[union-attr]


async def test_an_account_error_rolls_back_and_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(monkeypatch, ADMIN_EMAIL="admin@example.test", ADMIN_PASSWORD=PASSWORD)
    create = AsyncMock(side_effect=AccountError(409, "email already in use"))
    monkeypatch.setattr(cli, "create_user_with_roles", create)
    session = FakeSession(role=None, holder=None)
    code = await cli._ensure_admin(session)  # type: ignore[arg-type]
    assert code == 2
    session.rollback.assert_awaited_once()
    captured = capsys.readouterr()
    assert "email already in use" in captured.err
    assert PASSWORD not in captured.out + captured.err
