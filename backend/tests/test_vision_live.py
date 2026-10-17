"""LIVE: asks the real model to read the 12 June invoice images. Skipped unless you ask for it.

    docker compose run --rm -e RUN_LIVE_VISION=1 tests pytest tests/test_vision_live.py -s -v

Each image is one paid call (a few thousandths of a dollar). Run one image first with `-k DTDC_769`.
It needs ANTHROPIC_API_KEY and ANTHROPIC_MODEL in backend/.env (the test container reads that file) and the
June ZIP in tests/fixtures_private/. It checks the model's readings against the values read from the images
(implementation_plan.md tests 7.2 to 7.8) and prints the tokens used, so the real cost can be seen.
"""

import os
import zipfile
from pathlib import Path

import pytest

from app.config import Settings
from app.engine.invoices.types import VendorPattern
from app.engine.invoices.vision import read_image_invoice
from app.services.vision_client import build_vision
from seed import seed_rows
from vision_expected import EXPECTED, mismatches

ZIPS = sorted((Path(__file__).parent / "fixtures_private").glob("June2026*invoice*.zip"))
pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE_VISION") != "1", reason="live AI test: set RUN_LIVE_VISION=1")

VENDORS = [VendorPattern(r["vendor_key"], r["invoice_pattern"], r["display_name"]) for r in seed_rows()]
USED: list[tuple[int, int]] = []


@pytest.fixture(scope="module")
def vision():
    if not ZIPS:
        pytest.skip("June ZIP not in tests/fixtures_private/")
    client = build_vision(Settings())  # reads ANTHROPIC_API_KEY and ANTHROPIC_MODEL from the environment / .env
    if client is None:
        pytest.skip("ANTHROPIC_API_KEY or ANTHROPIC_MODEL is not set")
    print(f"\nmodel: {client.model}")
    return client


@pytest.fixture(scope="module")
def images() -> dict[str, bytes]:
    with zipfile.ZipFile(ZIPS[0]) as z:
        return {Path(i.filename).name: z.read(i) for i in z.infolist() if Path(i.filename).name in EXPECTED}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_the_model_reads_the_image_as_expected(name, vision, images):
    item = read_image_invoice(images[name], "image/png", vision, VENDORS)
    ai = item.extra["ai"]
    USED.append((ai["input_tokens"], ai["output_tokens"]))
    print(f"\n{name}: {item.vendor_key} {item.invoice_no} {item.order_id} inv={item.invoice_date} ord={item.order_date} "
          f"total={item.total_minor} | tokens in={ai['input_tokens']} out={ai['output_tokens']} calls={ai['calls']}")
    assert mismatches(item, EXPECTED[name]) == []


def test_zz_token_use_for_the_images_that_ran():
    if not USED:
        pytest.skip("no live image ran")
    inputs, outputs = sum(i for i, _ in USED), sum(o for _, o in USED)
    print(f"\n{len(USED)} images: {inputs} input tokens, {outputs} output tokens "
          f"(about {inputs // len(USED)} in / {outputs // len(USED)} out per image)")
