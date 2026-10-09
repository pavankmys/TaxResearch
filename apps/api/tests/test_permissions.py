"""Tests for the role-to-permission map."""

import pytest
from app.auth.permissions import PERMISSIONS, has_permission


def test_platform_admin_has_admin_actions() -> None:
    """platform_admin manages users, reads the audit log and runs the review console."""
    assert PERMISSIONS["platform_admin"] == frozenset(
        {
            "users.read",
            "users.manage",
            "audit.read",
            "ingest.submit",
            "ingest.read",
            "review.read",
            "review.decide",
            "documents.read",
            "documents.edit",
            "sources.read",
            "sources.manage",
            "dashboard.read",
            "jobs.retry",
            "ingest.upload",
            "miss_report.create",
            "baseline.read",
            "baseline.verify",
        }
    )
    assert has_permission(["platform_admin"], "users.manage")
    assert has_permission(["platform_admin"], "audit.read")
    assert has_permission(["platform_admin"], "sources.manage")
    assert has_permission(["platform_admin"], "baseline.read")
    assert has_permission(["platform_admin"], "baseline.verify")


def test_content_editor_works_the_queue_but_cannot_manage_sources() -> None:
    """platform_content_editor works review tasks, documents and ingestion; not admin actions."""
    assert PERMISSIONS["platform_content_editor"] == frozenset(
        {
            "ingest.submit",
            "ingest.read",
            "review.read",
            "review.decide",
            "documents.read",
            "documents.edit",
            "sources.read",
            "dashboard.read",
            "jobs.retry",
            "ingest.upload",
            "miss_report.create",
            "baseline.read",
            "baseline.verify",
        }
    )
    assert not has_permission(["platform_content_editor"], "users.read")
    assert not has_permission(["platform_content_editor"], "sources.manage")
    assert not has_permission(["platform_content_editor"], "audit.read")
    assert has_permission(["platform_content_editor"], "baseline.read")
    assert has_permission(["platform_content_editor"], "baseline.verify")


@pytest.mark.parametrize(
    "role",
    [
        "firm_admin",
        "partner",
        "professional",
        "junior",
        "client_viewer",
        "platform_content_editor",
        "platform_admin",
    ],
)
def test_every_role_can_file_a_miss_report(role: str) -> None:
    """Any signed-in user can report a miss; nothing else is open to the non-platform roles."""
    assert has_permission([role], "miss_report.create")


@pytest.mark.parametrize(
    "role",
    ["firm_admin", "partner", "professional", "junior", "client_viewer"],
)
def test_non_platform_roles_cannot_read_the_console(role: str) -> None:
    """The review, document, source, dashboard and upload actions are platform-only."""
    for action in (
        "review.read",
        "documents.read",
        "documents.edit",
        "sources.read",
        "dashboard.read",
        "jobs.retry",
        "ingest.upload",
    ):
        assert not has_permission([role], action)


def test_professional_has_no_admin_actions() -> None:
    """A professional role grants none of the admin actions."""
    assert not has_permission(["professional"], "users.read")
    assert not has_permission(["professional"], "audit.read")


def test_every_seeded_role_is_listed() -> None:
    """Every seeded role code appears in the map."""
    seeded = {
        "platform_content_editor",
        "platform_admin",
        "firm_admin",
        "partner",
        "professional",
        "junior",
        "client_viewer",
    }
    assert set(PERMISSIONS) == seeded


def test_unknown_role_and_no_roles_grant_nothing() -> None:
    """Unknown or empty role lists grant nothing."""
    assert not has_permission(["made_up"], "users.read")
    assert not has_permission([], "users.read")


def test_any_role_granting_action_is_enough() -> None:
    """Permissions are the union over the caller's roles."""
    assert has_permission(["professional", "platform_admin"], "users.manage")
