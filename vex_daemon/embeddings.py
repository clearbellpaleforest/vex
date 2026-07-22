"""
Optional semantic embedding index for Vex memory.

Behind VEX_EMBEDDING_ENABLE=1 (default 0). Lazy-loads sentence-transformers
(all-MiniLM-L6-v2, ~80 MB on first download, runs on CPU). On memory write and
during consolidation, embeddings are computed and stored in the `mem_embeddings`
table alongside the FTS5 index.

The embedding table is auxiliary — loss is non-fatal. reconstruct() does not
touch it, and recall() falls back to lexical search when embeddings are
unavailable or disabled.

Chamberlain: one embedder, one table, one similarity search.
"""

import json
import os
import sqlite3
import struct
from typing import Optional

from config import DB_PATH

EMBEDDING_ENABLED = os.environ.get("VEX_EMBEDDING_ENABLE", "0") == "1"
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2
_EMBEDDER = None
_EMBEDDER_ERROR: Optional[str] = None

EMBEDDINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS mem_embeddings (
    ref TEXT PRIMARY KEY,
    vec BLOB NOT NULL
)
"""


def _get_embedder():
    """Lazy-load sentence-transformers. Returns the model or raises."""
    global _EMBEDDER, _EMBEDDER_ERROR
    if _EMBEDDER is not None:
        return _EMBEDDER
    if _EMBEDDER_ERROR:
        raise RuntimeError(_EMBEDDER_ERROR)
    if not EMBEDDING_ENABLED:
        _EMBEDDER_ERROR = "embeddings disabled (VEX_EMBEDDING_ENABLE != 1)"
        raise RuntimeError(_EMBEDDER_ERROR)
    try:
        from sentence_transformers import SentenceTransformer
        model_name = os.environ.get("VEX_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        _EMBEDDER = SentenceTransformer(model_name)
        return _EMBEDDER
    except ImportError:
        _EMBEDDER_ERROR = "sentence-transformers not installed"
        raise RuntimeError(_EMBEDDER_ERROR)
    except Exception as e:
        _EMBEDDER_ERROR = f"embedding model load failed: {e}"
        raise RuntimeError(_EMBEDDER_ERROR)


def embed(text: str) -> list[float]:
    """Compute embedding for text. Returns a list of floats."""
    model = _get_embedder()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def _vec_to_blob(vec: list[float]) -> bytes:
    """Pack float32 list into binary blob."""
    return struct.pack(f"{len(vec)}f", *vec)


def _blob_to_vec(blob: bytes) -> list[float]:
    """Unpack binary blob into float32 list."""
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two normalized vectors."""
    return sum(x * y for x, y in zip(a, b))


def ensure_embeddings(conn: sqlite3.Connection) -> None:
    conn.execute(EMBEDDINGS_SCHEMA)
    conn.commit()


def index_embedding(ref: str, text: str, db_path=DB_PATH) -> bool:
    """Compute and store an embedding for a memory ref. Returns success."""
    if not EMBEDDING_ENABLED:
        return False
    try:
        vec = embed(text)
    except Exception:
        return False
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_embeddings(conn)
        conn.execute(
            "INSERT OR REPLACE INTO mem_embeddings (ref, vec) VALUES (?, ?)",
            (ref, _vec_to_blob(vec)),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def semantic_search(query: str, k: int = 5, db_path=DB_PATH) -> list[dict]:
    """Search memory by semantic similarity. Returns up to k results.

    Falls back to lexical search if embeddings are unavailable.
    Each result has {ref, date, summary, similarity}.
    """
    if not EMBEDDING_ENABLED:
        return []
    try:
        query_vec = embed(query)
    except Exception:
        return []

    conn = sqlite3.connect(str(db_path))
    try:
        ensure_embeddings(conn)
        cur = conn.execute("SELECT ref, vec FROM mem_embeddings")
        scored = []
        for ref, blob in cur.fetchall():
            try:
                doc_vec = _blob_to_vec(blob)
                sim = _cosine_similarity(query_vec, doc_vec)
                scored.append((ref, sim))
            except Exception:
                pass
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:k]

        # Hydrate from mem_fts
        results = []
        for ref, sim in top:
            cur2 = conn.execute(
                "SELECT ref, src, date, ts, raw FROM mem_fts WHERE ref = ?", (ref,))
            row = cur2.fetchone()
            if row:
                ref2, src, date, ts, raw = row
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    rec = {}
                results.append({
                    "ref": ref2, "date": date, "src": src,
                    "summary": rec.get("summary", ""),
                    "similarity": round(sim, 4),
                })
        return results
    except Exception:
        return []
    finally:
        conn.close()


def rebuild_embeddings(db_path=DB_PATH) -> int:
    """Recompute embeddings for all memory entries. Returns count."""
    if not EMBEDDING_ENABLED:
        return 0
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_embeddings(conn)
        cur = conn.execute(
            "SELECT ref, text FROM mem_fts WHERE src IN ('memory', 'summary')")
        n = 0
        for ref, text in cur.fetchall():
            try:
                vec = embed(text)
                conn.execute(
                    "INSERT OR REPLACE INTO mem_embeddings (ref, vec) VALUES (?, ?)",
                    (ref, _vec_to_blob(vec)),
                )
                n += 1
            except Exception:
                pass
        conn.commit()
        return n
    finally:
        conn.close()
