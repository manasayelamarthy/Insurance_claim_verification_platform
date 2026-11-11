from __future__ import annotations

from pathlib import Path


class PolicyError(ValueError):
    """Raised when an assigned policy cannot be read."""


def read_policy_text(policy_file: Path) -> str:
    """Read text from one assigned policy PDF."""
    try:
        import pypdf
    except ImportError as error:
        raise PolicyError(
            "The server is using the wrong Python environment. Start it with "
            r".\.venv\Scripts\python.exe -m uvicorn app.web:app --reload"
        ) from error

    try:
        reader = pypdf.PdfReader(str(policy_file))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except (OSError, pypdf.errors.PdfReadError) as error:
        raise PolicyError(f"Unable to read policy PDF: {policy_file.name}") from error

    if not text:
        raise PolicyError(f"Policy PDF contains no readable text: {policy_file.name}")
    return text
