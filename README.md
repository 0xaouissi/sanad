# Sanad (سند)

Open-source, self-hosted RAG chatbot that any company embeds on its website
with **one script tag**. Visitors ask about policies, rules and services; the
bot answers **only** from the documents the company uploaded — with sources.

- Languages: Modern Standard Arabic, French, English. The visitor's language
  is detected and the answer comes back in it, with proper RTL rendering.
- Local-first: Ollama (Qwen 2.5 instruct, quantized) + BGE-M3 embeddings.
  An OpenAI-compatible API is an optional, config-only fallback.
- Stack: FastAPI (async) · PostgreSQL + pgvector · Redis · vanilla-JS widget ·
  React SPA dashboard (Vite) · one `docker compose up` command.
- License: MIT.

> Status: **Step 4 — embeddable widget, public site keys, feedback**. Working project name.

## Quick start (Docker, one command)

```bash
docker compose up -d
```

Starts the API (port 8000), PostgreSQL 16 + pgvector, Redis and Ollama. A
one-shot `ollama-init` container pulls the model for your tier (first run
downloads ~2 GB for the small tier). With an NVIDIA GPU:

```bash
docker compose -f docker-compose.yml -f deployment/docker-compose.gpu.yml up -d
```

Try it:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/llm
curl http://localhost:8000/health/db
```

Chat answers **only from your uploaded documents** — create a company, upload
a policy file, then ask questions in Arabic, French or English: see
[Grounded chat](#grounded-chat-step-3) below. To embed the chat widget on a
website, use the public site key: see [the widget](#the-embeddable-widget-step-4).
If Ollama is down or the model is missing, the API returns **503 with a
message that tells you exactly what to run** (e.g. `ollama pull …`).

## Documents and search (Step 2)

Companies are isolated by API key. Create one with the admin key
(`ADMIN_API_KEY` in `.env`), then upload documents and search:

```bash
# 1. Create a company (admin). The returned api_key is shown only once.
curl -X POST http://localhost:8000/api/v1/companies \
  -H "X-Admin-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"name": "Acme"}'

# 2. Upload a document (PDF, DOCX, TXT, MD — or PNG/JPG with OCR installed).
#    Returns 202 immediately; ingestion runs in the background.
curl -X POST http://localhost:8000/api/v1/documents \
  -H "X-API-Key: $API_KEY" -F "file=@policy.pdf"

# 3. Check status (pending -> processing -> ready | failed + reason).
curl http://localhost:8000/api/v1/documents -H "X-API-Key: $API_KEY"

# 4. Similarity search in Arabic, French or English (BGE-M3, pgvector HNSW).
curl -X POST http://localhost:8000/api/v1/search \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"query": "كم يوما لدي لطلب استرجاع المبلغ؟", "top_k": 5}'
```

Also available: `DELETE /api/v1/documents/{id}` and
`POST /api/v1/documents/{id}/reindex`. Re-uploading identical content is
detected (SHA-256 per company) and skipped. `GET /health/db` checks
PostgreSQL + pgvector.

Ingestion pipeline: extract text per page/heading (pypdf, python-docx) →
repair visual-order Arabic from PDFs → clean → normalize Arabic (alef
variants, diacritics, tatweel) → overlapping chunks (filename + page +
heading kept) → BGE-M3 embeddings → pgvector. Scanned PDFs and images go
through Tesseract OCR when the `ocr` extras are installed.

Embeddings setup (native dev): install CPU torch first to avoid the 2.5 GB
CUDA download, then the extras and weights:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[embeddings,ocr]"
huggingface-cli download BAAI/bge-m3   # ~2.3 GB, cached under HF_HOME
```

## Grounded chat (Step 3)

