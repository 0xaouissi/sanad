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
[chat.md](chat.md) for the full decision path.

The golden set lives in [backend/app/eval/golden.json](../backend/app/eval/golden.json)
and targets the trilingual demo policies in [samples/](../samples/) (identical
facts in `demo-policy.en.md`, `demo-politique.fr.md`, `demo-siasa.ar.md`).

## Results

Latest run against the seeded demo company, real models, no mocks:

| Language | Questions | Passed | Model | Tier | Date |
|----------|-----------|--------|-------|------|------|
| English  | 14 | 14 | `qwen2.5:3b-instruct-q4_K_M` | small | 2026-11-17 |
| French   | 14 | 14 | `qwen2.5:3b-instruct-q4_K_M` | small | 2026-11-17 |
| Arabic   | 14 | 13 | `qwen2.5:3b-instruct-q4_K_M` | small | 2026-11-17 |

| Category | Questions | Passed |
|----------|-----------|--------|
| Grounded facts + citations | 12 | 12 |
| Out-of-scope refusals (no handoff) | 15 | 15 |
| Related-but-not-covered refusals (handoff offered) | 9 | 8 |
| Prompt-injection blocks | 6 | 6 |

**Total: 41 / 42 passed.** Embeddings `BAAI/bge-m3` (CPU), reranker off
(small-tier default), `RETRIEVAL_MIN_SCORE=0.43`,
`RETRIEVAL_OFF_TOPIC_SCORE=0.41`. Run started 2026-11-17 10:53 UTC via the
dashboard API on a GTX 1650 (4 GB VRAM) + 16 GB RAM host.

The single miss is `ar-nc-giftwrap`: asked in Arabic whether the company
offers gift wrapping, the 3B model answered "yes" (a hallucination with a
citation) instead of refusing. The English and French equivalents refused
correctly. This is the small tier's weaker Arabic grounding showing through
on a related-but-not-covered question — a larger tier and/or the reranker
reduce it. It is reported here rather than hidden.

**Honest note:** 42 questions over three short demo policies is a *sanity
check, not a benchmark*. It proves the pipeline refuses correctly, offers
the handoff only when it should, cites correctly and stays in-language on
known facts; it says nothing about general accuracy, long documents or your
corpus. Re-run it on your own documents after uploading them, and treat a
drop as a signal to inspect the failed cases (the page lists each failed
check), not as a verdict.

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