# Human handoff

Visitors can ask for a human at any time: a **"Talk to a human"** link in the
widget footer opens a small form (email + message + privacy notice). When a
question is company-related but the documents cannot answer it
(`refusal_kind = "not_covered"`), an **inline "Talk to a human" button** also
appears under the refusal and opens the same form **with the visitor's
question prefilled**. Off-topic refusals never show the inline button. The
request is delivered to the company's support **email** and/or **Telegram**
chat, and — when *Store conversations* is on — listed in the dashboard's
read-only **Handoffs** tab with per-channel delivery status.

Setup is two layers:

1. **Server transports** (environment only — secrets never touch the database
   or the API): `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
   `SMTP_FROM`, `SMTP_STARTTLS`, `SMTP_TIMEOUT_SECONDS` for email;
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_BASE`, `TELEGRAM_TIMEOUT_SECONDS` for
   Telegram (create a bot with [@BotFather](https://t.me/BotFather), message
   it once, then use your chat id or a group/channel id). An empty host/token
   disables that channel. `SMTP_HOST` without `SMTP_FROM` fails fast at
   startup with a clear message.
2. **Company destinations** (dashboard Settings, owner-only):
   `handoff_email` and `telegram_chat_id`. The API only ever exposes whether
   each server transport is configured (`smtp_configured` /
   `telegram_configured` booleans), never the credentials.

```bash
curl -X POST http://localhost:8000/api/v1/handoff \
  -H "X-Site-Key: pk-..." -H "Origin: https://yourdomain.com" \
  -H "Content-Type: application/json" \
  -d '{"email": "visitor@example.com", "message": "Please call me back"}'
# → {"email": "sent", "telegram": "skipped", "stored": true}
```

## Guarantees

- **Never automatic**: offering the handoff only opens the form (prefilled
  with the question for `not_covered`). No ticket is created and no email or
  Telegram message is sent until the visitor presses **Send** themselves.
- **Same auth as chat**: public site key + the company's `Origin` allowlist
  (or the secret API key server-side), plus the widget bot check
  (honeypot + timing) on the site-key path.
- **Validation & header-injection protection**: emails are strictly
  validated (length, shape, no control characters or line breaks); chat ids
  must be numeric or `@channelname`. Company names and addresses are
  additionally stripped of control characters when building email headers.
- **Rate limits**: `HANDOFF_RATE_LIMIT_PER_IP` (default 5/minute) and
  `HANDOFF_DAILY_CAP_PER_COMPANY` (default 50/UTC day), `0` disables,
  429 + `Retry-After`, fail-open when Redis is down — separate buckets from
  chat limits.
- **Actionable errors**: no destination configured → 409 telling the owner
  what to add in Settings; destination set but server transport missing →
  409 naming the exact env vars; one channel failing → 200 with per-channel
  statuses; both failing → 502 (the failed attempt is still stored when
  storage is on). SMTP passwords and Telegram tokens never appear in
  responses or logs.
- **Privacy**: the form shows a notice before sending; with *Store
  conversations* off the request is delivered but nothing is saved.
- The email carries `Reply-To: visitor@…` so the team can answer directly;
  Arabic/French/English messages are sent as UTF-8, and Telegram text is
  capped at the Bot API's 4096 characters.