from __future__ import annotations

import shutil
from pathlib import Path


class OCRError(RuntimeError):
    """Raised when image text extraction cannot be completed."""


class TesseractOCR:
    """Extract text from an image using the locally installed Tesseract binary."""

    def __init__(self, language: str = "eng") -> None:
        self.language = language

    def extract(self, image_path: Path) -> str:
        try:
            import pytesseract
            from PIL import Image
        except ImportError as error:
            raise OCRError(
                "OCR dependencies are missing; install pytesseract and Pillow"
            ) from error

        try:
            if pytesseract.pytesseract.tesseract_cmd == "tesseract":
                installed_tesseract = Path(
                    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
                )
                if installed_tesseract.is_file():
                    pytesseract.pytesseract.tesseract_cmd = str(installed_tesseract)
                elif shutil.which("tesseract") is None:
                    raise OCRError(
                        "Tesseract executable is not installed or not on PATH"
                    )
            with Image.open(image_path) as image:
                text = pytesseract.image_to_string(image, lang=self.language)
        except (OSError, pytesseract.TesseractError) as error:
            raise OCRError(
                "Tesseract OCR failed; install the Tesseract executable and retry"
            ) from error

        if not text.strip():
            raise OCRError(f"OCR returned no text for {image_path.name}")
        return text
