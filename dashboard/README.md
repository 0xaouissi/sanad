# Sanad dashboard

Admin single-page app: **Vite + React + TypeScript**, no router or i18n
libraries — five tabs, a small translation dictionary, ~55 kB gzipped.

- **Login** — email + password (scrypt-hashed server-side), httpOnly cookie
  session, CSRF token on every mutation, login rate limiting.
- **Documents** — upload, status badges, reindex and delete (owner only,
  each behind a confirm dialog).
- **Failed questions** — questions the bot refused, with language and date.
- **Ratings** — visitor thumbs up/down with the question and answer.
- **Evaluation** — run the 33-question golden set (11 per language) against
  the company's documents; live progress, per-language and per-category
  scores, and each case with its failed checks. Owner-only run button;
  warns when the demo documents from `samples/` are missing.
- **Settings** — widget snippet with copy button, allowed domains, the
  conversation-storage privacy toggle, key rotation (new keys shown once),
  JSON export, delete-all-conversations, and team management (add viewers).
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

The backend must be running on `127.0.0.1:8000` (see the main README).

## Build for production

```bash
npm run build      # tsc type-check + Vite build
```

The build lands in `backend/app/static/dashboard/` and is committed, so the
backend serves the dashboard at **`/dashboard/`** with no Node.js needed at
deploy time. Rebuild and commit after changing anything under `src/`.