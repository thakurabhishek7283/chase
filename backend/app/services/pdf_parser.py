import io
import re

import pdfplumber
from pypdf import PdfReader


class PdfParseError(ValueError):
    """Raised when a PDF cannot be read or contains no extractable text."""


_WHITESPACE_RUN = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def _normalize(text: str) -> str:
    """Collapse the ragged whitespace PDF extraction tends to produce."""
    lines = [_WHITESPACE_RUN.sub(" ", line).strip() for line in text.splitlines()]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def extract_text(data: bytes) -> str:
    """Extract plain text from a resume PDF.

    Tries pdfplumber first — it preserves layout-derived spacing better on the
    multi-column layouts common in resumes — and falls back to pypdf, which
    handles some malformed files pdfplumber rejects.
    """
    if not data:
        raise PdfParseError("Uploaded file is empty.")

    text = _extract_with_pdfplumber(data)
    if not text:
        text = _extract_with_pypdf(data)

    if not text:
        raise PdfParseError(
            "No text could be extracted. The PDF may be a scanned image, "
            "which requires OCR rather than text extraction."
        )
    return text


def _extract_with_pdfplumber(data: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    except Exception:
        return ""
    return _normalize("\n\n".join(pages))


def _extract_with_pypdf(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise PdfParseError(f"Could not read the PDF: {exc}") from exc
    return _normalize("\n\n".join(pages))


def to_markdown(text: str) -> str:
    """Best-effort conversion of extracted text into the Markdown the app stores.

    Deliberately conservative: it promotes lines that look like section headings
    and normalizes bullet glyphs, but does not try to reconstruct rich layout.
    """
    heading_pattern = re.compile(r"^[A-Z][A-Z \t&/-]{2,40}$")
    bullet_pattern = re.compile(r"^[•▪◦‣·\-\*]\s*")

    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            out.append("")
        elif heading_pattern.match(stripped):
            out.append(f"## {stripped.title()}")
        elif bullet_pattern.match(stripped):
            out.append(f"- {bullet_pattern.sub('', stripped)}")
        else:
            out.append(stripped)
    return _BLANK_LINES.sub("\n\n", "\n".join(out)).strip()
