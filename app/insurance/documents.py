from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.insurance.ocr import TesseractOCR


class DocumentError(ValueError):
    """Raised when an uploaded claim document cannot be processed."""


@dataclass(frozen=True)
class ExtractedDocument:
    filename: str
    document_type: str
    text: str


SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".png", ".jpg", ".jpeg"}


def extract_document(path: Path) -> ExtractedDocument:
    """Extract text from a text file, PDF, or image."""
    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentError(f"Unsupported document type: {extension or '<none>'}")

    if extension == ".txt":
        text = read_text_file(path)
        document_type = "text"
    elif extension == ".pdf":
        text = read_pdf(path)
        document_type = "pdf"
    else:
        text = TesseractOCR().extract(path)
        document_type = "image"

    return ExtractedDocument(
        filename=path.name,
        document_type=document_type,
        text=text,
    )


def read_text_file(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise DocumentError(f"Unable to read text file: {path.name}") from error
    if not text:
        raise DocumentError(f"Text file is empty: {path.name}")
    return text


def read_pdf(path: Path) -> str:
    try:
        import pypdf

        reader = pypdf.PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except (OSError, pypdf.errors.PdfReadError) as error:
        raise DocumentError(f"Unable to read PDF: {path.name}") from error
    if not text:
        raise DocumentError(f"PDF contains no readable text: {path.name}")
    return text
