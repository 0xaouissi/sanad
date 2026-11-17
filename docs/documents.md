# Documents and search

Companies are isolated by API key. Create one with the admin key
(`ADMIN_API_KEY` in `.env`), then upload documents and search:

```bash
# 1. Create a company (admin). The returned api_key is shown only once.
curl -X POST http://localhost:8000/api/v1/companies \
  -H "X-Admin-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"name": "Acme"}'

# 2. Upload a document (PDF, DOCX, TXT, MD — or PNG/JPG with OCR installed).
#    Returns 202 immediately; ingestion runs in the background.
curl -X POST http://localhost:8000/api/v1/documents \
  -H "X-API-Key: $API_KEY" -F "file=@policy.pdf"

# 3. Check status (pending -> processing -> ready | failed + reason).
curl http://localhost:8000/api/v1/documents -H "X-API-Key: $API_KEY"

# 4. Similarity search in Arabic, French or English (BGE-M3, pgvector HNSW).
curl -X POST http://localhost:8000/api/v1/search \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"query": "كم يوما لدي لطلب استرجاع المبلغ؟", "top_k": 5}'
```

Also available: `DELETE /api/v1/documents/{id}` and
`POST /api/v1/documents/{id}/reindex`. Re-uploading identical content is
detected (SHA-256 per company) and skipped. `GET /health/db` checks
PostgreSQL + pgvector.

## Ingestion pipeline

Extract text per page/heading (pypdf, python-docx) → repair visual-order
Arabic from PDFs → clean → normalize Arabic (alef variants, diacritics,
tatweel) → overlapping chunks (filename + page + heading kept) → BGE-M3
embeddings → pgvector. Scanned PDFs and images go through Tesseract OCR when
the `ocr` extras are installed.

Installing the embeddings and OCR weights for native development is covered
in [development.md](development.md).