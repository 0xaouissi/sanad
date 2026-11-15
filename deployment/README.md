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