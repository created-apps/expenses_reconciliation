"""The matching engine on the real June cycle, compared line by line with the expected CSV (Docker only),
and the September Amazon report in CSV mode (test 9.6).

Files are compared as sets, treating byte-identical pairs as the same file (implementation_plan.md note):
140626_Amazon_525.pdf = 140626_Amazon_525(1).pdf, DTDC_488.pdf = MH2727WI016880_GC001_10-Jun-2026.pdf.
"""

import csv
import shutil
from pathlib import Path

import pytest

from june_cycle import JUNE_ZIP, STATEMENT, build_june
from app.services.run_matching import match_summary, run_matching, start_matching

DOC_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "doc" / "reference",
    Path("/doc/reference"),
]
EXPECTED_CSV = next((p / "june_2026_expected_results.csv" for p in DOC_CANDIDATES if (p / "june_2026_expected_results.csv").exists()), None)

SAME_FILE = {"140626_Amazon_525.pdf": "140626_Amazon_525(1).pdf", "MH2727WI016880_GC001_10-Jun-2026.pdf": "DTDC_488.pdf"}

pytestmark = [
    pytest.mark.skipif(not (STATEMENT and JUNE_ZIP and EXPECTED_CSV), reason="June fixtures or expected CSV missing"),
    pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext (poppler) not installed; run in Docker"),
]


def canon(name: str) -> str:
    return SAME_FILE.get(name, name)


@pytest.fixture(scope="module")
def june():
    j = build_june()
    cycle = j.repo.get_cycle(j.cid)
    start_matching(j.repo, cycle)
    j.summary = run_matching(j.repo, cycle, "t")
    return j


def lines_with_files(j):
    """{ser_no: (status, set of file names, note)} as saved by the run (suggestions included)."""
    names = {i["id"]: j.names[i["file_id"]] for i in j.repo.list_invoices(j.cid)}
    files: dict[str, set[str]] = {}
    for m in j.repo.list_matches(j.cid):
        files.setdefault(m["transaction_id"], set()).add(canon(names[m["invoice_id"]]))
    return {t["ser_no"]: (t["status"], files.get(t["id"], set()), t["notes"]) for t in j.repo.list_transactions(j.cid)}


# ---- 9.18: every line agrees with the expected CSV -----------------------------------------------------------
def test_all_127_lines_agree_with_the_expected_csv_on_status_and_files(june):
    actual = lines_with_files(june)
    with open(EXPECTED_CSV, encoding="utf-8") as f:
        expected = list(csv.DictReader(f))
    assert len(expected) == len(actual) == 127
    differences = []
    for e in expected:
        status, files, note = actual[e["ser_no"]]
        want = {canon(n.strip()) for n in e["files"].split(",") if n.strip()}
        if status != e["status"] or files != want:
            differences.append((e["date"], e["ser_no"], e["description"], e["status"], sorted(want), status, sorted(files), note))
    assert differences == []


def test_the_read_only_compare_script_agrees_and_reports_a_difference(june):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from compare_expected import differences

    assert differences(june.repo, june.cid, EXPECTED_CSV) == []
    line = next(t for t in june.repo.transactions if t["ser_no"] == "13576983915")  # a bank charge
    original = line["status"]
    try:
        line["status"] = "Review"  # pretend the app saved something else
        report = differences(june.repo, june.cid, EXPECTED_CSV)
        assert len(report) == 1 and "13576983915" in report[0] and "expected Bank charge" in report[0]
    finally:
        line["status"] = original


# ---- 9.1: the counts and the amounts ---------------------------------------------------------------------------
def test_9_1_status_counts_and_amounts(june):
    got = {s["status"]: (s["count"], s["amount_paise"]) for s in june.summary["statuses"]}
    assert got == {
        "Matched": (65, 54172664), "Review": (5, 12415396), "Missing invoice": (20, 7659363), "No invoice": (6, 2043700),
        "Reversed": (8, 0), "Credit – manual": (4, -5598560), "Payment": (1, -6047200), "Bank charge": (18, 7858699),
    }
    assert june.summary["total"] == 127 and june.summary["ran"]


# ---- spot checks of the plan's tests 9.2 to 9.15 -----------------------------------------------------------------
def by_ser(june):
    return lines_with_files(june)


def test_9_2_the_eight_invoices_behind_13_06_2557_44(june):
    status, files, _ = by_ser(june)["13598184078"]
    assert status == "Matched" and files == {
        "130626_Amazon_187.16(2).pdf", "130626_Amazon_198.pdf", "130626_Amazon_220.pdf", "130626_Amazon_238.pdf",
        "130626_Amazon_499.pdf", "130626_Amazon_928.27.pdf", "130626_Amazon_98.01.pdf", "130626_amazon_189(1).pdf",
    }


def test_9_3_14_06_amazon_sums_use_the_order_date(june):
    lines = by_ser(june)
    assert lines["13605660075"][1] == {"140626_Amazon_228.pdf", "140626_Amazon_4028(1).pdf", "140626_Amazon_649(2).pdf", "140626_Amazon_173.63.png"}
    assert lines["13605670745"][1] == {"140626_Amazon_249.pdf", "140626_Amazon_309.pdf", "140626_Amazon_460.pdf"}
    # 140626_Amazon_99.png is invoiced on 22/06 but ordered on 14/06: only the order date puts it here.
    assert lines["13605716170"][1] == {"140626_Amazon_525(1).pdf", "140626_Amazon_585.19(3).pdf", "140626_Amazon_5984(2).pdf", "140626_Amazon_99.png"}


