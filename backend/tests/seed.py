"""The vendor table as seeded by supabase/migrations/0003_recon_seed_vendor_aliases.sql.

Tests read the migration itself, so they always use the patterns that are really seeded
(no second copy to drift). In Docker the folder is mounted at /supabase.
"""

import re
from pathlib import Path

from app.engine.invoices.types import VendorPattern

SEED_FILES = ["0003_recon_seed_vendor_aliases.sql", "0005_recon_vendor_aliases_oct.sql", "0006_recon_vendor_aliases_manus_twilio.sql"]  # later files overwrite by key
FOLDERS = [Path(__file__).resolve().parents[2] / "supabase" / "migrations", Path("/supabase/migrations")]
ROW = re.compile(
    r"\(\s*'(?P<key>\w+)',\s*'(?P<name>[^']*)',\s*(?P<stmt>NULL|'[^']*'),\s*(?P<inv>NULL|'[^']*'),"
    r"\s*'(?P<mode>\w+)',\s*(?P<before>\d+),\s*(?P<after>\d+),\s*true\)"
)


def _value(text: str) -> str | None:
    return None if text == "NULL" else text[1:-1]


def seed_rows() -> list[dict]:
    folder = next((p for p in FOLDERS if (p / SEED_FILES[0]).exists()), None)
    if folder is None:
        raise FileNotFoundError(f"{SEED_FILES[0]} not found")
    rows: dict[str, dict] = {}
    for name in SEED_FILES:
        for m in ROW.finditer((folder / name).read_text(encoding="utf-8")):
            rows[m["key"]] = {
                "vendor_key": m["key"],
                "display_name": m["name"],
                "statement_pattern": _value(m["stmt"]),
                "invoice_pattern": _value(m["inv"]),
                "match_mode": m["mode"],
                "date_before_days": int(m["before"]),
                "date_after_days": int(m["after"]),
                "active": True,
            }
    return list(rows.values())


def seed_vendors() -> list[VendorPattern]:
    return [VendorPattern(r["vendor_key"], r["invoice_pattern"]) for r in seed_rows()]
