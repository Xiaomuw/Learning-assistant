from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


TAXONOMY_DIR = Path(__file__).resolve().parent / "taxonomy"
CONCEPT_CONFIDENCE_THRESHOLD = 0.70
SUBJECT_CONFIDENCE_THRESHOLD = 0.55


Importance = Literal["low", "medium", "high"]
ExamFrequency = Literal["low", "medium", "high"]
MatchStatus = Literal["matched", "subject_only", "ambiguous", "unmapped"]


class ConceptNode(BaseModel):
    subject_id: str
    subject_name: str
    chapter_id: str
    chapter_name: str
    topic_id: str
    topic_name: str
    concept_id: str
    concept_name: str
    aliases: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    importance: Importance = "medium"
    exam_frequency: ExamFrequency = "medium"
    question_types: list[str] = Field(default_factory=list)

    def metadata(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "subject_name": self.subject_name,
            "chapter_id": self.chapter_id,
            "chapter_name": self.chapter_name,
            "topic_id": self.topic_id,
            "topic_name": self.topic_name,
            "concept_id": self.concept_id,
            "concept_name": self.concept_name,
        }


class ConceptMatch(BaseModel):
    subject_id: str | None = None
    subject_name: str | None = None
    chapter_id: str | None = None
    topic_id: str | None = None
    concept_id: str | None = None
    concept_name: str | None = None
    confidence: float = 0.0
    status: MatchStatus = "unmapped"
    candidates: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def is_mapped(self) -> bool:
        return self.status == "matched" and bool(self.concept_id)


class _ScoredConcept(BaseModel):
    node: ConceptNode
    score: float
    matched_terms: list[str] = Field(default_factory=list)

    def as_candidate(self) -> dict[str, Any]:
        return {
            **self.node.metadata(),
            "confidence": round(float(self.score), 4),
            "matched_terms": list(self.matched_terms),
        }


