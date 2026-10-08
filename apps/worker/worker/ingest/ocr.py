"""OCR: pypdfium2 renders a page, the Tesseract CLI reads it (TSV output gives word confidences)."""

import io
import shutil
import subprocess

import pypdfium2 as pdfium  # type: ignore[import-untyped]

_TIMEOUT_SECONDS = 120


class OcrError(RuntimeError):
    """Tesseract could not read the image."""


def tesseract_available() -> bool:
    """True when the `tesseract` binary is on PATH."""
    return shutil.which("tesseract") is not None


def ocr_image(png_bytes: bytes, lang: str) -> tuple[str, float]:
    """Run Tesseract on a PNG image.

    Returns (text, mean word confidence). The confidence is 0.0 when no word is found.
    """
    proc = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", lang, "--psm", "3", "tsv"],
        input=png_bytes,
        capture_output=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise OcrError(f"tesseract exited with {proc.returncode}: {detail}")
    return _tsv_to_text(proc.stdout.decode("utf-8", errors="replace"))


def _tsv_to_text(tsv: str) -> tuple[str, float]:
    """Rebuild text from Tesseract TSV: words to lines, lines to paragraphs."""
    paragraphs: dict[tuple[str, str], dict[str, list[str]]] = {}
    confidences: list[float] = []
    lines = tsv.splitlines()
    for raw in lines[1:]:
        parts = raw.split("\t")
        if len(parts) != 12 or parts[0] != "5":
            continue
        word = parts[11].strip()
        conf = float(parts[10])
        if conf < 0 or not word:
            continue
        confidences.append(conf)
        para_key = (parts[2], parts[3])
        line_key = parts[4]
        para = paragraphs.setdefault(para_key, {})
        para.setdefault(line_key, []).append(word)

    if not confidences:
        return "", 0.0
    text = "\n\n".join(
        "\n".join(" ".join(words) for words in para.values()) for para in paragraphs.values()
    )
    return text, sum(confidences) / len(confidences)


def render_page_png(page: pdfium.PdfPage, dpi: int) -> bytes:
    """Render a pypdfium2 page to PNG bytes at the given resolution."""
    bitmap = page.render(scale=dpi / 72)
    try:
        image = bitmap.to_pil()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        bitmap.close()
