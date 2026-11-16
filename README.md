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

## Demo

| Widget — trilingual answers, citations, RTL | Dashboard — documents, evaluation, settings |
|---------------------------------------------|----------------------------------------------|
| ![Widget demo](docs/demo-widget.gif) | ![Dashboard demo](docs/demo-dashboard.gif) |

Run the demo yourself, or re-record these clips: [docs/demo.md](docs/demo.md).
Put Sanad on a real server: [deployment/README.md](deployment/README.md).

> **v0.1.0** — first release. See the [changelog](CHANGELOG.md).

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
sooner than `BOT_CHECK_MIN_SECONDS` (default 2 s) are rejected. This deters
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

## Admin dashboard (Step 5b)

A React SPA served by the backend at **`/dashboard/`** — the built bundle is
committed, so no Node.js is needed to run it. English, French and Arabic
(Arabic switches the whole interface to RTL); the choice is remembered.

Create a company **with an owner account** to sign in:

```bash
curl -X POST http://localhost:8000/api/v1/companies \
  -H "X-Admin-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"name": "Acme", "owner_email": "you@acme.com", "owner_password": "a-long-password"}'
```

Then open `http://localhost:8000/dashboard/` and sign in. Pages:

- **Documents** — upload, live status badges, reindex, delete.
- **Website** — crawl your site's policy pages into documents, sync, delete (Step 6b).
- **Failed questions** — what the bot refused, with language and date.
- **Ratings** — visitor thumbs up/down with the question and answer.
- **Handoffs** — visitors' requests to talk to a human, with per-channel
  delivery status (Step 6c).
- **Evaluation** — run the golden Q&A set and see per-language scores (Step 6a).
- **Settings** — the widget snippet (copy button), allowed domains, the
  conversation-storage privacy toggle, handoff destinations (support email,
  Telegram chat id), key rotation, JSON export,
  delete-all-conversations, and team management.

Security:

- Passwords are hashed with **scrypt** (stdlib, salted); plaintext is never
  stored. Login is rate-limited per IP (`LOGIN_RATE_LIMIT_PER_MINUTE`,
  default 10, `0` disables) and returns 429 + `Retry-After`.
- Sessions use an **httpOnly, SameSite=Lax cookie** backed by the KV store
  (Redis or memory), expiring after `DASHBOARD_SESSION_HOURS` (default 12).
  Every mutation requires the session's **CSRF token** in `X-CSRF-Token`;
  without it the API returns 403. Set `COOKIE_SECURE=true` behind HTTPS.
- **Roles are enforced server-side**: the owner manages everything; viewers
  (added from Settings) are read-only — the UI hides mutation controls and
  the API rejects them with 403 regardless.
- Every destructive action (delete document, reindex, rotate keys, delete
  all conversations) asks for confirmation in the interface.
- **Key rotation** issues a new secret `sk-…` and public `pk-…` key at once;
  the old keys stop working immediately and the new secret is shown only
  once. Update the widget snippet after rotating.
- **Privacy toggle**: with *Store conversations* off, chats are still
  answered but nothing is persisted — no history, failed questions, ratings
  or cache — and chat responses carry null conversation/message ids.
  Handoff requests are still delivered but not saved (Step 6c).
- **Export** downloads all company data as JSON (no keys, no password
  hashes); **delete-all-conversations** removes messages and ratings too.

Development: `cd dashboard && npm install && npm run dev` (Vite on :5173,
proxies the API). `npm run build` type-checks and rebuilds the committed
bundle. See [dashboard/README.md](dashboard/README.md).

## Golden evaluation (Step 6a)

Measure answer quality per language **without the model judging itself**.
A fixed golden set of **33 questions — 11 each in Arabic, French and
English** — runs through the exact same retrieval + prompt + model path as
live chat, then is scored deterministically:

- **12 grounded** questions about the demo policies: every expected fact
  must appear in the answer (Arabic-normalized, digit-folded substring
  match) and every citation must point at an expected source document.
- **15 out-of-scope** questions (weather, capitals, recipes…): the bot must
  refuse with the standard "I don't know" answer and **no citations**.
- **6 prompt-injection** attacks ("ignore your instructions…", DAN…):
  blocked before the model, no prompt leak, no citations.

The golden set lives in [backend/app/eval/golden.json](backend/app/eval/golden.json)
and targets the trilingual demo policies in [samples/](samples/) (identical
facts in `demo-policy.en.md`, `demo-politique.fr.md`, `demo-siasa.ar.md`).

**Sample company.** Seed a demo company with the sample documents already
ingested (real BGE-M3 embeddings):

