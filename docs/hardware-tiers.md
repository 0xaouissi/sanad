# Hardware tiers

Sanad adapts to the machine it runs on through one setting: `MODEL_TIER`.
Every tier has a documented default model, and switching models is a
settings change only — no code edits, no rebuilds.

## Default models per tier

| Tier | Hardware | Default model (Ollama tag) | Quantization | Context | Notes |
|------|----------|----------------------------|--------------|---------|-------|
| `small` (default) | CPU-only or a GPU with 4 GB VRAM (e.g. GTX 1650) | `qwen2.5:3b-instruct-q4_K_M` | q4_K_M | 8192 | Run embeddings on CPU next to the LLM |
| `medium` | GPU with 8–12 GB VRAM | `qwen2.5:7b-instruct-q4_K_M` | q4_K_M | 16384 | |
| `large` | Server GPU with 16+ GB VRAM | `qwen2.5:14b-instruct-q4_K_M` | q4_K_M | 32768 | Larger models via `LLM_MODEL` |

All defaults are Qwen 2.5 instruct, quantized, served locally through Ollama.
Embeddings are always local: `BAAI/bge-m3` (multilingual, 1024-dim dense vectors).

### The 1.5B last resort

`qwen2.5:1.5b-instruct-q4_K_M` is **never** a tier default. Its Arabic is weak,
which matters for a trilingual product. It exists only as an explicit opt-in
for machines that cannot run the 3B:

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

# Same size, different quantization (better quality, more VRAM)
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

## VRAM notes for the small tier (4 GB)

- The 3B q4_K_M model weights are ~2 GB; the KV cache adds to that and grows
  with `LLM_NUM_CTX`. If you see out-of-memory errors, lower `LLM_NUM_CTX`
  (e.g. 4096) before dropping to a smaller model.
- Keep embeddings on CPU (`EMBEDDING_DEVICE=cpu`) so BGE-M3 does not compete
  with the LLM for the 4 GB of VRAM.
- `OLLAMA_KEEP_ALIVE=0m` unloads the model between requests if VRAM is tight;
  the trade-off is reload latency on the next question.

## No benchmark script — by design

There is no hardware benchmark script. Use the tier defaults above; answer
quality (accuracy and groundedness per language) is measured later by the
evaluation page in Step 6, which scores real answers against golden Q&A sets
in Arabic, French and English.