# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x (latest release) | ✅ |
| older / unreleased `main` | best effort |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private vulnerability reporting: repository **Security** tab →
**Report a vulnerability**. If that is unavailable, contact the maintainer
privately (see the repository owner profile) and we will arrange a channel.

Include: affected version/commit, a minimal reproduction, impact, and any
suggested fix. We aim to acknowledge within a few days and will coordinate a
fix and disclosure timeline with you.

## Design notes — what is *not* a vulnerability

These are intentional, documented properties (see
[docs/protection.md](docs/protection.md) and [docs/widget.md](docs/widget.md)):

- **The public `pk-…` site key is public by design.** It identifies a company
  and stops *other websites* from embedding it (browser `Origin` allowlist). It
  is not an authentication secret; a determined non-browser client can copy it
  and forge `Origin`. The real abuse backstops are server-side: per-IP and
  per-site rate limits, a daily company cap, and the widget bot check.
- **The bot check (honeypot + timing) deters trivial bots; it is not a security
  boundary.** Secret-key (server-side) callers are trusted and exempt.
- **Demo credentials are public.** The seeded demo password is for local demos
  only and must be changed before any real use.

Reports that merely restate these properties will be closed as documented
behaviour, not vulnerabilities.

## How secrets are handled

- Operator secrets (SMTP, Telegram, OpenAI-compatible API key, admin key) live
  **only in environment variables**; they never touch the database or API
  responses.
- Company API keys are stored **only as SHA-256 hashes**; plaintext is shown
  once at creation/rotation. Dashboard passwords use **scrypt** (salted).
- Dashboard sessions are **httpOnly, SameSite=Lax cookies** with a **CSRF
  token** required on every mutation; login is rate-limited.
- `backend/.env` is gitignored. Never commit real credentials.

## History and dependency scanning

- The **full git history** was scanned with **gitleaks v8.30.1** on
  **2026-11-17**: no leaks found. Re-run anytime with `gitleaks git .`
- **Secret scanning** and **push protection** are enabled on the repository.
- **Dependabot** version updates are configured in `.github/dependabot.yml`
  (pip, npm, GitHub Actions, Docker base images); Dependabot **alerts** and
  **security updates** are enabled at the repository level.

## Scope

In scope: the backend API, widget, dashboard, crawler (SSRF), handoff
transports, ingestion/OCR, and the Docker/deployment configs. Out of scope:
third-party model weights and their licenses (see
[docs/models.md](docs/models.md)), and vulnerabilities in dependencies
themselves (report upstream; Dependabot tracks bumps here).