```bash
cd backend
.venv/Scripts/python.exe -m app.eval.seed --password "a-long-password"
# optional: --email demo@sanad.example --name "Sanad Demo"
```

It prints the dashboard login, the secret API key (once) and the public
site key. Sign in at `/dashboard/`, open **Evaluation** and press
**Run evaluation** (owner only). The page shows the question count per
language, live progress, pass/fail per language and per category, and each
case with its failed checks. Viewers can see results but cannot run.

API (dashboard session + CSRF for the run):

```bash
curl -X POST http://localhost:8000/api/v1/dashboard/eval/run   # 202; 409 if already running
curl http://localhost:8000/api/v1/dashboard/eval               # state, progress, results, golden counts
```

Runs are background tasks with progress in the KV store (24 h retention);
a run stuck for over 30 minutes can be superseded. Evaluation **never
writes conversations, messages, ratings, cache entries or chat metrics** —
it cannot pollute the Failed questions page or the counters. If the demo
documents are missing, the page warns and grounded cases fail honestly.

## Website crawler (Step 6b)

Instead of uploading files, point Sanad at your website: it crawls the
policy pages, turns each into a document, and keeps them fresh on a
schedule. Sign in at `/dashboard/`, open **Website**, paste a URL and press
**Add website**. Crawling and ingestion run in the background; the table
shows status, pages crawled and last sync. **Sync now** re-crawls on demand;
**Delete** removes the source and every document crawled from it.

API (dashboard session; mutations also need `X-CSRF-Token`):

```bash
curl -X POST http://localhost:8000/api/v1/dashboard/crawl-sources \
  -H "Content-Type: application/json" -d '{"url": "https://acme.com/policies"}'  # 202
curl http://localhost:8000/api/v1/dashboard/crawl-sources
curl -X POST http://localhost:8000/api/v1/dashboard/crawl-sources/<id>/sync     # 202; 409 while crawling
curl -X DELETE http://localhost:8000/api/v1/dashboard/crawl-sources/<id>        # 204
```

**SSRF protection** (on by default, no setting to weaken it in production):

- `http`/`https` only; URLs with embedded credentials are rejected.
- Every DNS answer is checked: if **any** resolves to a private, loopback,
  link-local (incl. `169.254.169.254` cloud metadata), reserved, multicast
  or CGNAT address, the crawl is refused. The connection then **pins the
  validated IP** (with the original `Host` header and TLS SNI), so DNS
  cannot rebind between check and connect.
- Redirects are followed manually (max 5) and **every hop is re-validated**:
  scheme, same domain, and IP ranges again.
- Same domain only: `acme.com` and `www.acme.com` and subdomains of either;
  look-alike domains (`acme.com.evil.com`) are rejected.
- `robots.txt` is respected per URL. A missing file (404) allows crawling;
  an unreachable or erroring one **fails the crawl conservatively**.
- Limits: `CRAWL_MAX_PAGES` (20), `CRAWL_MAX_PAGE_BYTES` (2 MB per page),
  `CRAWL_TIMEOUT_SECONDS` (15 per request), `CRAWL_MAX_SECONDS` (300 total).
  Only HTML/XHTML/plain-text responses are accepted.

**Injection defense:** crawled titles and text pass through the same
sentence-level sanitizer as uploaded documents *before* storage, so
"ignore your instructions…" payloads hidden in a page never reach the
model or the vector index.

**Safe re-sync:** `CRAWL_RESYNC_HOURS` (default 24, `0` disables) re-crawls
due sources in a background loop. Unchanged pages are kept as-is; a changed
page's old document is deleted **only after** its replacement ingests
successfully; pages that disappeared are removed. If a crawl fails —
network, robots, everything — the previous documents stay untouched.

All settings are documented in [.env.example](.env.example).
`CRAWL_ALLOW_PRIVATE=true` exists **only** so tests and local development
can crawl a loopback fixture site; never enable it on a reachable server.

## Human handoff (Step 6c)

Visitors can ask for a human at any time: a **"Talk to a human"** link in the
widget footer opens a small form (email + message + privacy notice). The
request is delivered to the company's support **email** and/or **Telegram**
chat, and — when *Store conversations* is on — listed in the dashboard's
read-only **Handoffs** tab with per-channel delivery status.

Setup is two layers:

