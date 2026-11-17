# Sanad dashboard

Admin single-page app: **Vite + React + TypeScript**, no router or i18n
libraries — seven tabs, a small translation dictionary, ~57 kB gzipped.

- **Login** — email + password (scrypt-hashed server-side), httpOnly cookie
  session, CSRF token on every mutation, login rate limiting.
- **Documents** — upload, status badges, reindex and delete (owner only,
  each behind a confirm dialog).
- **Website** — add a URL to crawl into documents, live status badges,
  pages crawled and last sync, sync-now and delete (owner only, delete
  behind a confirm dialog). See [docs/crawling.md](../docs/crawling.md).
- **Failed questions** — questions the bot refused, with language and date.
- **Ratings** — visitor thumbs up/down with the question and answer.
- **Handoffs** — visitors' requests to talk to a human: email, message,
  language, per-channel delivery badges and date (read-only for everyone).
- **Evaluation** — run the 42-question golden set (14 per language) against
  the company's documents; live progress, per-language and per-category
  scores, and each case with its failed checks. Owner-only run button;
  warns when the demo documents from `samples/` are missing.
- **Settings** — widget snippet with copy button, allowed domains, the
  conversation-storage privacy toggle, handoff destinations (support email,
  Telegram chat id) with server-transport availability hints, key rotation
  (new keys shown once), JSON export, delete-all-conversations, and team
  management (add viewers).
- **Languages** — English, French, Arabic; Arabic switches the whole page to
  RTL. The choice is remembered in `localStorage`.

Viewers get a read-only interface; the server enforces roles regardless of
what the UI shows.

## Run in development

```bash
cd dashboard
npm install
npm run dev        # http://localhost:5173/dashboard/ (proxies /api to :8000)
```

The backend must be running on `127.0.0.1:8000` (see
[docs/development.md](../docs/development.md)).

## Build for production

```bash
npm run build      # tsc type-check + Vite build
```

The build lands in `backend/app/static/dashboard/` and is committed, so the
backend serves the dashboard at **`/dashboard/`** with no Node.js needed at
deploy time. Rebuild and commit after changing anything under `src/`.