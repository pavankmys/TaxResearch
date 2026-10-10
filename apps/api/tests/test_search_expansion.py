"""Unit tests for query expansion using synonyms (TSD 6.4a)."""

from app.modules.search.expansion import expand_query


def test_expand_query_disabled() -> None:
    query = "ITC mismatch in returns"
    augmented, terms = expand_query(query, expand=False)
    assert augmented == query
    assert terms == []


def test_expand_query_empty() -> None:
    augmented, terms = expand_query("", expand=True)
    assert augmented == ""
    assert terms == []


def test_expand_query_itc() -> None:
    query = "conditions for availing ITC"
    augmented, terms = expand_query(query, expand=True)
    assert len(terms) > 0
    assert any("input tax credit" in t.lower() for t in terms)
    assert "OR" in augmented


def test_expand_query_rcm() -> None:
    query = "liability under RCM"
    augmented, terms = expand_query(query, expand=True)
    assert any("reverse charge" in t.lower() for t in terms)


def test_expand_query_no_synonyms() -> None:
    query = "completely random query without acronyms"
    augmented, terms = expand_query(query, expand=True)
    assert augmented == query
    assert terms == []