`POST /api/v1/chat` answers **only from the company's documents**, in the
visitor's language (Arabic, French or English — auto-detected, or forced with
`"language": "ar"|"fr"|"en"`). Server-side: send the company `X-API-Key`.
From a browser: send the public `X-Site-Key` + an allowed `Origin` (see
[the widget](#the-embeddable-widget-step-4)).

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"message": "Combien de jours pour un remboursement ?"}'
```

Response: `answer`, `language`, `conversation_id`, `message_id`, `citations`
(filename, page, heading, chunk id), `model`, `provider`.

How it works:

- **Hybrid retrieval** — dense BGE-M3 similarity + PostgreSQL full-text
  keyword search, fused with reciprocal rank fusion. On medium/large tiers a
  local cross-encoder (`bge-reranker-v2-m3`) re-ranks the top candidates;
  off by default on the small tier, override with `RERANK_ENABLED`.
- **"I don't know" rule** — if the best source scores below
  `RETRIEVAL_MIN_SCORE` (default 0.43, calibrated on real BGE-M3 scores), the
  LLM is never called: the visitor gets a localized "I don't know" with an
  offer to contact support. Questions that retrieve sources but cannot be
  answered from them are refused by the same rule in the prompt. Refusals
  never carry citations.
- **Strict grounding** — the prompt forbids outside knowledge and requires
  inline `[n]` citations; the response maps them to document name + page.
- **Conversation memory** — pass `conversation_id` back to continue a chat;
  the last `MEMORY_MAX_TURNS` messages are replayed (and the previous turn
  helps retrieval understand follow-ups like "and how long does it take?").
- **Language retry** — if the model answers in the wrong language, it is
  retried once with an explicit instruction (works for streaming too).
- **Latency** — time to first streamed token is logged per request
  (`chat_latency`) against the tier budget: ≤8 s small, ≤3 s medium/large.

Streaming: add `"stream": true`. Server-sent events are `token` chunks, then
a final `done` event carrying `conversation_id`, `language`, `message_id` and
`citations` (or an `error` event with an actionable detail).

## The embeddable widget (Step 4)

One script tag on any website — no build step, no dependencies, Shadow DOM so
the host page's CSS can't break it (and vice versa):

```html
<script src="http://localhost:8000/widget.js" data-site-key="pk-…" defer></script>
```

The widget uses a **public site key**, never the secret company API key. Each
company gets a `pk-…` key at creation (also returned by
`POST /api/v1/companies`). The site key only works on the company's **allowed
domains** — set them once with the secret key:

```bash
curl -X PUT http://localhost:8000/api/v1/companies/domains \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"domains": ["example.com", "*.example.com"]}'
```

`*.example.com` matches subdomains only, not the apex — list both if needed.
Requests from other origins (or with no `Origin` header) get **403 with a
message explaining how to fix it**. The secret key still works everywhere for
server-side use and is required for documents, search and domain management;
the site key is rejected on those endpoints.

Configuration via `data-*` attributes on the script tag:

| Attribute | Default | Meaning |
|-----------|---------|---------|
| `data-site-key` | — | **Required.** The company's public `pk-…` key |
| `data-api-url` | script origin | Backend base URL (when served from a CDN) |
| `data-color` | `#2563eb` | Accent color (validated; falls back if invalid) |
| `data-logo` | none | Header logo URL (`http(s)` only) |
| `data-welcome` | localized greeting | First message shown when the panel opens |
| `data-lang` | `auto` | `auto` detects the visitor's language; `ar`/`fr`/`en` force it. A dropdown in the header lets visitors switch at any time |
| `data-theme` | `auto` | `auto` follows the OS setting; `light`/`dark` force it |

With `data-lang="auto"` the answer language always matches the question.
On the small tier, answers are most reliable when the documents, the question
and the answer share a language; mixing languages (e.g. asking in French
about English documents, or forcing a different answer language) can
occasionally give weak answers — medium/large tiers handle this better.

Features: floating button, streaming answers with a typing indicator,
clickable citation chips (filename, page, heading), thumbs up/down per answer
(`POST /api/v1/feedback`, one rating per message), full RTL for Arabic,
full-screen panel on mobile, light/dark themes, Escape to close, `aria-live`
messages.

**Safety:** answers are rendered with `textContent` only — no `innerHTML`, no
raw HTML anywhere in the widget. A malicious document containing
`<script>`/`<img onerror=…>` is displayed as literal text and cannot execute
(covered by a real-browser XSS test). Logo URLs are restricted to `http(s)`.

### What the public site key does and does not protect

The `pk-…` site key is **public by design**: anyone can read it from the page
source, and the `Origin` header it is checked against can be spoofed by
non-browser clients. It is an *identifier plus a browser-only guard rail*,
not an authentication secret:

- **It does:** identify the company, and stop *other websites* from embedding
  your widget key in their pages (browsers enforce the `Origin` allowlist).
- **It does not:** stop a determined script that calls the API directly with a
  copied key and a forged `Origin`.

That is why the real abuse backstops are server-side and apply to every chat
request: **per-IP and per-site rate limits, a daily cap per company, and the
widget bot check** (below). Keep the secret `sk-…` API key on your server
only — it is required for documents, search and domain management, and it
bypasses the bot check (server-side integrations are trusted callers).
Company API keys are stored **only as SHA-256 hashes**; the plaintext is shown
once at creation and never persisted.

## Protection, cache and observability (Step 5a)

**Rate limits and daily cap.** Chat requests are counted in fixed windows:
`RATE_LIMIT_PER_IP` (default 30/min), `RATE_LIMIT_PER_SITE` (120/min per
company) and `DAILY_CAP_PER_COMPANY` (1000 chats per UTC day). Exceeding any
limit returns **429 with `Retry-After`**; the widget displays the message.
`0` disables a limit. Behind a reverse proxy that overwrites
`X-Forwarded-For`, set `TRUST_FORWARDED_FOR=true` to count visitor IPs instead
of the proxy's.

**Bot check (widget path only).** The widget renders a hidden honeypot field
that must stay empty and sends the time the panel was opened; requests sent
sooner than `BOT_CHECK_MIN_SECONDS` (default 2 s) are rejected. This deter
trivial bots — it is not a security boundary. Secret-key callers are exempt.

**Answer cache.** Grounded first-turn answers are cached in Redis (or memory
when `REDIS_URL` is empty/unreachable — the app warns and falls back, it never
refuses to start). Keys embed **company id + language + question hash + a
per-company document epoch**, so answers can never leak between companies or
languages, and any upload/delete/reindex invalidates that company's cache.
Follow-up turns (with history) are never cached. Cache failures degrade to a
miss; chat keeps working.

**Prompt-injection defense (layered, verified on the live 3B model).**
1. Grounding rules declare sources and questions to be *data, never
   instructions*, and forbid revealing the system prompt.
2. Injection-matching sentences are stripped from the context sent to the
   LLM (stored documents and citations are untouched).
3. Obvious override/extraction questions ("ignore your instructions…",
   "print your system prompt", in ar/fr/en) are refused **before any model
   call**.
4. Answers that leak prompt text, or junk-prefixed refusals, are normalized
   to the clean localized "I don't know".
Live e2e tests upload a hostile document in each language and prove normal
questions stay grounded while attack questions never leak the prompt.

**Conversation privacy.** Conversation ids are unguessable UUID4 and are
scoped to their company: another company's key (or a random id) gets **404**,
on both the sync and streaming paths.

**Migrations.** Schema changes are managed by **Alembic**
(`backend/migrations/`); the app migrates to head at startup. For manual use:
`alembic upgrade head`, `alembic revision --autogenerate -m "…"`,
`alembic check` (drift detection).

**Metrics.** `GET /api/v1/metrics` (admin-protected, `X-Admin-Key`) returns
Prometheus text: `sanad_chats_total`, `sanad_refusals_total`,
`sanad_cache_hits_total`, `sanad_cache_misses_total`, `sanad_rate_limited_total`
plus database gauges (companies, documents, chunks, conversations, messages).

```bash
curl http://localhost:8000/api/v1/metrics -H "X-Admin-Key: $ADMIN_API_KEY"
```

All Step 5a settings are documented in [.env.example](.env.example).

## Native development (no Docker)

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

Configuration: copy [.env.example](.env.example) to `backend/.env` (native)
or `.env` (Docker). Every setting is documented there.

### PostgreSQL + pgvector (native dev)

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

The API creates its tables at startup and checks the setup at `GET /health/db`.

## Tests and lint

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q                 # unit tests (offline, mocked providers)
.venv/Scripts/python.exe -m pytest -m integration     # real PostgreSQL + pgvector (fake embeddings)
.venv/Scripts/python.exe -m pytest -m e2e             # live: real Ollama + BGE-M3, ar/fr/en grounded chat + refusal
.venv/Scripts/python.exe -m ruff check app tests
```

Integration/E2E tests need PostgreSQL with pgvector and the `sanad` database
(default `DATABASE_URL`; override with `TEST_DATABASE_URL`). They skip with a
clear message when a dependency is missing. The OCR E2E also needs
`TESSERACT_CMD` and `TESSDATA_PREFIX` set.

### Widget browser tests (real Chromium)

Nine Playwright tests drive the widget on a blank HTML page served from a
local site: Arabic RTL, mobile viewport, citation popovers, thumbs-up
persisted to the database, manual French, custom colors/logo/welcome/theme,
XSS from a malicious document, and rejection from a non-allowed domain.

```bash
pip install -e ".[browser]"
python -m playwright install chromium        # or set PLAYWRIGHT_BROWSERS_PATH to an existing install
.venv/Scripts/python.exe -m pytest tests/e2e/test_widget_browser.py -m e2e -v
```

They need the same live stack as the other E2E tests (Ollama + BGE-M3 +
PostgreSQL); each test starts its own API server on a free port, so nothing
else has to be running. Skips with an install hint when Playwright or the
browser is missing.

## Hardware tiers

One setting adapts the stack to the machine. Full details and the environment
reference: [docs/hardware-tiers.md](docs/hardware-tiers.md).

| Tier | Hardware | Default model | Context |
|------|----------|---------------|---------|
| `small` (default) | CPU-only or 4 GB VRAM | `qwen2.5:3b-instruct-q4_K_M` | 8192 |
| `medium` | 8–12 GB VRAM | `qwen2.5:7b-instruct-q4_K_M` | 16384 |
| `large` | 16+ GB server GPU | `qwen2.5:14b-instruct-q4_K_M` | 32768 |

Switching models is a settings change only:

```env
MODEL_TIER=medium                          # pick a tier
LLM_MODEL=qwen2.5:3b-instruct-q8_0         # or override name + quantization
LLM_NUM_CTX=4096                           # or shrink context to save VRAM
CPU_ONLY=true                              # force everything onto CPU
LLM_PROVIDER=openai                        # optional API fallback (+ OPENAI_API_KEY)
```

The 1.5B model is a last resort, never a default (weak Arabic). There is no
benchmark script; answer quality per language is measured by the evaluation
page (Step 6).

## Roadmap

Each step ships with tests, docs and small commits.

0. **Hardware tiers** — tier defaults, env overrides, CPU-only mode *(done)*
1. **Project setup, FastAPI and Ollama** — health, structured logging, provider interface, streaming chat, Docker Compose *(done)*
2. **Documents, chunking, multilingual embeddings** — multi-company isolation, PDF/DOCX/TXT/MD upload, OCR, Arabic normalization, pgvector, background ingestion *(done)*
3. **Retrieval, the "I don't know" rule, language detection** — hybrid search + rerank, citations, conversation memory, latency targets *(done)*
4. **The embeddable widget** — one script tag, Shadow DOM, RTL, themes, ratings *(done)*
5. **Protection, speed, admin dashboard** — split in two:
   - **5a** *(done)*: rate limits per IP/site, daily company cap, widget bot check, Redis answer cache with in-memory fallback, prompt-injection defense, Alembic migrations, Prometheus metrics
   - **5b**: React dashboard — login, roles, documents, failed questions, ratings, privacy controls, data export and deletion
6. **Evaluation page, website crawling, human handoff** — per-language accuracy scores, scheduled re-sync, email/Telegram handoff
7. **Documentation, demo and release** — demo GIF/video, CI, live demo, first release

## License

[MIT](LICENSE)