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

> Status: **Step 0 — hardware tiers**. Working project name; see the roadmap below.

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
```

The 1.5B model is a last resort, never a default (weak Arabic). There is no
benchmark script; answer quality per language is measured by the evaluation
page (Step 6).

## Development (Step 0)

Requires Python 3.11+.

```bash
cd backend
py -3.11 -m venv .venv                     # or: python3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"   # Windows
# source .venv/bin/activate && pip install -e ".[dev]"  # Linux/macOS
.venv/Scripts/python.exe -m pytest -q
```

Configuration lives in [backend/app/core/config.py](backend/app/core/config.py);
copy [.env.example](.env.example) to `backend/.env` to override defaults.

## Roadmap

Each step ships with tests, a README/docs note and small commits.

0. **Hardware tiers** — tier defaults, env overrides, CPU-only mode *(done)*
1. Scaffold + Docker Compose skeleton (pgvector, Redis, Ollama, API, nginx; Vite SPA + widget shells)
2. DB layer: models, Alembic migrations, pgvector, health endpoints
3. Ingestion: parsing, **OCR** (ara/fra/eng), **Arabic text normalization**, chunking, BGE-M3 embeddings
4. Retrieval: hybrid search + language detection (ar/fr/en)
5. LLM providers (Ollama / OpenAI-compatible) + grounded generation + SSE chat API
6. **Evaluation page**: golden Q&A sets, accuracy scores per language
7. Redis caching, rate limiting, site keys + CORS allowlists
8. Widget: one script tag, RTL, tiny bundle
9. Dashboard (Vite React SPA): auth, **user roles**, documents, sites, settings, conversation logs
10. **Website crawling** with scheduled re-sync
11. **Human handoff** by email or Telegram
12. **Privacy controls**: data retention, deletion, export
13. **Metrics endpoints** + compose polish + end-to-end docs + full test pass

## License

[MIT](LICENSE)