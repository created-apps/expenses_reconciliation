"""Pure rules for classifying uploaded files. No database, network, storage or subprocess calls."""

import re
import zipfile
from pathlib import PurePosixPath

KINDS = ("statement", "invoices", "amazon_report")

# What each upload slot accepts (doc/flow.md section 3). ZIPs are only accepted as invoices.
ALLOWED_EXTENSIONS: dict[str, frozenset[str]] = {
    "statement": frozenset({".pdf"}),
    "invoices": frozenset({".pdf", ".png", ".jpg", ".jpeg", ".zip"}),
    "amazon_report": frozenset({".csv"}),
}

# Files inside a ZIP are classified as invoices. A ZIP inside a ZIP is not expanded.
ZIP_MEMBER_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg"})

STATEMENT_COPY_NOTE = "copy of the statement"

_MIME = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".csv": "text/csv",
    ".zip": "application/zip",
}


def extension(name: str) -> str:
    return PurePosixPath(name.replace("\\", "/")).suffix.lower()


def mime_for(name: str) -> str:
    return _MIME.get(extension(name), "application/octet-stream")


def member_basename(path: str) -> str:
    """The file name of a ZIP member, without any folders (Windows or POSIX separators)."""
    return PurePosixPath(path.replace("\\", "/")).name


def is_junk_zip_member(path: str) -> bool:
    """Folders, `__MACOSX` resources and dot-files are skipped, as in the plan."""
    normalised = path.replace("\\", "/")
    if normalised.endswith("/"):
        return True
    parts = [p for p in normalised.split("/") if p]
    return any(p == "__MACOSX" or p.startswith(".") for p in parts)


def zip_member_name(info: zipfile.ZipInfo) -> str:
    """Member name with the right text encoding.

    Zip files made without the UTF-8 flag are decoded by Python as cp437, which garbles
    names that were really UTF-8. Recover those when the bytes are valid UTF-8.
    """
    name = info.filename
    if info.flag_bits & 0x800 or name.isascii():
        return name
    try:
        return name.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


_UNSAFE = re.compile(r"[^A-Za-z0-9._()\-]+")


def safe_storage_name(name: str, max_length: int = 120) -> str:
    """A file name safe to use as the last part of a storage key.

    The original name is kept in the database; the key only needs to be unique (it sits under
    the file's own id) and free of characters storage services reject (spaces, `$`, `=`, ...).
    """
    base = member_basename(name)
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    stem = _UNSAFE.sub("_", stem).strip("._") or "file"
    ext = _UNSAFE.sub("", ext)[:10]
    room = max_length - (len(ext) + 1 if ext else 0)
    stem = stem[: max(room, 1)]
    return f"{stem}.{ext}" if ext else stem


def is_statement_copy(text: str) -> bool:
    """True when invoice text is a copy of the card statement (both marker phrases present)."""
    normalised = re.sub(r"\s+", " ", text).upper()
    return "CREDIT CARD STATEMENT" in normalised and "STATEMENT SUMMARY" in normalised
