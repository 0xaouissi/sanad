# The embeddable widget

One script tag on any website — no build step, no dependencies, Shadow DOM so
the host page's CSS can't break it (and vice versa):

```html
<script src="http://localhost:8000/widget.js" data-site-key="pk-…" defer></script>
```

The widget uses a **public site key**, never the secret company API key. Each
company gets a `pk-…` key at creation (also returned by
`POST /api/v1/companies`). The site key only works on the company's **allowed
domains** — set them once with the secret key:

```bash
curl -X PUT http://localhost:8000/api/v1/companies/domains \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"domains": ["example.com", "*.example.com"]}'
```

`*.example.com` matches subdomains only, not the apex — list both if needed.
Requests from other origins (or with no `Origin` header) get **403 with a
message explaining how to fix it**. The secret key still works everywhere for
server-side use and is required for documents, search and domain management;
the site key is rejected on those endpoints.

## Configuration

`data-*` attributes on the script tag:

| Attribute | Default | Meaning |
|-----------|---------|---------|
| `data-site-key` | — | **Required.** The company's public `pk-…` key |
| `data-api-url` | script origin | Backend base URL (when served from a CDN) |
| `data-color` | `#2563eb` | Accent color (validated; falls back if invalid) |
| `data-logo` | none | Header logo URL (`http(s)` only) |
| `data-welcome` | localized greeting | First message shown when the panel opens |
| `data-lang` | `auto` | `auto` detects the visitor's language; `ar`/`fr`/`en` force it. A dropdown in the header lets visitors switch at any time |
| `data-theme` | `auto` | `auto` follows the OS setting; `light`/`dark` force it |

With `data-lang="auto"` the answer language always matches the question.
On the small tier, answers are most reliable when the documents, the question
and the answer share a language; mixing languages (e.g. asking in French
about English documents, or forcing a different answer language) can
occasionally give weak answers — medium/large tiers handle this better.

## Features

Floating button, streaming answers with a typing indicator, clickable
citation chips (filename, page, heading), thumbs up/down per answer
(`POST /api/v1/feedback`, one rating per message), full RTL for Arabic,
full-screen panel on mobile, light/dark themes, Escape to close, `aria-live`
messages, and a "Talk to a human" handoff form ([handoff.md](handoff.md)).

When a question is company-related but the documents cannot answer it
(`refusal_kind = "not_covered"`), the refusal bubble also gets an **inline
"Talk to a human" button**. Clicking it opens the handoff form with the
visitor's question prefilled — it never submits anything on its own. Off-topic
refusals (`off_topic`) show no inline button; the always-visible footer handoff
link is present in both cases. See [chat.md](chat.md) for the two refusal kinds.

**Safety:** answers are rendered with `textContent` only — no `innerHTML`, no
raw HTML anywhere in the widget. A malicious document containing
`<script>`/`<img onerror=…>` is displayed as literal text and cannot execute
(covered by a real-browser XSS test). Logo URLs are restricted to `http(s)`.

## What the public site key does and does not protect

The `pk-…` site key is **public by design**: anyone can read it from the page
source, and the `Origin` header it is checked against can be spoofed by
non-browser clients. It is an *identifier plus a browser-only guard rail*,
not an authentication secret:

- **It does:** identify the company, and stop *other websites* from embedding
  your widget key in their pages (browsers enforce the `Origin` allowlist).
- **It does not:** stop a determined script that calls the API directly with a
  copied key and a forged `Origin`.

That is why the real abuse backstops are server-side and apply to every chat
request: **per-IP and per-site rate limits, a daily cap per company, and the
widget bot check** ([protection.md](protection.md)). Keep the secret `sk-…`
API key on your server only — it is required for documents, search and domain
management, and it bypasses the bot check (server-side integrations are
trusted callers). Company API keys are stored **only as SHA-256 hashes**; the
plaintext is shown once at creation and never persisted.