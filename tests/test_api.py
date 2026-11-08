import io

import pytest
from fastapi.testclient import TestClient

from incident_atlas.app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "api.sqlite3")
    with TestClient(app, base_url="http://localhost") as c:
        c.headers["x-workspace-token"] = c.get("/api/config").json()["token"]
        yield c


def test_ui_and_health(client):
    assert client.get("/").status_code == 200
    assert "Incident Atlas" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/health").json()["documents"] == 7
    assert (
        "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]
    )


def test_server_rejects_cross_origin_and_untrusted_host(client):
    assert (
        client.get(
            "/api/config", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        client.get("/api/config", headers={"Host": "evil.example"}).status_code == 400
    )
    assert (
        client.post("/api/demo", headers={"x-workspace-token": "wrong"}).status_code
        == 403
    )


def test_execute_and_history(client):
    response = client.post(
        "/api/run",
        json={
            "question": "How do I revert a bad deploy?",
            "service": "atlas-api",
            "version": "2.4",
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["claims"] and result["attempts"] == 2
    assert client.get("/api/runs/" + result["id"]).json() == result
    assert client.get("/api/runs").json()[0]["id"] == result["id"]
    assert client.get("/api/runs/missing").status_code == 404


def test_invalid_inputs_and_unconfigured_provider(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    data = {
        "question": "What should I inspect?",
        "service": "atlas-api",
        "version": "2.4",
    }
    for extra in [
        {"max_attempts": 20},
        {"question": "      "},
        {"service": ""},
        {"provider": "bad"},
        {"provider": "openai"},
        {"arbitrary_url": "http://evil.example"},
    ]:
        assert client.post("/api/run", json={**data, **extra}).status_code == 422
    assert "OPENAI_API_KEY" not in client.get("/api/config").text


def test_upload_dedupe_and_delete(client):
    metadata = {"service": "custom", "version": "v1", "aliases": "overloaded"}
    payload = b"# Capacity\n\nCheck incoming concurrency and queue capacity."
    r = client.post(
        "/api/documents",
        data=metadata,
        files={"file": ("../capacity.md", payload, "text/plain")},
    )
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    assert client.post(
        "/api/documents", data=metadata, files={"file": ("capacity.md", payload)}
    ).json()["duplicate"]
    doc = next(d for d in client.get("/api/documents").json() if d["id"] == doc_id)
    assert doc["title"] == "capacity.md"
    assert client.delete("/api/documents/" + doc_id).status_code == 200
    assert client.delete("/api/documents/" + doc_id).status_code == 404


@pytest.mark.parametrize(
    "name,content,expected",
    [
        ("bad.exe", b"abc", 415),
        ("empty.txt", b"", 422),
        ("encoding.txt", b"\xff\xfe\x00", 422),
        ("broken.pdf", b"no pdf", 422),
    ],
)
def test_bad_uploads_fail_cleanly(client, name, content, expected):
    assert (
        client.post(
            "/api/documents",
            data={"service": "a", "version": "b"},
            files={"file": (name, content)},
        ).status_code
        == expected
    )


def test_oversized_upload(client):
    assert (
        client.post(
            "/api/documents",
            data={"service": "a", "version": "b"},
            files={"file": ("huge.txt", b"x" * 8_000_001)},
        ).status_code
        == 413
    )


def test_blank_pdf_requires_ocr(client):
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    w.write(buf)
    response = client.post(
        "/api/documents",
        data={"service": "a", "version": "b"},
        files={"file": ("blank.pdf", buf.getvalue())},
    )
    assert response.status_code == 422 and "OCR" in response.text


def test_evaluation_api(client):
    response = client.post("/api/evaluate")
    assert response.status_code == 200, response.text
    assert response.json()["case_count"] == 14
    assert client.get("/api/evaluations").json()[0]["id"] == response.json()["id"]


def test_active_run_blocks_mutations_and_second_run(client, monkeypatch):
    import concurrent.futures
    import threading

    from incident_atlas import app as app_module

    entered, release = threading.Event(), threading.Event()
    original = app_module.run

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(app_module, "run", slow)
    data = {
        "question": "How do I revert a bad deploy?",
        "service": "atlas-api",
        "version": "2.4",
    }
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(client.post, "/api/run", json=data)
        try:
            assert entered.wait(5)
            assert client.post("/api/run", json=data).status_code == 409
            assert client.post("/api/demo").status_code == 409
            doc_id = client.get("/api/documents").json()[0]["id"]
            assert client.delete("/api/documents/" + doc_id).status_code == 409
            assert client.post("/api/evaluate").status_code == 409
        finally:
            release.set()
        assert future.result().status_code == 200