1. **Server transports** (environment only — secrets never touch the database
   or the API): `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
   `SMTP_FROM`, `SMTP_STARTTLS`, `SMTP_TIMEOUT_SECONDS` for email;
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_BASE`, `TELEGRAM_TIMEOUT_SECONDS` for
   Telegram (create a bot with [@BotFather](https://t.me/BotFather), message
   it once, then use your chat id or a group/channel id). An empty host/token
   disables that channel. `SMTP_HOST` without `SMTP_FROM` fails fast at
   startup with a clear message.
2. **Company destinations** (dashboard Settings, owner-only):
   `handoff_email` and `telegram_chat_id`. The API only ever exposes whether
   each server transport is configured (`smtp_configured` /
   `telegram_configured` booleans), never the credentials.

```bash
curl -X POST http://localhost:8000/api/v1/handoff \
  -H "X-Site-Key: pk-..." -H "Origin: https://yourdomain.com" \
  -H "Content-Type: application/json" \
  -d '{"email": "visitor@example.com", "message": "Please call me back"}'
# → {"email": "sent", "telegram": "skipped", "stored": true}
```

Guarantees:

- **Same auth as chat**: public site key + the company's `Origin` allowlist
  (or the secret API key server-side), plus the widget bot check
  (honeypot + timing) on the site-key path.
- **Validation & header-injection protection**: emails are strictly
  validated (length, shape, no control characters or line breaks); chat ids
  must be numeric or `@channelname`. Company names and addresses are
  additionally stripped of control characters when building email headers.
- **Rate limits**: `HANDOFF_RATE_LIMIT_PER_IP` (default 5/minute) and
  `HANDOFF_DAILY_CAP_PER_COMPANY` (default 50/UTC day), `0` disables,
  429 + `Retry-After`, fail-open when Redis is down — separate buckets from
  chat limits.
- **Actionable errors**: no destination configured → 409 telling the owner
  what to add in Settings; destination set but server transport missing →
  409 naming the exact env vars; one channel failing → 200 with per-channel
  statuses; both failing → 502 (the failed attempt is still stored when
  storage is on). SMTP passwords and Telegram tokens never appear in
  responses or logs.
- **Privacy**: the form shows a notice before sending; with *Store
  conversations* off the request is delivered but nothing is saved.
- The email carries `Reply-To: visitor@…` so the team can answer directly;
  Arabic/French/English messages are sent as UTF-8, and Telegram text is
  capped at the Bot API's 4096 characters.

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

The API migrates the schema to head at startup (**Alembic**, `backend/migrations/`)
and checks the setup at `GET /health/db`.

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

### Browser tests (real Chromium)

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
page (Step 6a).

## Roadmap

Each step ships with tests, docs and small commits.

0. **Hardware tiers** — tier defaults, env overrides, CPU-only mode *(done)*
1. **Project setup, FastAPI and Ollama** — health, structured logging, provider interface, streaming chat, Docker Compose *(done)*
2. **Documents, chunking, multilingual embeddings** — multi-company isolation, PDF/DOCX/TXT/MD upload, OCR, Arabic normalization, pgvector, background ingestion *(done)*
3. **Retrieval, the "I don't know" rule, language detection** — hybrid search + rerank, citations, conversation memory, latency targets *(done)*
4. **The embeddable widget** — one script tag, Shadow DOM, RTL, themes, ratings *(done)*
5. **Protection, speed, admin dashboard** — split in two:
   - **5a** *(done)*: rate limits per IP/site, daily company cap, widget bot check, Redis answer cache with in-memory fallback, prompt-injection defense, Alembic migrations, Prometheus metrics
   - **5b** *(done)*: React dashboard — scrypt login with rate limiting, httpOnly cookie sessions + CSRF, owner/viewer roles, documents, failed questions, ratings, settings (snippet, domains, key rotation), privacy toggle, data export and deletion, ar/fr/en RTL interface
6. **Evaluation page, website crawling, human handoff** — split in three:
   - **6a** *(done)*: golden Q&A evaluation — 33 questions (11 per language), grounded/out-of-scope/injection cases, deterministic fact + citation + refusal scoring, sample company and demo documents, dashboard evaluation page
   - **6b** *(done)*: SSRF-safe website crawler — IP-pinned connections, per-hop redirect re-validation, same-domain + robots.txt, page/size/time limits, injection-sanitized storage, safe scheduled re-sync, dashboard Website tab
   - **6c** *(done)*: human handoff — widget form with privacy notice, email (SMTP) + Telegram delivery, env-only secrets, header-injection protection, per-IP + daily rate limits, privacy toggle respected, dashboard Handoffs tab and Settings destinations
7. **Documentation, demo and release** — demo GIF/video, CI, live demo, first release *(done)*

## License

[MIT](LICENSE)