"""Adding a vendor by hand (from the invoice drawer), for a vendor that is not in the list.

The vendor goes into the shared vendor table, so it is in the list from then on and, after matching is run
again, a statement line whose description contains it is matched to its invoices. The patterns are built
from the typed text with every special character escaped: a person never writes a regular expression.
"""

import logging
import re
from typing import Any

from app.services.gates import ServiceError

log = logging.getLogger("app.vendors")

MIN_LENGTH = 2
MAX_LENGTH = 60


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())[:30]


def add_vendor(repo, name: str, statement_text: str | None, actor: str) -> dict[str, Any]:
    """Returns the vendor row. A vendor with the same name (any capitalisation) is returned as it is."""
    name = _clean(name)
    statement_text = _clean(statement_text) or name
    for field, value in (("name", name), ("statement text", statement_text)):
        if not MIN_LENGTH <= len(value) <= MAX_LENGTH:
            raise ServiceError(422, f"The vendor {field} must be {MIN_LENGTH} to {MAX_LENGTH} characters")
        if not re.search(r"[A-Za-z0-9]", value):
            raise ServiceError(422, f"The vendor {field} needs at least one letter or digit")

    existing = repo.list_vendor_aliases()
    for vendor in existing:
        if vendor["display_name"].casefold() == name.casefold():
            return vendor

    base = _slug(name)
    if not base:
        raise ServiceError(422, "The vendor name needs at least one letter or digit")
    taken = {v["vendor_key"] for v in existing}
    key, n = base, 2
    while key in taken:  # same letters as another vendor under a different name: keep both
        key, n = f"{base}{n}", n + 1

    row = repo.add_vendor_alias(
        {
            "vendor_key": key,
            "display_name": name,
            "statement_pattern": re.escape(statement_text),
            "invoice_pattern": re.escape(name),
            "match_mode": "single",
            "date_before_days": 7,
            "date_after_days": 7,
            "active": True,
        }
    )
    log.info("Vendor %s added by %s", key, actor)
    return row
