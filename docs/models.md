# Model licenses

Sanad's own code is [MIT](../LICENSE), but the **models it downloads are
separate works with their own licenses**. The table below was verified against
the Hugging Face model cards on **2026-11-17**. Quantized Ollama tags
(`…-q4_K_M`, `…-q8_0`) inherit the license of the base model they quantize.

| Model (base) | Role in Sanad | License | Commercial use |
|--------------|---------------|---------|----------------|
| `Qwen/Qwen3-4B-Instruct-2507` | **small-tier default LLM** (non-thinking) | [Apache-2.0](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) | Yes |
| `Qwen/Qwen2.5-7B-Instruct` | medium-tier LLM | [Apache-2.0](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct) | Yes |
| `Qwen/Qwen2.5-14B-Instruct` | large-tier LLM | [Apache-2.0](https://huggingface.co/Qwen/Qwen2.5-14B-Instruct) | Yes |
| `Qwen/Qwen2.5-3B-Instruct` | former small default; opt-in via `LLM_MODEL` | [Qwen Research License](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/main/LICENSE) | **No — research / evaluation only** |
| `Qwen/Qwen2.5-1.5B-Instruct` / `0.5B-Instruct` | last-resort LLM (never a default) | Apache-2.0 | Yes |
| `BAAI/bge-m3` | embeddings (all tiers) | [MIT](https://huggingface.co/BAAI/bge-m3) | Yes |
| `BAAI/bge-reranker-v2-m3` | cross-encoder reranker (medium/large) | [Apache-2.0](https://huggingface.co/BAAI/bge-reranker-v2-m3) | Yes |
| Tesseract OCR | optional scanned-document / image OCR | Apache-2.0 | Yes |

## The small-tier default is Apache-2.0

The default `MODEL_TIER=small` pulls `qwen3:4b-instruct-2507-q4_K_M`
(Qwen3-4B-Instruct-2507, **non-thinking**), which is **Apache-2.0** and permits
commercial use. All three tier defaults — small (Qwen3-4B), medium (Qwen2.5-7B)
and large (Qwen2.5-14B) — are Apache-2.0, so the out-of-the-box stack is fine for
a **commercial support bot**, not just demos and evaluation.

The Instruct-2507 release was chosen over the research-licensed 3B because it
scores higher on both evaluation sets — **42/42 golden and 30/30 held-out** vs
the 3B's 41/42 and 27/30 — at similar warm latency, and it answers directly
without reasoning tokens. See
[evaluation.md](evaluation.md#model-comparison-an-apache-20-small-tier-candidate).

### The former 3B default is research-only (opt-in)

`qwen2.5:3b-instruct-q4_K_M` (Qwen2.5-3B-Instruct) is still selectable through
`LLM_MODEL` for anyone who prefers it, but its base model is under the **Qwen
RESEARCH LICENSE AGREEMENT**: use, reproduction and derivative works are granted
**for non-commercial (research or evaluation) purposes only**; commercial use
requires requesting a license from Alibaba Cloud. It also requires attribution
("Built with Qwen" / "Improved using Qwen") when its outputs are used to train or
improve a distributed model, and any redistribution must carry the agreement
plus a Notice file. Sanad logs a startup warning whenever this model is resolved
(see below).

### Other commercial options

1. **Use a bigger tier.** `MODEL_TIER=medium` (7B) or `large` (14B) are
   Apache-2.0 and permit commercial use. Simplest path if your hardware fits
   (see [hardware-tiers.md](hardware-tiers.md)).
2. **License the 3B commercially.** Request a commercial license from Alibaba
   Cloud if you must stay on the research-licensed 3B.
3. **Use your own licensed API.** `LLM_PROVIDER=openai` (+ `OPENAI_API_KEY`) or
   any OpenAI-compatible endpoint whose terms you control.

The Apache-2.0 Qwen2.5 1.5B / 0.5B sizes also work but are weaker Arabic,
last-resort quality (never a default). The embedding model (MIT) and the reranker
(Apache-2.0) impose **no** commercial restriction.

## Qwen3 thinking models and the startup license warning

Sanad logs a **startup warning** (`llm_model_research_license`) whenever the
resolved LLM is a research-licensed Qwen2.5-3B variant — including `LLM_MODEL`
overrides and OpenAI-compatible model names — pointing here for Apache-2.0
options. The check is general-purpose: the Apache-2.0 default (Qwen3-4B) does
**not** trigger it, but setting `LLM_MODEL` back to a restricted 3B does.

The plain Ollama `qwen3:4b` tag is a **hybrid thinking** model: it always emits
reasoning tokens before the answer. Two consequences on small/CPU hosts:

- A single grounded answer can **exceed `LLM_TIMEOUT`** (120 s default) because
  the reasoning tokens dominate generation time.
- Ollama 0.40.16's `think:false` (forwarded by the optional `LLM_THINK` setting)
  only disables the reasoning *parser*: the reasoning then leaks **inline into
  the answer** instead of being suppressed. `LLM_THINK` is unset by default, so
  non-thinking models like Qwen2.5 and the Qwen3-4B-Instruct-2507 default are
  unaffected.

The small-tier default is already the **non-thinking**
`qwen3:4b-instruct-2507-q4_K_M` (Qwen3-4B-Instruct-2507), which answers directly.
If you override `LLM_MODEL`, prefer it over the hybrid `qwen3:4b` — it is the
official non-thinking release of the same 4B model.

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

- [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) —
  Apache-2.0, non-thinking (the small-tier default). The hybrid `Qwen3-4B` is
  also Apache-2.0 but always emits reasoning tokens.
- [Qwen2.5-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct) —
  license `other`, name `qwen-research` (Qwen RESEARCH LICENSE AGREEMENT).
- [Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct),
  [14B](https://huggingface.co/Qwen/Qwen2.5-14B-Instruct),
  [1.5B](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct),
  [0.5B](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct) — Apache-2.0.
- [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) — MIT.
- [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) —
  Apache-2.0.