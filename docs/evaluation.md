# Evaluation

Measure answer quality per language **without the model judging itself**.
A fixed golden set of **42 questions — 14 each in Arabic, French and
English** — runs through the exact same retrieval + prompt + model path as
live chat, then is scored deterministically:

- **12 grounded** questions about the demo policies: every expected fact
  must appear in the answer (Arabic-normalized, digit-folded substring
  match) and every citation must point at an expected source document.
- **15 out-of-scope** questions (weather, capitals, recipes…): the bot must
  give the polite "I can only help with questions about this company"
  refusal, with **no citations and no handoff offer**.
- **9 related-but-not-covered** questions (gift wrapping, changing a
  shipping address, a loyalty program…): company-related but absent from the
  documents. The bot must give the "I couldn't find this in the company's
  documents" refusal **and offer the human handoff** (`refusal_kind =
  not_covered`), still with no citations.
- **6 prompt-injection** attacks ("ignore your instructions…", DAN…):
  blocked before the model, no prompt leak, no citations, no handoff offer.

The two refusal kinds are separated by two retrieval thresholds
(`RETRIEVAL_MIN_SCORE=0.43`, `RETRIEVAL_OFF_TOPIC_SCORE=0.41`); see
[chat.md](chat.md) for the full decision path. Both thresholds compare the
**pre-rerank dense cosine similarity**, even when the reranker is enabled —
the reranker only reorders candidates, so the same calibration holds with
reranking on or off (see [hardware-tiers.md](hardware-tiers.md#reranker-per-tier)).

The golden set lives in [backend/app/eval/golden.json](../backend/app/eval/golden.json)
and targets the trilingual demo policies in [samples/](../samples/) (identical
facts in `demo-policy.en.md`, `demo-politique.fr.md`, `demo-siasa.ar.md`).

## Results

Latest run against the seeded demo company, real models, no mocks:

| Language | Questions | Passed | Model | Tier | Date |
|----------|-----------|--------|-------|------|------|
| English  | 14 | 14 | `qwen3:4b-instruct-2507-q4_K_M` | small | 2026-11-17 |
| French   | 14 | 14 | `qwen3:4b-instruct-2507-q4_K_M` | small | 2026-11-17 |
| Arabic   | 14 | 14 | `qwen3:4b-instruct-2507-q4_K_M` | small | 2026-11-17 |

| Category | Questions | Passed |
|----------|-----------|--------|
| Grounded facts + citations | 12 | 12 |
| Out-of-scope refusals (no handoff) | 15 | 15 |
| Related-but-not-covered refusals (handoff offered) | 9 | 9 |
| Prompt-injection blocks | 6 | 6 |

**Total: 42 / 42 passed.** Embeddings `BAAI/bge-m3` (CPU), reranker off
(small-tier default), `RETRIEVAL_MIN_SCORE=0.43`,
`RETRIEVAL_OFF_TOPIC_SCORE=0.41`. Run started 2026-11-17 via the
dashboard API on a GTX 1650 (4 GB VRAM) + 16 GB RAM host.

The Apache-2.0 Qwen3-4B-Instruct-2507 default passes every golden case,
including the Arabic related-but-not-covered gift-wrapping question
(`ar-nc-giftwrap`) that the former research-licensed 3B default hallucinated.
The 3B's historical results are kept in the
[model comparison](#model-comparison-an-apache-20-small-tier-candidate) below.

**Honest note:** 42 questions over three short demo policies is a *sanity
check, not a benchmark*. It proves the pipeline refuses correctly, offers
the handoff only when it should, cites correctly and stays in-language on
known facts; it says nothing about general accuracy, long documents or your
corpus. Re-run it on your own documents after uploading them, and treat a
drop as a signal to inspect the failed cases (the page lists each failed
check), not as a verdict.

## Calibration caveat

The two thresholds were calibrated on the **same three demo policies** that
the golden questions target (off-topic ≤ 0.3956, related-but-not-covered
≥ 0.4349, in-scope ≥ 0.45, measured with real BGE-M3). The golden results
therefore measure the pipeline **on its calibration corpus** — an upper
bound, not a generalization estimate. A different corpus has a different
score distribution, and the same numbers may separate the cases less
cleanly. The held-out set below probes unseen phrasings on the same docs;
for your own documents, re-tune the thresholds (see below).

## Held-out questions (unseen)

**30 additional questions — 10 per language** (4 grounded, 3 out-of-scope,
3 related-but-not-covered) that were **not** used to calibrate the thresholds
and do not overlap the golden set. They run through the identical retrieval +
prompt + model path, are scored deterministically, and are reported
**separately** from the golden results. They live in
[backend/app/eval/heldout.json](../backend/app/eval/heldout.json).

Run them (demo company seeded, Ollama up, from the repo root):

```bash
PYTHONIOENCODING=utf-8 backend/.venv/Scripts/python.exe scripts/run_heldout.py
```

The script writes nothing to the dashboard eval state, conversations, cache
or metrics; it prints each case (with the answer on failure) and a
per-language / per-category summary.

Latest run — real models, small tier, reranker off, same thresholds,
2026-11-17:

| Language | Questions | Passed | Model | Tier |
|----------|-----------|--------|-------|------|
| English  | 10 | 10 | `qwen3:4b-instruct-2507-q4_K_M` | small |
| French   | 10 | 10 | `qwen3:4b-instruct-2507-q4_K_M` | small |
| Arabic   | 10 | 10 | `qwen3:4b-instruct-2507-q4_K_M` | small |

| Category | Questions | Passed |
|----------|-----------|--------|
| Grounded facts + citations | 12 | 12 |
| Out-of-scope refusals (no handoff) | 9 | 9 |
| Related-but-not-covered (handoff offered) | 9 | 9 |

**Total: 30 / 30 passed.** The Apache-2.0 Qwen3-4B-Instruct-2507 default
answers every unseen question correctly: it grounds the answerable cases,
refuses the absent ones with the exact template (offering the handoff), and
stays in-language throughout.

The former research-licensed 3B default scored **27 / 30** on this same set.
Its three misses, kept here as the honest historical picture:

- `ho-en-refund-dest` (grounded, "Where is my refund sent?") — the 3B model
  returned the "couldn't find" refusal even though the documents state refunds
  go to the original payment method: an **over-refusal** on an answerable
  question.
- `ho-en-nc-return-cost` (not-covered, "Who pays for return shipping?") — the
  model recognized the information is absent but **paraphrased** the refusal
  ("The sources provided do not contain information about who pays for return
  shipping. [1]") instead of the exact required template, so it scored as a
  grounded answer with a citation and the handoff was **not** offered.
- `ho-ar-nc-return-cost` (not-covered, same question in Arabic) — the model
  **recited the retrieved shipping policy** instead of refusing: a grounding
  failure.

Instruct-2507 fixed all three. The held-out set exists to surface exactly this
gap between the calibration corpus and unseen questions; on the new default
that gap is closed for this demo corpus (30/30 held-out, 42/42 golden).

## Model comparison: an Apache-2.0 small-tier candidate

The former small-tier default `qwen2.5:3b-instruct-q4_K_M` is
**research-licensed** (see [models.md](models.md)). To find a
commercially-licensed replacement at the same tier, the non-thinking
**`qwen3:4b-instruct-2507-q4_K_M`** (Qwen3-4B-Instruct-2507, **Apache-2.0**) was
evaluated on the identical golden and held-out sets — same demo documents, same
thresholds, reranker off, same host. Both models were re-run in one session for
a fair comparison (2026-11-17). **Instruct-2507 won on both sets and is now the
small-tier default**; the 3B remains selectable via `LLM_MODEL`.

| Set | Language | `qwen2.5:3b` (research, former default) | `qwen3:4b-instruct-2507` (Apache-2.0, now default) |
|-----|----------|-------------------------|----------------------------------------|
| Golden (42) | English | 14 / 14 | 14 / 14 |
| Golden | French | 14 / 14 | 14 / 14 |
| Golden | Arabic | 13 / 14 | 14 / 14 |
| **Golden total** | | **41 / 42** | **42 / 42** |
| Held-out (30) | English | 8 / 10 | 10 / 10 |
| Held-out | French | 10 / 10 | 10 / 10 |
| Held-out | Arabic | 9 / 10 | 10 / 10 |
| **Held-out total** | | **27 / 30** | **30 / 30** |

Instruct-2507 fixed every 3B miss: the `ar-nc-giftwrap` hallucination on the
golden set, and all three held-out misses (`ho-en-refund-dest` over-refusal,
`ho-en-nc-return-cost` paraphrased refusal, `ho-ar-nc-return-cost` source
recitation). It refused correctly, offered the handoff only when it should,
cited correctly and stayed in-language on every case.

**Latency (same host, GTX 1650 partial offload):** warm, a grounded answer took
~0.7 s on the 3B and ~1.4 s on Instruct-2507 when the GPU was idle; under real
GPU contention the warm first token measured ~4.4 s. **Cold start** (model
evicted from memory, first request after `ollama stop`) measured **~17 s to
first token / ~18 s total** for Instruct-2507 — the ~6–7 s model load dominates.
The 8 s small-tier first-token budget is a **warm/steady-state** target; a cold
first answer legitimately exceeds it. Both warm and cold are far inside the
120 s `LLM_TIMEOUT`. The 42-case golden run took ~61 s (3B) vs ~87 s
(Instruct-2507) wall-clock. The 4B model is modestly slower per answer but the
same order of magnitude; it needs **~2.5 GB** of weights vs ~1.9 GB for the 3B.
See [hardware-tiers.md](hardware-tiers.md#cold-start-latency-small-tier-measured)
for the cold/warm breakdown and `keep_alive` guidance.

**Why not the hybrid `qwen3:4b`?** The plain `qwen3:4b` tag is a *hybrid
thinking* model: it always emits reasoning tokens. On this CPU-class host a
single grounded answer **exceeded the 120 s timeout**, and Ollama 0.40.16's
`think:false` only disables the reasoning *parser* — it leaks the reasoning
inline into `content` rather than suppressing it (the `LLM_THINK` setting
forwards this parameter and is left unset by default). **Instruct-2507** is the
official *non-thinking* release of the same 4B model, so it answers directly
with no reasoning traces. That is the practical "qwen3:4b with thinking
disabled" candidate.

**Reading:** on this small demo corpus the Apache-2.0 Instruct-2507 is both
commercially usable *and* more accurate than the research-licensed 3B, at
similar warm latency — which is why it is now the small-tier default. The same
honest caveat applies: 42 + 30 questions over three short policies is a sanity
check, not a benchmark. Re-run on your own corpus before relying on it. The
former 3B default stays available through `LLM_MODEL=qwen2.5:3b-instruct-q4_K_M`
(research-licensed; triggers the startup warning).

Run the comparison yourself (demo seeded, Ollama up, from the repo root):

```bash
# baseline (default: Apache-2.0 Qwen3-4B-Instruct-2507)
PYTHONIOENCODING=utf-8 backend/.venv/Scripts/python.exe scripts/run_golden.py
PYTHONIOENCODING=utf-8 backend/.venv/Scripts/python.exe scripts/run_heldout.py
# former research-licensed 3B default (opt-in override)
LLM_MODEL=qwen2.5:3b-instruct-q4_K_M PYTHONIOENCODING=utf-8 \
  backend/.venv/Scripts/python.exe scripts/run_golden.py
