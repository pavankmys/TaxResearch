"""Tests for the role-to-permission map."""

from app.auth.permissions import PERMISSIONS, has_permission


def test_platform_admin_has_admin_actions() -> None:
    """platform_admin can manage users and read the audit log."""
    assert PERMISSIONS["platform_admin"] == frozenset(
        {"users.read", "users.manage", "audit.read", "ingest.submit", "ingest.read"}
    )
    assert has_permission(["platform_admin"], "users.manage")
    assert has_permission(["platform_admin"], "audit.read")


def test_content_editor_can_submit_and_read_ingestion() -> None:
    """platform_content_editor submits and reads ingestion jobs, and nothing else."""
    assert PERMISSIONS["platform_content_editor"] == frozenset({"ingest.submit", "ingest.read"})
    assert not has_permission(["platform_content_editor"], "users.read")


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
