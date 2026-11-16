# Changelog

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