# Grounded chat

`POST /api/v1/chat` answers **only from the company's documents**, in the
visitor's language (Arabic, French or English — auto-detected, or forced with
`"language": "ar"|"fr"|"en"`). Server-side: send the company `X-API-Key`.
From a browser: send the public `X-Site-Key` + an allowed `Origin` (see
[the widget](widget.md)).

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"message": "Combien de jours pour un remboursement ?"}'
```

Response: `answer`, `language`, `conversation_id`, `message_id`, `citations`
(filename, page, heading, chunk id), `model`, `provider`, and `refusal_kind`
(`"off_topic"`, `"not_covered"`, or `null` for a grounded answer).

## How it works

- **Hybrid retrieval** — dense BGE-M3 similarity + PostgreSQL full-text
  keyword search, fused with reciprocal rank fusion. On medium/large tiers a
  local cross-encoder (`bge-reranker-v2-m3`) re-ranks the top candidates;
  off by default on the small tier, override with `RERANK_ENABLED`. The
  reranker only **reorders** candidates: its sigmoid relevance probability is
  a different scale than cosine similarity, so the refusal thresholds below
  always compare the **pre-rerank dense cosine score**, with reranking on or
  off. One calibration stays valid either way.
- **Two refusal kinds** — retrieval uses two thresholds. Below
  `RETRIEVAL_OFF_TOPIC_SCORE` (default 0.41) a question is treated as
  **off-topic**; between that and `RETRIEVAL_MIN_SCORE` (default 0.43) it is
  **company-related but not covered**. Both thresholds are calibrated on real
  BGE-M3 cosine scores and `RETRIEVAL_OFF_TOPIC_SCORE` must be ≤ `RETRIEVAL_MIN_SCORE`.
  See [Refusals and the human handoff](#refusals-and-the-human-handoff) below.
- **Strict grounding** — the prompt forbids outside knowledge and requires
  inline `[n]` citations; the response maps them to document name + page.
- **Conversation memory** — pass `conversation_id` back to continue a chat;
  the last `MEMORY_MAX_TURNS` messages are replayed (and the previous turn
  helps retrieval understand follow-ups like "and how long does it take?").
- **Language retry** — if the model answers in the wrong language, it is
  retried once with an explicit instruction (works for streaming too).
- **Latency** — time to first streamed token is logged per request
  (`chat_latency`) against the tier budget: ≤8 s small, ≤3 s medium/large.

## Refusals and the human handoff

Sanad distinguishes two refusals so the visitor gets the right next step:

| Kind | When | Reply (en) | Handoff |
|------|------|-----------|---------|
| `off_topic` | Best source below `RETRIEVAL_OFF_TOPIC_SCORE`, no sources at all, or a prompt-injection attempt | "Sorry, I can only help with questions about this company." | Not offered inline |
| `not_covered` | Company-related (sources at/above the off-topic floor) but the documents cannot answer it | "I couldn't find an answer to this question in the company's documents." | **Offered** — a "Talk to a human" button prefilled with the question |

Both replies are localized into Arabic and French. The decision path:

1. Retrieve with the lower `RETRIEVAL_OFF_TOPIC_SCORE` floor.
2. **Injection attempt or no hits** → `off_topic`, the LLM is never called.
3. **Best pre-rerank cosine score below `RETRIEVAL_MIN_SCORE`** → `not_covered`,
   the LLM is never called (the question is related but the sources are too
   weak to answer). "Best" is the highest cosine similarity across the retrieved
   hits, not the first hit, because a reranker may reorder them.
4. Otherwise keep only hits at/above `RETRIEVAL_MIN_SCORE` and call the LLM.
   If it leaks the system prompt → `off_topic`; if it returns the localized
   "couldn't find" template → `not_covered`; else it is a grounded answer
   (`refusal_kind = null`).

"Sources found but cannot answer" is always treated as company-related
(`not_covered`), so the handoff is offered. Refusals never carry citations.
The handoff is **never sent automatically**: the inline button only opens the
form with the question prefilled, and the visitor must submit it themselves
(see [handoff.md](handoff.md)). The always-visible footer handoff link is
unchanged; the inline button appears *only* for `not_covered`.

## Streaming

Add `"stream": true`. Server-sent events are `token` chunks, then a final
`done` event carrying `conversation_id`, `language`, `message_id`,
`citations` and `refusal_kind` (or an `error` event with an actionable
detail and `refusal_kind`).