"""SQLite persistence. Runs retain evidence snapshots even after a document is removed."""

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def chunks(text, size=1100, overlap=160):
    """Paragraph-aware windows; offsets refer to the normalized source text."""
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind("\n\n", start + size // 2, end)
            if boundary > start:
                end = boundary
        raw = text[start:end]
        part = raw.strip()
        if part:
            yield start + len(raw) - len(raw.lstrip()), part
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, service TEXT NOT NULL,
                version TEXT NOT NULL, text TEXT NOT NULL, aliases TEXT NOT NULL,
                hash TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(hash, service, version));
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY, document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
                position INTEGER NOT NULL, text TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks(document_id);
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evaluations (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def add_document(
        self, title, text, service="general", version="current", aliases=""
    ):
        text = text.replace("\r\n", "\n").strip()
        if not text:
            raise ValueError("The document contains no extractable text.")
        if len(text) > 500_000:
            raise ValueError("Document text exceeds 500,000 characters.")
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self.connect() as db:
            existing = db.execute(
                "SELECT id FROM documents WHERE hash=? AND service=? AND version=?",
                (digest, service, version),
            ).fetchone()
            if existing:
                return {"id": existing["id"], "duplicate": True}
            if db.execute("SELECT count(*) FROM documents").fetchone()[0] >= 100:
                raise ValueError("This local workspace supports at most 100 documents.")
            doc_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)",
                (doc_id, title, service, version, text, aliases, digest, now()),
            )
            for index, (offset, part) in enumerate(chunks(text)):
                db.execute(
                    "INSERT INTO chunks VALUES (?,?,?,?)",
                    (f"{doc_id}:{index}", doc_id, offset, part),
                )
        return {"id": doc_id, "duplicate": False}

    def documents(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute("""SELECT d.id,d.title,d.service,d.version,d.aliases,
                d.created_at,length(d.text) AS characters,count(c.id) AS chunks FROM documents d
                LEFT JOIN chunks c ON d.id=c.document_id GROUP BY d.id ORDER BY d.created_at DESC""")
            ]

    def corpus(self, service="", version=""):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    """SELECT c.*, d.title,d.service,d.version,d.aliases
                FROM chunks c JOIN documents d ON c.document_id=d.id
                WHERE (?='' OR d.service=?) AND (?='' OR d.version=?) ORDER BY c.id""",
                    (service, service, version, version),
                )
            ]

    def delete_document(self, doc_id):
        with self.connect() as db:
            return (
                db.execute("DELETE FROM documents WHERE id=?", (doc_id,)).rowcount > 0
            )

    def save(self, table, payload):
        if table not in {"runs", "evaluations"}:
            raise ValueError("Unknown record type")
        with self.connect() as db:
            db.execute(
                f"INSERT INTO {table} VALUES (?,?,?)",
                (payload["id"], payload["created_at"], json.dumps(payload)),
            )

    def records(self, table, record_id=None):
        if table not in {"runs", "evaluations"}:
            raise ValueError("Unknown record type")
        with self.connect() as db:
            if record_id:
                row = db.execute(
                    f"SELECT payload FROM {table} WHERE id=?", (record_id,)
                ).fetchone()
                return json.loads(row[0]) if row else None
            rows = db.execute(
                f"SELECT payload FROM {table} ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
            return [json.loads(r[0]) for r in rows]
