"""Repository configuration loaded from config/*.yaml.

The config directory is ``$CONFIG_DIR`` when set (the container sets it), otherwise the
nearest ``config/`` directory that holds ``sources.yaml`` above this file.
"""

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

VALID_SOURCE_KINDS = frozenset({"html_list", "rss", "api", "manual"})
VALID_COURT_LEVELS = frozenset({"SC", "HC", "GSTAT", "AAR", "AAAR"})
MIN_RANK = 1
MAX_RANK = 11


@dataclass(frozen=True)
class CourtConfig:
    """One entry of config/courts.yaml."""

    code: str
    name: str
    level: str
    patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class CaseNumberPattern:
    """One entry of citation_aliases.yaml case_number_patterns (named groups: number, year)."""

    abbr: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class SourceConfig:
    """One entry of config/sources.yaml that the worker needs."""

    code: str
    kind: str
    enabled: bool
    allowed_hosts: frozenset[str]
    user_agent: str


@dataclass(frozen=True)
class FetchConfig:
    """The fetch section of config/ingestion.yaml."""

    max_bytes: int
    timeout_seconds: float
    allowed_content_types: frozenset[str]


@dataclass(frozen=True)
class WatchConfig:
    """The watch section of config/ingestion.yaml."""

    stable_scans: int


@dataclass(frozen=True)
class IngestionConfig:
    """config/ingestion.yaml. ``parse`` stays a plain dict for the parsing library."""

    fetch: FetchConfig
    watch: WatchConfig
    parse: dict[str, Any]


def config_dir() -> Path:
    """Return the config directory, from CONFIG_DIR or by searching upwards."""
    override = os.environ.get("CONFIG_DIR")
    if override:
        path = Path(override)
        if not (path / "sources.yaml").is_file():
            raise ValueError(f"CONFIG_DIR={override} does not contain sources.yaml")
        return path
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config"
        if (candidate / "sources.yaml").is_file():
            return candidate
    raise ValueError("config/sources.yaml not found; set CONFIG_DIR to the config directory")


def _load_mapping(name: str) -> dict[str, Any]:
    path = config_dir() / name
    if not path.is_file():
        raise ValueError(f"{name} not found in {path.parent}")
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{name} must contain a mapping at the top level")
    return data


