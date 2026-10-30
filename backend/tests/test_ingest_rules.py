import zipfile

import pytest

from app.engine.ingest_rules import (
    extension,
    is_junk_zip_member,
    is_statement_copy,
    member_basename,
    mime_for,
    safe_storage_name,
    zip_member_name,
)


def test_extension_and_mime():
    assert extension("Invoice.PDF") == ".pdf"
    assert extension("photo.JPeG") == ".jpeg"
    assert extension("noext") == ""
    assert extension("a\\b\\c.png") == ".png"
    assert mime_for("x.pdf") == "application/pdf"
    assert mime_for("x.jpg") == "image/jpeg"
    assert mime_for("x.csv") == "text/csv"
    assert mime_for("x.bin") == "application/octet-stream"


@pytest.mark.parametrize(
    "path, junk",
    [
        ("invoice.pdf", False),
        ("folder/invoice.pdf", False),
        ("folder/", True),
        ("__MACOSX/._invoice.pdf", True),
        ("folder/__MACOSX/x.pdf", True),
        (".DS_Store", True),
        ("folder/.hidden.pdf", True),
        ("a\\b\\.secret", True),
        ("Fathom $36.pdf", False),
    ],
)
def test_junk_zip_members(path, junk):
    assert is_junk_zip_member(path) is junk


def test_member_basename_strips_folders_of_both_kinds():
    assert member_basename("a/b/c.pdf") == "c.pdf"
    assert member_basename("a\\b\\c.pdf") == "c.pdf"


def test_zip_member_name_recovers_utf8_written_without_the_flag():
    info = zipfile.ZipInfo("é.pdf".encode("utf-8").decode("cp437"))
    info.flag_bits = 0
    assert zip_member_name(info) == "é.pdf"


def test_zip_member_name_leaves_plain_and_flagged_names_alone():
    plain = zipfile.ZipInfo("a.pdf")
    flagged = zipfile.ZipInfo("é.pdf")
    flagged.flag_bits = 0x800
    assert zip_member_name(plain) == "a.pdf"
    assert zip_member_name(flagged) == "é.pdf"


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Fathom $36.pdf", "Fathom_36.pdf"),
        ("130626_Amazon_187.16(2).pdf", "130626_Amazon_187.16(2).pdf"),
        ("a b&c=d.png", "a_b_c_d.png"),
        ("folder/inner name.pdf", "inner_name.pdf"),
        ("...pdf", "file.pdf"),
        ("noext", "noext"),
    ],
)
def test_safe_storage_name(name, expected):
    assert safe_storage_name(name) == expected


def test_safe_storage_name_is_bounded_and_keeps_extension():
    safe = safe_storage_name("ACFrOg" + "x" * 300 + "==.pdf")
    assert safe.endswith(".pdf")
    assert len(safe) <= 120
    assert all(c.isalnum() or c in "._()-" for c in safe)


def test_statement_copy_needs_both_markers_whatever_the_spacing_or_case():
    assert is_statement_copy("ICICI Bank\nCREDIT  CARD STATEMENT\n...\nStatement   Summary\n")
    assert not is_statement_copy("CREDIT CARD STATEMENT only")
    assert not is_statement_copy("An ordinary Amazon tax invoice")
