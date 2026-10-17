"""PDF text extraction with poppler's `pdftotext`. Needs poppler (installed in the Docker image)."""

import os
import shutil
import subprocess
import tempfile


class PdfToolUnavailable(RuntimeError):
    """pdftotext is not installed on this machine."""


def render_first_page_png(data: bytes, dpi: int = 150, timeout: int = 60) -> bytes:
    """Page 1 of a PDF as a PNG (for scans with no text layer). Empty bytes if it can't be rendered."""
    exe = shutil.which("pdftoppm")
    if exe is None:
        raise PdfToolUnavailable("pdftoppm (poppler) is not installed")
    with tempfile.TemporaryDirectory() as folder:
        source = os.path.join(folder, "input.pdf")
        with open(source, "wb") as f:
            f.write(data)
        out = os.path.join(folder, "page")
        try:
            result = subprocess.run(
                [exe, "-png", "-f", "1", "-l", "1", "-r", str(dpi), "-singlefile", source, out],
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return b""
        if result.returncode != 0 or not os.path.exists(out + ".png"):
            return b""
        with open(out + ".png", "rb") as f:
            return f.read()


def pdf_text(data: bytes, last_page: int | None = 3, timeout: int = 30) -> str:
    """Text of the first pages of a PDF (all pages if `last_page` is None), layout preserved.
    Pages are separated by a form feed. Empty string if the PDF can't be read."""
    exe = shutil.which("pdftotext")
    if exe is None:
        raise PdfToolUnavailable("pdftotext (poppler) is not installed")
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "input.pdf")
        with open(path, "wb") as f:
            f.write(data)
        try:
            result = subprocess.run(
                [exe, "-layout", *(["-l", str(last_page)] if last_page else []), path, "-"],
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ""
    return result.stdout.decode("utf-8", errors="replace") if result.returncode == 0 else ""
