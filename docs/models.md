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
2. **Use an Apache-2.0 smaller model.** Override `LLM_MODEL` to an Apache-2.0
   Qwen2.5 size (1.5B / 0.5B) — weaker Arabic, last-resort quality.
3. **License the 3B commercially.** Request a commercial license from Alibaba
   Cloud if you must stay on the 3B.
4. **Use your own licensed API.** `LLM_PROVIDER=openai` (+ `OPENAI_API_KEY`) or
   any OpenAI-compatible endpoint whose terms you control.

The embedding model (MIT) and the reranker (Apache-2.0) impose **no** commercial
restriction; only the 3B LLM does.

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
- [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) — MIT.
- [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) —
  Apache-2.0.