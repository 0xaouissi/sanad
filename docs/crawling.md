# Website crawler

Instead of uploading files, point Sanad at your website: it crawls the
policy pages, turns each into a document, and keeps them fresh on a
schedule. Sign in at `/dashboard/`, open **Website**, paste a URL and press
**Add website**. Crawling and ingestion run in the background; the table
shows status, pages crawled and last sync. **Sync now** re-crawls on demand;
**Delete** removes the source and every document crawled from it.

API (dashboard session; mutations also need `X-CSRF-Token`):

```bash
curl -X POST http://localhost:8000/api/v1/dashboard/crawl-sources \
  -H "Content-Type: application/json" -d '{"url": "https://acme.com/policies"}'  # 202
curl http://localhost:8000/api/v1/dashboard/crawl-sources
curl -X POST http://localhost:8000/api/v1/dashboard/crawl-sources/<id>/sync     # 202; 409 while crawling
curl -X DELETE http://localhost:8000/api/v1/dashboard/crawl-sources/<id>        # 204
```

## SSRF protection

On by default, no setting to weaken it in production:

- `http`/`https` only; URLs with embedded credentials are rejected.
- Every DNS answer is checked: if **any** resolves to a private, loopback,
  link-local (incl. `169.254.169.254` cloud metadata), reserved, multicast
  or CGNAT address, the crawl is refused. The connection then **pins the
  validated IP** (with the original `Host` header and TLS SNI), so DNS
  cannot rebind between check and connect.
- Redirects are followed manually (max 5) and **every hop is re-validated**:
  scheme, same domain, and IP ranges again.
- Same domain only: `acme.com` and `www.acme.com` and subdomains of either;
  look-alike domains (`acme.com.evil.com`) are rejected.
- `robots.txt` is respected per URL. A missing file (404) allows crawling;
  an unreachable or erroring one **fails the crawl conservatively**.
- Limits: `CRAWL_MAX_PAGES` (20), `CRAWL_MAX_PAGE_BYTES` (2 MB per page),
  `CRAWL_TIMEOUT_SECONDS` (15 per request), `CRAWL_MAX_SECONDS` (300 total).
  Only HTML/XHTML/plain-text responses are accepted.

## Injection defense

Crawled titles and text pass through the same sentence-level sanitizer as
uploaded documents *before* storage, so "ignore your instructions…" payloads
hidden in a page never reach the model or the vector index.

## Safe re-sync

`CRAWL_RESYNC_HOURS` (default 24, `0` disables) re-crawls due sources in a
background loop. Unchanged pages are kept as-is; a changed page's old
document is deleted **only after** its replacement ingests successfully;
pages that disappeared are removed. If a crawl fails — network, robots,
everything — the previous documents stay untouched.

All settings are documented in [.env.example](../.env.example).
`CRAWL_ALLOW_PRIVATE=true` exists **only** so tests and local development
can crawl a loopback fixture site; never enable it on a reachable server.