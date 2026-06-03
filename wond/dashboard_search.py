from __future__ import annotations

import hashlib
import json
import math
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .dashboard_shared import (
    clamp,
    compact,
    http_json,
    json_object,
    parse_int,
    report_file_payload,
    row_payload,
    safe_report_path,
    search_keywords,
)
from .observation_filters import is_project_owned_path, project_owned_roots, resolved_path, visible_observations
from .store import Store
from .timeutil import now


DEFAULT_SEARCH_EMBEDDING_CANDIDATES = [
    "bge-m3:latest",
    "bge-m3",
    "qwen3-embedding:4b",
    "nomic-embed-text:latest",
    "mxbai-embed-large:latest",
]
SEARCH_INDEX_SOURCE_PRIORITIES: dict[tuple[str, str], int] = {
    ("mobile", "audio_segment"): 100,
    ("mobile", "bookmark"): 96,
    ("apple_mail", "email"): 92,
    ("local_ai", "media_analysis"): 90,
    ("calendar", "event"): 88,
    ("messages", "message"): 86,
    ("mobile", "location_sample"): 82,
    ("report", "reports"): 58,
    ("browser", "web_visit"): 34,
    ("filesystem", "file_modified"): 22,
    ("system", "collector_error"): 10,
}
SEARCH_INDEX_SOURCE_DEFAULT_PRIORITY = 45


@dataclass(frozen=True)
class SearchDocument:
    record_type: str
    record_key: str
    title: str
    text: str
    observed_at: str | None
    source: str
    kind: str
    path: str | None = None
    payload: dict[str, Any] | None = None


