import hashlib
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from sqlalchemy import select

from app.api.deps import CompanyDep, SessionDep
from app.core.config import get_settings
from app.db.models import Document, DocumentStatus
from app.providers.kv import get_kv_store
from app.rag.parsing import SUPPORTED_EXTENSIONS
from app.schemas.document import DocumentAccepted, DocumentOut
from app.services.answer_cache import bump_doc_epoch
from app.services.ingestion import document_path, ingest_document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentAccepted, status_code=202)
async def upload_document(
    company: CompanyDep,
    session: SessionDep,
    background: BackgroundTasks,
    file: UploadFile,
) -> DocumentAccepted:
    settings = get_settings()
    filename = Path(file.filename or "").name
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ext}'. Allowed: PDF, DOCX, TXT, MD, PNG, JPG.",
        )
    data = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds MAX_UPLOAD_MB={settings.max_upload_mb}. "
            "Split the document or raise the limit in .env.",
        )
    if not data:
        raise HTTPException(status_code=422, detail="The file is empty.")

    digest = hashlib.sha256(data).hexdigest()
    existing = await session.scalar(
        select(Document).where(Document.company_id == company.id, Document.sha256 == digest)
    )
    if existing is not None:
        return DocumentAccepted(
            id=existing.id,
            filename=existing.filename,
            status=existing.status,
            duplicate_of=existing.id,
        )

    doc = Document(
        company_id=company.id,
        filename=filename,
        sha256=digest,
        size_bytes=len(data),
        status=DocumentStatus.PENDING,
    )
    session.add(doc)
    await session.flush()
    path = document_path(company.id, doc.id, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    await session.commit()
    await bump_doc_epoch(get_kv_store(), company.id)
    background.add_task(ingest_document, doc.id)
    return DocumentAccepted(id=doc.id, filename=doc.filename, status=DocumentStatus.PENDING)


@router.get("", response_model=list[DocumentOut])
async def list_documents(company: CompanyDep, session: SessionDep) -> list[Document]:
    result = await session.scalars(
        select(Document)
        .where(Document.company_id == company.id)
        .order_by(Document.created_at.desc())
    )
    return list(result)


async def _get_owned_document(company: CompanyDep, session: SessionDep, document_id: UUID):
    doc = await session.get(Document, document_id)
    if doc is None or doc.company_id != company.id:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    company: CompanyDep, session: SessionDep, document_id: UUID
) -> None:
    doc = await _get_owned_document(company, session, document_id)
    path = document_path(company.id, doc.id, doc.filename)
    await session.delete(doc)
    await session.commit()
    await bump_doc_epoch(get_kv_store(), company.id)
    path.unlink(missing_ok=True)


@router.post("/{document_id}/reindex", response_model=DocumentAccepted, status_code=202)
async def reindex_document(
    company: CompanyDep,
    session: SessionDep,
    background: BackgroundTasks,
    document_id: UUID,
) -> DocumentAccepted:
    doc = await _get_owned_document(company, session, document_id)
    if not document_path(company.id, doc.id, doc.filename).exists():
        raise HTTPException(
            status_code=409,
            detail="Stored file is missing; upload the document again instead of reindexing.",
        )
    doc.status = DocumentStatus.PENDING
    doc.error = None
    await session.commit()
    await bump_doc_epoch(get_kv_store(), company.id)
    background.add_task(ingest_document, doc.id)
    return DocumentAccepted(id=doc.id, filename=doc.filename, status=DocumentStatus.PENDING)