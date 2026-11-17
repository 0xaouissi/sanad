# Changelog

## 0.2.0 — 2026-11-17

Repository polish, a clearer refusal split, and an Apache-2.0 model evaluation.

### Added

- **Held-out evaluation** — 30 unseen questions (10 per language, including
  related-but-not-covered) in `backend/app/eval/heldout.json`, run through the
  identical scored path by `scripts/run_heldout.py` and reported separately from
  the golden set. Latest real-model run: 27/30. docs/evaluation.md now states
  that the thresholds were calibrated on the same demo documents as the golden
  set, and documents how to re-tune both thresholds on your own corpus.
- **Apache-2.0 model evaluation** — the non-thinking
  `qwen3:4b-instruct-2507-q4_K_M` (Qwen3-4B-Instruct-2507, Apache-2.0) scored
  **42/42 golden and 30/30 held-out**, beating the research-licensed 3B
  (41/42, 27/30) at similar warm latency. `scripts/run_golden.py` is the CLI
  twin of the dashboard evaluation for comparing models without touching the
  default config. The default is unchanged pending a decision; see
  docs/evaluation.md and docs/models.md.
- **Startup license warning** — the app logs `llm_model_research_license` when
  the resolved LLM is a research-licensed Qwen2.5-3B variant (including
  `LLM_MODEL` overrides and OpenAI-compatible model names), pointing to
  Apache-2.0 options in docs/models.md.
- **`LLM_THINK` setting** — optional Ollama `think` parameter for reasoning
  models such as qwen3 (default unset = the field is not sent, so Qwen2.5
  behavior is unchanged).
- **Repository kit** — CONTRIBUTING.md, SECURITY.md, issue templates, a
  cross-platform Makefile, and Dependabot configuration
  (`.github/dependabot.yml`).
- **CI compose-smoke job** — `docker compose up --build` plus a health smoke
  test (`/health`, `/health/db`, `/widget.js`, `/dashboard/`).

### Changed

- **Two refusal kinds** — the single "I don't know" reply is split into
  `off_topic` ("I can only help with questions about this company", no handoff)
  and `not_covered` ("I couldn't find this in the company's documents", with a
  "Talk to a human" button). A new lower threshold `RETRIEVAL_OFF_TOPIC_SCORE`
  (default 0.41, must be ≤ `RETRIEVAL_MIN_SCORE`) separates them; questions
  that retrieve sources but cannot be answered are treated as company-related.
  Chat responses and stream `done`/`error` events carry `refusal_kind`; the
  answer cache key was bumped to `chat:v2:`.
- **Widget handoff offer** — for `not_covered` refusals an inline "Talk to a
  human" button opens the handoff form prefilled with the visitor's question.
  It never submits automatically; the visitor must press Send. The
  always-visible footer link is unchanged.
- **Golden evaluation** — grew from 33 to **42 questions** (14 per language)
  with a new *related-but-not-covered* category (9 cases) scored on whether the
  handoff is offered; out-of-scope and injection cases now also assert that no
  handoff is offered. Latest real-model run: 41/42 (see docs/evaluation.md).
- **Retrieval thresholds under reranking** — both thresholds now always compare
  the pre-rerank dense cosine similarity. The reranker's sigmoid probability is
  a different scale, so it only reorders candidates and is never used for the
  refusal decision; one calibration stays valid with reranking on or off. The
  decision uses the best cosine score across hits, not the first (reranked) hit.
- **README and docs** — README rewritten as a short pitch (demo GIFs, features,
  quick start, architecture diagram, evaluation results, limitations, links);
  detailed sections moved into `docs/` and renamed by topic, not build step.
  Added an evaluation results table (per language, model, tier, date, question
  count) with the honest small-set caveat, and a model-licenses note
  (`docs/models.md`).
- **README privacy claim** — "No data leaves your server" now states that the
  default local models keep data on-server, while two opt-in features send data
  outward: the OpenAI-compatible API fallback (`LLM_PROVIDER=openai`) and human
  handoff (SMTP email / Telegram).
- **Demo GIFs** — re-recorded with the contextual handoff offer; verified no
  frame shows a secret key or personal email; docs note the demo password must
  be changed before any real use.

