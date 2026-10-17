"""The vendor table as seeded by supabase/migrations/0003_recon_seed_vendor_aliases.sql.

Tests read the migration itself, so they always use the patterns that are really seeded
(no second copy to drift). In Docker the folder is mounted at /supabase.
"""

import re
from pathlib import Path

from app.engine.invoices.types import VendorPattern

CANDIDATES = [
    Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0003_recon_seed_vendor_aliases.sql",
    Path("/supabase/migrations/0003_recon_seed_vendor_aliases.sql"),
]
ROW = re.compile(
    r"\(\s*'(?P<key>\w+)',\s*'(?P<name>[^']*)',\s*(?P<stmt>NULL|'[^']*'),\s*(?P<inv>NULL|'[^']*'),"
    r"\s*'(?P<mode>\w+)',\s*(?P<before>\d+),\s*(?P<after>\d+),\s*true\)"
)


def _value(text: str) -> str | None:
    return None if text == "NULL" else text[1:-1]


def seed_rows() -> list[dict]:
    path = next((p for p in CANDIDATES if p.exists()), None)
    if path is None:
        raise FileNotFoundError("0003_recon_seed_vendor_aliases.sql not found")
    rows = []
    for m in ROW.finditer(path.read_text(encoding="utf-8")):
        rows.append(
            {
                "vendor_key": m["key"],
                "display_name": m["name"],
                "statement_pattern": _value(m["stmt"]),
                "invoice_pattern": _value(m["inv"]),
                "match_mode": m["mode"],
                "date_before_days": int(m["before"]),
                "date_after_days": int(m["after"]),
                "active": True,
            }
        )
    return rows


def seed_vendors() -> list[VendorPattern]:
    return [VendorPattern(r["vendor_key"], r["invoice_pattern"]) for r in seed_rows()]
