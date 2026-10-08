"""Citation alias resolution for legal documents."""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Aliases:
    """Immutable container for citation aliases.

    Stores mappings from series/act/rules spellings to canonical codes.
    """

    notification_series: dict[str, str]  # e.g., "ct" -> "CT", "central tax" -> "CT"
    act_aliases: dict[str, str]  # e.g., "cgst" -> "CGST_ACT"
    rules_aliases: dict[str, str]  # e.g., "cgst rules" -> "CGST_RULES"


def load_aliases(path: str | Path | None = None) -> Aliases:
    """Load citation aliases from YAML.

    Default path: env CITATION_ALIASES_PATH else config/citation_aliases.yaml
    searched upwards from the current dir.

    Args:
        path: Optional path to the alias config file.

    Returns:
        Aliases object with normalized mappings.

    Raises:
        FileNotFoundError: If the alias file cannot be found.
        yaml.YAMLError: If the YAML is malformed.
    """
    if path is None:
        # Try environment variable first
        path = os.environ.get("CITATION_ALIASES_PATH")
        if path:
            path = Path(path)
        else:
            # Search upwards from current directory
            path = _find_config_upwards("config/citation_aliases.yaml")

    if path is None:
        raise FileNotFoundError(
            "citation_aliases.yaml not found. "
            "Set CITATION_ALIASES_PATH or place config/citation_aliases.yaml "
            "in the project root."
        )

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Alias file not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    # Build normalized lookup tables (lowercase keys -> canonical codes)
    notification_series: dict[str, str] = {}
    act_aliases: dict[str, str] = {}
    rules_aliases: dict[str, str] = {}

    # Notification series
    if data.get("notification_series"):
        for entry in data["notification_series"]:
            code = entry.get("code")
            if code:
                notification_series[code.lower()] = code
                for alias in entry.get("aliases", []):
                    notification_series[alias.lower()] = code

    # Act aliases
    if data.get("act_aliases"):
        for entry in data["act_aliases"]:
            # Map full name to normalized code (e.g., "CGST Act, 2017" -> "CGST_ACT")
            full_name = entry.get("full_name")
            if full_name:
                canonical = _normalize_instrument_code(full_name)
                act_aliases[full_name.lower()] = canonical
                for code_variant in entry.get("codes", []):
                    act_aliases[code_variant.lower()] = canonical

    # Rules aliases
    if data.get("rules_aliases"):
        for entry in data["rules_aliases"]:
            full_name = entry.get("full_name")
            if full_name:
                canonical = _normalize_instrument_code(full_name)
                rules_aliases[full_name.lower()] = canonical
                for code_variant in entry.get("codes", []):
                    rules_aliases[code_variant.lower()] = canonical

    return Aliases(
        notification_series=notification_series,
        act_aliases=act_aliases,
        rules_aliases=rules_aliases,
    )


def normalise_series(raw: str, aliases: Aliases) -> str | None:
    """Normalize a series spelling to its canonical code.

    Maps spellings such as "CT", "ct", "CT (R)", "CT(R)", "Central Tax (Rate)"
    to the canonical code if present in the alias table.

    Args:
        raw: Raw series spelling.
        aliases: Loaded aliases.

    Returns:
        Canonical series code, or None if not in the alias table.
    """
    if not raw:
        return None

    # Normalize whitespace and case
    normalized = " ".join(raw.split()).lower()

    # Try direct lookup
    if normalized in aliases.notification_series:
        return aliases.notification_series[normalized]

    return None


def _normalize_instrument_code(full_name: str) -> str:
    """Convert full instrument name to canonical code.

    E.g., "CGST Act, 2017" -> "CGST_ACT"
    """
    # Extract the acronym part before "Act" or "Rules"
    parts = full_name.split()
    if not parts:
        return full_name.replace(" ", "_").upper()

    # Take the first part (usually the acronym) and add _ACT or _RULES
    prefix = parts[0].upper()
    if "rules" in full_name.lower():
        return f"{prefix}_RULES"
    else:
        return f"{prefix}_ACT"


def _find_config_upwards(config_file: str) -> Path | None:
    """Search upwards from current directory for config file.

    Args:
        config_file: Relative path to config file (e.g., "config/citation_aliases.yaml").

    Returns:
        Path object if found, None otherwise.
    """
    current = Path.cwd()

    # Search up to 10 levels or filesystem root
    for _ in range(10):
        candidate = current / config_file
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            # Reached filesystem root
            break
        current = parent

    return None