def test_9_5_indigo_sums_prefer_one_pnr_and_the_near_miss_is_a_review(june):
    lines = by_ser(june)
    assert lines["13538346030"][1] == {"TaxInvoiceDL1262706AT38326.pdf", "TaxInvoiceMH1262706AY53125.pdf"}
    assert lines["13543994330"][1] == {"TaxInvoiceMH1262706AY75969.pdf", "TaxInvoiceWB1262706AJ54054.pdf"}
    assert lines["13562505147"][1] == {"TaxInvoiceMH1262706AZ69244.pdf", "TaxInvoiceUP1262706AG47449.pdf"}
    status, files, note = lines["13562235353"]
    assert status == "Review" and files == {"TaxInvoiceDL1262706AU17753.pdf", "TaxInvoiceMH1262706AZ48672.pdf"}
    assert "₹735.00 more" in note  # AU17753 + AZ48672 = ₹16,581 against a ₹15,846 charge


def test_9_7_to_9_9_single_vendors_and_paise_rounding(june):
    lines = by_ser(june)
    assert lines["13629230456"][:2] == ("Matched", {"190626_Macfos_715.pdf"})  # named 715, really ₹611
    assert lines["13562532936"][:2] == ("Matched", {"DTDC_215.pdf"}) and "within Rs 1" in lines["13562532936"][2]
    assert lines["13593129438"][:2] == ("Matched", {"DTDC_770.pdf"}) and "within Rs 1" in lines["13593129438"][2]
    assert lines["13647505360"][:2] == ("Matched", {"Fathom $36.pdf"})  # 21/06: $36 matches
    assert lines["13463194859"][:2] == ("Missing invoice", set())  # 21/05: before the invoice set
    assert "before the invoice set" in lines["13463194859"][2]


def test_9_10_and_9_11_the_second_of_two_identical_charges(june):
    lines = by_ser(june)
    assert lines["13619311367"][:2] == ("Matched", {"Vercel_20USD.pdf"})
    assert lines["13647506424"][:2] == ("Missing invoice", set())
    assert lines["13558103213"][:2] == ("Matched", {"ScriptIt.pdf"})
    status, files, note = lines["13558105225"]
    assert (status, files) == ("Review", set()) and "Possible duplicate charge" in note


def test_9_12_and_9_13_review_lines(june):
    lines = by_ser(june)
    status, files, note = lines["13642517948"]  # 20/06 ₹52,539
    assert (status, files) == ("Review", {"200626_Amazon_52390.pdf"}) and "₹149.00 less" in note
    status, files, note = lines["13592943880"]  # 12/06 ₹53,139 = the two same-day credits
    assert (status, files) == ("Review", set()) and "₹52,990.00 + ₹149.00" in note
    assert lines["13548975360"][:2] == ("Review", {"Genspark_$17.49.pdf"})  # a USD-only invoice


def test_9_14_and_9_15_reversals_payment_and_bank_charges(june):
    lines = by_ser(june)
    for ser in ("13513665287", "13513788899", "13598194425", "13630061944", "13642448945", "13642451260",
                "13642456881", "13642459365"):
        assert lines[ser][0] == "Reversed", ser
    assert "(SerNo 13630061944)" in lines["13598194425"][2] and "(SerNo 13598194425)" in lines["13630061944"][2]
    assert lines["13578455906"][0] == "Payment" and lines["13576983915"][0] == "Bank charge"


def test_the_four_images_whose_vendor_a_person_chose_and_mailchimps_candidate_amount_match(june):
    lines = by_ser(june)
    for ser, name in {"13525094801": "010626_DTDC_769.png", "13583684421": "DTDC_1124.png", "13593362938": "DTDC_240.png",
                      "13568373034": "080626_thinkrobotics_124.99.png"}.items():
        assert lines[ser][:2] == ("Matched", {name}), ser
    assert lines["13600187680"][:2] == ("Matched", {"mailchimp-receipt-MC26118597.pdf"})  # an invoice with no total line


def test_9_16_the_invoices_no_line_used(june):
    names = {i["id"]: june.names[i["file_id"]] for i in june.repo.list_invoices(june.cid)}
    linked = {m["invoice_id"] for m in june.repo.list_matches(june.cid)}
    unused = {names[i] for i in names if i not in linked}
    must = {"240626_Amazon_175.pdf", "040626_Sembly_USD29.pdf", "created invc.pdf", "CREATED-25947.pdf",
            "Fathom Video$20.pdf", "Anthropic.pdf", "300626_Macfos_801.pdf"}
    assert must <= unused
    # Everything dated after the statement date is unused: all 280626_Amazon_*, 290626_* and 300626_*.
    after_statement = {n for n in names.values() if n.startswith(("280626_Amazon_", "290626_", "300626_"))}
    assert after_statement and after_statement <= unused


def test_9_17_running_twice_gives_identical_results(june):
    first = lines_with_files(june)
    links_before = len(june.repo.list_matches(june.cid))
    cycle = june.repo.get_cycle(june.cid)
    start_matching(june.repo, cycle)
    run_matching(june.repo, june.repo.get_cycle(june.cid), "t")
    assert lines_with_files(june) == first  # same statuses, files and notes
    assert len(june.repo.list_matches(june.cid)) == links_before  # the old system links were replaced, not added to


def test_the_run_moves_the_cycle_to_matched_and_logs_it(june):
    assert june.repo.get_cycle(june.cid)["status"] == "matched"
    assert [e["action"] for e in june.repo.events if e["action"] == "matching_run"]
    assert match_summary(june.repo, june.cid)["total"] == 127
