"""Inspectable lexical retrieval, not an embedding or semantic-search substitute."""

import math
import re
from collections import Counter
from difflib import get_close_matches

STOP = set(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "with",
        "from",
        "by",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "do",
        "does",
        "did",
        "how",
        "what",
        "when",
        "where",
        "why",
        "which",
        "who",
        "can",
        "could",
        "should",
        "would",
        "i",
        "we",
        "you",
        "my",
        "our",
        "it",
        "its",
        "this",
        "that",
        "as",
        "after",
        "before",
        "into",
        "get",
        "have",
        "has",
        "had",
        "me",
        "please",
        "tell",
        "show",
        "give",
        "about",
        "then",
        "than",
        "if",
        "during",
        "much",
        "many",
        "help",
        "check",
        "need",
        "steps",
        "resolve",
        "fix",
        "issue",
        "problem",
        "service",
        "system",
        "explain",
        "investigate",
    ]
)


def tokens(text):
    words = re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", text.lower())
    return [
        w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w
        for w in words
        if w not in STOP and len(w) > 1
    ]


def corrected_query(query, corpus):
    vocabulary = sorted(
        set(t for c in corpus for t in tokens(c["text"] + " " + c["aliases"]))
    )
    corrected = []
    for term in tokens(query):
        if len(term) >= 5 and term not in vocabulary:
            matches = get_close_matches(term, vocabulary, n=1, cutoff=0.84)
            corrected.append(matches[0] if matches else term)
        else:
            corrected.append(term)
    # Replace misspellings instead of keeping impossible original terms in coverage.
    revised = " ".join(corrected)
    return revised if corrected != tokens(query) else query


def search(corpus, query, k=3, include_aliases=False):
    if not corpus:
        return []
    terms = set(tokens(query))
    docs = [
        tokens(c["text"] + (" " + c["aliases"] if include_aliases else ""))
        for c in corpus
    ]
    frequencies = [Counter(d) for d in docs]
    avg = sum(map(len, docs)) / len(docs) or 1
    idf = {
        t: math.log(
            1
            + (len(docs) - sum(t in d for d in frequencies) + 0.5)
            / (sum(t in d for d in frequencies) + 0.5)
        )
        for t in terms
    }
    ranked = []
    for chunk, freq, doc in zip(corpus, frequencies, docs):
        score = sum(
            idf[t] * (freq[t] * 2.5) / (freq[t] + 1.5 * (0.25 + 0.75 * len(doc) / avg))
            for t in terms
            if freq[t]
        )
        if score > 0:
            content_terms = set(tokens(chunk["text"]))
            alias_terms = set(tokens(chunk["aliases"])) if include_aliases else set()
            matched = terms & (content_terms | alias_terms)
            ranked.append(
                {
                    **chunk,
                    "score": round(score, 4),
                    "matched_terms": sorted(matched),
                    "alias_matches": sorted((terms & alias_terms) - content_terms),
                }
            )
    return sorted(ranked, key=lambda c: (-c["score"], c["id"]))[:k]


def coverage(candidates, query):
    terms = set(tokens(query))
    matched = set(t for c in candidates for t in c["matched_terms"])
    # Query coverage is a lexical diagnostic, not calibrated confidence in truth.
    return round(len(terms & matched) / max(len(terms), 1), 3), sorted(terms - matched)


def excerpt(text, query, limit=950):
    parts = [
        p.strip()
        for p in re.split(r"\n\s*\n", text)
        if p.strip() and not p.lstrip().startswith("#")
    ]
    if not parts:
        parts = [text]
    terms = set(tokens(query))
    best = max(
        parts,
        key=lambda p: (
            sum(min(3, n) for t, n in Counter(tokens(p)).items() if t in terms),
            -len(p),
        ),
    )
    start = text.find(best)
    # Include adjacent context rather than returning an isolated matching sentence.
    end = min(len(text), start + limit)
    if end < len(text):
        boundary = text.rfind("\n\n", start + len(best), end)
        if boundary > start:
            end = boundary
    return text[start:end].rstrip()