def search_observations(settings: Settings, store: Store, term: str, *, source: str = "", limit: int = 50) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = "1=1"
    if source:
        where += " AND source = ?"
        params.append(source)
    if term:
        keywords = search_keywords(term)
        clauses = []
        for keyword in keywords:
            like = f"%{keyword}%"
            clauses.append(
                "(coalesce(title,'') LIKE ? OR coalesce(subtitle,'') LIKE ? OR coalesce(body,'') LIKE ? "
                "OR coalesce(actor,'') LIKE ? OR coalesce(url,'') LIKE ? OR coalesce(location,'') LIKE ?)"
            )
            params.extend([like] * 6)
        if clauses:
            where += " AND " + " AND ".join(clauses)
    fetch_limit = max(limit, limit * 4)
    params.append(fetch_limit)
    rows = store.conn.execute(
        f"""
        SELECT *
        FROM observations
        WHERE {where}
        ORDER BY observed_at DESC, id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [row_payload(row) for row in visible_observations(settings, rows)[:limit]]


def latest_reports(settings: Settings, *, limit: int) -> list[dict[str, Any]]:
    roots = [
        settings.report_dir,
        settings.summary_dir / "daily",
        settings.summary_dir / "weekly",
        settings.summary_dir / "monthly",
        settings.summary_dir / "email",
        settings.summary_dir / "feedback",
    ]
    files = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("*.md"):
            files.append(report_file_payload(settings, path))
    files.sort(key=lambda item: item["modified_at"], reverse=True)
    return files[:limit]


def search_reports(settings: Settings, term: str, *, limit: int) -> list[dict[str, Any]]:
    if not term:
        return latest_reports(settings, limit=limit)
    keywords = search_keywords(term)
    matches = []
    for item in latest_reports(settings, limit=500):
        path = safe_report_path(settings, item["path"])
        if path is None or not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lower = text.lower()
        index = lower.find(term.lower())
        if index < 0:
            found = [keyword for keyword in keywords if keyword.lower() in lower or keyword.lower() in path.name.lower()]
        else:
            found = keywords
        if not found:
            continue
        if index < 0:
            index = min((lower.find(keyword.lower()) for keyword in found if lower.find(keyword.lower()) >= 0), default=0)
        start = max(0, index - 120) if index >= 0 else 0
        item = dict(item)
        item["snippet"] = compact(text[start : start + 360], 360)
        item["score"] = len(found)
        matches.append(item)
        if len(matches) >= limit:
            break
    return matches


def semantic_search(
    settings: Settings,
    store: Store,
    term: str,
    *,
    source: str = "",
    limit: int = 20,
    auto_index: bool = False,
) -> dict[str, Any]:
    if not term.strip():
        return {"status": "empty", "mode": "hybrid", "model": "", "items": [], "indexed": 0, "index": search_index_status(settings, store)}
    ensure_search_schema(store)
    try:
        model = select_search_embedding_model(settings)
        indexed = 0
        cleaned = cleanup_internal_search_embeddings(settings, store)
        index_status = search_index_status(settings, store)
        if auto_index and search_auto_index_limit(settings) > 0:
            docs = search_documents(
                settings,
                store,
                source=source,
                limit=search_auto_index_limit(settings),
                model=model,
            )
            indexed = index_search_documents(settings, store, docs, model=model, force=False)["indexed"]
            index_status = search_index_status(settings, store)
        question_vector = ollama_embed(settings, model, [term])[0]
        rows = store.conn.execute(
            """
            SELECT *
            FROM search_embeddings
            WHERE model = ?
              AND (? = '' OR source = ? OR record_type = ?)
            """,
            (model, source, source, source),
        ).fetchall()
        scored = []
        for row in rows:
            try:
                vector = json.loads(row["vector"])
            except json.JSONDecodeError:
                continue
            score = cosine_similarity(question_vector, vector)
            if score <= 0:
                continue
            scored.append(semantic_item_payload(row, score))
        scored.sort(key=lambda item: (float(item["score"]), item.get("observed_at") or ""), reverse=True)
        return {
            "status": "ok" if scored else "no_matches",
            "mode": "hybrid",
            "model": model,
            "items": scored[:limit],
            "indexed": indexed,
            "cleaned": cleaned,
            "index": index_status,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "mode": "keyword-fallback",
            "model": search_embedding_model_config(settings),
            "items": [],
            "indexed": 0,
            "error": str(exc),
            "index": search_index_status(settings, store),
        }


def rebuild_search_index(settings: Settings, *, limit: int | None = None, force: bool = False, source: str = "") -> dict[str, Any]:
    store = Store(settings.db_path)
    try:
        ensure_search_schema(store)
        cleaned = cleanup_internal_search_embeddings(settings, store)
        model = select_search_embedding_model(settings)
        docs = search_documents(settings, store, source=source, limit=limit or search_index_limit(settings), model=model)
        result = index_search_documents(settings, store, docs, model=model, force=force)
        return {
            "ok": True,
            "model": model,
            "documents": len(docs),
            "cleaned": cleaned,
            **result,
            "index": search_index_status(settings, store),
        }
    finally:
        store.close()


def ensure_search_schema(store: Store) -> None:
    store.conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS search_embeddings (
            id INTEGER PRIMARY KEY,
            record_type TEXT NOT NULL,
            record_key TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            model TEXT NOT NULL,
            vector TEXT NOT NULL,
            dimension INTEGER NOT NULL,
            title TEXT,
            text TEXT,
            observed_at TEXT,
            source TEXT,
            kind TEXT,
            path TEXT,
            metadata TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(record_type, record_key, model)
        );
        CREATE INDEX IF NOT EXISTS idx_search_embeddings_model
            ON search_embeddings(model);
        CREATE INDEX IF NOT EXISTS idx_search_embeddings_source
            ON search_embeddings(source, kind);
        CREATE INDEX IF NOT EXISTS idx_search_embeddings_time
            ON search_embeddings(observed_at);
        """
    )
    store.conn.commit()


def search_embedding_row_is_internal_file(settings: Settings, row: Any) -> bool:
    if row["source"] != "filesystem" or row["kind"] != "file_modified":
        return False
    path = resolved_path(row["path"])
    if is_project_owned_path(settings, path):
        return True
    haystack = "\n".join(str(row[field] or "") for field in ("path", "metadata", "text"))
    return any(str(root) in haystack for root in project_owned_roots(settings))


def cleanup_internal_search_embeddings(settings: Settings, store: Store) -> int:
    rows = store.conn.execute(
        """
        SELECT id, source, kind, path, metadata, text
        FROM search_embeddings
        WHERE source = 'filesystem'
          AND kind = 'file_modified'
        """
    ).fetchall()
    ids = [int(row["id"]) for row in rows if search_embedding_row_is_internal_file(settings, row)]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    store.conn.execute(f"DELETE FROM search_embeddings WHERE id IN ({placeholders})", ids)
    store.conn.commit()
    return len(ids)


