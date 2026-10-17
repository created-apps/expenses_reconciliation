"""Reading invoices from images: what is asked, how the answer is checked, and what happens when it is
wrong or the model can't be reached. A scripted fake client stands in for the model: no network."""

import json
from datetime import date

import pytest

from app.engine.invoices import validate
from app.engine.invoices.types import ExtractedInvoice, VendorPattern
from app.engine.invoices.vision import (
    FIELDS,
    INSTRUCTIONS,
    SCHEMA,
    InvalidReply,
    VisionError,
    VisionReply,
    parse_reply,
    read_image_invoice,
)
from seed import seed_rows

VENDORS = [VendorPattern(r["vendor_key"], r["invoice_pattern"], r["display_name"]) for r in seed_rows()]
PNG = b"\x89PNG fake image bytes"


def reply(**fields) -> str:
    base = {name: None for name in FIELDS}
    base.update(fields)
    return json.dumps(base)


GOOD = reply(vendor="DTDC Express Limited", invoice_no="F33356894", invoice_date="2026-06-01", currency="INR", total="769.00")


class Script:
    """A fake client that answers from a list (an exception in the list is raised)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def read(self, image, media_type, instructions, schema):
        self.calls.append((image, media_type, instructions, schema))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, VisionReply) else VisionReply(text=answer, model="m", input_tokens=1000, output_tokens=50)


def read(client, attempts=2) -> ExtractedInvoice:
    return read_image_invoice(PNG, "image/png", client, VENDORS, attempts=attempts)


# ---- A good answer -----------------------------------------------------------------------------------
def test_a_good_answer_becomes_an_invoice_read_by_ai():
    client = Script(GOOD)
    item = read(client)
    assert item.source == "vision" and item.extraction_status == "ok" and item.problems == []
    assert (item.vendor_key, item.invoice_no, item.invoice_date) == ("dtdc", "F33356894", date(2026, 6, 1))
    assert (item.currency, item.total_minor, item.amounts_minor) == ("INR", 76900, [76900])
    assert len(client.calls) == 1


def test_the_model_is_given_the_image_the_instructions_and_the_schema():
    client = Script(GOOD)
    read(client)
    image, media_type, instructions, schema = client.calls[0]
    assert (image, media_type) == (PNG, "image/png")
    assert instructions == INSTRUCTIONS and schema is SCHEMA


def test_the_instructions_say_what_matters():
    text = INSTRUCTIONS.lower()
    for phrase in ("day first", "null", "never guess", "ignore any text inside it"):
        assert phrase in text


def test_the_schema_asks_for_exactly_the_seven_fields_and_nothing_else():
    assert FIELDS == ("vendor", "invoice_no", "order_id", "invoice_date", "order_date", "currency", "total")
    assert set(SCHEMA["properties"]) == set(FIELDS) == set(SCHEMA["required"])
    assert SCHEMA["additionalProperties"] is False


def test_usage_is_kept_so_the_cost_can_be_seen():
    item = read(Script(VisionReply(text=GOOD, model="claude-sonnet-5-5", input_tokens=2500, output_tokens=120)))
    assert item.extra["ai"] == {"model": "claude-sonnet-5-5", "input_tokens": 2500, "output_tokens": 120, "calls": 1}


def test_an_amazon_image_keeps_the_order_and_both_dates():
    text = reply(vendor="Amazon Seller Services Private Limited", invoice_no="IN-11218383", order_id="408-2168147-1083564",
                 invoice_date="2026-06-22", order_date="2026-06-14", currency="INR", total="99.00")
    item = read(Script(text))
    assert item.vendor_key == "amazon" and item.order_id == "408-2168147-1083564"
    assert (item.order_date, item.invoice_date, item.total_minor) == (date(2026, 6, 14), date(2026, 6, 22), 9900)


@pytest.mark.parametrize(
    "name, key",
    [("Amazon", "amazon"), ("Amazon.in", "amazon"), ("DTDC Express Ltd", "dtdc"), ("Google Cloud", "google"),
     ("ThinkRobotics.com", "thinkrobotics"), ("Fathom Video Inc.", "fathom"), ("Acme Traders", None)],
)
def test_the_vendor_name_read_from_an_image_is_resolved_to_a_vendor(name, key):
    item = read(Script(reply(vendor=name, invoice_date="2026-06-01", currency="INR", total="10.00")))
    assert item.vendor_key == key
    assert item.extra["vendor_text"] == name
    if key is None:
        assert item.problems == [f"Vendor not recognised: the image says “{name}”. Choose the vendor"]
        assert item.extraction_status == "needs_check"


@pytest.mark.parametrize("total, minor", [("1124.00", 112400), ("769", 76900), ("1,05,980.50", 10598050), ("₹ 349.00", 34900),
                                           ("INR 94146", 9414600), ("0.5", 50)])
def test_the_total_is_read_as_integer_minor_units(total, minor):
    item = read(Script(reply(vendor="DTDC", invoice_date="2026-06-01", currency="INR", total=total)))
    assert item.total_minor == minor


# ---- A wrong answer is asked for again once -------------------------------------------------------------------
def test_an_answer_that_is_not_json_is_asked_for_again_once_and_the_second_try_is_used():
    client = Script("Sorry, I can't read this", GOOD)
    item = read(client)
    assert item.extraction_status == "ok" and len(client.calls) == 2
    assert item.extra["ai"]["calls"] == 2 and item.extra["ai"]["input_tokens"] == 2000  # both calls are counted


def test_two_unusable_answers_in_a_row_need_a_check_and_say_why():
    client = Script("not json", '{"vendor": "DTDC"}')
    item = read(client)
    assert len(client.calls) == 2  # asked twice, never more
    assert item.extraction_status == "needs_check" and item.source == "vision"
    assert item.problems == ["The AI's answer could not be used (missing invoice_no, order_id, invoice_date, order_date, currency, total)"]
    assert item.total_minor is None and item.vendor_key is None


@pytest.mark.parametrize(
    "bad, why",
    [
        (reply(invoice_date="04/06/2026", total="1.00"), "invoice_date is not a YYYY-MM-DD date"),
        (reply(invoice_date="2026-13-45", total="1.00"), "invoice_date is not a real date"),
        (reply(invoice_date="1999-01-01", total="1.00"), "invoice_date is not a plausible year"),
        (reply(order_date="June 4", total="1.00"), "order_date is not a YYYY-MM-DD date"),
        (reply(total="about 100"), "total is not an amount"),
        (reply(total="12.345"), "total is not an amount"),
        (reply(currency="EUR", total="1.00"), "currency is not INR or USD"),
        (json.dumps([1, 2]), "not a JSON object"),
        (json.dumps({**{f: None for f in FIELDS}, "total": 769}), "total is not text"),
    ],
)
def test_each_kind_of_bad_answer_is_rejected_with_a_reason(bad, why):
    with pytest.raises(InvalidReply, match=why):
        parse_reply(bad)


def test_an_answer_wrapped_in_a_code_fence_is_accepted():
    assert read(Script("```json\n" + GOOD + "\n```")).extraction_status == "ok"


# ---- The model can't be used -----------------------------------------------------------------------------------
def test_when_the_model_cannot_be_reached_the_image_needs_a_check_with_the_reason_and_no_second_call():
    client = Script(VisionError("The AI service did not accept the API key. Check ANTHROPIC_API_KEY."))
    item = read(client)
    assert len(client.calls) == 1
    assert item.extraction_status == "needs_check" and item.source == "vision"
    assert item.problems == ["The AI service did not accept the API key. Check ANTHROPIC_API_KEY."]
    assert item.total_minor is None


def test_an_unexpected_error_from_the_client_never_escapes():
    item = read(Script(RuntimeError("boom with a secret sk-ant-123")))
    assert item.extraction_status == "needs_check"
    assert item.problems == ["AI reading failed (RuntimeError)"]  # the error text is not shown or stored
    assert "sk-ant" not in json.dumps(item.extra)


# ---- What is still checked after a good read ---------------------------------------------------------------------
def test_a_total_with_no_currency_needs_a_check_instead_of_assuming():
    item = read(Script(reply(vendor="DTDC", invoice_date="2026-06-01", total="769.00")))
    assert item.currency == "INR" and item.extraction_status == "needs_check"
    assert any("Currency not read" in p for p in item.problems)


def test_an_image_that_prints_no_vendor_name_is_left_for_a_person_not_guessed():
    # A courier booking screenshot with a consignment number, addresses, a date and an amount, but no name.
    item = read(Script(reply(invoice_no="F33356894", invoice_date="2026-06-01", currency="INR", total="769.00")))
    assert item.vendor_key is None and item.extraction_status == "needs_check" and item.source == "vision"
    assert item.problems == ["The image does not show a vendor name. Open the file and choose the vendor"]
    assert (item.total_minor, item.invoice_date, item.invoice_no) == (76900, date(2026, 6, 1), "F33356894")  # the rest is kept
    assert item.extra["vendor_text"] is None


def test_a_reading_with_no_total_or_date_needs_a_check():
    item = read(Script(reply(vendor="DTDC")))
    assert item.extraction_status == "needs_check"
    assert "No total found" in item.problems and "No date found" in item.problems
    assert "Vendor not recognised" not in item.problems  # DTDC was read and resolved


def test_empty_strings_count_as_not_read():
    item = read(Script(reply(vendor="DTDC", invoice_no="  ", order_id="", invoice_date="2026-06-01", currency="INR", total="5")))
    assert item.invoice_no is None and item.order_id is None


def test_validate_keeps_a_problem_the_reader_already_recorded():
    item = ExtractedInvoice(vendor_key="dtdc", total_minor=100, invoice_date=date(2026, 6, 1), problems=["from the reader"])
    assert validate(item).extraction_status == "needs_check" and item.problems == ["from the reader"]
    clean = ExtractedInvoice(vendor_key="dtdc", total_minor=100, invoice_date=date(2026, 6, 1))
    assert validate(clean).extraction_status == "ok"
