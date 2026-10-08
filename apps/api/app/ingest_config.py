"""Source and doc_type configuration for the ingestion endpoints.

Reads config/sources.yaml and config/authority.yaml, the same files the worker reads. The API
does not import the worker package. The location is $CONFIG_DIR, otherwise the nearest
config/ directory above this file (the container sets CONFIG_DIR=/app/config).
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SourceInfo:
    """The parts of a source entry that the API checks."""

    code: str
    kind: str
    enabled: bool
    allowed_hosts: frozenset[str]


def config_dir() -> Path:
    """Return the directory that holds sources.yaml and authority.yaml."""
    override = os.environ.get("CONFIG_DIR")
    if override:
        return Path(override)
    for parent in Path(__file__).resolve().parents:
        if (parent / "config" / "sources.yaml").is_file():
            return parent / "config"
    raise ValueError("config/sources.yaml not found; set CONFIG_DIR")


def _load(name: str) -> dict[str, Any]:
    with open(config_dir() / name, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{name} must contain a mapping")
    return data


@lru_cache(maxsize=1)
def load_sources() -> dict[str, SourceInfo]:
    """Return the sources from sources.yaml, keyed by code."""
    entries = _load("sources.yaml").get("sources") or []
    sources: dict[str, SourceInfo] = {}
    for entry in entries:
        code = str(entry["code"])
        hosts = entry.get("allowed_hosts") or []
        sources[code] = SourceInfo(
            code=code,
            kind=str(entry["kind"]),
            enabled=bool(entry["enabled"]),
            allowed_hosts=frozenset(str(host).strip().lower() for host in hosts),
        )
    return sources


@lru_cache(maxsize=1)
def load_doc_types() -> dict[str, int]:
    """Return the doc_type to authority rank map from authority.yaml."""
    doc_types = _load("authority.yaml").get("doc_types") or {}
    return {str(name): int(rank) for name, rank in doc_types.items()}
