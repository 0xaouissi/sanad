from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import CompanyDep, SessionDep
from app.db.models import Chunk, Document
from app.providers.embeddings import get_embedding_provider
from app.providers.embeddings.base import EmbeddingError, EmbeddingProvider
from app.rag.arabic import normalize_arabic
from app.schemas.search import SearchHit, SearchRequest, SearchResponse

router = APIRouter(prefix="/search", tags=["search"])

EmbedderDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]


@router.post("", response_model=SearchResponse)
async def search(
    body: SearchRequest, company: CompanyDep, session: SessionDep, embedder: EmbedderDep
) -> SearchResponse:
    try:
        vectors = await embedder.embed([normalize_arabic(body.query)])
    except EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    distance = Chunk.embedding.cosine_distance(vectors[0])
    rows = await session.execute(
        select(Chunk, Document.filename, distance.label("distance"))
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.company_id == company.id)
        .order_by(distance)
        .limit(body.top_k)
    )
    hits = [
        SearchHit(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            filename=filename,
            page_number=chunk.page_number,
            heading=chunk.heading,
            content=chunk.content,
            score=round(1.0 - float(dist), 4),
        )
        for chunk, filename, dist in rows
    ]
    return SearchResponse(query=body.query, hits=hits)