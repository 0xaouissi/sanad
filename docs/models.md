# Model licenses

Sanad's own code is [MIT](../LICENSE), but the **models it downloads are
separate works with their own licenses**. The table below was verified against
the Hugging Face model cards on **2026-11-17**. Quantized Ollama tags
(`…-q4_K_M`, `…-q8_0`) inherit the license of the base model they quantize.

| Model (base) | Role in Sanad | License | Commercial use |
|--------------|---------------|---------|----------------|
| `Qwen/Qwen2.5-3B-Instruct` | **small-tier default LLM** | [Qwen Research License](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/main/LICENSE) | **No — research / evaluation only** |
| `Qwen/Qwen2.5-7B-Instruct` | medium-tier LLM | [Apache-2.0](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct) | Yes |
| `Qwen/Qwen2.5-14B-Instruct` | large-tier LLM | [Apache-2.0](https://huggingface.co/Qwen/Qwen2.5-14B-Instruct) | Yes |
| `Qwen/Qwen2.5-1.5B-Instruct` / `0.5B-Instruct` | last-resort LLM (never a default) | Apache-2.0 | Yes |
| `Qwen/Qwen3-4B-Instruct-2507` | Apache-2.0 small-tier candidate (evaluated, **not** the default) | [Apache-2.0](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) | Yes |
| `BAAI/bge-m3` | embeddings (all tiers) | [MIT](https://huggingface.co/BAAI/bge-m3) | Yes |
| `BAAI/bge-reranker-v2-m3` | cross-encoder reranker (medium/large) | [Apache-2.0](https://huggingface.co/BAAI/bge-reranker-v2-m3) | Yes |
| Tesseract OCR | optional scanned-document / image OCR | Apache-2.0 | Yes |

## The small-tier default is research-only

The default `MODEL_TIER=small` pulls `qwen2.5:3b-instruct-q4_K_M`, whose base
model is under the **Qwen RESEARCH LICENSE AGREEMENT**: use, reproduction and
derivative works are granted **for non-commercial (research or evaluation)
purposes only**; commercial use requires requesting a license from Alibaba
Cloud. It also requires attribution ("Built with Qwen" / "Improved using Qwen")
when its outputs are used to train or improve a distributed model, and any
redistribution must carry the agreement plus a Notice file.

So the out-of-the-box small tier is fine for **local demos, research and
evaluation** — which is exactly what the demo kit and the golden/held-out
evaluation are — but **not for running a commercial support bot as-is**.

### Options for commercial deployment

1. **Use a bigger tier.** `MODEL_TIER=medium` (7B) or `large` (14B) are
   Apache-2.0 and permit commercial use. Simplest path if your hardware fits
   (see [hardware-tiers.md](hardware-tiers.md)).
2. **Use an Apache-2.0 model at a similar tier.** Override `LLM_MODEL` to
   `qwen3:4b-instruct-2507-q4_K_M` (Qwen3-4B-Instruct-2507, non-thinking) — on
   the demo evaluation it scored **42/42 golden and 30/30 held-out**, beating
   the research-licensed 3B (41/42, 27/30) at similar latency. See
   [evaluation.md](evaluation.md#model-comparison-an-apache-20-small-tier-candidate).
   The Apache-2.0 Qwen2.5 1.5B / 0.5B sizes also work but are weaker Arabic,
   last-resort quality.
3. **License the 3B commercially.** Request a commercial license from Alibaba
   Cloud if you must stay on the 3B.
4. **Use your own licensed API.** `LLM_PROVIDER=openai` (+ `OPENAI_API_KEY`) or
   any OpenAI-compatible endpoint whose terms you control.

The embedding model (MIT) and the reranker (Apache-2.0) impose **no** commercial
restriction; only the 3B LLM does.

## Qwen3 thinking models and the startup license warning

Sanad logs a **startup warning** (`llm_model_research_license`) whenever the
resolved LLM is a research-licensed Qwen2.5-3B variant — including `LLM_MODEL`
overrides and OpenAI-compatible model names — pointing here for Apache-2.0
options.

The plain Ollama `qwen3:4b` tag is a **hybrid thinking** model: it always emits
reasoning tokens before the answer. Two consequences on small/CPU hosts:

- A single grounded answer can **exceed `LLM_TIMEOUT`** (120 s default) because
  the reasoning tokens dominate generation time.
- Ollama 0.40.16's `think:false` (forwarded by the optional `LLM_THINK` setting)
  only disables the reasoning *parser*: the reasoning then leaks **inline into
  the answer** instead of being suppressed. `LLM_THINK` is unset by default, so
  non-thinking models like Qwen2.5 are unaffected.

For a small-tier Apache-2.0 model that answers directly, use the **non-thinking**
`qwen3:4b-instruct-2507-q4_K_M` (Qwen3-4B-Instruct-2507) rather than the hybrid
`qwen3:4b` — it is the official non-thinking release of the same 4B model.

## Obligations when redistributing

If you ship model weights or derivatives (for example a Docker image that
bundles them), comply with each license: Apache-2.0 and MIT require retaining
copyright and license notices; the Qwen Research License additionally requires
a copy of the agreement, prominent change notices and the
"Qwen is licensed under the Qwen RESEARCH LICENSE AGREEMENT…" Notice file, and
limits you to non-commercial purposes. Sanad's Docker Compose **pulls** models
at first run (the `ollama-init` container) rather than bundling weights, so the
operator accepts each model's license at download time.

## Sources

- [Qwen2.5-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct) —
  license `other`, name `qwen-research` (Qwen RESEARCH LICENSE AGREEMENT).
- [Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct),
  [14B](https://huggingface.co/Qwen/Qwen2.5-14B-Instruct),
  [1.5B](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct),
  [0.5B](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct) — Apache-2.0.
- [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) —
  Apache-2.0, non-thinking. The hybrid `Qwen3-4B` is also Apache-2.0 but always
  emits reasoning tokens.
- [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) — MIT.
- [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) —
  Apache-2.0.