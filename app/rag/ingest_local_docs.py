# app/rag/ingest_local_docs.py
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import List

from dotenv import load_dotenv
import psycopg  # pip install psycopg[binary]
from openai import OpenAI  # pip install openai>=1.0

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
DOCS_DIR = Path("knowledge")  # put your .md/.txt docs in this folder
ORG_ID = os.getenv("TEST_ORG_ID", "00000000-0000-0000-0000-000000000000")
EMBED_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")


def load_env() -> None:
    """
    Load .env from the project root (same level as pyproject.toml / .env).
    """
    project_root = Path(__file__).resolve().parents[2]  # app/rag -> app -> root
    env_path = project_root / ".env"

    print(f"[ingest] Using .env at: {env_path}")
    if env_path.exists():
        load_dotenv(env_path, override=True)
        print(f"[ingest] Loaded .env from {env_path}")
    else:
        print("[ingest] ⚠️ No .env found, relying on environment variables")


# ---------------------------------------------------------------------
# Simple text chunking
# ---------------------------------------------------------------------
def chunk_text(text: str, max_chars: int = 900) -> List[str]:
    """
    Naive but effective: split on blank lines, then merge paragraphs
    until ~max_chars per chunk.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    for p in paragraphs:
        # collapse excessive whitespace
        p = " ".join(p.split())
        if current_len + len(p) + 2 > max_chars and current:
            chunks.append("\n\n".join(current))
            current = [p]
            current_len = len(p)
        else:
            current.append(p)
            current_len += len(p) + 2

    if current:
        chunks.append("\n\n".join(current))

    return chunks


# ---------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------
_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()  # uses OPENAI_API_KEY from env
    return _client


def embed(text: str) -> list[float]:
    client = get_client()
    resp = client.embeddings.create(
        model=EMBED_MODEL,
        input=text,
    )
    return resp.data[0].embedding


def embedding_to_pgvector(values: list[float]) -> str:
    # pgvector accepts text like `[0.1,0.2,0.3]`
    return "[" + ",".join(f"{v:.6f}" for v in values) + "]"


# ---------------------------------------------------------------------
# Main ingest logic
# ---------------------------------------------------------------------
def ingest_file(conn: psycopg.Connection, path: Path) -> None:
    print(f"[ingest] Processing {path}")

    title = path.stem.replace("_", " ").title()
    source = "local_file"

    text = path.read_text(encoding="utf-8")
    chunks = chunk_text(text)  # ✅ uses the top-level function

    if not chunks:
        print(f"[ingest]  ⚠️ No non-empty chunks in {path}")
        return

    # Stable doc_id from file path so re-ingest updates same doc
    doc_id = uuid.uuid5(uuid.NAMESPACE_URL, str(path.resolve()))
    cur = conn.cursor()

    # Upsert doc row
    cur.execute(
        """
        INSERT INTO docs (id, title, source, org_id)
        VALUES (%s::uuid, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE
          SET title = excluded.title,
              source = excluded.source,
              org_id = excluded.org_id;
        """,
        (str(doc_id), title, source, ORG_ID),
    )

    # Remove old chunks for this doc
    cur.execute("DELETE FROM doc_chunks WHERE doc_id = %s::uuid;", (str(doc_id),))

    for idx, chunk_body in enumerate(chunks, start=1):
        emb = embed(chunk_body)
        vec = embedding_to_pgvector(emb)
        metadata = {
            "source_path": str(path),
            "chunk_index": idx,
        }

        cur.execute(
            """
            INSERT INTO doc_chunks (doc_id, content, embedding, metadata, org_id)
            VALUES (%s::uuid, %s, %s::vector, %s::jsonb, %s);
            """,
            (str(doc_id), chunk_body, vec, json.dumps(metadata), ORG_ID),
        )

    conn.commit()
    print(f"[ingest]  ✅ Ingested {len(chunks)} chunk(s) for doc_id={doc_id}")


def main() -> None:
    load_env()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise SystemExit("DATABASE_URL is not set in env")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[ingest] Using docs dir: {DOCS_DIR}")

    files = sorted(
        [p for p in DOCS_DIR.glob("*.md")] + [p for p in DOCS_DIR.glob("*.txt")]
    )
    if not files:
        print("[ingest] ⚠️ No .md or .txt files found in knowledge/. Add docs first.")
        return

    print("[ingest] Connecting to DB...")
    with psycopg.connect(db_url) as conn:
        # Ensure pgvector is available (no-op if already installed)
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

        for path in files:
            ingest_file(conn, path)

    print("[ingest] ✅ All files processed.")


if __name__ == "__main__":
    main()
