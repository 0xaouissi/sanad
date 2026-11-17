"""Hybrid retrieval: dense vectors + keyword full-text search, RRF fusion,
optional cross-encoder rerank, then a relevance threshold.

Below-threshold results are dropped so the chat layer can refuse instead of
hallucinating from weakly related chunks. Callers may lower the threshold
(min_score) to inspect near-misses and classify the refusal kind themselves.

The reranker only reorders candidates (RetrievalHit.rank_score); the threshold
always compares the pre-rerank dense cosine similarity (RetrievalHit.score),
because the cross-encoder sigmoid probability is a different, uncalibrated
scale. This keeps one set of thresholds valid with reranking on or off.
"""

import uuid
from dataclasses import dataclass, replace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Chunk, Document
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.reranker.base import RerankProvider
from app.rag.arabic import normalize_arabic

RRF_K = 60
CANDIDATE_POOL = 20


@dataclass(frozen=True)
class RetrievalHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_number: int | None
    heading: str | None
    content: str
    # Pre-rerank dense cosine similarity. This is the calibrated relevance
    # scale RETRIEVAL_MIN_SCORE / RETRIEVAL_OFF_TOPIC_SCORE compare against,
    # whether or not a reranker is enabled.
    score: float
    # Reranker relevance probability when reranking is on, else None. Used only
    # to order candidates; never compared against the thresholds, because the
    # cross-encoder sigmoid is a different scale than cosine similarity.
    rank_score: float | None = None

    @property
    def order_score(self) -> float:
        return self.score if self.rank_score is None else self.rank_score


def rrf_fuse(rankings: list[list[uuid.UUID]], k: int = RRF_K) -> dict[uuid.UUID, float]:
    """Reciprocal rank fusion: an item ranked by both lists beats one-list items."""
    scores: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for position, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + position)
    return scores


async def retrieve(
    session: AsyncSession,
    company_id: uuid.UUID,
    query: str,
    embedder: EmbeddingProvider,
    settings: Settings,
    reranker: RerankProvider | None = None,
    min_score: float | None = None,
) -> list[RetrievalHit]:
    normalized = normalize_arabic(query)
    vectors = await embedder.embed([normalized])
    distance = Chunk.embedding.cosine_distance(vectors[0])

    dense_ids = list(
        (
            await session.execute(
                select(Chunk.id)
                .where(Chunk.company_id == company_id)
                .order_by(distance)
                .limit(CANDIDATE_POOL)
            )
        )
        .scalars()
        .all()
    )

    tsquery = func.plainto_tsquery("simple", normalized)
    tsvector = func.to_tsvector("simple", Chunk.content)
    keyword_ids = list(
        (
            await session.execute(
                select(Chunk.id)
                .where(Chunk.company_id == company_id, tsvector.op("@@")(tsquery))
                .order_by(func.ts_rank(tsvector, tsquery).desc())
                .limit(CANDIDATE_POOL)
            )
        )
        .scalars()
        .all()
    )

    fused = rrf_fuse([dense_ids, keyword_ids])
    if not fused:
        return []
    limit = settings.rerank_candidates if reranker is not None else settings.retrieval_top_k
    candidate_ids = sorted(fused, key=lambda cid: fused[cid], reverse=True)[:limit]

    rows = (
        await session.execute(
            select(Chunk, Document.filename, distance.label("distance"))
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.id.in_(candidate_ids))
        )
    ).all()
    hits = [
        RetrievalHit(
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

    if reranker is not None:
        scores = await reranker.rerank(query, [hit.content for hit in hits])
        hits = [
            replace(hit, rank_score=round(score, 4))
            for hit, score in zip(hits, scores, strict=True)
        ]

    # Order by the reranker probability when present, else by cosine similarity.
    hits.sort(key=lambda hit: hit.order_score, reverse=True)
    # Thresholds always compare the pre-rerank cosine similarity (hit.score),
    # the scale they are calibrated on — never the reranker sigmoid.
    threshold = settings.retrieval_min_score if min_score is None else min_score
    hits = [hit for hit in hits if hit.score >= threshold]
    return hits[: settings.retrieval_top_k]