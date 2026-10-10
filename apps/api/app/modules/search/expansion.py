"""Query expansion using expert-maintained synonyms and abbreviations (TSD 6.4a)."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import yaml
from app.ingest_config import config_dir


@lru_cache(maxsize=1)
def load_synonyms() -> list[dict[str, Any]]:
    """Load active synonym entries from config/synonyms.yaml."""
    path = config_dir() / "synonyms.yaml"
    if not path.is_file():
        return []
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        return []
    entries = data.get("synonyms") or []
    return [e for e in entries if isinstance(e, dict) and e.get("active", True)]


def expand_query(query: str, expand: bool = True) -> tuple[str, list[str]]:
    """Expand search query with synonyms and abbreviations (TSD 6.4a).

    Returns:
        (augmented_query, expanded_terms)
    """
    cleaned = (query or "").strip()
    if not cleaned or not expand:
        return cleaned, []

    synonyms = load_synonyms()
    expanded_terms: list[str] = []
    replacement_phrases: list[str] = []

    for entry in synonyms:
        term = str(entry.get("term", "")).strip()
        if not term:
            continue
        expansions = entry.get("expansions") or []
        pattern = rf"\b{re.escape(term)}\b"

        if re.search(pattern, cleaned, re.IGNORECASE):
            for exp in expansions:
                exp_clean = str(exp).strip()
                if exp_clean and exp_clean not in expanded_terms:
                    expanded_terms.append(exp_clean)
                    replacement_phrases.append(f'"{exp_clean}"')

    if not replacement_phrases:
        return cleaned, []

    # OR-append expanded phrases with lower weight
    augmented = f"{cleaned} OR ({' OR '.join(replacement_phrases)})"
    return augmented, expanded_terms
