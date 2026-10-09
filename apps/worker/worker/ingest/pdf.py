"""PDF parsing: per-page text-layer test, two-engine cross-check, OCR fallback, blocks.

Every page gets a PageResult, so len(pages) always equals page_count. A page that raises
is recorded as "failed" with reason "exception: <ErrorType>".
"""

import io
import math
import re
import statistics
from dataclasses import dataclass
from typing import Any

import pdfplumber
import pypdfium2 as pdfium  # type: ignore[import-untyped]
from legal_core.text import normalise_text
from pdfplumber.pdf import PDF

from worker.ingest.ocr import ocr_image, render_page_png, tesseract_available
from worker.ingest.quality import (
    cross_check_mismatch,
    detect_lang,
    garble_score,
    para_label,
    starts_numbered,
    table_texts,
)
from worker.ingest.types import Block, PageResult, ParseConfig, ParseResult

Word = dict[str, Any]
_FLAG_TRIGGERS = frozenset({"garbled", "cross_check_mismatch"})
_ZONE_FRACTION = 0.08
_LINE_TOLERANCE = 3.0
_HEADING_MAX_CHARS = 80
_GUTTER_BAND = (0.35, 0.65)  # fraction of page width searched for a gutter
_GUTTER_MIN_WIDTH = 0.02  # fraction of page width
_COLUMN_WORD_SHARE = 0.7
_COLUMN_MIN_WORDS = 3


class PdfParseError(Exception):
    """The bytes could not be opened as a PDF."""


@dataclass
class _Line:
    text: str
    top: float
    bottom: float
    x0: float
    x1: float
    bold: bool
    zone_key: str | None  # set when the line sits in the top or bottom margin band


@dataclass(frozen=True)
class _Draft:
    """A block before boilerplate and seq numbers are known."""

    kind: str
    page: int
    bbox: dict[str, float] | None
    text: str
    para_label: str | None
    line_keys: tuple[str | None, ...]  # margin keys of the lines, empty when not applicable


def parse_pdf(data: bytes, cfg: ParseConfig) -> ParseResult:
    """Parse PDF bytes into per-page results and reading-order blocks."""
    try:
        engine_a = pdfium.PdfDocument(data)
    except Exception as exc:
        raise PdfParseError(f"pypdfium2 cannot open the PDF: {exc}") from exc
    try:
        try:
            engine_b = pdfplumber.open(io.BytesIO(data))
        except Exception as exc:
            raise PdfParseError(f"pdfplumber cannot open the PDF: {exc}") from exc
        try:
            return _parse_open(engine_a, engine_b, cfg)
        finally:
            engine_b.close()
    finally:
        engine_a.close()


def _parse_open(engine_a: pdfium.PdfDocument, engine_b: PDF, cfg: ParseConfig) -> ParseResult:
    page_count = len(engine_a)
    pages: list[PageResult] = []
    drafts: list[_Draft] = []
    for index in range(page_count):
        page_no = index + 1
        try:
            result, page_drafts = _extract_page(engine_a, engine_b, index, cfg)
        except Exception as exc:
            result = PageResult(
                page_no=page_no,
                method="failed",
                chars_engine_a=None,
                chars_engine_b=None,
                garble_score=None,
                ocr_conf=None,
                status="failed",
                flagged=True,
                text="",
                reason=f"exception: {type(exc).__name__}",
            )
            page_drafts = []
        pages.append(result)
        drafts.extend(page_drafts)

    ocr_confs = [p.ocr_conf for p in pages if p.method == "ocr" and p.ocr_conf is not None]
    return ParseResult(
        page_count=page_count,
        pages=pages,
        blocks=_finalise_blocks(drafts, page_count),
        ocr_used=any(p.method == "ocr" for p in pages),
        ocr_conf=statistics.fmean(ocr_confs) if ocr_confs else None,
        parser_version=cfg.parser_version,
    )


