# Contributing to Sanad

Thanks for considering a contribution! Sanad is a self-hosted, grounded RAG
chatbot (Arabic / French / English). This guide gets you from clone to a
reviewable pull request.

## Ground rules

- Be kind and constructive. We follow a simple code of conduct: treat people
  with respect.
- Every feature ships with **tests** and **docs**. New settings go in
  [`.env.example`](.env.example) with a sensible default and a comment.
- **Never commit secrets.** Credentials live in environment variables only;
  `backend/.env` is gitignored. API keys are stored hashed, passwords scrypt.
- Keep changes focused. One logical change per commit/PR.

## Development setup

Prerequisites: Python 3.11+, Node 18+ (dashboard only), PostgreSQL with
pgvector, Ollama. Optional: Redis (cache/limits fall back to memory), Tesseract
(OCR), Playwright Chromium (browser tests).

The fastest path is Docker:

```bash
docker compose up -d
```

For native development (venv, pgvector setup, embeddings weights, running the
API and the dashboard dev server) follow
[docs/development.md](docs/development.md). A `Makefile` wraps the common
commands cross-platform (`make help`).

## Workflow

1. Fork and create a topic branch.
2. Make your change with tests and docs.
3. Run the gate locally (below). Integration/E2E need the live stack; they skip
   with a clear message when a dependency is missing.
4. Open a pull request describing the behaviour change and the tests you ran.

## The test gate

```bash
make lint            # ruff check app tests
make test-unit       # offline, mocked providers
make test-integration# real PostgreSQL + pgvector, fake embeddings
make test-e2e        # live Ollama + BGE-M3: ar/fr/en chat, refusal, crawl, handoff
make test-browser    # real Chromium widget + dashboard
```

Or directly from `backend/` (see [docs/development.md](docs/development.md) for
the exact environment variables). **Behaviour changes need a real end-to-end
check**, including at least one Arabic, French and English question where the
change touches chat, retrieval or the widget.

## Code style

- Python: `ruff` (rules E, F, I, UP, B; line length 100), type hints, async
  FastAPI handlers. Prefer small pure functions; keep provider interfaces
  swappable (Ollama / OpenAI-compatible, embeddings, reranker).
- Dashboard: React + TypeScript; `npm run build` type-checks and rebuilds the
  committed bundle. Keep the bundle committed so running Sanad needs no Node.
- Widget: vanilla JS, Shadow DOM, `textContent` only (no `innerHTML`).
- Error messages must tell the user **how to fix** the problem (e.g. the exact
  `ollama pull …` command), not just that something failed.

## Retrieval / prompt / threshold changes

If you touch retrieval, the prompt, or the refusal thresholds, re-run the
golden **and** held-out evaluations and report the results honestly (including
regressions) in the PR. See [docs/evaluation.md](docs/evaluation.md) for how to
run them and how to re-tune thresholds on a corpus.

## Commits and pull requests

- Imperative, concise subject line ("Add …", "Fix …", "Document …").
- Reference the issue when there is one.
- Describe what changed, why, and which tests you ran (unit / integration /
  e2e / browser, and languages exercised).

## Reporting problems

- Bugs and feature ideas: use the [issue templates](.github/ISSUE_TEMPLATE).
- Security vulnerabilities: **do not** open a public issue — follow
  [SECURITY.md](SECURITY.md).