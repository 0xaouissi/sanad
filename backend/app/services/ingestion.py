"""Background document ingestion: parse -> normalize -> chunk -> embed -> store."""

import asyncio
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import structlog
from sqlalchemy import delete

from app.core.config import get_settings
from app.db.models import Chunk, Document, DocumentStatus
from app.db.session import get_session_factory
from app.providers.embeddings import get_embedding_provider
from app.providers.embeddings.base import EmbeddingError
from app.rag.arabic import normalize_arabic
from app.rag.chunking import chunk_blocks
from app.rag.parsing import ParseError, parse_file

log = structlog.get_logger()


def document_path(company_id: UUID, document_id: UUID, filename: str) -> Path:
    ext = Path(filename).suffix.lower()
    return Path(get_settings().data_dir) / str(company_id) / f"{document_id}{ext}"


async def ingest_document(document_id: UUID) -> None:
    settings = get_settings()
    async with get_session_factory()() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return
        doc.status = DocumentStatus.PROCESSING
        doc.error = None
        await session.commit()

        try:
            path = document_path(doc.company_id, doc.id, doc.filename)
            data = await asyncio.to_thread(path.read_bytes)
            blocks = await asyncio.to_thread(parse_file, doc.filename, data, settings)
            blocks = [
                replace(
                    block,
                    text=normalize_arabic(block.text),
                    heading=normalize_arabic(block.heading) if block.heading else None,
                )
                for block in blocks
            ]
            chunks = chunk_blocks(blocks, settings.chunk_size, settings.chunk_overlap)
            vectors = await get_embedding_provider().embed([c.text for c in chunks])

            await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
            session.add_all(
                Chunk(
                    document_id=doc.id,
                    company_id=doc.company_id,
                    chunk_index=chunk.index,
                    content=chunk.text,
                    heading=chunk.heading,
                    page_number=chunk.page,
                    embedding=vector,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            )
            doc.status = DocumentStatus.READY
            doc.chunk_count = len(chunks)
        except (ParseError, EmbeddingError, OSError) as exc:
            doc.status = DocumentStatus.FAILED
            doc.error = str(exc)
            log.warning("ingestion_failed", document_id=str(doc.id), error=str(exc))
        except Exception as exc:
            doc.status = DocumentStatus.FAILED
            doc.error = f"Unexpected ingestion error: {exc}"
            log.exception("ingestion_unexpected_error", document_id=str(doc.id))
        await session.commit()