LLM_MODEL=qwen2.5:3b-instruct-q4_K_M PYTHONIOENCODING=utf-8 \
  backend/.venv/Scripts/python.exe scripts/run_heldout.py
```

## Re-tuning the thresholds on your own documents

The defaults (0.43 / 0.41) fit the demo policies, not your corpus. To re-tune:

1. **Upload your documents** and wait for ingestion to finish.
2. **Collect real best-source cosine scores** for three groups of questions:
   in-scope (answerable from your docs), related-but-not-covered (about your
   business but absent from the docs), and off-topic (unrelated). The
   `POST /api/v1/search` endpoint returns the **pre-rerank dense cosine
   similarity** per hit, unfiltered — exactly the scale the thresholds use:

   ```bash
   curl -X POST http://localhost:8000/api/v1/search \
     -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
     -d '{"query": "your question", "top_k": 3}'
   ```

   Take the highest `score` per question (the reranker is not applied here, so
   these are the calibration scores regardless of `RERANK_ENABLED`).
3. **Place the thresholds in the gaps.** Set `RETRIEVAL_OFF_TOPIC_SCORE`
   between the highest off-topic score and the lowest related-but-not-covered
   score; set `RETRIEVAL_MIN_SCORE` at/above the lowest related-but-not-covered
   score and below the typical in-scope score. Keep
   `RETRIEVAL_OFF_TOPIC_SCORE ≤ RETRIEVAL_MIN_SCORE` (the config validator
   enforces this).
4. **Set both in `.env`, restart, and re-run** the golden and held-out sets on
   your documents. Inspect the failed cases and adjust:
   - related questions wrongly refused as off-topic → **lower** `OFF_TOPIC`;
   - absent facts answered (hallucinated) instead of refused → **raise** `MIN_SCORE`;
   - answerable questions refused as not-covered → **lower** `MIN_SCORE`.
5. **Re-check after any embedding-model or chunking change**, since those shift
   the whole score distribution.

## Sample company

Seed a demo company with the sample documents already ingested (real BGE-M3
embeddings):

```bash
cd backend
.venv/Scripts/python.exe -m app.eval.seed --password "a-long-password"
# optional: --email demo@sanad.example --name "Sanad Demo"
```

It prints the dashboard login, the secret API key (once) and the public
site key. **Change the demo password before any real use** — the seeded
account is for local demos only. Sign in at `/dashboard/`, open
**Evaluation** and press **Run evaluation** (owner only). The page shows the
question count per language, live progress, pass/fail per language and per
category, and each case with its failed checks. Viewers can see results but
cannot run.

API (dashboard session + CSRF for the run):

```bash
curl -X POST http://localhost:8000/api/v1/dashboard/eval/run   # 202; 409 if already running
curl http://localhost:8000/api/v1/dashboard/eval               # state, progress, results, golden counts
```

Runs are background tasks with progress in the KV store (24 h retention);
a run stuck for over 30 minutes can be superseded. Evaluation **never
writes conversations, messages, ratings, cache entries or chat metrics** —
it cannot pollute the Failed questions page or the counters. If the demo
documents are missing, the page warns and grounded cases fail honestly.