# Changelog

## 0.2.1 — 2026-11-17

A dashboard visual redesign and a build-tooling security bump. No backend,
widget, API or schema changes.

### Changed

- **Dashboard redesign** — the dashboard stylesheet was rewritten as a
  tokenized design system: neutral surfaces with the blue accent kept, a
  refined type scale, spacing/radius/shadow tokens, a sticky blurred header
  with a brand mark, a pill segmented tab bar, elevated panels, focus rings
  on inputs, hover/active/disabled button states, uppercase table headers
  with row hover, and tinted status badges. Uses CSS logical properties so
  the Arabic RTL layout mirrors correctly, plus a responsive mobile layout.
  CSS-only — no React logic, selectors or behaviour changed; all 8 dashboard
  browser tests still pass.

### Security

- **Dashboard build tooling** — bumped Vite from 5.4.21 to 6.4.6, which
  resolves its transitive esbuild to 0.25.12. This clears the 9 open
  Dependabot alerts (8 in Vite, 1 in esbuild). These are build-time dev
  dependencies and are not shipped in the static bundle. Note: Vite ≥ 6.3
  pulls a transitive `picomatch` with an open ReDoS advisory that has no
  upstream fix yet (`picomatch ≤ 4.0.7`); it is dev-only, does not affect the
  production bundle, and GitHub raised no Dependabot alert for it.

### Tests

Dashboard build clean (tsc + Vite 6.4.6) and all 8 dashboard browser tests
pass on the redesigned UI and the bumped toolchain. Backend is unchanged from
0.2.0 (443 unit / 193 integration / 30 live API e2e / 23 browser).

## 0.2.0 — 2026-11-17

Repository polish, a clearer refusal split, and a new Apache-2.0 small-tier
default (Qwen3-4B-Instruct-2507).

### Added

- **Held-out evaluation** — 30 unseen questions (10 per language, including
  related-but-not-covered) in `backend/app/eval/heldout.json`, run through the
  identical scored path by `scripts/run_heldout.py` and reported separately from
  the golden set. Latest real-model run on the default: 30/30. docs/evaluation.md
  now states that the thresholds were calibrated on the same demo documents as
  the golden set, and documents how to re-tune both thresholds on your own corpus.
- **Apache-2.0 small-tier default** — the non-thinking
  `qwen3:4b-instruct-2507-q4_K_M` (Qwen3-4B-Instruct-2507, Apache-2.0) is now the
  `small`-tier default, scoring **42/42 golden and 30/30 held-out** vs the
  research-licensed 3B's 41/42 and 27/30 at similar warm latency. All tier
  defaults are now Apache-2.0 (commercial-OK). The former 3B stays selectable
  via `LLM_MODEL=qwen2.5:3b-instruct-q4_K_M` (research-only; triggers the startup
  warning). `scripts/run_golden.py` is the CLI twin of the dashboard evaluation
  for comparing models. Cold-start latency (~17 s first token / ~18 s total) and
  the ~2.5 GB download are documented in docs/hardware-tiers.md; see also
  docs/evaluation.md and docs/models.md.
- **Startup license warning** — the app logs `llm_model_research_license` when
  the resolved LLM is a research-licensed Qwen2.5-3B variant (including
  `LLM_MODEL` overrides and OpenAI-compatible model names), pointing to
  Apache-2.0 options in docs/models.md. The check is general-purpose: the new
  Apache-2.0 Qwen3-4B default is silent, but overriding `LLM_MODEL` back to a
  restricted 3B still warns.
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
  handoff is offered. Latest real-model run on the default: 42/42 (see
  docs/evaluation.md).
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

689 automated tests: 443 unit, 193 integration (real PostgreSQL + pgvector,
0 skipped), 30 live API e2e (real Ollama + BGE-M3, trilingual chat, refusal,
crawl, evaluation, handoff transports), 23 real-Chromium browser tests.
Golden 42/42 and held-out 30/30 on the Apache-2.0 Qwen3-4B-Instruct-2507
default; the former research-licensed 3B scored 41/42 and 27/30.

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