"""HTML parsing with the standard library: headings, paragraphs, lists and tables become blocks."""

import re
from html.parser import HTMLParser

from legal_core.text import normalise_text

from worker.ingest.quality import detect_lang, garble_score, para_label, table_texts
from worker.ingest.types import Block, PageResult, ParseConfig, ParseResult

PARSER_VERSION = "html-1"

_SKIP_TAGS = frozenset({"script", "style", "nav", "header", "footer", "noscript", "head", "title"})
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_BLOCK_TAGS = frozenset(
    {
        "p",
        "li",
        "blockquote",
        "div",
        "section",
        "article",
        "main",
        "ul",
        "ol",
        "dl",
        "dd",
        "dt",
        "pre",
        "address",
        "hr",
    }
)
_CHARSET = re.compile(rb"<meta[^>]+charset\s*=\s*[\"']?\s*([A-Za-z0-9_\-]+)", re.IGNORECASE)


class _Extractor(HTMLParser):
    """Collects (kind, text) pairs in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[str, str]] = []
        self._skip = 0
        self._buf: list[str] = []
        self._kind = "para"
        self._table_depth = 0
        self._rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "table":
            if self._table_depth == 0:
                self._flush()
                self._rows = []
            self._table_depth += 1
            return
        if self._table_depth:
            self._table_tag_start(tag)
            return
        if tag == "br":
            self._buf.append(" ")
        elif tag in _HEADING_TAGS:
            self._flush()
            self._kind = "heading"
        elif tag in _BLOCK_TAGS:
            self._flush()
            self._kind = "para"

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0:
                self._emit_table()
            return
        if self._table_depth:
            self._table_tag_end(tag)
            return
        if tag in _HEADING_TAGS or tag in _BLOCK_TAGS:
            self._flush()
            self._kind = "para"

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._table_depth:
            if self._cell is not None:
                self._cell.append(data)
            return
        self._buf.append(data)

    def finish(self) -> None:
        """Flush pending text and close any table left open by malformed markup."""
        self._flush()
        if self._table_depth:
            self._table_depth = 0
            self._emit_table()

    def _table_tag_start(self, tag: str) -> None:
        if self._table_depth > 1:
            return
        if tag == "tr":
            self._close_row()
            self._row = []
        elif tag in ("td", "th"):
            self._close_cell()
            if self._row is None:
                self._row = []
            self._cell = []
        elif tag in _BLOCK_TAGS and self._cell is not None:
            self._cell.append(" ")

    def _table_tag_end(self, tag: str) -> None:
        if self._table_depth > 1:
            return
        if tag in ("td", "th"):
            self._close_cell()
        elif tag == "tr":
            self._close_row()
        elif tag in _BLOCK_TAGS and self._cell is not None:
            self._cell.append(" ")

    def _close_cell(self) -> None:
        if self._cell is not None:
            if self._row is None:
                self._row = []
            self._row.append(normalise_text("".join(self._cell)))
            self._cell = None

    def _close_row(self) -> None:
        self._close_cell()
        if self._row is not None:
            if any(self._row):
                self._rows.append(self._row)
            self._row = None

    def _emit_table(self) -> None:
        self._close_row()
        table_text, row_texts = table_texts(self._rows)
        self._rows = []
        if not table_text:
            return
        self.items.append(("table", table_text))
        self.items.extend(("table_row", text) for text in row_texts)

    def _flush(self) -> None:
        text = normalise_text("".join(self._buf))
        self._buf = []
        if text:
            self.items.append((self._kind, text))


def _decode(data: bytes) -> str:
    match = _CHARSET.search(data[:4096])
    if match is not None:
        try:
            return data.decode(match.group(1).decode("ascii"), errors="replace")
        except LookupError:
            pass
    return data.decode("utf-8", errors="replace")


def parse_html(data: bytes, cfg: ParseConfig) -> ParseResult:
    """Parse an HTML document into blocks and a single page-accounting row."""
    extractor = _Extractor()
    extractor.feed(_decode(data))
    extractor.close()
    extractor.finish()

    blocks: list[Block] = []
    for seq, (kind, text) in enumerate(extractor.items):
        label = para_label(text) if kind == "para" else None
        blocks.append(
            Block(
                seq=seq,
                kind=kind,
                page=1,
                bbox=None,
                para_label=label,
                text=text,
                is_boilerplate=False,
                lang=detect_lang(text),
            )
        )

    page_text = "\n\n".join(block.text for block in blocks)
    chars = sum(1 for ch in page_text if not ch.isspace())
    garble = garble_score(page_text)
    flagged = garble > cfg.garble_threshold
    page = PageResult(
        page_no=1,
        method="text",
        chars_engine_a=None,
        chars_engine_b=chars,
        garble_score=garble,
        ocr_conf=None,
        status="flagged" if flagged else "ok",
        flagged=flagged,
        text=page_text,
        reason="garbled" if flagged else None,
    )
    return ParseResult(
        page_count=1,
        pages=[page],
        blocks=blocks,
        ocr_used=False,
        ocr_conf=None,
        parser_version=PARSER_VERSION,
    )
