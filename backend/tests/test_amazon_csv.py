"""The Amazon Business report: parsing, card payment groups, gift orders, upload and the report endpoint.

Small made-up samples test each rule; the real September report (git-ignored, Docker) is checked against
implementation_plan.md tests 8.1 to 8.3."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amazon_samples import GIFT, UNPAID, amazon_csv, row
from app.auth import CurrentUser, get_current_user
from app.config import Settings, get_settings
from app.db import get_repo
from app.engine.amazon_csv import AmazonCsvError, card_groups, gift_orders, parse_amazon_csv
from app.main import app
from app.services.ingest import Incoming, Limits, ingest_upload
from app.storage import get_storage
from fakes import FakeRepo, FakeStorage

FIXTURES = Path(__file__).parent / "fixtures_private"
found = sorted(FIXTURES.glob("reconciliation_from_*.csv"))
SEPT = found[0] if found else None
needs_sept = pytest.mark.skipif(SEPT is None, reason="September CSV not in tests/fixtures_private/")


# ---- Parsing ---------------------------------------------------------------------------------------------
def test_a_row_is_read_into_typed_values_with_money_in_paise():
    (r,) = parse_amazon_csv(amazon_csv(row(order="404-1-2", order_date="09/09/2026", ref="R1", paid="22/09/2026",
                                           card='="4002"', qty="2", net="1,234.50")))
    assert (r.order_id, r.order_date, r.payment_ref, r.payment_date) == ("404-1-2", date(2026, 9, 9), "R1", date(2026, 9, 22))
    assert (r.payment_method, r.card_last4, r.shipment_qty, r.net_total_paise) == ("Visa", "4002", 2, 123450)


def test_na_and_empty_cells_mean_no_value_and_an_empty_net_total_is_zero():
    (r,) = parse_amazon_csv(amazon_csv(row(**UNPAID)))
    assert (r.payment_method, r.payment_ref, r.payment_date, r.card_last4) == (None, None, None, None)
    assert (r.shipment_qty, r.net_total_paise) == (0, 0)


def test_the_identifier_keeps_only_the_last_four_digits():
    for cell, last4 in [('="4002"', "4002"), ("4002", "4002"), ("************4002", "4002"), ("12", None), ("", None)]:
        assert parse_amazon_csv(amazon_csv(row(card=cell)))[0].card_last4 == last4


def test_a_byte_order_mark_is_accepted():
    assert parse_amazon_csv(b"\xef\xbb\xbf" + amazon_csv(row(net="5.00")))[0].net_total_paise == 500


def test_a_file_saved_in_windows_1252_is_read_not_rejected():
    # "é" is one byte in Windows-1252 and is not valid UTF-8: a column we don't use must not break the read.
    data = amazon_csv(dict(row(net="5.00"), Title="Café mug"), extra_columns=("Title",)).decode("utf-8").encode("cp1252")
    assert b"\xe9" in data
    assert parse_amazon_csv(data)[0].net_total_paise == 500


def test_negative_amounts_are_kept_so_a_refund_would_reduce_its_group():
    rows = parse_amazon_csv(amazon_csv(row(net="100.00"), row(order="2", net="-30.50")))
    assert [g.amount_paise for g in card_groups(rows)] == [6950]


def test_a_header_with_stray_spaces_is_still_recognised():
    data = amazon_csv(row()).replace(b"Net total", b" Net total ", 1)
    assert parse_amazon_csv(data)[0].net_total_paise == 10000


@pytest.mark.parametrize(
    "bad, message",
    [
        (row(order_date="2026-09-09"), "row 2: Order Date '2026-09-09' is not a dd/mm/yyyy date"),
        (row(paid="31/02/2026"), "row 2: Payment Date '31/02/2026' is not a dd/mm/yyyy date"),
        (row(net="about 100"), "row 2: Net total 'about 100' is not an amount"),
        (row(qty="two"), "row 2: Shipment Quantity 'two' is not a whole number"),
    ],
)
def test_a_value_that_cannot_be_read_is_an_error_with_its_row_number(bad, message):
    with pytest.raises(AmazonCsvError, match=message):
        parse_amazon_csv(amazon_csv(bad))


def test_only_the_first_few_bad_rows_are_listed():
    with pytest.raises(AmazonCsvError) as caught:
        parse_amazon_csv(amazon_csv(*[row(order=str(i), net="x") for i in range(6)]))
    assert str(caught.value).count("row ") == 3 and "(and 3 more)" in str(caught.value)


def test_a_csv_that_is_not_an_amazon_report_says_which_columns_are_missing():
    with pytest.raises(AmazonCsvError, match="Missing columns: Order ID"):
        parse_amazon_csv(b"Date,Amount\n01/01/2026,5\n")
    with pytest.raises(AmazonCsvError, match="doesn't look like an Amazon Business reconciliation report"):
        parse_amazon_csv(b"")


def test_a_report_with_no_rows_is_refused():
    header_only = amazon_csv(row()).split(b"\n")[0] + b"\n"
    with pytest.raises(AmazonCsvError, match="no rows"):
        parse_amazon_csv(header_only)


# ---- Groups and gift orders ---------------------------------------------------------------------------------------
def test_card_rows_are_grouped_by_reference_and_summed_with_distinct_orders_counted():
    rows = parse_amazon_csv(amazon_csv(
        row(order="A", ref="R1", net="100.00"), row(order="A", ref="R1", net="50.25"), row(order="B", ref="R1", net="10.00"),
        row(order="C", ref="R2", paid="07/09/2026", net="7.00"),
    ))
    first, second = card_groups(rows)  # R1 was paid on 05/09 (the sample default), R2 on 07/09
    assert (first.payment_ref, first.orders, first.amount_paise) == ("R1", 2, 16025)  # two orders, three rows
    assert first.order_ids == ("A", "B")
    assert (second.payment_ref, second.payment_date, second.card_last4, second.amount_paise) == ("R2", date(2026, 9, 7), "4002", 700)


def test_groups_are_listed_oldest_payment_first():
    rows = parse_amazon_csv(amazon_csv(row(ref="L", paid="22/09/2026"), row(ref="E", paid="09/09/2026"), row(ref="M", paid="11/09/2026")))
    assert [g.payment_ref for g in card_groups(rows)] == ["E", "M", "L"]


def test_gift_balance_and_unpaid_rows_are_not_card_charges():
    rows = parse_amazon_csv(amazon_csv(row(ref="R1"), row(order="G", net="158.00", **GIFT), row(order="U", **UNPAID)))
    assert [g.payment_ref for g in card_groups(rows)] == ["R1"]
    gifts = gift_orders(rows)
    assert [(g.order_id, g.amount_paise) for g in gifts] == [("G", 15800)]


def test_a_group_whose_rows_were_not_shipped_is_listed_with_zero():
    rows = parse_amazon_csv(amazon_csv(row(ref="Z", qty="0", net="")))
    (group,) = card_groups(rows)
    assert group.amount_paise == 0 and group.orders == 1


def test_gift_orders_are_oldest_first_and_fall_back_to_the_order_date():
    rows = parse_amazon_csv(amazon_csv(
        row(order="B", net="2.00", method="Gift Certificate/Card", paid="22/09/2026", ref="G1", card=""),
        row(order="A", net="1.00", method="Gift Certificate/Card", paid="N/A", order_date="09/09/2026", ref="G2", card=""),
    ))
    assert [(g.order_id, g.paid_on) for g in gift_orders(rows)] == [("A", date(2026, 9, 9)), ("B", date(2026, 9, 22))]


# ---- The real September report (8.1 to 8.3) -----------------------------------------------------------------------
@needs_sept
def test_8_1_133_rows_are_read():
    assert len(parse_amazon_csv(SEPT.read_bytes())) == 133


@needs_sept
def test_8_2_the_ten_card_groups_match_the_plan_to_the_paisa():
    groups = card_groups(parse_amazon_csv(SEPT.read_bytes()))
    assert [(g.payment_date.isoformat(), g.amount_paise) for g in groups] == [
        ("2026-09-09", 2751934), ("2026-09-10", 192000), ("2026-09-11", 818291),
        ("2026-09-22", 71700), ("2026-09-22", 1171346), ("2026-09-22", 1271314),
        ("2026-09-23", 353771), ("2026-09-27", 454246), ("2026-09-29", 200800), ("2026-09-30", 0),
    ]
    assert {g.card_last4 for g in groups} == {"4002"}
    assert [g.orders for g in groups] == [20, 1, 10, 2, 8, 8, 7, 2, 1, 1]  # distinct orders, not rows
    # The four September card charges that matched exactly in the prototype (project_context 5.4).
    amounts = {g.amount_paise for g in groups}
    assert {71700, 1171346, 1271314, 454246} <= amounts


@needs_sept
def test_8_3_five_gift_balance_orders():
    rows = parse_amazon_csv(SEPT.read_bytes())
    assert [(g.paid_on.isoformat(), g.amount_paise) for g in gift_orders(rows)] == [
        ("2026-09-09", 15800), ("2026-09-17", 65000), ("2026-09-22", 15800), ("2026-09-23", 15900), ("2026-09-30", 25500),
    ]
    assert sum(1 for r in rows if not r.payment_method) == 40  # ordered but not paid or not shipped: in neither list


# ---- Upload and the report endpoint ----------------------------------------------------------------------------------
LIMITS = Limits(max_file_bytes=1_000_000, max_zip_total_bytes=5_000_000, max_zip_entries=50)
USER = CurrentUser(email="harsh@create-ed.in", user_id="u1")


@pytest.fixture
def api():
    repo, storage = FakeRepo(), FakeStorage()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    client = TestClient(app)
    client.repo, client.storage = repo, storage
    yield client
    app.dependency_overrides.clear()


def new_cycle(api):
    return api.post("/api/cycles").json()["id"]


def upload_report(api, cid, data, name="report.csv"):
    return api.post(f"/api/cycles/{cid}/files", data={"kind": "amazon_report"}, files=[("files", (name, data, "text/csv"))])


def report(api, cid):
    r = api.get(f"/api/cycles/{cid}/amazon-report")
    assert r.status_code == 200, r.text
    return r.json()


SAMPLE = amazon_csv(
    row(order="A", ref="R1", paid="09/09/2026", net="100.00"), row(order="B", ref="R1", paid="09/09/2026", net="50.50"),
    row(order="C", ref="R2", paid="22/09/2026", net="717.00"), row(order="G", net="158.00", paid="17/09/2026", **GIFT),
    row(order="U", **UNPAID),
)


def test_the_report_endpoint_needs_a_token():
    assert TestClient(app).get("/api/cycles/6f9619ff-8b86-d011-b42d-00c04fc964ff/amazon-report").status_code == 401


def test_without_a_report_the_panel_has_nothing():
    app.dependency_overrides[get_current_user] = lambda: USER
    repo = FakeRepo()
    app.dependency_overrides[get_repo] = lambda: repo
    try:
        cid = repo.create_cycle(None, "t")["id"]
        body = TestClient(app).get(f"/api/cycles/{cid}/amazon-report").json()
        assert body["file"] is None and body["rows"] == 0 and body["groups"] == [] and body["gift"] == []
    finally:
        app.dependency_overrides.clear()


def test_unknown_cycle_is_404(api):
    assert api.get("/api/cycles/6f9619ff-8b86-d011-b42d-00c04fc964ff/amazon-report").status_code == 404


def test_uploading_a_report_saves_its_rows_and_shows_groups_and_gift_orders(api):
    cid = new_cycle(api)
    result = upload_report(api, cid, SAMPLE)
    assert result.status_code == 200 and result.json()["rejected"] == []
    assert result.json()["files"][0]["kind"] == "amazon_report" and result.json()["files"][0]["status"] == "uploaded"
    body = report(api, cid)
    assert body["file"]["name"] == "report.csv" and body["file"]["has_copy"]
    assert (body["rows"], body["unpaid_rows"], body["card_last4s"]) == (5, 1, ["4002"])
    assert body["groups"] == [
        {"payment_date": "2026-09-09", "reference": "R1", "card_last4": "4002", "orders": 2, "amount_paise": 15050},
        {"payment_date": "2026-09-22", "reference": "R2", "card_last4": "4002", "orders": 1, "amount_paise": 71700},
    ]
    assert body["gift"] == [{"paid_on": "2026-09-17", "order_id": "G", "amount_paise": 15800}]
    assert (body["payment_date_from"], body["payment_date_to"]) == ("2026-09-09", "2026-09-22")
    assert len(api.repo.amazon_rows) == 5


def test_a_csv_that_is_not_an_amazon_report_is_refused_with_the_reason_and_stores_nothing(api):
    cid = new_cycle(api)
    r = upload_report(api, cid, b"Date,Amount\n01/01/2026,5\n", "bank.csv")
    assert r.status_code == 200 and r.json()["files"] == []
    (rejected,) = r.json()["rejected"]
    assert rejected["name"] == "bank.csv" and "doesn't look like an Amazon Business reconciliation report" in rejected["message"]
    assert api.repo.files == {} and api.repo.amazon_rows == [] and api.storage.objects == {}


def test_a_report_with_an_unreadable_value_is_refused_naming_the_row(api):
    cid = new_cycle(api)
    r = upload_report(api, cid, amazon_csv(row(), row(order="2", paid="99/99/2026")))
    assert r.json()["files"] == [] and "row 3: Payment Date '99/99/2026'" in r.json()["rejected"][0]["message"]
    assert api.repo.files == {}


def test_a_new_report_replaces_the_old_one_and_its_rows(api):
    cid = new_cycle(api)
    upload_report(api, cid, SAMPLE, "old.csv")
    upload_report(api, cid, amazon_csv(row(order="Z", ref="R9", net="9.00")), "new.csv")
    body = report(api, cid)
    assert body["file"]["name"] == "new.csv" and body["rows"] == 1
    assert [g["reference"] for g in body["groups"]] == ["R9"] and body["gift"] == []
    assert len(api.repo.amazon_rows) == 1  # the old rows went with the old file


def test_the_same_report_again_is_a_duplicate_and_adds_no_rows(api):
    cid = new_cycle(api)
    upload_report(api, cid, SAMPLE)
    again = upload_report(api, cid, SAMPLE, "copy.csv")
    assert again.json()["files"][0]["status"] == "duplicate"
    assert len(api.repo.amazon_rows) == 5 and report(api, cid)["file"]["name"] == "report.csv"


def test_deleting_the_cycle_removes_the_rows(api):
    cid = new_cycle(api)
    upload_report(api, cid, SAMPLE)
    assert api.delete(f"/api/cycles/{cid}").status_code == 204
    assert api.repo.amazon_rows == []


def test_if_the_rows_cannot_be_saved_the_whole_upload_is_undone():
    repo, storage = FakeRepo(), FakeStorage()
    cycle = repo.create_cycle(None, "t")

    def broken(rows):
        raise RuntimeError("database unavailable")

    repo.insert_amazon_rows = broken
    with pytest.raises(RuntimeError):
        ingest_upload(repo=repo, storage=storage, cycle=cycle, kind="amazon_report",
                      uploads=[Incoming("r.csv", SAMPLE)], actor="t", limits=LIMITS)
    assert repo.files == {} and storage.objects == {}  # no half-saved report


@needs_sept
def test_the_real_september_report_goes_through_upload(api):
    cid = new_cycle(api)
    assert upload_report(api, cid, SEPT.read_bytes(), SEPT.name).json()["rejected"] == []
    body = report(api, cid)
    assert body["rows"] == 133 and len(body["groups"]) == 10 and len(body["gift"]) == 5 and body["unpaid_rows"] == 40
    assert (body["payment_date_from"], body["payment_date_to"]) == ("2026-09-09", "2026-09-30")
