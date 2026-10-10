"""Role-to-permission map (TSD 9.2). Every seeded role is listed."""

from collections.abc import Iterable

# Granted to every role: any signed-in user can search, read provisions,
# and report missed search results.
_ANY_USER: frozenset[str] = frozenset({"miss_report.create", "provisions.read", "search.read"})

_EDITOR_ACTIONS: frozenset[str] = _ANY_USER | frozenset(
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
        "baseline.read",
        "baseline.verify",
    }
)

PERMISSIONS: dict[str, frozenset[str]] = {
    "platform_admin": _EDITOR_ACTIONS
    | frozenset(
        {
            "users.read",
            "users.manage",
            "audit.read",
            "sources.manage",
        }
    ),
    "platform_content_editor": _EDITOR_ACTIONS,
    "firm_admin": _ANY_USER,
    "partner": _ANY_USER,
    "professional": _ANY_USER,
    "junior": _ANY_USER,
    "client_viewer": _ANY_USER,
}


def has_permission(roles: Iterable[str], action: str) -> bool:
    """Return True if any of the roles grants the action."""
    return any(action in PERMISSIONS.get(role, frozenset()) for role in roles)
