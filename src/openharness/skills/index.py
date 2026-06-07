"""BM25-based skill index for lightweight recall."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict
from typing import TYPE_CHECKING

from openharness.skills.types import SkillCandidate, SkillDefinition

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# BM25 parameters
_K1 = 1.5
_B = 0.75
AVG_DOC_LEN = 100

# Chinese tokenizer pattern
_CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff]+")


def _normalize_text(text: str) -> str:
    """Normalize text for matching: lowercase and normalize punctuation."""
    if not text:
        return ""
    # Normalize unicode characters
    text = unicodedata.normalize("NFKC", text)
    # Lowercase
    text = text.lower()
    # Normalize Chinese/English punctuation
    text = (
        text.replace("\uff0c", ",")
        .replace("\u3002", ".")
        .replace("\uff01", "!")
        .replace("\uff1f", "?")
        .replace("\uff1a", ":")
        .replace("\uff1b", ";")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\uff08", "(")
        .replace("\uff09", ")")
    )
    return text


def _tokenize(text: str) -> list[str]:
    """Simple tokenization: split on non-alphanumeric, keep Chinese characters as tokens."""
    if not text:
        return []
    # Extract Chinese character clusters
    chinese_tokens = _CHINESE_PATTERN.findall(text)
    # Extract English/alphanumeric tokens
    english_tokens = re.findall(r"[a-zA-Z0-9_]+", text)
    return chinese_tokens + english_tokens


def _skill_identifier_values(skill: SkillDefinition) -> set[str]:
    """Return normalized public identifiers for a skill."""
    values = (skill.name, skill.command_name, skill.display_name, *skill.aliases)
    return {_normalize_text(value) for value in values if value and _normalize_text(value)}


def _compute_avg_doc_len(documents: list[set[str]]) -> float:
    """Compute average document length for BM25."""
    if not documents:
        return AVG_DOC_LEN
    return sum(len(doc) for doc in documents) / len(documents)


class SkillIndex:
    """In-memory BM25 index for skill recall.

    Supports:
    - Exact/alias matching (case-insensitive, punctuation-normalized)
    - BM25 keyword-based recall
    - Permission filtering (excludes disable_model_invocation=true skills)
    """

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}
        self._name_to_key: dict[str, str] = {}  # normalized name -> skill key
        self._alias_to_key: dict[str, str] = {}  # normalized alias -> skill key
        self._inverted_index: dict[str, set[str]] = defaultdict(set)  # token -> skill keys
        self._doc_term_freqs: dict[str, dict[str, int]] = {}  # skill key -> {token: freq}
        self._doc_len: dict[str, int] = {}  # skill key -> term count
        self._avg_doc_len: float = AVG_DOC_LEN
        self._idf: dict[str, float] = {}  # token -> IDF score
        self._disabled_keys: set[str] = set()
        logger.debug("[skills] SkillIndex initialized")

    def build(
        self,
        skills: Sequence[SkillDefinition],
        *,
        debug_mode: bool = False,
    ) -> None:
        """Build the index from a list of skills."""
        logger.info("[skills] Building skill index from %d skills", len(skills))

        self._skills.clear()
        self._name_to_key.clear()
        self._alias_to_key.clear()
        self._inverted_index.clear()
        self._doc_term_freqs.clear()
        self._doc_len.clear()
        self._disabled_keys.clear()

        # Register all skills. Later skills with the same public identifier win,
        # matching SkillRegistry's overlay behavior for user/project/plugin skills.
        active_skills = self._resolve_overrides(skills)
        logger.debug("[skills] Resolved %d active skills after override resolution", len(active_skills))

        for skill in active_skills:
            key = self._register_skill(skill)
            if skill.disable_model_invocation:
                self._disabled_keys.add(key)
                logger.debug("[skills] Skill '%s' disabled for model invocation", skill.name)

        # Build inverted index and compute IDF
        all_docs: list[set[str]] = []
        for key in self._skills:
            doc_terms = set(self._get_skill_terms(key))
            all_docs.append(doc_terms)
            for term in doc_terms:
                self._inverted_index[term].add(key)

        # Compute IDF for all terms
        N = len(self._skills)
        doc_freqs: dict[str, int] = defaultdict(int)
        for doc_terms in all_docs:
            for term in doc_terms:
                doc_freqs[term] += 1

        self._idf = {}
        for term, df in doc_freqs.items():
            self._idf[term] = max(0.01, (N - df + 0.5) / (df + 0.5))

        self._avg_doc_len = _compute_avg_doc_len(all_docs)

        logger.info(
            "[skills] Built index with %d skills, %d unique terms, avg_doc_len=%.1f",
            N,
            len(self._idf),
            self._avg_doc_len,
        )

    def _resolve_overrides(self, skills: Sequence[SkillDefinition]) -> list[SkillDefinition]:
        """Drop skills superseded by later entries sharing any public identifier."""
        retained: list[SkillDefinition] = []
        identifiers_by_index: list[set[str]] = []
        owner_by_identifier: dict[str, int] = {}

        for skill in skills:
            identifiers = _skill_identifier_values(skill)
            superseded = {
                owner_by_identifier[identifier]
                for identifier in identifiers
                if identifier in owner_by_identifier
            }
            for index in superseded:
                identifiers_by_index[index].clear()
            retained.append(skill)
            identifiers_by_index.append(identifiers)
            current_index = len(retained) - 1
            for identifier in identifiers:
                owner_by_identifier[identifier] = current_index

        return [skill for skill, identifiers in zip(retained, identifiers_by_index) if identifiers]

    def _register_skill(self, skill: SkillDefinition) -> str:
        """Register a skill and return its key."""
        key = f"{skill.source}:{skill.name}"
        self._skills[key] = skill

        # Register name (case-insensitive)
        for name_field in (skill.name, skill.command_name, skill.display_name):
            if name_field:
                normalized = _normalize_text(name_field)
                if normalized:
                    self._name_to_key[normalized] = key

        # Register aliases
        for alias in skill.aliases:
            if alias:
                normalized = _normalize_text(alias)
                if normalized:
                    self._alias_to_key[normalized] = key

        logger.debug("[skills] Registered skill '%s' with key '%s'", skill.name, key)
        return key

    def _get_skill_terms(self, key: str) -> list[str]:
        """Get all searchable terms for a skill."""
        skill = self._skills.get(key)
        if not skill:
            return []

        terms: list[str] = []

        # Keywords / bm25_search_keywords
        for kw_list in (skill.keywords, skill.bm25_search_keywords):
            for kw in kw_list:
                terms.extend(_tokenize(_normalize_text(kw)))

        # Description
        if skill.description:
            terms.extend(_tokenize(_normalize_text(skill.description)))

        # Name and aliases
        for name_field in (skill.name, skill.command_name, skill.display_name):
            if name_field:
                terms.extend(_tokenize(_normalize_text(name_field)))
        for alias in skill.aliases:
            if alias:
                terms.extend(_tokenize(_normalize_text(alias)))

        return terms

    def _bm25_score(self, query_terms: list[str], key: str) -> float:
        """Compute BM25 score for a query against a skill."""
        if key in self._disabled_keys:
            return 0.0

        doc_tf = self._doc_term_freqs.get(key, {})
        doc_len = self._doc_len.get(key, 0)

        score = 0.0
        for term in query_terms:
            tf = doc_tf.get(term, 0)
            idf = self._idf.get(term, 0)
            if tf > 0 and idf > 0:
                numerator = tf * (_K1 + 1)
                denominator = tf + _K1 * (1 - _B + _B * doc_len / self._avg_doc_len)
                score += idf * numerator / denominator
        return score

    def _build_doc_stats(self) -> None:
        """Build document term frequencies and lengths for all skills."""
        self._doc_term_freqs.clear()
        self._doc_len.clear()

        for key in self._skills:
            terms = self._get_skill_terms(key)
            tf: dict[str, int] = defaultdict(int)
            for term in terms:
                tf[term] += 1
            self._doc_term_freqs[key] = dict(tf)
            self._doc_len[key] = len(terms)

    def recall(
        self,
        query: str,
        *,
        top_k: int = 10,
        exclude_names: set[str] | None = None,
    ) -> list[SkillCandidate]:
        """Recall top-K skill candidates for a query.

        Uses layered strategy:
        1. Exact/alias match (highest priority)
        2. BM25 keyword recall
        """
        logger.debug("[skills] Recall query: '%s', top_k=%d", query, top_k)

        self._build_doc_stats()

        exclude_names = self._resolve_exclude_keys(exclude_names or set())
        query_normalized = _normalize_text(query)
        query_terms = _tokenize(query_normalized)

        candidates: dict[str, SkillCandidate] = {}

        # Phase 1: Exact/alias matching
        # Check if query directly matches a skill name or alias
        if query_normalized in self._name_to_key:
            key = self._name_to_key[query_normalized]
            if key not in exclude_names and key not in self._disabled_keys:
                skill = self._skills[key]
                candidates[key] = SkillCandidate(
                    skill_name=skill.command_name or skill.name,
                    description=skill.trigger or skill.description,
                    trigger=skill.trigger,
                    negative_trigger=skill.negative_trigger,
                    source=skill.source,
                    trust_level=self._get_trust_level(skill),
                    score=100.0,
                    match_type="exact",
                )
                logger.debug("[skills] Found exact match: '%s'", skill.name)

        # Check aliases
        for term in query_terms:
            if term in self._alias_to_key:
                key = self._alias_to_key[term]
                if key not in exclude_names and key not in self._disabled_keys:
                    skill = self._skills[key]
                    if key not in candidates:
                        candidates[key] = SkillCandidate(
                            skill_name=skill.command_name or skill.name,
                            description=skill.trigger or skill.description,
                            trigger=skill.trigger,
                            negative_trigger=skill.negative_trigger,
                            source=skill.source,
                            trust_level=self._get_trust_level(skill),
                            score=90.0,
                            match_type="alias",
                        )
                        logger.debug("[skills] Found alias match: '%s' via '%s'", skill.name, term)

        # Also check direct command_name match (for slash commands like /skill-name)
        if query.startswith("/"):
            query_no_slash = query[1:].strip()
            query_normalized = _normalize_text(query_no_slash)
            if query_normalized in self._name_to_key:
                key = self._name_to_key[query_normalized]
                if key not in exclude_names and key not in self._disabled_keys:
                    skill = self._skills[key]
                    if key not in candidates:
                        candidates[key] = SkillCandidate(
                            skill_name=skill.command_name or skill.name,
                            description=skill.trigger or skill.description,
                            trigger=skill.trigger,
                            negative_trigger=skill.negative_trigger,
                            source=skill.source,
                            trust_level=self._get_trust_level(skill),
                            score=100.0,
                            match_type="exact",
                        )
                        logger.debug("[skills] Found slash command match: '%s'", skill.name)

        # Phase 2: BM25 keyword recall
        if query_terms:
            bm25_scores: list[tuple[str, float]] = []
            for key in self._skills:
                if key in candidates or key in exclude_names or key in self._disabled_keys:
                    continue
                score = self._bm25_score(query_terms, key)
                if score > 0:
                    bm25_scores.append((key, score))

            # Sort by score descending
            bm25_scores.sort(key=lambda x: x[1], reverse=True)

            # Take top BM25 candidates
            for key, score in bm25_scores[:top_k]:
                skill = self._skills[key]
                candidates[key] = SkillCandidate(
                    skill_name=skill.command_name or skill.name,
                    description=skill.trigger or skill.description,
                    trigger=skill.trigger,
                    negative_trigger=skill.negative_trigger,
                    source=skill.source,
                    trust_level=self._get_trust_level(skill),
                    score=score,
                    match_type="bm25",
                )
                logger.debug("[skills] Found BM25 match: '%s' (score=%.2f)", skill.name, score)

        # Sort all candidates by score descending
        result = sorted(candidates.values(), key=lambda c: c.score, reverse=True)[:top_k]

        logger.info(
            "[skills] Recall completed: query='%s', found %d candidates, returning %d results",
            query,
            len(candidates),
            len(result),
        )

        return result

    def _get_trust_level(self, skill: SkillDefinition) -> str:
        """Get trust level based on skill source."""
        if skill.source == "bundled":
            return "high"
        elif skill.source == "user":
            return "medium"
        elif skill.source == "project":
            return "low"
        elif skill.source == "plugin":
            return "low"
        return "medium"

    def _resolve_exclude_keys(self, exclude_names: set[str]) -> set[str]:
        """Convert public skill names from tool input into internal index keys."""
        excluded: set[str] = set()
        normalized_names = {
            _normalize_text(name)
            for name in exclude_names
            if _normalize_text(name)
        }
        for name in normalized_names:
            key = self._name_to_key.get(name) or self._alias_to_key.get(name)
            if key:
                excluded.add(key)
        for key, skill in self._skills.items():
            if key in exclude_names or _skill_identifier_values(skill) & normalized_names:
                excluded.add(key)
        return excluded

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        exclude_names: set[str] | None = None,
    ) -> list[SkillCandidate]:
        """Secondary search for skill miss handling.

        Similar to recall but designed for expanding search when
        initial candidates are insufficient.
        """
        logger.debug("[skills] Search query: '%s', limit=%d", query, limit)
        return self.recall(query, top_k=limit, exclude_names=exclude_names)

    def get_skill(self, name: str) -> SkillDefinition | None:
        """Get a skill by name."""
        normalized = _normalize_text(name)
        key = self._name_to_key.get(normalized)
        if key:
            result = self._skills.get(key)
            if result:
                logger.debug("[skills] Retrieved skill '%s'", name)
            else:
                logger.debug("[skills] Skill '%s' not found in index", name)
            return result
        logger.debug("[skills] Skill '%s' not found (key not in index)", name)
        return None
