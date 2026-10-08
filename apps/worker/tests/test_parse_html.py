"""Tests for the HTML parser."""

from worker.ingest.html import parse_html
from worker.ingest.types import ParseConfig

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Notification</title>
<style>p { color: red; }</style></head>
<body>
<nav>Home | Notifications</nav>
<header>Site header</header>
<script>var secret = 1;</script>
<h2>Notification No. 11/2017</h2>
<p>1. The rate of tax on   the supply
   of goods shall be as notified.</p>
<div>Loose text inside a div.</div>
<ul><li>(a) first item</li></ul>
<table>
  <tr><th>Item</th><th>Rate</th></tr>
  <tr><td>Cement</td><td>28%</td></tr>
</table>
<footer>Footer text</footer>
</body></html>
"""


def _blocks() -> list[tuple[str, str]]:
    result = parse_html(_PAGE.encode("utf-8"), ParseConfig())
    return [(b.kind, b.text) for b in result.blocks]


def test_html_headings_paragraphs_and_tables() -> None:
    blocks = _blocks()
    assert blocks[0] == ("heading", "Notification No. 11/2017")
    assert blocks[1] == ("para", "1. The rate of tax on the supply of goods shall be as notified.")
    assert ("para", "Loose text inside a div.") in blocks
    assert ("para", "(a) first item") in blocks
    assert ("table", "Item | Rate\nCement | 28%") in blocks
    assert ("table_row", "Item: Cement; Rate: 28%") in blocks


def test_html_skips_ignored_elements() -> None:
    text = " ".join(t for _, t in _blocks())
    for hidden in ("Home", "Site header", "secret", "color", "Footer text"):
        assert hidden not in text


def test_html_para_labels_and_pages() -> None:
    result = parse_html(_PAGE.encode("utf-8"), ParseConfig())
    labels = {b.text[:3]: b.para_label for b in result.blocks if b.kind == "para"}
    assert labels["1. "] == "1"
    assert labels["(a)"] == "(a)"
    assert result.page_count == 1
    assert len(result.pages) == 1
    assert result.pages[0].method == "text"
    assert result.parser_version == "html-1"
    assert all(b.page == 1 and b.bbox is None for b in result.blocks)
    assert [b.seq for b in result.blocks] == list(range(len(result.blocks)))


def test_html_charset_from_meta() -> None:
    body = '<html><head><meta charset="iso-8859-1"></head><body><p>caf\xe9 tax</p></body></html>'
    result = parse_html(body.encode("iso-8859-1"), ParseConfig())
    assert result.blocks[0].text == "café tax"


def test_html_empty_document() -> None:
    result = parse_html(b"", ParseConfig())
    assert result.page_count == 1
    assert result.blocks == []