def search_index_status(settings: Settings, store: Store) -> dict[str, Any]:
    ensure_search_schema(store)
    rows = store.conn.execute(
        """
        SELECT model, count(*) AS n, max(updated_at) AS latest
        FROM search_embeddings
        GROUP BY model
        ORDER BY n DESC
        """
    ).fetchall()
    models = [{"model": row["model"], "count": int(row["n"]), "latest": row["latest"]} for row in rows]
    active_model = search_index_active_model(settings, models)
    coverage = search_index_source_coverage(settings, store, active_model)
    return {
        "total_embeddings": sum(item["count"] for item in models),
        "models": models,
        "configured_model": search_embedding_model_config(settings),
        "candidate_models": search_embedding_candidates(settings),
        "index_limit": search_index_limit(settings),
        "auto_index_limit": search_auto_index_limit(settings),
        "active_model": active_model,
        "coverage": coverage,
    }


def search_index_active_model(settings: Settings, models: list[dict[str, Any]]) -> str:
    configured = search_embedding_model_config(settings)
    if configured:
        return configured
    if models:
        return str(models[0].get("model") or "")
    candidates = search_embedding_candidates(settings)
    return candidates[0] if candidates else ""


def search_document_priority(source: str, kind: str) -> int:
    return SEARCH_INDEX_SOURCE_PRIORITIES.get((source, kind), SEARCH_INDEX_SOURCE_DEFAULT_PRIORITY)


def search_observation_priority_sql() -> str:
    cases = " ".join(
        f"WHEN source = '{source}' AND kind = '{kind}' THEN {priority}"
        for (source, kind), priority in sorted(SEARCH_INDEX_SOURCE_PRIORITIES.items(), key=lambda item: item[1], reverse=True)
        if source not in {"report"}
    )
    return f"CASE {cases} ELSE {SEARCH_INDEX_SOURCE_DEFAULT_PRIORITY} END"


def search_document_fetch_limit(limit: int) -> int:
    return clamp(max(limit * 8, limit + 250), limit, 50000)


def search_indexed_keys(store: Store, model: str) -> set[tuple[str, str]]:
    if not model:
        return set()
    rows = store.conn.execute(
        """
        SELECT record_type, record_key
        FROM search_embeddings
        WHERE model = ?
        """,
        (model,),
    ).fetchall()
    return {(str(row["record_type"]), str(row["record_key"])) for row in rows}


def sort_search_documents_for_indexing(docs: list[SearchDocument], indexed_keys: set[tuple[str, str]]) -> list[SearchDocument]:
    def key(doc: SearchDocument) -> tuple[int, int, str, str, str]:
        missing = 0 if (doc.record_type, doc.record_key) in indexed_keys else 1
        return (
            missing,
            search_document_priority(doc.source, doc.kind),
            doc.observed_at or "",
            doc.record_type,
            doc.record_key,
        )

    return sorted(docs, key=key, reverse=True)


def search_index_source_coverage(settings: Settings, store: Store, model: str) -> dict[str, Any]:
    observation_rows = store.conn.execute(
        """
        SELECT source, kind, count(*) AS n, max(observed_at) AS latest
        FROM observations
        GROUP BY source, kind
        """
    ).fetchall()
    indexed_rows = (
        store.conn.execute(
            """
            SELECT source, kind, count(*) AS n, max(observed_at) AS latest
            FROM search_embeddings
            WHERE model = ?
              AND record_type = 'observation'
            GROUP BY source, kind
            """,
            (model,),
        ).fetchall()
        if model
        else []
    )
    indexed_by_key = {
        (str(row["source"] or ""), str(row["kind"] or "")): {"indexed": int(row["n"] or 0), "latest_indexed": row["latest"]}
        for row in indexed_rows
    }
    rows = []
    total_observations = 0
    total_indexed = 0
    for row in observation_rows:
        source_name = str(row["source"] or "")
        kind = str(row["kind"] or "")
        total = int(row["n"] or 0)
        indexed = int(indexed_by_key.get((source_name, kind), {}).get("indexed") or 0)
        indexed_capped = min(indexed, total)
        total_observations += total
        total_indexed += indexed_capped
        rows.append(
            {
                "source": source_name,
                "kind": kind,
                "total": total,
                "indexed": indexed_capped,
                "indexed_raw": indexed,
                "missing": max(0, total - indexed_capped),
                "coverage": round(indexed_capped / total, 4) if total else 0.0,
                "latest_observed": row["latest"],
                "latest_indexed": indexed_by_key.get((source_name, kind), {}).get("latest_indexed"),
                "priority": search_document_priority(source_name, kind),
            }
        )
    rows.sort(key=lambda item: (int(item["priority"]), int(item["missing"]), item.get("latest_observed") or ""), reverse=True)
    return {
        "model": model,
        "total_observations": total_observations,
        "indexed_observations": total_indexed,
        "missing_observations": max(0, total_observations - total_indexed),
        "coverage": round(total_indexed / total_observations, 4) if total_observations else 0.0,
        "by_source": rows[:16],
        "approximate": True,
    }


