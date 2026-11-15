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

> Status: **Step 1 — FastAPI + Ollama chat with streaming**. Working project name.

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
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Bonjour, qui es-tu ?"}'
```

Streaming (server-sent events): add `"stream": true` to the same request.
If Ollama is down or the model is missing, the API returns **503 with a
message that tells you exactly what to run** (e.g. `ollama pull …`).

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

## Tests and lint

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q        # unit tests (offline, mocked providers)
.venv/Scripts/python.exe -m pytest -m e2e    # live E2E: ar/fr/en against real Ollama
.venv/Scripts/python.exe -m ruff check app tests
```

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
2. **Documents, chunking, multilingual embeddings** — multi-company isolation, PDF/DOCX/TXT/MD upload, OCR, Arabic normalization, pgvector, background ingestion
3. **Retrieval, the "I don't know" rule, language detection** — hybrid search + rerank, citations, conversation memory, latency targets
4. **The embeddable widget** — one script tag, Shadow DOM, RTL, themes, ratings
5. **Protection, speed, admin dashboard** — rate limits, cache, prompt-injection defense, roles, privacy, metrics, migrations
6. **Evaluation page, website crawling, human handoff** — per-language accuracy scores, scheduled re-sync, email/Telegram handoff
7. **Documentation, demo and release** — demo GIF/video, CI, live demo, first release

## License

[MIT](LICENSE)