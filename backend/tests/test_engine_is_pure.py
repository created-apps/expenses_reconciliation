"""backend/app/engine is pure Python (hard rule): no database, network, storage or process calls, and no
import of the rest of the app. This reads every engine file and fails if one imports anything that could."""

import ast
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "app" / "engine"

# Modules that would reach outside the process or into the rest of the app.
FORBIDDEN = {
    "supabase", "postgrest", "storage3", "httpx", "httpx2", "requests", "urllib", "urllib3", "http", "socket", "ssl",
    "aiohttp", "anthropic", "fastapi", "starlette", "uvicorn", "subprocess", "asyncio", "threading", "multiprocessing",
    "os", "shutil", "tempfile", "sqlite3", "psycopg", "psycopg2", "smtplib", "ftplib",
}
FORBIDDEN_APP_PARTS = {"db", "storage", "pdf", "config", "auth", "main", "api", "services", "schemas"}


def imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append(node.module)
    return found


def test_there_are_engine_files_to_check():
    names = {p.name for p in ENGINE.rglob("*.py")}
    assert {"matcher.py", "subsets.py", "amazon_csv.py", "statement_icici.py", "vision.py", "generic.py"} <= names


def test_no_engine_file_imports_a_database_network_storage_or_process_module():
    problems = []
    for path in sorted(ENGINE.rglob("*.py")):
        for module in imports(path):
            top = module.split(".")[0]
            if top in FORBIDDEN:
                problems.append(f"{path.relative_to(ENGINE)} imports {module}")
    assert problems == []


def test_no_engine_file_imports_the_rest_of_the_app():
    problems = []
    for path in sorted(ENGINE.rglob("*.py")):
        for module in imports(path):
            parts = module.split(".")
            if parts[0] == "app" and (len(parts) < 2 or parts[1] != "engine" or parts[1] in FORBIDDEN_APP_PARTS):
                problems.append(f"{path.relative_to(ENGINE)} imports {module}")
    assert problems == []


def test_the_matcher_takes_no_clock_and_reads_no_files():
    source = (ENGINE / "matcher.py").read_text(encoding="utf-8")
    for needle in ("datetime.now", "date.today", "open(", "time.time", "random"):
        assert needle not in source, needle
