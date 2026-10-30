"""Print the pdftotext of invoices in a ZIP whose names contain the given words (Docker only: needs poppler).

    docker compose run --rm -e PYTHONPATH=/app tests python scripts/dump_invoice_text.py "October*Invoices.zip" IHC_3564 Netflix
"""

import sys
import zipfile
from pathlib import Path

from app.pdf import pdf_text

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures_private"

if __name__ == "__main__":
    archive = sorted(FIXTURES.glob(sys.argv[1]))[0]
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name = Path(info.filename).name
            if any(w.lower() in name.lower() for w in sys.argv[2:]) and name.lower().endswith(".pdf"):
                print(f"\n######## {name}\n{pdf_text(z.read(info))}")
