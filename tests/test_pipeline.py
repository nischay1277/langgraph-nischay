import pytest

from incident_atlas import providers
from incident_atlas.engine import run, validate_claims
from incident_atlas.evaluation import evaluate, seed
from incident_atlas.retrieval import corrected_query
from incident_atlas.store import Store, chunks


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.sqlite3")
    seed(s)
    return s


def test_recovery_bridges_declared_aliases(store):
    baseline = run(
        store, "How do I revert a bad deploy?", "atlas-api", "2.4", recovery=False
    )
    healed = run(store, "How do I revert a bad deploy?", "atlas-api", "2.4")
    assert baseline["status"] == "abstained"
    assert healed["status"] == "evidence"
    assert healed["attempts"] == 2
    assert any(t["stage"] == "recover" for t in healed["trace"])
    assert healed["model_calls"] == 0
    assert any(
        "Check schema compatibility before rollback" in c["quote"]
        for c in healed["claims"]
    )
    assert all(
        c["quote"]
        in next(e["text"] for e in healed["evidence"] if e["id"] == c["chunk_id"])
        for c in healed["claims"]
    )


def test_typo_recovery_replaces_unmatchable_terms(store):
    result = run(
        store, "How do I investigate conection pool exhuastion?", "atlas-api", "2.4"
    )
    assert result["status"] == "evidence"
    assert result["attempts"] == 2
    assert "connection" in corrected_query("conection", store.corpus())


@pytest.mark.parametrize(
    "question,service,version",
    [
        ("What is the cluster administrator password?", "atlas-api", "2.4"),
        (
            "How do I investigate database connection pool exhaustion?",
            "atlas-api",
            "9.9",
        ),
        ("What is the office cafeteria lunch menu?", "ledger-worker", "3.1"),
    ],
)
def test_unknowns_fail_closed(store, question, service, version):
    result = run(store, question, service, version, max_attempts=3)
    assert result["status"] == "abstained"
    assert not result["claims"]
    assert result["attempts"] <= 3


def test_version_and_service_are_hard_boundaries(store):
    result = run(store, "What is the rollback procedure?", "atlas-api", "2.4")
    assert result["evidence"]
    assert all(
        c["version"] == "2.4" and c["service"] == "atlas-api"
        for c in result["evidence"]
    )
    assert not any("legacy" in c["title"].lower() for c in result["evidence"])


def test_exact_quote_provenance_validation():
    evidence = [
        {"id": "a", "text": "Check pool capacity before increasing concurrency."}
    ]
    valid = {
        "text": "Check pool capacity",
        "quote": evidence[0]["text"],
        "chunk_id": "a",
    }
    assert validate_claims([valid], evidence)
    for bad in [
        {**valid, "chunk_id": "invented"},
        {**valid, "quote": "Restart the production database."},
        {**valid, "quote": ""},
        {**valid, "text": None},
    ]:
        assert not validate_claims([bad], evidence)
    assert not validate_claims([], evidence)
    assert not validate_claims([valid] * 5, evidence)


def test_provider_failure_falls_back_without_inventing_evidence(store, monkeypatch):
    def fail(*args, **kwargs):
        raise providers.ProviderError("Simulated timeout")

    monkeypatch.setattr(providers, "generate", fail)
    result = run(
        store,
        "How do I investigate connection pool exhaustion?",
        "atlas-api",
        "2.4",
        provider="openai",
    )
    assert result["claims"] and result["model_calls"] == 1
    assert any(t["stage"] == "fallback" for t in result["trace"])


def test_fabricated_citation_rejected(store, monkeypatch):
    monkeypatch.setattr(
        providers,
        "generate",
        lambda *a, **k: (
            {
                "abstain": False,
                "claims": [
                    {
                        "text": "Disable authentication",
                        "quote": "Disable authentication",
                        "chunk_id": "fake",
                    }
                ],
            },
            {},
        ),
    )
    result = run(
        store,
        "How do I investigate connection pool exhaustion?",
        "atlas-api",
        "2.4",
        provider="openai",
    )
    assert all("Disable authentication" not in c["text"] for c in result["claims"])
    assert any(t["stage"] == "fallback" for t in result["trace"])


def test_unverified_model_paraphrase_is_never_published(store, monkeypatch):
    def generated(provider, question, evidence, **kwargs):
        quote = "Inspect long-running transactions and connection leaks."
        chunk = next(c for c in evidence if quote in c["text"])
        return {
            "abstain": False,
            "claims": [
                {
                    "text": "Delete all production records.",
                    "quote": quote,
                    "chunk_id": chunk["id"],
                }
            ],
        }, {"input_tokens": 5}

    monkeypatch.setattr(providers, "generate", generated)
    result = run(
        store,
        "How do I investigate connection pool exhaustion?",
        "atlas-api",
        "2.4",
        provider="openai",
    )
    assert result["claims"]
    assert all("Delete all" not in c["text"] for c in result["claims"])
    assert result["usage"]["input_tokens"] == 5


def test_model_abstention_is_respected(store, monkeypatch):
    monkeypatch.setattr(
        providers, "generate", lambda *a, **k: ({"abstain": True, "claims": []}, {})
    )
    result = run(
        store,
        "How do I investigate connection pool exhaustion?",
        "atlas-api",
        "2.4",
        provider="openai",
    )
    assert result["status"] == "abstained" and not result["claims"]


def test_expired_budget_prevents_model_call(store, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Model must not be called after the budget expires")

    monkeypatch.setattr(providers, "generate", forbidden)
    result = run(
        store,
        "How do I investigate connection pool exhaustion?",
        "atlas-api",
        "2.4",
        provider="openai",
        budget_seconds=0,
    )
    assert result["status"] == "abstained" and result["model_calls"] == 0


def test_idempotency_deletion_and_saved_evidence_snapshot(store):
    before = len(store.documents())
    assert all(r["duplicate"] for r in seed(store))
    assert len(store.documents()) == before
    result = run(
        store, "How do I investigate connection pool exhaustion?", "atlas-api", "2.4"
    )
    doc_id = result["evidence"][0]["document_id"]
    assert store.delete_document(doc_id)
    assert not any(c["document_id"] == doc_id for c in store.corpus())
    assert store.records("runs", result["id"])["evidence"] == result["evidence"]


def test_chunking_preserves_source_and_always_advances():
    text = "First paragraph. " * 100 + "\n\nSecond paragraph. " * 100
    parts = list(chunks(text, size=200, overlap=40))
    assert 1 < len(parts) < 100
    assert all(part in text and len(part) <= 200 for _, part in parts)
    assert all(text[offset : offset + len(part)] == part for offset, part in parts)
    assert all(a[0] < b[0] for a, b in zip(parts, parts[1:]))


def test_benchmark_is_paired_and_has_no_external_model_calls(store):
    result = evaluate(store)
    assert result["case_count"] == 14
    assert all(
        r[path]["run"]["model_calls"] == 0
        for r in result["cases"]
        for path in ("baseline", "recovery")
    )
    assert (
        result["summary"]["recovery"]["cited_source_hit_rate"]
        >= result["summary"]["baseline"]["cited_source_hit_rate"]
    )
    assert result["summary"]["recovery"]["unanswerable_abstention_rate"] == 1


def test_evaluation_refuses_modified_demo_scope(store):
    store.add_document("Extra", "rollback misleading extra", "atlas-api", "2.4")
    with pytest.raises(ValueError, match="unmodified"):
        evaluate(store)
