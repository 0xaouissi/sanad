# Admin dashboard

A React SPA served by the backend at **`/dashboard/`** — the built bundle is
committed, so no Node.js is needed to run it. English, French and Arabic
(Arabic switches the whole interface to RTL); the choice is remembered.

Create a company **with an owner account** to sign in:

```bash
curl -X POST http://localhost:8000/api/v1/companies \
  -H "X-Admin-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"name": "Acme", "owner_email": "you@acme.com", "owner_password": "a-long-password"}'
```

Then open `http://localhost:8000/dashboard/` and sign in. Pages:

- **Documents** — upload, live status badges, reindex, delete.
- **Website** — crawl your site's policy pages into documents, sync, delete
  ([crawling.md](crawling.md)).
- **Failed questions** — what the bot refused, with language and date.
- **Ratings** — visitor thumbs up/down with the question and answer.
- **Handoffs** — visitors' requests to talk to a human, with per-channel
  delivery status ([handoff.md](handoff.md)).
- **Evaluation** — run the golden Q&A set and see per-language scores
  ([evaluation.md](evaluation.md)).
- **Settings** — the widget snippet (copy button), allowed domains, the
  conversation-storage privacy toggle, handoff destinations (support email,
  Telegram chat id), key rotation, JSON export,
  delete-all-conversations, and team management.

## Security

- Passwords are hashed with **scrypt** (stdlib, salted); plaintext is never
  stored. Login is rate-limited per IP (`LOGIN_RATE_LIMIT_PER_MINUTE`,
  default 10, `0` disables) and returns 429 + `Retry-After`.
- Sessions use an **httpOnly, SameSite=Lax cookie** backed by the KV store
  (Redis or memory), expiring after `DASHBOARD_SESSION_HOURS` (default 12).
  Every mutation requires the session's **CSRF token** in `X-CSRF-Token`;
  without it the API returns 403. Set `COOKIE_SECURE=true` behind HTTPS.
- **Roles are enforced server-side**: the owner manages everything; viewers
  (added from Settings) are read-only — the UI hides mutation controls and
  the API rejects them with 403 regardless.
- Every destructive action (delete document, reindex, rotate keys, delete
  all conversations) asks for confirmation in the interface.
- **Key rotation** issues a new secret `sk-…` and public `pk-…` key at once;
  the old keys stop working immediately and the new secret is shown only
  once. Update the widget snippet after rotating.
- **Privacy toggle**: with *Store conversations* off, chats are still
  answered but nothing is persisted — no history, failed questions, ratings
  or cache — and chat responses carry null conversation/message ids.
  Handoff requests are still delivered but not saved.
- **Export** downloads all company data as JSON (no keys, no password
  hashes); **delete-all-conversations** removes messages and ratings too.

## Development

`cd dashboard && npm install && npm run dev` (Vite on :5173, proxies the API).
`npm run build` type-checks and rebuilds the committed bundle. See
[dashboard/README.md](../dashboard/README.md).