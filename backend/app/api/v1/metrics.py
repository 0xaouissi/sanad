"""Admin-protected Prometheus metrics: in-process counters + database gauges."""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select

from app.api.deps import AdminDep, SessionDep
from app.core import metrics
from app.db.models import Chunk, Company, Conversation, Document, Message

router = APIRouter(tags=["metrics"])

_GAUGES = {
    "companies": Company,
    "documents": Document,
    "chunks": Chunk,
    "conversations": Conversation,
    "messages": Message,
}


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics(session: SessionDep, _: AdminDep) -> PlainTextResponse:
    lines = []
    for name, value in sorted(metrics.snapshot().items()):
        lines.append(f"# TYPE sanad_{name} counter")
        lines.append(f"sanad_{name} {value}")
    for name, model in _GAUGES.items():
        count = await session.scalar(select(func.count()).select_from(model))
        lines.append(f"# TYPE sanad_{name} gauge")
        lines.append(f"sanad_{name} {count}")
    return PlainTextResponse("\n".join(lines) + "\n")