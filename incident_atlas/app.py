"""Loopback-only workbench. Run with python -m incident_atlas."""

import io
import os
import secrets
import threading
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import providers
from .engine import run
from .evaluation import evaluate, seed
from .store import Store

ROOT = Path(__file__).parent


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=5, max_length=2000)
    service: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=80)
    recovery: bool = True
    provider: str = "extractive"
    max_attempts: int = Field(default=2, ge=1, le=3)

    @field_validator("question", "service", "version")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Must not be blank")
        return value.strip()


def create_app(db_path=None, auto_seed=True):
    path = Path(
        db_path or os.getenv("ATLAS_DB", str(Path.cwd() / "data" / "atlas.sqlite3"))
    )
    first_run = not path.exists()
    store = Store(path)
    if auto_seed and first_run:
        seed(store)
    app = FastAPI(
        title="Incident Atlas", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.store = store
    token = secrets.token_urlsafe(32)
    # Keep CPU/memory and live-model spending bounded in this single-user workbench.
    work_lock = threading.Lock()

    @contextmanager
    def exclusive_workspace():
        if not work_lock.acquire(blocking=False):
            raise HTTPException(
                409, "The workspace is busy. Wait for the current run to finish."
            )
        try:
            yield
        finally:
            work_lock.release()

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse(
                {"detail": "Cross-origin access is disabled."}, status_code=403
            )
        if request.method not in {"GET", "HEAD"}:
            if not secrets.compare_digest(
                request.headers.get("x-workspace-token", ""), token
            ):
                return JSONResponse(
                    {"detail": "Reload the workspace before changing data."},
                    status_code=403,
                )
        if (
            request.url.path == "/api/documents"
            and request.method == "POST"
            and "content-length" not in request.headers
        ):
            return JSONResponse(
                {"detail": "Uploads require a Content-Length header."}, status_code=411
            )
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "Invalid content length."}, status_code=400)
        if length > 8_500_000:
            return JSONResponse(
                {"detail": "Request exceeds the 8 MB upload limit."}, status_code=413
            )
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/config")
    def config():
        return {
            "token": token,
            "providers": providers.availability(),
            "documents": store.documents(),
            "demo": True,
            "version": "0.1.0",
        }

    @app.get("/api/health")
    def health():
        return {"status": "ok", "documents": len(store.documents())}

    @app.get("/api/documents")
    def documents():
        return store.documents()

    @app.post("/api/documents")
    async def upload(
        file: UploadFile = File(...),
        service: str = Form(...),
        version: str = Form(...),
        aliases: str = Form(""),
    ):
        if (
            not service.strip()
            or not version.strip()
            or max(len(service), len(version)) > 80
            or len(aliases) > 1000
        ):
            raise HTTPException(
                422,
                "Provide a service and version (up to 80 characters); aliases up to 1000.",
            )
        raw = await file.read(8_000_001)
        if len(raw) > 8_000_000:
            raise HTTPException(413, "File exceeds 8 MB.")
        title = Path((file.filename or "document").replace("\\", "/")).name[:160]
        suffix = Path(title).suffix.lower()
        try:
            if suffix in {".txt", ".md"}:
                text = raw.decode("utf-8-sig")
            elif suffix == ".pdf":
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(raw))
                if reader.is_encrypted or len(reader.pages) > 100:
                    raise ValueError("Use an unencrypted PDF with at most 100 pages.")
                text = "\n\n".join(
                    f"[Page {i + 1}]\n{p.extract_text() or ''}"
                    for i, p in enumerate(reader.pages)
                )
                if not any(
                    p.extract_text().strip() for p in reader.pages if p.extract_text()
                ):
                    raise ValueError(
                        "No text layer found. OCR the PDF before uploading."
                    )
            else:
                raise HTTPException(
                    415, "Upload UTF-8 .txt/.md or a text-based .pdf file."
                )
            with exclusive_workspace():
                return store.add_document(
                    title, text, service.strip(), version.strip(), aliases.strip()
                )
        except HTTPException:
            raise
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                422,
                "Could not parse this document. Use plain text or a text-based PDF.",
            ) from exc

    @app.delete("/api/documents/{doc_id}")
    def delete(doc_id: str):
        with exclusive_workspace():
            if not store.delete_document(doc_id):
                raise HTTPException(404, "Document not found")
        return {"deleted": True}

    @app.post("/api/demo")
    def load_demo():
        with exclusive_workspace():
            return {"documents": seed(store)}

    @app.post("/api/run")
    def execute(query: Query):
        if query.provider not in providers.availability():
            raise HTTPException(422, "Unknown model provider")
        if not providers.availability()[query.provider]["ready"]:
            raise HTTPException(422, "Configure the provider on the server first.")
        if not work_lock.acquire(blocking=False):
            raise HTTPException(409, "A run is already active. Wait for it to finish.")
        try:
            return run(store, **query.model_dump())
        finally:
            work_lock.release()

    @app.get("/api/runs")
    def history():
        return [
            {
                k: r[k]
                for k in (
                    "id",
                    "created_at",
                    "question",
                    "status",
                    "service",
                    "version",
                    "latency_ms",
                    "attempts",
                    "recovery",
                )
            }
            for r in store.records("runs")
        ]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        result = store.records("runs", run_id)
        if not result:
            raise HTTPException(404, "Run not found")
        return result

    @app.post("/api/evaluate")
    def evaluation():
        if not work_lock.acquire(blocking=False):
            raise HTTPException(409, "A run is already active.")
        try:
            return evaluate(store)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            work_lock.release()

    @app.get("/api/evaluations")
    def evaluations():
        return store.records("evaluations")

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app
