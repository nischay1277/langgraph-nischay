"""Bounded LangGraph workflow. Recovery repairs retrieval, never the user's servers."""

import time
import uuid
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from . import providers
from .retrieval import corrected_query, coverage, excerpt, search
from .store import now


class State(TypedDict, total=False):
    question: str
    query: str
    corpus: list
    candidates: list
    trace: list
    attempt: int
    max_attempts: int
    recovery: bool
    aliases: bool
    k: int
    threshold: float
    sufficient: bool
    provider: str
    claims: list
    status: str
    reason: str
    model_calls: int
    usage: dict
    deadline: float
    started: float
    budget_seconds: float


def event(s, stage, message, **details):
    s["trace"].append(
        {
            "stage": stage,
            "message": message,
            "elapsed_ms": round((time.perf_counter() - s["started"]) * 1000, 2),
            "attempt": s["attempt"],
            **details,
        }
    )


def retrieve(s):
    s["attempt"] += 1
    s["candidates"] = search(s["corpus"], s["query"], s["k"], s["aliases"])
    event(
        s,
        "retrieve",
        f"Retrieved {len(s['candidates'])} passages",
        query=s["query"],
        aliases=s["aliases"],
        k=s["k"],
        chunk_ids=[c["id"] for c in s["candidates"]],
    )
    return s


def assess(s):
    value, missing = coverage(s["candidates"], s["query"])
    s["sufficient"] = bool(s["candidates"]) and value >= s["threshold"]
    event(
        s,
        "assess",
        "Lexical coverage passed"
        if s["sufficient"]
        else "Evidence coverage is incomplete",
        coverage=value,
        missing_terms=missing,
        threshold=s["threshold"],
    )
    return s


def route(s):
    if s["sufficient"]:
        return "answer"
    if (
        s["recovery"]
        and s["attempt"] < s["max_attempts"]
        and time.perf_counter() < s["deadline"]
    ):
        return "recover"
    return "abstain"


def recover(s):
    s["aliases"] = True
    s["k"] = min(8, s["k"] + 2)
    revised = corrected_query(s["query"], s["corpus"])
    if revised != s["query"]:
        event(
            s,
            "recover",
            "Expanded spelling variants; enabled runbook aliases and wider retrieval",
            previous_query=s["query"],
            next_query=revised,
        )
        s["query"] = revised
    elif s["attempt"] > 1:
        # No repeat of an identical retrieval with no plausible new evidence.
        s["max_attempts"] = s["attempt"] + 1
        event(
            s,
            "recover",
            "Final wider retrieval; no additional spelling correction found",
        )
    else:
        event(
            s,
            "recover",
            "Enabled runbook search aliases and widened candidate retrieval",
        )
    return s


def extractive_claims(s):
    selected = []
    seen = set()
    for c in s["candidates"]:
        if c["document_id"] in seen:
            continue
        topic = c["title"].split("·")[-1]
        quote = excerpt(c["text"], s["query"] + " " + topic)
        selected.append({"text": quote, "chunk_id": c["id"], "quote": quote})
        seen.add(c["document_id"])
        if len(selected) == 3:
            break
    return selected


def validate_claims(claims, candidates):
    """Verifies exact quote provenance. Does not establish semantic entailment."""
    allowed = {c["id"]: c["text"] for c in candidates}
    if not isinstance(claims, list) or not 1 <= len(claims) <= 4:
        return False
    for claim in claims:
        if not isinstance(claim, dict):
            return False
        text, quote, cid = claim.get("text"), claim.get("quote"), claim.get("chunk_id")
        if not all(isinstance(v, str) for v in (text, quote, cid)):
            return False
        if (
            cid not in allowed
            or not text.strip()
            or len(text) > 2000
            or len(quote.strip()) < 12
        ):
            return False
        if quote not in allowed[cid]:
            return False
    return True