class ConceptRegistry:
    """In-memory taxonomy registry for deterministic subject/topic/concept linking."""

    def __init__(self, taxonomy_dir: Path | None = None) -> None:
        self.taxonomy_dir = taxonomy_dir or TAXONOMY_DIR
        self.subjects: dict[str, dict[str, Any]] = {}
        self.concepts: dict[str, ConceptNode] = {}
        self._subject_terms: dict[str, list[str]] = {}
        self._concept_terms: dict[str, list[tuple[str, str]]] = {}
        self._load_taxonomies()

    def _load_taxonomies(self) -> None:
        for path in sorted(self.taxonomy_dir.glob("*.yaml")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            subject_id = _clean_id(payload.get("subject_id"))
            subject_name = str(payload.get("subject_name") or subject_id).strip()
            if not subject_id:
                continue
            self.subjects[subject_id] = {
                "subject_id": subject_id,
                "subject_name": subject_name,
                "source_file": str(path),
            }
            self._subject_terms[subject_id] = _dedupe_terms(
                [
                    subject_id,
                    subject_name,
                    *SUBJECT_ALIASES.get(subject_id, []),
                ]
            )
            for chapter in list(payload.get("chapters") or []):
                chapter_id = _clean_id(chapter.get("chapter_id"))
                chapter_name = str(chapter.get("chapter_name") or chapter_id).strip()
                for topic in list(chapter.get("topics") or []):
                    topic_id = _clean_id(topic.get("topic_id"))
                    topic_name = str(topic.get("topic_name") or topic_id).strip()
                    for concept in list(topic.get("concepts") or []):
                        concept_id = _clean_id(concept.get("concept_id"))
                        concept_name = str(concept.get("concept_name") or concept_id).strip()
                        if not concept_id or not concept_name:
                            continue
                        node = ConceptNode(
                            subject_id=subject_id,
                            subject_name=subject_name,
                            chapter_id=chapter_id,
                            chapter_name=chapter_name,
                            topic_id=topic_id,
                            topic_name=topic_name,
                            concept_id=concept_id,
                            concept_name=concept_name,
                            aliases=[
                                str(alias).strip()
                                for alias in list(concept.get("aliases") or [])
                                if str(alias).strip()
                            ],
                            prerequisites=[
                                _clean_id(item)
                                for item in list(concept.get("prerequisites") or [])
                                if _clean_id(item)
                            ],
                            importance=_importance(concept.get("importance")),
                            exam_frequency=_exam_frequency(concept.get("exam_frequency")),
                            question_types=[
                                str(item).strip()
                                for item in list(concept.get("question_types") or [])
                                if str(item).strip()
                            ],
                        )
                        self.concepts[node.concept_id] = node
                        self._concept_terms[node.concept_id] = self._terms_for_node(node)

    def _terms_for_node(self, node: ConceptNode) -> list[tuple[str, str]]:
        terms: list[tuple[str, str]] = []
        for term in _dedupe_terms([node.concept_name, *node.aliases]):
            terms.append((term, "concept"))
        for term in _dedupe_terms([node.topic_name, node.chapter_name]):
            terms.append((term, "topic"))
        for term in _dedupe_terms([node.subject_name, *self._subject_terms.get(node.subject_id, [])]):
            terms.append((term, "subject"))
        for term in _id_terms(node.concept_id):
            terms.append((term, "id"))
        return terms

    def get_concept(self, concept_id: str | None) -> ConceptNode | None:
        return self.concepts.get(_clean_id(concept_id))

    def list_candidates(self, *, subject_id: str | None = None, limit: int = 50) -> list[ConceptNode]:
        nodes = [
            node
            for node in self.concepts.values()
            if not subject_id or node.subject_id == subject_id
        ]
        return sorted(nodes, key=lambda item: item.concept_id)[: max(1, int(limit or 50))]

    def match_query(
        self,
        query: str,
        *,
        subject_id: str | None = None,
        top_k: int = 5,
    ) -> ConceptMatch:
        return self._match_text(
            query,
            subject_id=subject_id,
            strict_subject=False,
            top_k=top_k,
        )

    def match_chunk(
        self,
        text: str,
        *,
        subject_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        top_k: int = 5,
    ) -> ConceptMatch:
        metadata = dict(metadata or {})
        metadata_text = " ".join(
            str(metadata.get(key) or "")
            for key in (
                "subject_name",
                "chapter_name",
                "chapter",
                "topic_name",
                "topic",
                "concept_name",
                "knowledge_point",
                "source",
                "source_file",
            )
        )
        strict_subject = _clean_id(subject_id) in self.subjects
        return self._match_text(
            f"{metadata_text}\n{text}",
            subject_id=subject_id,
            strict_subject=strict_subject,
            top_k=top_k,
        )

    def _match_text(
        self,
        text: str,
        *,
        subject_id: str | None,
        strict_subject: bool,
        top_k: int,
    ) -> ConceptMatch:
        raw_text = str(text or "")
        normalized_text = _normalize_text(raw_text)
        if not normalized_text:
            return ConceptMatch(status="unmapped")

        subject_hint = _clean_id(subject_id)
        scored: list[_ScoredConcept] = []
        for node in self.concepts.values():
            if strict_subject and subject_hint and node.subject_id != subject_hint:
                continue
            score, matched_terms = self._score_node(node, raw_text, normalized_text, subject_hint)
            if score > 0:
                scored.append(_ScoredConcept(node=node, score=score, matched_terms=matched_terms))

        scored.sort(key=lambda item: (item.score, _importance_rank(item.node.importance), _frequency_rank(item.node.exam_frequency)), reverse=True)
        candidates = [item.as_candidate() for item in scored[: max(1, int(top_k or 5))]]

        if scored:
            top = scored[0]
            if top.score >= CONCEPT_CONFIDENCE_THRESHOLD:
                if len(scored) > 1 and scored[1].score >= CONCEPT_CONFIDENCE_THRESHOLD and top.score - scored[1].score <= 0.04:
                    return ConceptMatch(
                        subject_id=top.node.subject_id,
                        subject_name=top.node.subject_name,
                        confidence=round(float(top.score), 4),
                        status="ambiguous",
                        candidates=candidates,
                    )
                return ConceptMatch(
                    subject_id=top.node.subject_id,
                    subject_name=top.node.subject_name,
                    chapter_id=top.node.chapter_id,
                    topic_id=top.node.topic_id,
                    concept_id=top.node.concept_id,
                    concept_name=top.node.concept_name,
                    confidence=round(float(top.score), 4),
                    status="matched",
                    candidates=candidates,
                )

        subject_match = self._match_subject(raw_text, normalized_text, subject_hint)
        if subject_match[0] >= SUBJECT_CONFIDENCE_THRESHOLD:
            matched_subject = self.subjects[subject_match[1]]
            return ConceptMatch(
                subject_id=matched_subject["subject_id"],
                subject_name=matched_subject["subject_name"],
                confidence=round(float(subject_match[0]), 4),
                status="subject_only",
                candidates=candidates,
            )

        return ConceptMatch(
            subject_id=subject_hint if subject_hint in self.subjects else None,
            subject_name=self.subjects.get(subject_hint, {}).get("subject_name"),
            confidence=round(float(scored[0].score), 4) if scored else 0.0,
            status="unmapped",
            candidates=candidates,
        )

    def _score_node(
        self,
        node: ConceptNode,
        raw_text: str,
        normalized_text: str,
        subject_hint: str,
    ) -> tuple[float, list[str]]:
        score = 0.0
        matched_terms: list[str] = []
        for term, term_type in self._concept_terms.get(node.concept_id, []):
            if not _contains_term(raw_text, normalized_text, term):
                continue
            matched_terms.append(term)
            normalized_term = _normalize_text(term)
            length_bonus = min(0.18, len(normalized_term) / 60)
            if term_type == "concept":
                score = max(score, 0.76 + length_bonus)
            elif term_type == "topic":
                score = max(score, 0.50 + length_bonus)
            elif term_type == "subject":
                score = max(score, 0.35 + length_bonus)
            else:
                score = max(score, 0.42 + length_bonus)

        if subject_hint and node.subject_id == subject_hint and score > 0:
            score = min(1.0, score + 0.05)
        if node.importance == "high" and score >= 0.65:
            score = min(1.0, score + 0.02)
        if node.exam_frequency == "high" and score >= 0.65:
            score = min(1.0, score + 0.02)
        return round(score, 4), _dedupe_terms(matched_terms)

    def _match_subject(self, raw_text: str, normalized_text: str, subject_hint: str) -> tuple[float, str]:
        best_score = 0.0
        best_subject = subject_hint if subject_hint in self.subjects else ""
        for current_subject_id, terms in self._subject_terms.items():
            score = 0.0
            for term in terms:
                if _contains_term(raw_text, normalized_text, term):
                    score = max(score, 0.68 if current_subject_id != subject_hint else 0.74)
            if subject_hint == current_subject_id:
                score = max(score, 0.58)
            if score > best_score:
                best_score = score
                best_subject = current_subject_id
        return best_score, best_subject


SUBJECT_ALIASES: dict[str, list[str]] = {
    "data-structure": ["数据结构", "算法", "DSA", "408 数据结构"],
    "computer-network": ["计算机网络", "计网", "网络", "408 网络"],
    "operating-system": ["操作系统", "OS", "计操", "408 操作系统"],
    "computer-organization": ["计算机组成", "计算机组成原理", "计组", "组成原理", "408 组成原理"],
}


def _clean_id(value: Any) -> str:
    return str(value or "").strip()


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[\s\-_./:：,，。;；、()（）\[\]【】{}<>《》\"'“”‘’!?！？]+", "", normalized)


def _contains_term(raw_text: str, normalized_text: str, term: str) -> bool:
    normalized_term = _normalize_text(term)
    if not normalized_term:
        return False
    if _is_ascii_term(term):
        pattern = rf"(?<![a-zA-Z0-9_+#.-]){re.escape(str(term).lower())}(?![a-zA-Z0-9_+#.-])"
        return re.search(pattern, raw_text.lower()) is not None
    return normalized_term in normalized_text


def _is_ascii_term(term: str) -> bool:
    value = str(term or "").strip()
    return bool(value) and all(ord(char) < 128 for char in value)


def _dedupe_terms(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = str(raw_value or "").strip()
        key = _normalize_text(value)
        if not value or not key or key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _id_terms(concept_id: str) -> list[str]:
    ignored = {"data", "structure", "computer", "network", "operating", "system", "organization"}
    terms = [
        token
        for token in re.split(r"[.\-_]+", concept_id)
        if len(token) >= 3 and token not in ignored
    ]
    return _dedupe_terms(terms)


def _importance(value: Any) -> Importance:
    raw = str(value or "medium").strip().lower()
    return raw if raw in {"low", "medium", "high"} else "medium"  # type: ignore[return-value]


def _exam_frequency(value: Any) -> ExamFrequency:
    raw = str(value or "medium").strip().lower()
    return raw if raw in {"low", "medium", "high"} else "medium"  # type: ignore[return-value]


def _importance_rank(value: Importance) -> int:
    return {"low": 0, "medium": 1, "high": 2}[value]


def _frequency_rank(value: ExamFrequency) -> int:
    return {"low": 0, "medium": 1, "high": 2}[value]


@lru_cache(maxsize=1)
def get_concept_registry() -> ConceptRegistry:
    return ConceptRegistry()
