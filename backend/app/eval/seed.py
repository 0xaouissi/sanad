"""Seed the sample company with the demo documents.

    cd backend
    .venv/Scripts/python.exe -m app.eval.seed --password "a-long-password"

Creates a company with an owner login, uploads samples/ and ingests them with
the real embedding provider (needs HF_HOME / the BGE-M3 weights). The secret
API key is printed once. Re-running with the same email fails with a clear
message instead of creating duplicates.
"""

import argparse
import asyncio
import hashlib
import sys

from sqlalchemy import select

from app.core.passwords import hash_password
from app.core.security import generate_api_key, generate_site_key, hash_api_key
from app.db.models import Company, DashboardUser, Document, DocumentStatus, UserRole
from app.db.session import dispose_db, get_session_factory, init_db
from app.eval.golden import read_samples
from app.services.ingestion import document_path, ingest_document


async def seed(email: str, password: str, name: str) -> int:
    await init_db()
    api_key = generate_api_key()
    doc_ids = []
    async with get_session_factory()() as session:
        existing = await session.scalar(select(DashboardUser).where(DashboardUser.email == email))
        if existing is not None:
            print(f"Email {email} already has an account. Use another --email.")
            return 1
        company = Company(
            name=name, api_key_hash=hash_api_key(api_key), site_key=generate_site_key()
        )
        session.add(company)
        await session.flush()
        session.add(
            DashboardUser(
                company_id=company.id,
                email=email,
                password_hash=hash_password(password),
                role=UserRole.OWNER,
            )
        )
        for filename, data in read_samples():
            doc = Document(
                company_id=company.id,
                filename=filename,
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
                status=DocumentStatus.PENDING,
            )
            session.add(doc)
            await session.flush()
            path = document_path(company.id, doc.id, filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            doc_ids.append(doc.id)
        site_key = company.site_key
        await session.commit()

    print("Ingesting demo documents (real embeddings, first run loads BGE-M3)…")
    for doc_id in doc_ids:
        await ingest_document(doc_id)

    failed = []
    async with get_session_factory()() as session:
        for doc_id in doc_ids:
            doc = await session.get(Document, doc_id)
            if doc is None or doc.status != DocumentStatus.READY:
                failed.append(f"{doc.filename if doc else doc_id}: {doc.error if doc else 'gone'}")
    await dispose_db()
    if failed:
        print("Ingestion failed:\n" + "\n".join(failed))
        print("Check HF_HOME / embedding setup (see README) and re-run with a new --email.")
        return 1

    print(f"\nSample company '{name}' is ready.")
    print(f"  Dashboard login: {email} (password you provided)")
    print(f"  Secret API key (shown once): {api_key}")
    print(f"  Public site key: {site_key}")
    print("Open /dashboard/ and run the Evaluation tab.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default="demo@sanad.example")
    parser.add_argument("--password", required=True, help="Owner password (min 8 characters)")
    parser.add_argument("--name", default="Sanad Demo")
    args = parser.parse_args()
    if len(args.password) < 8:
        parser.error("--password must be at least 8 characters")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(seed(args.email, args.password, args.name)))


if __name__ == "__main__":
    main()