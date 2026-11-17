# Hardware tiers

Sanad adapts to the machine it runs on through one setting: `MODEL_TIER`.
Every tier has a documented default model, and switching models is a
settings change only — no code edits, no rebuilds.

## Default models per tier

| Tier | Hardware | Default model (Ollama tag) | Quantization | Context | Notes |
|------|----------|----------------------------|--------------|---------|-------|
| `small` (default) | CPU-only or a GPU with 4 GB VRAM (e.g. GTX 1650) | `qwen3:4b-instruct-2507-q4_K_M` | q4_K_M | 8192 | ~2.5 GB download; non-thinking, Apache-2.0; embeddings on CPU |
| `medium` | GPU with 8–12 GB VRAM | `qwen2.5:7b-instruct-q4_K_M` | q4_K_M | 16384 | |
| `large` | Server GPU with 16+ GB VRAM | `qwen2.5:14b-instruct-q4_K_M` | q4_K_M | 32768 | Larger models via `LLM_MODEL` |

The `small` default is **Qwen3-4B-Instruct-2507** (non-thinking, Apache-2.0);
`medium`/`large` are Qwen2.5 instruct. All are quantized q4_K_M and served
locally through Ollama. Embeddings are always local: `BAAI/bge-m3`
(multilingual, 1024-dim dense vectors).

**License.** Every tier default is **Apache-2.0** (commercial use OK). The
former small default, Qwen2.5-3B, is **research-licensed (non-commercial)** and
is now opt-in only via `LLM_MODEL`; Sanad logs a startup warning if you select
it. Embeddings (MIT) and the reranker (Apache-2.0) are unrestricted. Read
[models.md](models.md) before deploying commercially.

### The 1.5B last resort

`qwen2.5:1.5b-instruct-q4_K_M` is **never** a tier default. Its Arabic is weak,
which matters for a trilingual product. It exists only as an explicit opt-in
for machines that cannot run the default 4B:

```env
LLM_MODEL=qwen2.5:1.5b-instruct-q4_K_M
```

## CPU-only mode

```env
CPU_ONLY=true
```

Forces the whole stack onto CPU: Ollama receives `num_gpu=0` (no GPU offload)
and embeddings run on CPU, regardless of other device settings. Combine with
the `small` tier (the default). `medium`/`large` on CPU are allowed but slow.

## Switching models: settings only