def _require_mapping(data: dict[str, Any], key: str, where: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{where}: '{key}' must be a mapping")
    return value


def _str_list(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{where} must be a list of strings")
    return value


@lru_cache(maxsize=1)
def load_sources() -> dict[str, SourceConfig]:
    """Load config/sources.yaml, keyed by source code."""
    data = _load_mapping("sources.yaml")
    scraping = _require_mapping(data, "scraping", "sources.yaml")
    user_agent = scraping.get("user_agent")
    if not isinstance(user_agent, str) or not user_agent.strip():
        raise ValueError("sources.yaml: scraping.user_agent must be a non-empty string")

    entries = data.get("sources")
    if not isinstance(entries, list):
        raise ValueError("sources.yaml: 'sources' must be a list")

    sources: dict[str, SourceConfig] = {}
    for index, entry in enumerate(entries):
        where = f"sources.yaml sources[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be a mapping")
        code = entry.get("code")
        if not isinstance(code, str) or not code:
            raise ValueError(f"{where}: 'code' must be a non-empty string")
        where = f"sources.yaml source '{code}'"
        kind = entry.get("kind")
        if kind not in VALID_SOURCE_KINDS:
            raise ValueError(f"{where}: kind must be one of {sorted(VALID_SOURCE_KINDS)}")
        enabled = entry.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError(f"{where}: 'enabled' must be true or false")
        hosts = {host.strip().lower() for host in _str_list(entry.get("allowed_hosts"), where)}
        if code in sources:
            raise ValueError(f"sources.yaml: duplicate source code '{code}'")
        sources[code] = SourceConfig(
            code=code,
            kind=kind,
            enabled=enabled,
            allowed_hosts=frozenset(hosts),
            user_agent=user_agent,
        )
    return sources


@lru_cache(maxsize=1)
def load_doc_type_ranks() -> dict[str, int]:
    """Load the doc_types map from config/authority.yaml (doc_type to authority rank)."""
    data = _load_mapping("authority.yaml")
    doc_types = data.get("doc_types")
    if not isinstance(doc_types, dict) or not doc_types:
        raise ValueError("authority.yaml: 'doc_types' must be a non-empty mapping")
    ranks: dict[str, int] = {}
    for name, rank in doc_types.items():
        if not isinstance(name, str) or not name:
            raise ValueError("authority.yaml: doc_types keys must be non-empty strings")
        if isinstance(rank, bool) or not isinstance(rank, int):
            raise ValueError(f"authority.yaml: doc_types.{name} must be an integer rank")
        if not MIN_RANK <= rank <= MAX_RANK:
            raise ValueError(
                f"authority.yaml: doc_types.{name} must be between {MIN_RANK} and {MAX_RANK}"
            )
        ranks[name] = rank
    return ranks


def _positive_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{where} must be a positive integer")
    return value


@lru_cache(maxsize=1)
def load_ingestion_config() -> IngestionConfig:
    """Load config/ingestion.yaml: the fetch and watch sections, and the parse section."""
    data = _load_mapping("ingestion.yaml")

    fetch = _require_mapping(data, "fetch", "ingestion.yaml")
    max_bytes = _positive_int(fetch.get("max_bytes"), "ingestion.yaml: fetch.max_bytes")
    timeout = fetch.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0:
        raise ValueError("ingestion.yaml: fetch.timeout_seconds must be a positive number")
    content_types = _str_list(fetch.get("allowed_content_types"), "ingestion.yaml: fetch")
    if not content_types:
        raise ValueError("ingestion.yaml: fetch.allowed_content_types must not be empty")

    watch = _require_mapping(data, "watch", "ingestion.yaml")
    stable_scans = _positive_int(watch.get("stable_scans"), "ingestion.yaml: watch.stable_scans")

    parse = _require_mapping(data, "parse", "ingestion.yaml")

    return IngestionConfig(
        fetch=FetchConfig(
            max_bytes=max_bytes,
            timeout_seconds=float(timeout),
            allowed_content_types=frozenset(content_types),
        ),
        watch=WatchConfig(stable_scans=stable_scans),
        parse=dict(parse),
    )


@lru_cache(maxsize=1)
def load_courts() -> dict[str, CourtConfig]:
    """Load config/courts.yaml, keyed by court code (DRAFT, A-26)."""
    data = _load_mapping("courts.yaml")
    entries = data.get("courts")
    if not isinstance(entries, list) or not entries:
        raise ValueError("courts.yaml: 'courts' must be a non-empty list")
    courts: dict[str, CourtConfig] = {}
    for index, entry in enumerate(entries):
        where = f"courts.yaml courts[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be a mapping")
        code = entry.get("code")
        name = entry.get("name")
        level = entry.get("level")
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z]{2,5}(?:-[A-Z]{2})?", code):
            raise ValueError(f"{where}: 'code' must be a court code such as SC or HC-KA")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{where}: 'name' must be a non-empty string")
        if level not in VALID_COURT_LEVELS:
            raise ValueError(f"{where}: level must be one of {sorted(VALID_COURT_LEVELS)}")
        if code in courts:
            raise ValueError(f"courts.yaml: duplicate court code '{code}'")
        patterns = _str_list(entry.get("patterns"), f"{where} patterns")
        if not patterns:
            raise ValueError(f"{where}: 'patterns' must not be empty")
        compiled = tuple(
            re.compile(re.escape(p).replace(r"\ ", r"\s+"), re.IGNORECASE) for p in patterns
        )
        courts[code] = CourtConfig(code=code, name=name, level=level, patterns=compiled)
    return courts


@lru_cache(maxsize=1)
def load_case_number_patterns() -> tuple[CaseNumberPattern, ...]:
    """Load case_number_patterns from config/citation_aliases.yaml (DRAFT, A-26)."""
    data = _load_mapping("citation_aliases.yaml")
    entries = data.get("case_number_patterns")
    if not isinstance(entries, list):
        raise ValueError("citation_aliases.yaml: 'case_number_patterns' must be a list")
    patterns: list[CaseNumberPattern] = []
    for index, entry in enumerate(entries):
        where = f"citation_aliases.yaml case_number_patterns[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be a mapping")
        abbr = entry.get("abbr")
        pattern = entry.get("pattern")
        if not isinstance(abbr, str) or not abbr:
            raise ValueError(f"{where}: 'abbr' must be a non-empty string")
        if not isinstance(pattern, str):
            raise ValueError(f"{where}: 'pattern' must be a string")
        compiled = re.compile(pattern, re.IGNORECASE)
        if not {"number", "year"} <= set(compiled.groupindex):
            raise ValueError(f"{where}: pattern needs named groups number and year")
        patterns.append(CaseNumberPattern(abbr=abbr, pattern=compiled))
    return tuple(patterns)


def clear_caches() -> None:
    """Forget loaded config (used by tests that change CONFIG_DIR)."""
    load_sources.cache_clear()
    load_doc_type_ranks.cache_clear()
    load_ingestion_config.cache_clear()
    load_courts.cache_clear()
    load_case_number_patterns.cache_clear()