### Fixed

- **Docker image migrations** — the image now copies `migrations/`, so Alembic
  runs at startup (`init_db`) instead of aborting with "Path doesn't exist:
  /app/migrations". Caught by the new compose-smoke CI job.

### Security

- Secret scanning and push protection enabled; Dependabot alerts, security
  updates and private vulnerability reporting enabled. gitleaks scanned the
  full git history (no leaks).

### Tests

688 automated tests: 442 unit, 193 integration (real PostgreSQL + pgvector,
0 skipped), 30 live API e2e (real Ollama + BGE-M3, trilingual chat, refusal,
crawl, evaluation, handoff transports), 23 real-Chromium browser tests.
Golden 41/42 and held-out 27/30 on the default 3B; 42/42 and 30/30 on the
Apache-2.0 Qwen3-4B-Instruct-2507 candidate.

## 0.1.0 — 2026-11-16

First public release. Self-hosted, grounded RAG chatbot: one script tag on any
website, answers only from the company's documents, in Arabic (MSA), French
and English.

### Added

- **Hardware tiers** — `small` / `medium` / `large` defaults (Qwen 2.5 3B/7B/14B
  quantized via Ollama), env overrides for model, context and CPU-only mode;
  clear errors when the machine or a dependency is too weak. Optional
  OpenAI-compatible provider by config.
- **Grounded chat** — hybrid retrieval (BGE-M3 dense + PostgreSQL FTS, RRF
  fusion, optional BGE reranker on medium/large), sentence-level citations,
  conversation memory, language detection with same-language answers and full
  RTL, and the "I don't know" rule for anything the documents do not cover.
- **Documents** — per-company isolation by hashed API key; PDF, DOCX, TXT, MD
  upload with background ingestion; Tesseract OCR for scans and images;
  Arabic normalization and visual-order repair; SHA-256 dedupe; reindex and
  delete; pgvector HNSW search.
- **Embeddable widget** — vanilla JS, Shadow DOM, streaming answers, citation
  popovers, thumbs up/down, light/dark themes, custom color/logo/welcome,
  forced or auto language, mobile full-screen panel, `textContent`-only
  rendering (XSS-safe), public site key restricted to allowed domains.
- **Protection and observability** — per-IP and per-site rate limits, daily
  company cap, widget bot check (honeypot + timing), Redis answer cache with
  in-memory fallback, prompt-injection sanitization of documents and crawled
  pages, Alembic migrations, Prometheus metrics.
- **Admin dashboard** — Vite + React SPA (ar/fr/en, RTL): scrypt login with
  rate limiting, httpOnly cookie sessions + CSRF, owner/viewer roles,
  documents, failed questions, ratings, settings (snippet, domains, privacy
  toggle, key rotation, export, delete-all), team management.
- **Golden evaluation** — 33 questions (11 per language) with deterministic
  fact, citation and refusal scoring; dashboard Evaluation page with live
  progress and per-language/per-category scores; sample company seed.
- **Website crawler** — SSRF-safe (IP-pinned connections, per-hop redirect
  re-validation, private-range DNS blocking), same-domain + robots.txt,
  page/size/time caps, injection-sanitized storage, safe scheduled re-sync,
  dashboard Website tab.
- **Human handoff** — visitor form in the widget, delivery by email (SMTP) and
  Telegram from env-only credentials, per-IP rate limit and daily cap, email
  and header-injection validation, privacy notice, conversation-storage
  toggle respected, dashboard Handoffs tab and destination settings.
- **Demo kit** — `scripts/record_demo.py` records trilingual widget and
  dashboard GIFs with real Chromium and real models; `docs/demo.md`
  walkthrough; deployment guide with a before-going-public checklist.
- **CI** — GitHub Actions: ruff + unit tests, integration tests on a
  pgvector service container, dashboard type-check and build. Live model and
  browser suites remain a local pre-release gate.

### Tests

634 automated tests: 397 unit, 188 integration (real PostgreSQL + pgvector),
28 live API e2e (real Ollama + BGE-M3, trilingual chat, refusal, crawl,
evaluation, handoff transports), 21 real-Chromium browser tests (13 widget,
8 dashboard).