def _extract_page(
    engine_a: pdfium.PdfDocument,
    engine_b: PDF,
    index: int,
    cfg: ParseConfig,
) -> tuple[PageResult, list[_Draft]]:
    page_no = index + 1
    text_a = _engine_a_text(engine_a, index)
    plumber_page = engine_b.pages[index]
    text_b = plumber_page.extract_text() or ""
    chars_a = _non_space(text_a)
    chars_b = _non_space(text_b)
    area = float(plumber_page.width) * float(plumber_page.height)
    density = chars_b / area if area > 0 else 0.0
    garble = garble_score(text_b)

    trigger = _ocr_trigger(density, garble, chars_a, chars_b, cfg)
    if trigger is None:
        result = PageResult(
            page_no=page_no,
            method="text",
            chars_engine_a=chars_a,
            chars_engine_b=chars_b,
            garble_score=garble,
            ocr_conf=None,
            status="ok",
            flagged=False,
            text=text_b,
            reason=None,
        )
        return result, _text_drafts(plumber_page, page_no)
    return _ocr_page(engine_a, index, trigger, text_b, (chars_a, chars_b, garble), cfg)


def _ocr_trigger(
    density: float, garble: float, chars_a: int, chars_b: int, cfg: ParseConfig
) -> str | None:
    if density < cfg.min_chars_per_page_area:
        return "no_text"
    if garble > cfg.garble_threshold:
        return "garbled"
    if cross_check_mismatch(chars_a, chars_b, cfg.cross_check_margin):
        return "cross_check_mismatch"
    return None


def _ocr_page(
    engine_a: pdfium.PdfDocument,
    index: int,
    trigger: str,
    text_b: str,
    counts: tuple[int, int, float],
    cfg: ParseConfig,
) -> tuple[PageResult, list[_Draft]]:
    page_no = index + 1
    chars_a, chars_b, garble = counts
    if not cfg.ocr_enabled or not tesseract_available():
        result = PageResult(
            page_no=page_no,
            method="failed",
            chars_engine_a=chars_a,
            chars_engine_b=chars_b,
            garble_score=garble,
            ocr_conf=None,
            status="failed",
            flagged=True,
            text=text_b,
            reason=f"ocr_unavailable:{trigger}",
        )
        return result, []

    ocr_text, conf = ocr_image(_render(engine_a, index, cfg.ocr_dpi), cfg.ocr_lang)
    if conf < cfg.min_ocr_conf:
        result = PageResult(
            page_no=page_no,
            method="ocr",
            chars_engine_a=chars_a,
            chars_engine_b=chars_b,
            garble_score=garble,
            ocr_conf=conf,
            status="failed",
            flagged=True,
            text=ocr_text,
            reason="low_ocr_conf",
        )
        return result, []

    flagged = trigger in _FLAG_TRIGGERS
    result = PageResult(
        page_no=page_no,
        method="ocr",
        chars_engine_a=chars_a,
        chars_engine_b=chars_b,
        garble_score=garble,
        ocr_conf=conf,
        status="flagged" if flagged else "ok",
        flagged=flagged,
        text=ocr_text,
        reason=trigger if flagged else None,
    )
    return result, _ocr_drafts(ocr_text, page_no)


def _engine_a_text(engine_a: pdfium.PdfDocument, index: int) -> str:
    page = engine_a[index]
    try:
        textpage = page.get_textpage()
        try:
            return str(textpage.get_text_range())
        finally:
            textpage.close()
    finally:
        page.close()


def _render(engine_a: pdfium.PdfDocument, index: int, dpi: int) -> bytes:
    page = engine_a[index]
    try:
        return render_page_png(page, dpi)
    finally:
        page.close()