def answer(s):
    if time.perf_counter() >= s["deadline"]:
        s["claims"] = []
        s["status"] = "abstained"
        s["reason"] = "The run exhausted its time budget before answer selection."
        event(s, "budget", s["reason"])
        return s
    s["status"] = "evidence"
    s["reason"] = (
        "Relevant excerpts found; review these checks against the actual incident."
    )
    if s["provider"] == "extractive":
        s["claims"] = extractive_claims(s)
        event(s, "answer", "Selected verbatim runbook excerpts; no model called")
        return s
    s["model_calls"] += 1
    try:
        result, usage = providers.generate(
            s["provider"],
            s["question"],
            s["candidates"],
            timeout=max(0.1, min(20, s["deadline"] - time.perf_counter())),
        )
        s["usage"] = usage
        if time.perf_counter() >= s["deadline"]:
            raise providers.ProviderError(
                "Model response arrived after the run time budget."
            )
        if result["abstain"]:
            s["claims"] = []
            s["status"] = "abstained"
            s["reason"] = "The model found insufficient evidence for this incident."
            event(s, "answer", s["reason"])
        elif validate_claims(result["claims"], s["candidates"]):
            # Publish only the proven quotes, not unverified generated paraphrases.
            s["claims"] = [
                {"text": c["quote"], "quote": c["quote"], "chunk_id": c["chunk_id"]}
                for c in result["claims"]
            ]
            event(
                s,
                "answer",
                "Model selected evidence; unverified paraphrases were discarded",
            )
        else:
            raise providers.ProviderError(
                "Model citations failed exact-quote validation."
            )
    except providers.ProviderError as exc:
        s["claims"] = extractive_claims(s)
        s["reason"] = "Model selection failed; showing local evidence instead."
        event(s, "fallback", str(exc))
    return s


def abstain(s):
    s["claims"] = []
    s["status"] = "abstained"
    s["reason"] = (
        "Insufficient matching evidence for this service/version. Add the relevant runbook or give a more specific symptom."
    )
    event(s, "abstain", s["reason"])
    return s


def verify(s):
    valid = validate_claims(s["claims"], s["candidates"]) if s["claims"] else False
    if s["claims"] and not valid:
        s["claims"] = []
        s["status"] = "abstained"
        s["reason"] = "Evidence failed provenance validation."
    event(
        s,
        "verify",
        "All displayed quotes match retrieved sources"
        if valid
        else "No answer published",
        citation_validity=valid if s["claims"] else None,
    )
    return s


def graph():
    g = StateGraph(State)
    for name, node in [
        ("retrieve", retrieve),
        ("assess", assess),
        ("recover", recover),
        ("answer", answer),
        ("abstain", abstain),
        ("verify", verify),
    ]:
        g.add_node(name, node)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "assess")
    g.add_conditional_edges("assess", route)
    g.add_edge("recover", "retrieve")
    g.add_edge("answer", "verify")
    g.add_edge("abstain", "verify")
    g.add_edge("verify", END)
    return g.compile()


GRAPH = graph()


def run(
    store,
    question,
    service,
    version,
    recovery=True,
    provider="extractive",
    max_attempts=2,
    budget_seconds=30,
    persist=True,
):
    started = time.perf_counter()
    corpus = store.corpus(service, version)
    state = GRAPH.invoke(
        {
            "question": question,
            "query": question,
            "corpus": corpus,
            "trace": [],
            "attempt": 0,
            "max_attempts": max(1, min(3, max_attempts)),
            "recovery": recovery,
            "aliases": False,
            "k": 3,
            "threshold": 0.6,
            "provider": provider,
            "claims": [],
            "model_calls": 0,
            "usage": {},
            "deadline": started + budget_seconds,
            "started": started,
            "budget_seconds": budget_seconds,
        },
        {"recursion_limit": 24},
    )
    result = {
        "id": uuid.uuid4().hex,
        "created_at": now(),
        "question": question,
        "service": service,
        "version": version,
        "recovery": recovery,
        "provider": provider,
        "status": state["status"],
        "reason": state["reason"],
        "claims": state["claims"],
        "evidence": state["candidates"],
        "trace": state["trace"],
        "attempts": state["attempt"],
        "model_calls": state["model_calls"],
        "usage": state["usage"],
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "config": {
            "max_attempts": max_attempts,
            "coverage_threshold": 0.6,
            "budget_seconds": budget_seconds,
            "retriever": "BM25 + optional metadata aliases",
        },
        "corpus_fingerprint": sorted(set(c["document_id"] for c in corpus)),
    }
    if persist:
        store.save("runs", result)
    return result
