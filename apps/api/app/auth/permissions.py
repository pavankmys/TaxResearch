"""Role-to-permission map (TSD 9.2). Every seeded role is listed; POC only grants platform_admin."""

from collections.abc import Iterable

PERMISSIONS: dict[str, frozenset[str]] = {
    "platform_admin": frozenset(
        {"users.read", "users.manage", "audit.read", "ingest.submit", "ingest.read"}
    ),
    "platform_content_editor": frozenset({"ingest.submit", "ingest.read"}),
    "firm_admin": frozenset(),
    "partner": frozenset(),
    "professional": frozenset(),
    "junior": frozenset(),
    "client_viewer": frozenset(),
}


def has_permission(roles: Iterable[str], action: str) -> bool:
    """Return True if any of the roles grants the action."""
    return any(action in PERMISSIONS.get(role, frozenset()) for role in roles)
