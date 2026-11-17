# Protection, cache and observability

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

**Prompt-injection defense (layered, verified on the live small-tier model).**
1. Grounding rules declare sources and questions to be *data, never
   instructions*, and forbid revealing the system prompt.
2. Injection-matching sentences are stripped from the context sent to the
   LLM (stored documents and citations are untouched).
3. Obvious override/extraction questions ("ignore your instructions…",
   "print your system prompt", in ar/fr/en) are refused **before any model
   call**.
4. Answers that leak prompt text, or junk-prefixed refusals, are normalized
   to the clean localized **off-topic** refusal (no handoff offer).
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

All settings are documented in [.env.example](../.env.example).