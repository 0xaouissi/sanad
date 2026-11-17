# Roadmap (build history)

Sanad was built in seven approved steps, each shipped with tests, docs and
small commits. All are complete as of v0.1.0; this page is the historical
plan, not a promise of future work.

0. **Hardware tiers** — tier defaults, env overrides, CPU-only mode *(done)*
1. **Project setup, FastAPI and Ollama** — health, structured logging, provider interface, streaming chat, Docker Compose *(done)*
2. **Documents, chunking, multilingual embeddings** — multi-company isolation, PDF/DOCX/TXT/MD upload, OCR, Arabic normalization, pgvector, background ingestion *(done)*
3. **Retrieval, refusal rules, language detection** — hybrid search + rerank, citations, conversation memory, latency targets *(done)*
4. **The embeddable widget** — one script tag, Shadow DOM, RTL, themes, ratings *(done)*
5. **Protection, speed, admin dashboard** — split in two:
   - **5a** *(done)*: rate limits per IP/site, daily company cap, widget bot check, Redis answer cache with in-memory fallback, prompt-injection defense, Alembic migrations, Prometheus metrics
   - **5b** *(done)*: React dashboard — scrypt login with rate limiting, httpOnly cookie sessions + CSRF, owner/viewer roles, documents, failed questions, ratings, settings (snippet, domains, key rotation), privacy toggle, data export and deletion, ar/fr/en RTL interface
6. **Evaluation page, website crawling, human handoff** — split in three:
   - **6a** *(done)*: golden Q&A evaluation — 42 questions (14 per language), grounded/out-of-scope/related-but-not-covered/injection cases, deterministic fact + citation + refusal + handoff scoring, sample company and demo documents, dashboard evaluation page
   - **6b** *(done)*: SSRF-safe website crawler — IP-pinned connections, per-hop redirect re-validation, same-domain + robots.txt, page/size/time limits, injection-sanitized storage, safe scheduled re-sync, dashboard Website tab
   - **6c** *(done)*: human handoff — widget form with privacy notice, email (SMTP) + Telegram delivery, env-only secrets, header-injection protection, per-IP + daily rate limits, privacy toggle respected, dashboard Handoffs tab and Settings destinations
7. **Documentation, demo and release** — demo GIFs, CI, local demo kit, first release *(done)*

Feature documentation lives under topic names in [docs/](.):
[documents](documents.md), [chat](chat.md), [widget](widget.md),
[protection](protection.md), [dashboard](dashboard.md),
[evaluation](evaluation.md), [crawling](crawling.md), [handoff](handoff.md),
[development](development.md), [hardware tiers](hardware-tiers.md),
[demo](demo.md), [models and licenses](models.md).