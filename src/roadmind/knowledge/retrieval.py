from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from roadmind.domain.models import Brand, EvidenceRef
from roadmind.knowledge.corpus import DOCUMENTS, FAULT_GRAPH


def _tokens(text: str) -> list[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    latin = re.findall(r"[a-z0-9_-]+", normalized)
    han = re.findall(r"[\u4e00-\u9fff]", normalized)
    bigrams = ["".join(han[index : index + 2]) for index in range(max(0, len(han) - 1))]
    return latin + han + bigrams


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    dot = sum(value * right.get(key, 0) for key, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


@dataclass
class SearchHit:
    document: dict[str, Any]
    bm25_rank: int | None = None
    vector_rank: int | None = None
    graph_rank: int | None = None
    rrf_score: float = 0.0
    rerank_score: float = 0.0


class HybridRetriever:
    """BM25-like lexical + vector similarity + structured filter + graph expansion + RRF."""

    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents = documents or DOCUMENTS

    def search(
        self,
        *,
        query: str,
        brand: Brand,
        model: str,
        dtc_codes: list[str],
        limit: int = 4,
    ) -> list[EvidenceRef]:
        candidates = [
            document
            for document in self.documents
            if document["brand"] == brand
            and (document["model"] is None or document["model"] == model)
        ]
        if not candidates:
            return []

        query_tokens = Counter(_tokens(query + " " + " ".join(dtc_codes)))
        lexical = sorted(
            candidates,
            key=lambda item: self._lexical_score(query_tokens, item),
            reverse=True,
        )
        vector = sorted(
            candidates,
            key=lambda item: _cosine(query_tokens, Counter(_tokens(item["text"]))),
            reverse=True,
        )
        graph_terms = {term for code in dtc_codes for term in FAULT_GRAPH.get(code.upper(), [])}
        graph = sorted(
            candidates,
            key=lambda item: sum(term in item["text"] for term in graph_terms),
            reverse=True,
        )

        hits = {item["evidence_id"]: SearchHit(document=item) for item in candidates}
        for rank, item in enumerate(lexical, start=1):
            hits[item["evidence_id"]].bm25_rank = rank
        for rank, item in enumerate(vector, start=1):
            hits[item["evidence_id"]].vector_rank = rank
        for rank, item in enumerate(graph, start=1):
            hits[item["evidence_id"]].graph_rank = rank

        for hit in hits.values():
            ranks = [hit.bm25_rank, hit.vector_rank, hit.graph_rank]
            hit.rrf_score = sum(1 / (60 + rank) for rank in ranks if rank is not None)
            dtc_match = sum(code.upper() in hit.document["dtc"] for code in dtc_codes)
            source_bonus = 0.04 if hit.document["source_type"] in {"FIM", "SOP"} else 0.01
            model_bonus = 0.03 if hit.document["model"] == model else 0.0
            hit.rerank_score = hit.rrf_score + 0.08 * dtc_match + source_bonus + model_bonus

        ranked = sorted(hits.values(), key=lambda hit: hit.rerank_score, reverse=True)[:limit]
        max_score = max((hit.rerank_score for hit in ranked), default=1.0)
        return [
            EvidenceRef(
                evidence_id=hit.document["evidence_id"],
                source_type=hit.document["source_type"],
                title=hit.document["title"],
                section=hit.document["section"],
                brand=hit.document["brand"],
                model=hit.document["model"],
                version=hit.document["version"],
                score=round(hit.rerank_score / max_score, 4),
                excerpt=hit.document["text"],
            )
            for hit in ranked
        ]

    @staticmethod
    def _lexical_score(query: Counter[str], document: dict[str, Any]) -> float:
        body = Counter(_tokens(document["title"] + document["section"] + document["text"]))
        return sum(min(count, body.get(token, 0)) for token, count in query.items())