```env
# Move up a tier (7B, 16k context)
MODEL_TIER=medium

# Opt back into the former research-licensed 3B default (non-commercial only;
# Sanad logs a startup license warning when you select it)
LLM_MODEL=qwen2.5:3b-instruct-q4_K_M

# Same model, different quantization, e.g. the 3B at q8_0 (better quality, more VRAM)
LLM_MODEL=qwen2.5:3b-instruct-q8_0

# Shrink the context window to save VRAM (KV cache grows with context)
LLM_NUM_CTX=4096

# Optional API fallback instead of local Ollama
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

Model name and quantization are both part of the Ollama tag, so `LLM_MODEL`
changes either. `LLM_NUM_CTX` overrides the tier's context size. Resolution
order for every value: explicit env override → tier default.

## Reranker per tier

Hybrid retrieval (dense vectors + keyword full-text, fused with RRF) can be
sharpened by a cross-encoder reranker, `BAAI/bge-reranker-v2-m3` (~2.3 GB).
Default is tier-aware:

| Tier | Reranker default | Why |
|------|------------------|-----|
| `small` | **off** | CPU reranking adds seconds; the small tier's 8 s first-token budget is better spent on the LLM |
| `medium` / `large` | **on** | GPU reranking is fast and improves source ordering |

Override either way with `RERANK_ENABLED=true|false`. When enabled, only the
top `RERANK_CANDIDATES` (default 8) hybrid candidates are re-scored, bounding
latency. First use downloads the weights into `HF_HOME`:

```bash
huggingface-cli download BAAI/bge-reranker-v2-m3
```

**Score scale.** The reranker returns a sigmoid relevance probability, which is
a different, more polarized scale than the dense cosine similarity. It is used
**only to reorder** the candidates handed to the LLM. The refusal thresholds
(`RETRIEVAL_MIN_SCORE`, `RETRIEVAL_OFF_TOPIC_SCORE`) always compare the
**pre-rerank cosine similarity**, so the same calibration is valid whether
reranking is on or off — no separate reranker thresholds are needed.

## Latency targets

Time to first streamed token, measured and logged per request (`chat_latency`
event with `first_token_ms`, `budget_ms`, `within_budget`):

| Tier | First-token budget (warm) |
|------|--------------------|
| `small` | ≤ 8 s |
| `medium` / `large` | ≤ 3 s |

The E2E suite asserts the budget on the running tier. The budget is a
**warm / steady-state** target — the model is already resident in memory.

### Cold-start latency (small tier, measured)

The **first** question after boot — or after `OLLAMA_KEEP_ALIVE` (default `5m`)
has unloaded the model — pays a one-time model-load cost on top of inference.
Measured on the demo host (GTX 1650 4 GB + 16 GB RAM, Ollama partial offload
≈45% CPU / 55% GPU, `LLM_NUM_CTX=8192`, reranker off, embedder already warm),
through the real streaming chat path on a grounded question:

| State | Time to first token | Full grounded answer |
|-------|--------------------|----------------------|
| **Cold** (model unloaded) | ~17 s (16.7–17.7 s over two runs) | ~18 s (17.4–18.6 s) |
| **Warm** (model resident) | ~4.4 s | ~4.4 s |

- The cold model load is ~6–7 s of that; the rest is prompt prefill + generation.
  With the GPU idle (fuller offload) warm answers are faster — the earlier
  evaluation measured ~1.4 s per grounded answer. Warm latency scales with how
  much of the model fits on the GPU and what else is using it.
- Cold-start **exceeds the 8 s warm budget by design**: it is a one-time load,
  not steady-state. Keep the model warm with `OLLAMA_KEEP_ALIVE` (e.g. `30m`, or
  `-1` to never unload) if first-question latency matters; the trade-off is
  resident VRAM/RAM. `OLLAMA_KEEP_ALIVE=0m` unloads after every request and pays
  the cold cost each time.
- **Download size:** the `small` default `qwen3:4b-instruct-2507-q4_K_M` is a
  **~2.5 GB** Ollama pull (vs ~1.9 GB for the former 3B). It downloads once on
  first run; the resident footprint with an 8192 context is ~4.2 GB split across
  CPU/GPU.

## Environment reference

| Variable | Default | Meaning |
|----------|---------|---------|
| `MODEL_TIER` | `small` | `small` \| `medium` \| `large` |
| `CPU_ONLY` | `false` | Force CPU for LLM and embeddings |
| `LLM_PROVIDER` | `ollama` | `ollama` \| `openai` (OpenAI-compatible API) |
| `LLM_MODEL` | tier default | Full model tag; overrides name + quantization |
| `LLM_NUM_CTX` | tier default | Context window, 512–131072 tokens |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server address |
| `OLLAMA_NUM_GPU` | auto | Layers offloaded to GPU; `CPU_ONLY` forces 0 |
| `OLLAMA_KEEP_ALIVE` | `5m` | How long Ollama keeps the model loaded |
| `OPENAI_API_KEY` | — | Required when `LLM_PROVIDER=openai` |
| `OPENAI_MODEL` | `gpt-4o-mini` | API model name |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible endpoint |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | Local multilingual embedding model |
| `EMBEDDING_DEVICE` | `auto` | `auto` \| `cpu` \| `cuda`; `CPU_ONLY` forces `cpu` |
| `RERANK_ENABLED` | tier default | `true` \| `false`; unset = off on small, on elsewhere |
| `RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` | Cross-encoder reranker |
| `RERANK_CANDIDATES` | `8` | Hybrid candidates re-scored by the reranker |
| `RETRIEVAL_TOP_K` | `5` | Chunks passed to the LLM as numbered sources |
| `RETRIEVAL_MIN_SCORE` | `0.43` | Pre-rerank cosine. At/above: strong source. Below: related-but-not-covered refusal + handoff |
| `RETRIEVAL_OFF_TOPIC_SCORE` | `0.41` | Pre-rerank cosine. Below: off-topic refusal (no handoff). Must be ≤ `RETRIEVAL_MIN_SCORE` |
| `MEMORY_MAX_TURNS` | `6` | Past messages replayed per conversation (0 = off) |

## VRAM notes for the small tier (4 GB)

- The 4B q4_K_M model weights are ~2.5 GB; the KV cache adds to that and grows
  with `LLM_NUM_CTX`. On a 4 GB GPU Ollama partially offloads (the rest runs on
  CPU). If you see out-of-memory errors, lower `LLM_NUM_CTX` (e.g. 4096) before
  dropping to a smaller model.
- Keep embeddings on CPU (`EMBEDDING_DEVICE=cpu`) so BGE-M3 does not compete
  with the LLM for the 4 GB of VRAM.
- `OLLAMA_KEEP_ALIVE=0m` unloads the model between requests if VRAM is tight;
  the trade-off is the ~17 s cold-start reload on the next question (see above).

## No benchmark script — by design

There is no hardware benchmark script. Use the tier defaults above; answer
quality (accuracy and groundedness per language) is measured by the
evaluation page, which scores real answers against golden Q&A sets
in Arabic, French and English ([evaluation.md](evaluation.md)).