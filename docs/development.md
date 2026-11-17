# Development

Everything below runs natively, without Docker. The Docker path is one
command from the repository root: see the [README](../README.md#quick-start).

## Native setup (no Docker)

1. Install [Ollama](https://ollama.com/download) and pull the small-tier model:
   `ollama pull qwen2.5:3b-instruct-q4_K_M`
2. Backend:

```bash
cd backend
py -3.11 -m venv .venv                                # Python 3.11+
.venv/Scripts/python.exe -m pip install -e ".[dev]"   # Windows
# source .venv/bin/activate && pip install -e ".[dev]"  # Linux/macOS
.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

Configuration: copy [.env.example](../.env.example) to `backend/.env` (native)
or `.env` (Docker). Every setting is documented there. A `Makefile` at the
repository root wraps the common commands on Windows, Linux and macOS.

## PostgreSQL + pgvector

Docker Compose uses the `pgvector/pgvector:pg16` image, so nothing to do there.
On a native PostgreSQL install, pgvector must be added once:

- **Windows**: EDB StackBuilder does not carry pgvector. Either compile it
  (`nmake` with Visual Studio C++, see the
  [pgvector README](https://github.com/pgvector/pgvector#installation)) or use
  the community prebuilt DLLs referenced in
  [pgvector issue #54](https://github.com/pgvector/pgvector/issues/54)
  (e.g. `andreiramani/pgvector_pgsql_windows` — unofficial; verify the source).
  Copy `lib/vector.dll` and `share/extension/vector*` into your PostgreSQL
  folder (admin rights needed).
- **Linux/macOS**: `apt install postgresql-16-pgvector` (PGDG) or `brew install pgvector`.

Then create the role, database and extension once (as superuser):

```sql
CREATE ROLE sanad LOGIN PASSWORD 'sanad';
CREATE DATABASE sanad OWNER sanad;
\c sanad
CREATE EXTENSION IF NOT EXISTS vector;
```

The API migrates the schema to head at startup (**Alembic**, `backend/migrations/`)
and checks the setup at `GET /health/db`.

## Embeddings and OCR weights

Install CPU torch first to avoid the 2.5 GB CUDA download, then the extras
and weights:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[embeddings,ocr]"
huggingface-cli download BAAI/bge-m3   # ~2.3 GB, cached under HF_HOME
```

Point `HF_HOME` at a disk with space. OCR needs Tesseract installed and
`TESSERACT_CMD` / `TESSDATA_PREFIX` set (Arabic traineddata included).
Model licenses: [models.md](models.md).

## Tests and lint

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q                 # unit tests (offline, mocked providers)
.venv/Scripts/python.exe -m pytest -m integration     # real PostgreSQL + pgvector (fake embeddings)
.venv/Scripts/python.exe -m pytest -m e2e             # live: real Ollama + BGE-M3, ar/fr/en chat + refusal + crawl→chat + handoff transports
.venv/Scripts/python.exe -m ruff check app tests
```

Integration/E2E tests need PostgreSQL with pgvector and the `sanad` database
(default `DATABASE_URL`; override with `TEST_DATABASE_URL`). They skip with a
clear message when a dependency is missing. The OCR E2E also needs
`TESSERACT_CMD` and `TESSDATA_PREFIX` set.

**Never run the integration and e2e suites concurrently**: they truncate
shared tables. Re-seed the demo company afterwards
([evaluation.md](evaluation.md)).

## Browser tests (real Chromium)

Twenty-one Playwright tests drive real pages. **Widget (13):** Arabic RTL,
mobile viewport, citation popovers, thumbs-up persisted to the database,
manual French, custom colors/logo/welcome/theme, XSS from a malicious
document, rejection from a non-allowed domain, the bot check (hidden
honeypot field, filled-honeypot rejection), and the handoff form (real
delivery to a local SMTP sink + stored row, Arabic labels and the
not-configured error). **Dashboard (8):** login with
wrong-password error and cookie-session persistence, document upload and
delete through the UI, confirm dialogs (dismiss keeps, accept deletes),
viewer read-only access added through the UI, Arabic RTL / French labels,
settings (snippet, domains save, key-rotation confirm), the evaluation
tab (golden counts per language, missing-documents warning, owner-only run
button hidden from viewers), the website tab (crawl a local fixture
site with real embeddings, robots-blocked page never fetched, crawled
documents appear and are deleted with the source, viewer read-only), and
the handoffs tab (destinations saved in Settings, a real visitor request
delivered to the SMTP sink and listed, viewer read-only).

```bash
pip install -e ".[browser]"
python -m playwright install chromium        # or set PLAYWRIGHT_BROWSERS_PATH to an existing install
.venv/Scripts/python.exe -m pytest tests/e2e/test_widget_browser.py tests/e2e/test_dashboard_browser.py -m e2e -v
```

They need the same live stack as the other E2E tests (Ollama + BGE-M3 +
PostgreSQL; the dashboard tests alone need no LLM); each test starts its own
API server on a free port, so nothing else has to be running. Skips with an
install hint when Playwright or the browser is missing.