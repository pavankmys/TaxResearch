"""Builders for synthetic PDF fixtures used by the parsing tests.

All text is Latin (fpdf2 core font Helvetica). Nothing here touches the database.
"""

import io
import math
from pathlib import Path

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

_DEJAVU = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
_BODY_TOP_MM = 30  # clear of the header and of the top margin band
_FOOTER_MM = 15


def _new_pdf() -> FPDF:
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=False)
    pdf.set_font("Helvetica", size=11)
    return pdf


def _header_footer(pdf: FPDF, header: str, page_no: int, footer: bool) -> None:
    pdf.set_font("Helvetica", size=9)
    pdf.set_xy(10, 8)
    pdf.cell(0, 6, header)
    if footer:
        pdf.set_xy(10, 297 - _FOOTER_MM)
        pdf.cell(0, 6, f"Page {page_no}", align="C")
    pdf.set_font("Helvetica", size=11)


def _chunks(items: list[str], parts: int) -> list[list[str]]:
    size = max(1, math.ceil(len(items) / parts))
    return [items[i : i + size] for i in range(0, len(items), size)] + [
        [] for _ in range(parts - math.ceil(len(items) / size))
    ]


def born_digital(
    paragraphs: list[str],
    pages: int = 2,
    header: str = "CBIC Notification",
    footer_with_page_numbers: bool = True,
    title: str = "",
) -> bytes:
    """A text-layer PDF. Paragraphs are spread over the pages in order.

    ``title`` only sets the PDF document title, so two calls with the same text and different
    titles give different bytes and the same extracted text.
    """
    pdf = _new_pdf()
    if title:
        pdf.set_title(title)
    for page_no, chunk in enumerate(_chunks(paragraphs, pages), start=1):
        pdf.add_page()
        _header_footer(pdf, header, page_no, footer_with_page_numbers)
        pdf.set_xy(10, _BODY_TOP_MM)
        for paragraph in chunk:
            pdf.multi_cell(0, 6, paragraph)
            pdf.ln(3)
    return bytes(pdf.output())


def two_column(left: list[str], right: list[str]) -> bytes:
    """One page with two text columns. Left column is drawn first, then right."""
    pdf = _new_pdf()
    pdf.add_page()
    for column_x, paragraphs in ((10, left), (110, right)):
        pdf.set_xy(column_x, _BODY_TOP_MM)
        for paragraph in paragraphs:
            pdf.set_x(column_x)  # ln() resets x to the margin, so set it per paragraph
            pdf.multi_cell(90, 5, paragraph)
            pdf.ln(2)
    return bytes(pdf.output())


def with_table(header: list[str], rows: list[list[str]]) -> bytes:
    """One page with an intro paragraph and a bordered table."""
    pdf = _new_pdf()
    pdf.add_page()
    pdf.set_xy(10, _BODY_TOP_MM)
    pdf.multi_cell(
        0,
        6,
        "The following rates apply to the supplies listed in the schedule below. "
        "Registered persons must apply the rate shown against each item. Where an item is "
        "not listed, the residual rate notified for the category applies, subject to the "
        "conditions and exemptions in the relevant notification and the explanatory notes.",
    )
    pdf.ln(4)
    pdf.set_font("Helvetica", size=10)
    with pdf.table(col_widths=(60, 40)) as table:
        head = table.row()
        for cell in header:
            head.cell(cell)
        for row_values in rows:
            row = table.row()
            for cell in row_values:
                row.cell(cell)
    return bytes(pdf.output())


def scanned(text: str) -> bytes:
    """An image-only PDF: the text is drawn onto a 300 dpi A4 page and saved as an image."""
    width, height = 2480, 3508  # A4 at 300 dpi
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    if _DEJAVU.exists():
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont = ImageFont.truetype(str(_DEJAVU), 56)
    else:
        font = ImageFont.load_default(size=56)
    y = 300
    for line in text.split("\n"):
        draw.text((200, y), line, fill="black", font=font)
        y += 110
    buffer = io.BytesIO()
    image.save(buffer, format="PDF", resolution=300.0)
    return buffer.getvalue()


def cid_garbled() -> bytes:
    """A page whose text is literal "(cid:N)" markers, as a broken font encoding looks."""
    pdf = _new_pdf()
    pdf.add_page()
    pdf.set_xy(10, _BODY_TOP_MM)
    garbage = "(cid:12) (cid:34) (cid:56) (cid:78) (cid:90) " * 10
    for _ in range(5):
        pdf.set_x(10)
        pdf.multi_cell(0, 6, garbage)
    return bytes(pdf.output())
