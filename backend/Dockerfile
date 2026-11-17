FROM python:3.11-slim

WORKDIR /app

# Tesseract + ara/fra packs for optional OCR of scanned PDFs and images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-ara tesseract-ocr-fra \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
# Alembic migrations run at app startup (init_db); they must be in the image.
COPY migrations ./migrations
# CPU torch first: avoids pulling the multi-GB CUDA build on CPU-only hosts.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir ".[embeddings,ocr]"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]