def search_documents(settings: Settings, store: Store, *, source: str = "", limit: int, model: str = "") -> list[SearchDocument]:
    docs: list[SearchDocument] = []
    if limit <= 0:
        return docs
    params: list[Any] = []
    where = "1=1"
    if source and source != "report":
        where += " AND source = ?"
        params.append(source)
    if source != "report":
        priority_sql = search_observation_priority_sql()
        fetch_limit = search_document_fetch_limit(limit)
        params.append(fetch_limit)
        rows = store.conn.execute(
            f"""
            SELECT *
            FROM observations
            WHERE {where}
            ORDER BY {priority_sql} DESC, observed_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        for row in visible_observations(settings, rows):
            doc = observation_search_document(row, settings)
            if doc is not None:
                docs.append(doc)
    if not source or source == "report":
        docs.extend(report_search_documents(settings, limit=limit))
    if model:
        docs = sort_search_documents_for_indexing(docs, search_indexed_keys(store, model))
    else:
        docs.sort(key=lambda doc: (search_document_priority(doc.source, doc.kind), doc.observed_at or ""), reverse=True)
    return docs[:limit]


def observation_search_document(row, settings: Settings) -> SearchDocument | None:
    meta = json_object(row["metadata"])
    analysis = meta.get("audio_analysis") if isinstance(meta.get("audio_analysis"), dict) else {}
    if row["source"] == "mobile" and row["kind"] == "audio_segment" and not row["body"] and not analysis.get("summary"):
        return None
    title = row["title"] or row["subtitle"] or row["actor"] or f"{row['source']}/{row['kind']}"
    parts = [
        title,
        row["subtitle"],
        row["actor"],
        row["location"],
        row["url"],
        analysis.get("summary") if isinstance(analysis, dict) else "",
        row["body"],
    ]
    text = "\n".join(str(part) for part in parts if part)
    text = compact(text, search_chunk_chars(settings))
    if not text.strip():
        return None
    payload = row_payload(row)
    return SearchDocument(
        record_type="observation",
        record_key=str(row["id"]),
        title=str(title),
        text=text,
        observed_at=row["observed_at"],
        source=row["source"],
        kind=row["kind"],
        payload=payload,
    )


def report_search_documents(settings: Settings, *, limit: int) -> list[SearchDocument]:
    docs: list[SearchDocument] = []
    if limit <= 0:
        return docs
    chunk_chars = search_chunk_chars(settings)
    for item in latest_reports(settings, limit=200):
        path = safe_report_path(settings, item["path"])
        if path is None or not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for idx, chunk in enumerate(chunk_text(text, chunk_chars)):
            docs.append(
                SearchDocument(
                    record_type="report",
                    record_key=f"{item['path']}#{idx}",
                    title=item["name"],
                    text=chunk,
                    observed_at=item["modified_at"],
                    source="report",
                    kind=item["category"],
                    path=item["path"],
                    payload={**item, "snippet": compact(chunk, 500), "chunk": idx},
                )
            )
            if len(docs) >= limit:
                return docs
    return docs


def index_search_documents(
    settings: Settings,
    store: Store,
    docs: list[SearchDocument],
    *,
    model: str,
    force: bool,
) -> dict[str, Any]:
    ensure_search_schema(store)
    if force and docs:
        sources = sorted({doc.source for doc in docs})
        placeholders = ",".join("?" for _ in sources)
        store.conn.execute(
            f"DELETE FROM search_embeddings WHERE model = ? AND source IN ({placeholders})",
            (model, *sources),
        )
        store.conn.commit()
    pending: list[tuple[SearchDocument, str]] = []
    for doc in docs:
        digest = content_hash(doc.text)
        existing = store.conn.execute(
            """
            SELECT content_hash
            FROM search_embeddings
            WHERE record_type = ?
              AND record_key = ?
              AND model = ?
            """,
            (doc.record_type, doc.record_key, model),
        ).fetchone()
        if existing is not None and existing["content_hash"] == digest and not force:
            continue
        pending.append((doc, digest))
    indexed = 0
    skipped = len(docs) - len(pending)
    batch_size = 16
    for offset in range(0, len(pending), batch_size):
        batch = pending[offset : offset + batch_size]
        vectors = ollama_embed(settings, model, [doc.text for doc, _digest in batch])
        updated_at = now(settings.timezone).isoformat(timespec="seconds")
        for (doc, digest), vector in zip(batch, vectors):
            store.conn.execute(
                """
                INSERT INTO search_embeddings (
                    record_type, record_key, content_hash, model, vector, dimension,
                    title, text, observed_at, source, kind, path, metadata, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_type, record_key, model) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    vector = excluded.vector,
                    dimension = excluded.dimension,
                    title = excluded.title,
                    text = excluded.text,
                    observed_at = excluded.observed_at,
                    source = excluded.source,
                    kind = excluded.kind,
                    path = excluded.path,
                    metadata = excluded.metadata,
                    updated_at = excluded.updated_at
                """,
                (
                    doc.record_type,
                    doc.record_key,
                    digest,
                    model,
                    json.dumps(vector, ensure_ascii=False),
                    len(vector),
                    doc.title,
                    compact(doc.text, 1600),
                    doc.observed_at,
                    doc.source,
                    doc.kind,
                    doc.path,
                    json.dumps(doc.payload or {}, ensure_ascii=False, sort_keys=True),
                    updated_at,
                ),
            )
            indexed += 1
        store.conn.commit()
    return {"indexed": indexed, "skipped": skipped}


def semantic_item_payload(row, score: float) -> dict[str, Any]:
    metadata = json_object(row["metadata"])
    return {
        "type": row["record_type"],
        "key": row["record_key"],
        "score": round(score, 4),
        "title": row["title"],
        "text": compact(row["text"], 700),
        "observed_at": row["observed_at"],
        "source": row["source"],
        "kind": row["kind"],
        "path": row["path"],
        "payload": metadata,
    }


def select_search_embedding_model(settings: Settings) -> str:
    configured = search_embedding_model_config(settings)
    candidates = search_embedding_candidates(settings)
    if configured:
        return configured
    names = ollama_model_names(settings)
    if not names:
        return candidates[0]
    normalized = {name.replace(":latest", ""): name for name in names}
    for candidate in candidates:
        if candidate in names:
            return candidate
        base = candidate.replace(":latest", "")
        if base in normalized:
            return normalized[base]
    return candidates[0]


def search_embedding_model_config(settings: Settings) -> str:
    return str(settings.local_ai.get("search_embedding_model") or "").strip()


def search_embedding_candidates(settings: Settings) -> list[str]:
    raw = settings.local_ai.get("search_embedding_candidates") or DEFAULT_SEARCH_EMBEDDING_CANDIDATES
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()] or list(DEFAULT_SEARCH_EMBEDDING_CANDIDATES)
    if isinstance(raw, list):
        values = [str(item).strip() for item in raw if str(item).strip()]
        return values or list(DEFAULT_SEARCH_EMBEDDING_CANDIDATES)
    return list(DEFAULT_SEARCH_EMBEDDING_CANDIDATES)


def search_index_limit(settings: Settings) -> int:
    return clamp(parse_int(settings.local_ai.get("search_index_limit")) or 5000, 100, 50000)


def search_auto_index_limit(settings: Settings) -> int:
    return clamp(parse_int(settings.local_ai.get("search_auto_index_limit")) or 400, 0, 3000)


def search_chunk_chars(settings: Settings) -> int:
    return clamp(parse_int(settings.local_ai.get("search_chunk_chars")) or 1400, 300, 4000)


def ollama_model_names(settings: Settings) -> list[str]:
    url = str(settings.local_ai.get("ollama_base_url") or "http://127.0.0.1:11434").rstrip("/") + "/api/tags"
    payload = http_json(url, timeout=3)
    return [str(item.get("name")) for item in payload.get("models", []) if isinstance(item, dict) and item.get("name")]


def ollama_embed(settings: Settings, model: str, texts: list[str]) -> list[list[float]]:
    base = str(settings.local_ai.get("ollama_base_url") or "http://127.0.0.1:11434").rstrip("/")
    payload = {"model": model, "input": texts}
    req = urllib.request.Request(
        f"{base}/api/embed",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
        vectors = data.get("embeddings") if isinstance(data, dict) else None
        if isinstance(vectors, list) and len(vectors) == len(texts):
            return [normalize_vector(vector) for vector in vectors]
        vector = data.get("embedding") if isinstance(data, dict) else None
        if len(texts) == 1 and isinstance(vector, list):
            return [normalize_vector(vector)]
    except Exception:
        if len(texts) > 1:
            return [ollama_embed(settings, model, [text])[0] for text in texts]
        return [ollama_legacy_embedding(settings, model, texts[0])]
    raise RuntimeError("Ollama embedding response did not include matching vectors")


def ollama_legacy_embedding(settings: Settings, model: str, text: str) -> list[float]:
    base = str(settings.local_ai.get("ollama_base_url") or "http://127.0.0.1:11434").rstrip("/")
    payload = {"model": model, "prompt": text}
    req = urllib.request.Request(
        f"{base}/api/embeddings",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        data = json.loads(response.read().decode("utf-8"))
    vector = data.get("embedding") if isinstance(data, dict) else None
    if not isinstance(vector, list):
        raise RuntimeError("Ollama legacy embedding response did not include vector")
    return normalize_vector(vector)


def normalize_vector(raw: Any) -> list[float]:
    vector = [float(value) for value in raw]
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def chunk_text(text: str, limit: int) -> list[str]:
    cleaned = "\n".join(line.rstrip() for line in text.splitlines())
    paragraphs = [part.strip() for part in cleaned.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs or [cleaned.strip()]:
        if not paragraph:
            continue
        if len(paragraph) > limit:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(paragraph), limit):
                chunks.append(paragraph[start : start + limit])
            continue
        next_value = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(next_value) > limit and current:
            chunks.append(current)
            current = paragraph
        else:
            current = next_value
    if current:
        chunks.append(current)
    return chunks


def build_answer_context(
    observations: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    semantic_items: list[dict[str, Any]] | None = None,
) -> str:
    chunks = []
    seen = set()
    for item in (semantic_items or [])[:14]:
        evidence_id = f"semantic:{item.get('type')}:{item.get('key')}"
        seen.add(evidence_id)
        chunks.append(
            f"[{evidence_id}] score={item.get('score')} {item.get('observed_at')} "
            f"{item.get('source')}/{item.get('kind')} {compact(item.get('text'), 900)}"
        )
    for item in observations[:12]:
        evidence_id = f"obs:{item['id']}"
        if f"semantic:observation:{item['id']}" in seen:
            continue
        body_parts = [item.get("title"), f"@ {item.get('location')}" if item.get("location") else "", item.get("body")]
        body = " ".join(str(part) for part in body_parts if part)
        date_context = f" {item.get('date_context')}" if item.get("date_context") else ""
        chunks.append(f"[{evidence_id}]{date_context} {item.get('observed_at')} {item.get('source')}/{item.get('kind')} {compact(body, 700)}")
    for item in reports[:5]:
        date_context = f" {item.get('date_context')}" if item.get("date_context") else ""
        chunks.append(f"[report:{item['path']}]{date_context} {item.get('snippet') or item.get('name')}")
    return "\n".join(chunks)[:12000]


def answer_citations(
    observations: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    semantic_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    citations = []
    for item in (semantic_items or [])[:14]:
        citations.append(
            {
                "type": item.get("type"),
                "key": item.get("key"),
                "score": item.get("score"),
                "time": item.get("observed_at"),
                "source": item.get("source"),
                "kind": item.get("kind"),
                "path": item.get("path"),
            }
        )
    for item in observations[:12]:
        citations.append(
            {
                "type": "observation",
                "id": item["id"],
                "time": item.get("observed_at"),
                "source": item.get("source"),
                "kind": item.get("kind"),
                "date_context": item.get("date_context"),
            }
        )
    for item in reports[:5]:
        citations.append({"type": "report", "path": item["path"], "name": item["name"], "date_context": item.get("date_context")})
    return citations


def fallback_answer(question: str, observations: list[dict[str, Any]], reports: list[dict[str, Any]], exc: Exception) -> str:
    lines = [f"本地模型暂时不可用，改用检索结果摘要。错误：{exc}", ""]
    if observations:
        lines.append("相关记录：")
        for item in observations[:6]:
            lines.append(f"- {item.get('observed_at')} {item.get('source')}/{item.get('kind')}: {compact(item.get('body') or item.get('title'), 180)}")
    if reports:
        lines.append("相关报告：")
        for item in reports[:4]:
            lines.append(f"- {item.get('name')}: {compact(item.get('snippet'), 180)}")
    return "\n".join(lines)


def ollama_generate(settings: Settings, prompt: str, *, model: str) -> str:
    base = str(settings.local_ai.get("ollama_base_url") or "http://127.0.0.1:11434").rstrip("/")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.1},
    }
    req = urllib.request.Request(
        f"{base}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        data = json.loads(response.read().decode("utf-8"))
    message = data.get("message") if isinstance(data, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Ollama returned no answer")
    return content.strip()