def _non_space(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


# --- Text pages -------------------------------------------------------------------------


_MAX_SKEW = 0.1  # |sin| of the text angle; a diagonal watermark is far above this


def _is_axis_aligned(obj: dict[str, Any]) -> bool:
    """False for characters drawn at an angle (a diagonal watermark); True for everything else."""
    if obj.get("object_type") != "char":
        return True
    matrix = obj.get("matrix")
    if not matrix:
        return True
    return abs(float(matrix[1])) < _MAX_SKEW and abs(float(matrix[2])) < _MAX_SKEW


def _text_drafts(page: Any, page_no: int) -> list[_Draft]:
    """Blocks for a page with a usable text layer, in reading order.

    Characters drawn at an angle (the diagonal portal watermark on India Code PDFs) are dropped,
    because they split into single-letter blocks and break words in the body text.
    """
    page = page.filter(_is_axis_aligned)
    width = float(page.width)
    height = float(page.height)
    words: list[Word] = page.extract_words(
        keep_blank_chars=False, use_text_flow=False, extra_attrs=["fontname"]
    )
    table_groups = _table_groups(page, page_no)
    body = [w for w in words if not any(_inside(w, bbox) for bbox, _ in table_groups)]

    gutter = _two_column_gutter(body, width)
    if gutter is None:
        columns: list[list[Word]] = [body]
    else:
        columns = [
            [w for w in body if _centre_x(w) < gutter],
            [w for w in body if _centre_x(w) >= gutter],
        ]

    items: list[tuple[int, float, list[_Draft]]] = []
    for col, col_words in enumerate(columns):
        for group in _paragraph_groups(_group_lines(col_words, height)):
            items.append((col, group[0].top, [_group_draft(group, page_no)]))
    for bbox, drafts in table_groups:
        col = 0 if gutter is None else _column_of((bbox[0] + bbox[2]) / 2, gutter)
        items.append((col, bbox[1], drafts))

    items.sort(key=lambda item: (item[0], item[1]))
    return [draft for _, _, drafts in items for draft in drafts]


def _column_of(x: float, gutter: float) -> int:
    return 0 if x < gutter else 1


def _centre_x(word: Word) -> float:
    return (float(word["x0"]) + float(word["x1"])) / 2


def _inside(word: Word, bbox: tuple[float, float, float, float]) -> bool:
    cy = (float(word["top"]) + float(word["bottom"])) / 2
    return bbox[0] <= _centre_x(word) <= bbox[2] and bbox[1] <= cy <= bbox[3]


def _table_groups(
    page: Any, page_no: int
) -> list[tuple[tuple[float, float, float, float], list[_Draft]]]:
    groups: list[tuple[tuple[float, float, float, float], list[_Draft]]] = []
    for table in page.find_tables():
        drafts = _table_drafts(table, page_no)
        if drafts:
            x0, top, x1, bottom = (float(v) for v in table.bbox)
            groups.append(((x0, top, x1, bottom), drafts))
    return groups


def _table_drafts(table: Any, page_no: int) -> list[_Draft]:
    raw_rows: list[list[str | None]] = table.extract() or []
    rows = [[cell or "" for cell in row] for row in raw_rows]
    table_text, row_texts = table_texts(rows)
    if not table_text:
        return []
    x0, top, x1, bottom = (float(v) for v in table.bbox)
    drafts = [_Draft("table", page_no, _bbox(x0, top, x1, bottom), table_text, None, ())]
    drafts.extend(_Draft("table_row", page_no, None, text, None, ()) for text in row_texts)
    return drafts


def _two_column_gutter(words: list[Word], width: float) -> float | None:
    """Return the x position of a vertical gutter if the page looks like two columns."""
    if width <= 0 or len(words) < 2 * _COLUMN_MIN_WORDS:
        return None
    lo, hi = _GUTTER_BAND[0] * width, _GUTTER_BAND[1] * width
    spans = sorted(
        (float(w["x0"]), float(w["x1"]))
        for w in words
        if float(w["x1"]) > lo and float(w["x0"]) < hi
    )
    merged: list[list[float]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    gaps: list[tuple[float, float]] = []
    cursor = lo
    for start, end in merged:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < hi:
        gaps.append((cursor, hi))

    wide = [
        (end - start, (start + end) / 2)
        for start, end in gaps
        if end - start >= _GUTTER_MIN_WIDTH * width
    ]
    if not wide:
        return None
    gutter = max(wide)[1]

    left = sum(1 for w in words if float(w["x1"]) <= gutter)
    right = sum(1 for w in words if float(w["x0"]) >= gutter)
    if left < _COLUMN_MIN_WORDS or right < _COLUMN_MIN_WORDS:
        return None
    if (left + right) / len(words) < _COLUMN_WORD_SHARE:
        return None
    return gutter


def _group_lines(words: list[Word], height: float) -> list[_Line]:
    ordered = sorted(words, key=lambda w: (float(w["top"]), float(w["x0"])))
    rows: list[list[Word]] = []
    for word in ordered:
        if rows and abs(float(word["top"]) - float(rows[-1][0]["top"])) <= _LINE_TOLERANCE:
            rows[-1].append(word)
        else:
            rows.append([word])

    lines: list[_Line] = []
    for row in rows:
        row.sort(key=lambda w: float(w["x0"]))
        text = " ".join(str(w["text"]) for w in row)
        top = min(float(w["top"]) for w in row)
        bottom = max(float(w["bottom"]) for w in row)
        lines.append(
            _Line(
                text=text,
                top=top,
                bottom=bottom,
                x0=min(float(w["x0"]) for w in row),
                x1=max(float(w["x1"]) for w in row),
                bold=all("bold" in str(w.get("fontname", "")).lower() for w in row),
                zone_key=_zone_key(text, top, bottom, height),
            )
        )
    return lines


def _zone_key(text: str, top: float, bottom: float, height: float) -> str | None:
    """Normalised text for lines in the top or bottom margin band (digits masked)."""
    if height <= 0:
        return None
    if top < _ZONE_FRACTION * height or bottom > (1 - _ZONE_FRACTION) * height:
        return normalise_text(re.sub(r"\d+", "#", text)).lower()
    return None


def _is_heading(line: _Line) -> bool:
    text = line.text
    return (
        len(text) < _HEADING_MAX_CHARS
        and any(ch.isalpha() for ch in text)
        and (text.isupper() or line.bold)
    )


# A numbered line that starts_numbered misses: an amendment bracket with its footnote digit
# ("1[20. Manner"), a bracketed sub-item ("[(2) Subject"), a spaced dot ("80 . Payment") or no
# space after the dot ("31.Residual"). Acts and Rules published "as amended" use all of these.
_AMENDED_NUMBERING = re.compile(
    r"^(?:\d{1,3}\s*)?\[\s*(?:\d{1,3}[A-Z]{0,2}\s?\.|\(\s*\w{1,4}\s*\))"
    r"|^\d{1,3}[A-Z]{0,2}\s\.\s"
    r"|^\d{1,3}[A-Z]{0,2}\.[A-Z][a-z]"
)


def _paragraph_groups(lines: list[_Line]) -> list[list[_Line]]:
    if not lines:
        return []
    median_height = max(statistics.median(line.bottom - line.top for line in lines), 1.0)
    groups: list[list[_Line]] = [[lines[0]]]
    for prev, cur in zip(lines, lines[1:], strict=False):
        breaks = (
            cur.top - prev.bottom > 1.5 * median_height
            or starts_numbered(cur.text)
            or _AMENDED_NUMBERING.match(cur.text) is not None
            or _is_heading(prev)
            or _is_heading(cur)
            or bool(prev.zone_key) != bool(cur.zone_key)
        )
        if breaks:
            groups.append([cur])
        else:
            groups[-1].append(cur)
    return groups


def _group_draft(lines: list[_Line], page_no: int) -> _Draft:
    text = normalise_text(" ".join(line.text for line in lines))
    heading = len(lines) == 1 and _is_heading(lines[0])
    bbox = _bbox(
        min(line.x0 for line in lines),
        min(line.top for line in lines),
        max(line.x1 for line in lines),
        max(line.bottom for line in lines),
    )
    return _Draft(
        kind="heading" if heading else "para",
        page=page_no,
        bbox=bbox,
        text=text,
        para_label=None if heading else para_label(text),
        line_keys=tuple(line.zone_key for line in lines),
    )


def _bbox(x0: float, top: float, x1: float, bottom: float) -> dict[str, float]:
    return {"x0": x0, "top": top, "x1": x1, "bottom": bottom}


# --- OCR pages --------------------------------------------------------------------------


def _ocr_drafts(text: str, page_no: int) -> list[_Draft]:
    drafts: list[_Draft] = []
    for chunk in re.split(r"\n\s*\n", text):
        para = normalise_text(chunk)
        if para:
            drafts.append(_Draft("para", page_no, None, para, para_label(para), ()))
    return drafts


# --- Document-level assembly ------------------------------------------------------------


def _finalise_blocks(drafts: list[_Draft], page_count: int) -> list[Block]:
    """Flag repeated margin lines as boilerplate and number the blocks in reading order."""
    pages_by_key: dict[str, set[int]] = {}
    for draft in drafts:
        for key in draft.line_keys:
            if key:
                pages_by_key.setdefault(key, set()).add(draft.page)
    min_pages = max(3, math.ceil(page_count / 2))
    boilerplate = {key for key, pages in pages_by_key.items() if len(pages) >= min_pages}

    blocks: list[Block] = []
    for seq, draft in enumerate(drafts):
        is_boilerplate = bool(draft.line_keys) and all(
            key is not None and key in boilerplate for key in draft.line_keys
        )
        blocks.append(
            Block(
                seq=seq,
                kind=draft.kind,
                page=draft.page,
                bbox=draft.bbox,
                para_label=draft.para_label,
                text=draft.text,
                is_boilerplate=is_boilerplate,
                lang=detect_lang(draft.text),
            )
        )
    return blocks
