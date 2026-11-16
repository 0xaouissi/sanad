# Deployment

Everything runs with one command from the repository root:

```bash
docker compose up -d
```

Services: `api` (FastAPI), `db` (PostgreSQL 16 + pgvector), `redis`,
`ollama` (local LLM), plus a one-shot `ollama-init` that pulls the model
for the configured tier.

- Compose file: [`../docker-compose.yml`](../docker-compose.yml)
- GPU override for Ollama: `docker compose -f docker-compose.yml -f deployment/docker-compose.gpu.yml up -d`
- Configuration: copy `../.env.example` to `../.env` (optional — sane defaults apply).

The API is then at http://localhost:8000 (`/health`, `/api/v1/chat`).

## Before going public

- **Secrets**: set a strong `ADMIN_API_KEY` in `.env` (company creation is
  admin-only). SMTP and Telegram credentials for human handoff also live only
  in `.env` — never in the database or the code. `.env` is gitignored.
- **Domains**: give each company its allowed domains (dashboard Settings or
  `PUT /api/v1/companies/domains`); the public site key is rejected from any
  other origin.
- **HTTPS**: terminate TLS in front of the API (reverse proxy) and set
  `COOKIE_SECURE=true` so dashboard session cookies are only sent over HTTPS.
- **Crawler**: keep `CRAWL_ALLOW_PRIVATE=false` (the default). It exists only
  for local tests and development against loopback fixture sites.
- **Sizing**: pick `MODEL_TIER` for the machine (see
  [../docs/hardware-tiers.md](../docs/hardware-tiers.md)); the GPU override
  above passes the NVIDIA device through to Ollama.
- **Demo**: to try everything locally first — seed company, widget page,
  evaluation run, recorded GIFs — see [../docs/demo.md](../docs/demo.md).