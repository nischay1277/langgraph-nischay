import hashlib
import json
import statistics
import uuid
from pathlib import Path

from .engine import run
from .store import now

DEMO = Path(__file__).parent / "demo"


def seed(store):
    docs = json.loads((DEMO / "corpus.json").read_text(encoding="utf-8"))
    return [store.add_document(**d) for d in docs]


def evaluate(store):
    """Fixed synthetic development fixtures, not an independent production benchmark."""
    docs = json.loads((DEMO / "corpus.json").read_text(encoding="utf-8"))
    with store.connect() as db:
        for d in docs:
            digest = hashlib.sha256(d["text"].encode()).hexdigest()
            if not db.execute(
                "SELECT id FROM documents WHERE hash=? AND service=? AND version=?",
                (digest, d["service"], d["version"]),
            ).fetchone():
                raise ValueError(
                    "Load the complete bundled demo corpus before evaluating."
                )
        # Extra docs in the same scope would change the meaning of this fixed benchmark.
        for service, version in {(d["service"], d["version"]) for d in docs}:
            expected = sum(
                d["service"] == service and d["version"] == version for d in docs
            )
            if (
                db.execute(
                    "SELECT count(*) FROM documents WHERE service=? AND version=?",
                    (service, version),
                ).fetchone()[0]
                != expected
            ):
                raise ValueError(
                    "Demo evaluation requires an unmodified demo scope. Remove extra documents from these service/version pairs or use another workspace."
                )
    cases = json.loads((DEMO / "cases.json").read_text(encoding="utf-8"))
    rows = []
    for case in cases:
        row = {**case}
        for name, recovery in [("baseline", False), ("recovery", True)]:
            result = run(
                store,
                case["question"],
                case["service"],
                case["version"],
                recovery=recovery,
                persist=False,
            )
            retrieved = {c["title"] for c in result["evidence"]}
            expected = set(case["expected_titles"])
            cited = {
                c["title"]
                for c in result["evidence"]
                if any(claim["chunk_id"] == c["id"] for claim in result["claims"])
            }
            row[name] = {
                "source_recall": len(expected & retrieved) / len(expected)
                if expected
                else None,
                "cited_source_hit": expected <= cited if expected else None,
                "outcome_correct": bool(result["claims"]) == case["answerable"],
                "abstained": result["status"] == "abstained",
                "attempts": result["attempts"],
                "latency_ms": result["latency_ms"],
                "status": result["status"],
                "trace": result["trace"],
                "run": result,
            }
        rows.append(row)
    summary = {}
    for name in ("baseline", "recovery"):
        values = [r[name] for r in rows]
        answerable = [r[name] for r in rows if r["answerable"]]
        negative = [r[name] for r in rows if not r["answerable"]]
        summary[name] = {
            "source_recall": statistics.mean(v["source_recall"] for v in answerable),
            "cited_source_hit_rate": statistics.mean(
                v["cited_source_hit"] for v in answerable
            ),
            "outcome_accuracy": statistics.mean(v["outcome_correct"] for v in values),
            "unanswerable_abstention_rate": statistics.mean(
                v["abstained"] for v in negative
            ),
            "median_latency_ms": statistics.median(v["latency_ms"] for v in values),
        }
    result = {
        "id": uuid.uuid4().hex,
        "created_at": now(),
        "case_count": len(cases),
        "summary": summary,
        "cases": rows,
        "scope": "Synthetic development fixtures; lexical retrieval and extractive answers. No diagnosis or semantic correctness score.",
        "corpus": [
            {
                "title": d["title"],
                "sha256": hashlib.sha256(d["text"].encode()).hexdigest(),
            }
            for d in docs
        ],
    }
    store.save("evaluations", result)
    return result
