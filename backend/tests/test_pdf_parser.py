import io

import pytest
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from app.services.pdf_parser import PdfParseError, extract_text, to_markdown


def _make_pdf(lines: list[str]) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=LETTER)
    y = 750
    for line in lines:
        pdf.drawString(72, y, line)
        y -= 18
    pdf.save()
    return buffer.getvalue()


def test_extract_text_reads_a_real_pdf() -> None:
    data = _make_pdf(["Abhishek Thakur", "Senior Backend Engineer", "Python, FastAPI, Postgres"])
    text = extract_text(data)
    assert "Abhishek Thakur" in text
    assert "FastAPI" in text


def test_extract_text_rejects_empty_upload() -> None:
    with pytest.raises(PdfParseError, match="empty"):
        extract_text(b"")


def test_extract_text_rejects_non_pdf_bytes() -> None:
    with pytest.raises(PdfParseError):
        extract_text(b"this is definitely not a pdf")


def test_to_markdown_promotes_headings_and_bullets() -> None:
    raw = "EXPERIENCE\n• Built an API\n- Shipped a feature\nRegular prose line"
    markdown = to_markdown(raw)
    assert "## Experience" in markdown
    assert "- Built an API" in markdown
    assert "- Shipped a feature" in markdown
    assert "Regular prose line" in markdown


def test_to_markdown_round_trips_from_a_real_pdf() -> None:
    data = _make_pdf(["EXPERIENCE", "Built payment APIs at scale"])
    markdown = to_markdown(extract_text(data))
    assert "## Experience" in markdown
    assert "Built payment APIs at scale" in markdown
