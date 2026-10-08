"""Dataclasses shared by the PDF and HTML parsers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ParseConfig:
    """Thresholds and switches for parsing (values come from config/ingestion.yaml)."""

    min_chars_per_page_area: float = 0.00002  # chars per pt^2, ~10 chars on A4
    cross_check_margin: float = 0.05  # relative |a-b|/max(a,b,1)
    garble_threshold: float = 0.15
    min_ocr_conf: float = 60.0
    ocr_dpi: int = 300
    ocr_lang: str = "eng"
    ocr_enabled: bool = True
    parser_version: str = "pdf-1"


@dataclass(frozen=True)
class PageResult:
    """Extraction outcome for one page (page accounting row)."""

    page_no: int  # 1-based
    method: str  # "text" | "ocr" | "failed"
    chars_engine_a: int | None  # pypdfium2
    chars_engine_b: int | None  # pdfplumber
    garble_score: float | None
    ocr_conf: float | None
    status: str  # "ok" | "flagged" | "failed"
    flagged: bool
    text: str  # final page text (used for page_texts)
    reason: str | None  # why flagged/failed


@dataclass(frozen=True)
class Block:
    """One unit of extracted content, in reading order."""

    seq: int
    kind: str  # "heading" | "para" | "table" | "table_row" | "footnote"
    page: int | None
    bbox: dict[str, float] | None  # {"x0", "top", "x1", "bottom"} in PDF points
    para_label: str | None
    text: str
    is_boilerplate: bool
    lang: str | None  # "en" | "hi" | None


@dataclass(frozen=True)
class ParseResult:
    """Everything a parser produces for one document."""

    page_count: int
    pages: list[PageResult]
    blocks: list[Block]
    ocr_used: bool
    ocr_conf: float | None  # mean over OCR'd pages
    parser_version: str
