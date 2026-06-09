"""Experience storage and retrieval, backed by durable memory system."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from openharness.introspection.config import IntrospectionConfig
from openharness.introspection.types import ExperienceQuery, ExperienceRecord
from openharness.utils.fs import atomic_write_text

log = logging.getLogger("openharness.introspection.experience_store")


class ExperienceStore:
    """Store and retrieve experience records, backed by durable memory."""

    def __init__(self, cwd: str | Path, config: IntrospectionConfig) -> None:
        self._cwd = str(Path(cwd).resolve())
        self._config = config

    def save_experience(self, experience: ExperienceRecord) -> Path | None:
        """Save an experience record to durable memory.

        Returns the memory file path if written, None otherwise.
        """
        try:
            from openharness.memory.manager import add_memory_entry

            lesson_text = "\n".join(experience.lessons)
            if not lesson_text.strip():
                return None

            tags = ["introspection", experience.source_kind, experience.task_type]
            if experience.outcome == "failure":
                tags.append("failure_pattern")
            elif experience.outcome == "success":
                tags.append("success_pattern")

            path = add_memory_entry(
                cwd=self._cwd,
                title=f"Experience: {experience.task_type}",
                content=lesson_text,
                memory_type="feedback",
                scope="project",
                description=lesson_text[:100],
                tags=tuple(tags),
            )
            self._mark_as_introspection_memory(path, experience)
            log.info("Saved experience to memory: %s", path)
            return path
        except Exception as exc:
            log.warning("Failed to save experience: %s", exc)
            return None

    def _mark_as_introspection_memory(self, path: Path, experience: ExperienceRecord) -> None:
        """Patch memory frontmatter with introspection-specific metadata."""
        from openharness.memory.schema import render_memory_file, split_memory_file

        metadata, body, _, _ = split_memory_file(path.read_text(encoding="utf-8"))
        metadata["category"] = "introspection"
        metadata["source"] = experience.source_kind
        metadata["introspection_task_type"] = experience.task_type
        metadata["introspection_outcome"] = experience.outcome
        metadata["introspection_confidence"] = experience.confidence
        tags = list(metadata.get("tags") or [])
        metadata["tags"] = list(dict.fromkeys([*tags, "introspection", experience.source_kind, experience.task_type]))
        atomic_write_text(path, render_memory_file(metadata, body))

    def retrieve_experiences(
        self,
        query: ExperienceQuery,
    ) -> list[ExperienceRecord]:
        """Retrieve relevant experiences from durable memory.

        V1 implementation: reads memory files with introspection tags
        and scores them by relevance.
        """
        try:
            from openharness.memory.scan import scan_memory_files
            from openharness.memory.schema import split_memory_file

            headers = scan_memory_files(
                self._cwd,
                max_files=None,
                include_disabled=False,
                include_expired=False,
            )

            candidates: list[tuple[ExperienceRecord, float]] = []
            for header in headers:
                # Only consider introspection-tagged memories
                tags = getattr(header, "tags", [])
                if "introspection" not in tags:
                    continue

                try:
                    content = header.path.read_text(encoding="utf-8")
                    metadata, body, _, _ = split_memory_file(content)
                except Exception:
                    continue

                score = self._score_relevance(metadata, body, query)
                if score > 0:
                    record = self._header_to_record(header, metadata, body)
                    candidates.append((record, score))

            # Sort by score descending
            candidates.sort(key=lambda x: x[1], reverse=True)

            # Apply confidence filter and top-k
            results = []
            for record, score in candidates:
                if record.confidence < query.min_confidence:
                    continue
                results.append(record)
                if len(results) >= self._config.max_experience_top_k:
                    break

            log.info(
                "Retrieved %d experiences (from %d candidates)",
                len(results),
                len(candidates),
            )
            return results

        except Exception as exc:
            log.warning("Failed to retrieve experiences: %s", exc)
            return []

    def _score_relevance(
        self,
        metadata: dict[str, Any],
        body: str,
        query: ExperienceQuery,
    ) -> float:
        """Score an experience record's relevance to the query."""
        score = 0.0

        # Task type match
        task_type = str(metadata.get("introspection_task_type") or metadata.get("category") or "").lower()
        if query.task_type and query.task_type.lower() in task_type:
            score += 3.0

        # Tag matching
        tags = metadata.get("tags", [])
        if isinstance(tags, list):
            tag_set = {str(t).lower() for t in tags}
            if query.task_type and query.task_type.lower() in tag_set:
                score += 2.0
            for tool in query.tools:
                if tool.lower() in tag_set:
                    score += 1.0

        # Keyword matching in body
        body_lower = body.lower()
        for keyword in query.keywords:
            if keyword.lower() in body_lower:
                score += 0.5

        # Source kind filter
        if query.source_kinds:
            source = metadata.get("source", "").lower()
            if source and source not in query.source_kinds:
                score *= 0.3  # Reduce score but don't eliminate

        # Importance weighting
        importance = int(metadata.get("importance", 0))
        score += importance * 0.2

        # Recency weighting (newer = slightly better)
        use_count = int(metadata.get("use_count", 0))
        score += use_count * 0.1

        return score

    def _header_to_record(
        self,
        header: Any,
        metadata: dict[str, Any],
        body: str,
    ) -> ExperienceRecord:
        """Convert a memory header + metadata to an ExperienceRecord."""
        source_kind = metadata.get("source", "interactive")
        if source_kind not in ("interactive", "bot_chat", "cron", "remote_trigger", "subtask"):
            source_kind = "interactive"

        tags = metadata.get("tags", [])
        outcome = str(metadata.get("introspection_outcome") or "unknown")
        if isinstance(tags, list):
            if "failure_pattern" in tags:
                outcome = "failure"
            elif "success_pattern" in tags:
                outcome = "success"

        return ExperienceRecord(
            id=metadata.get("id", header.path.stem),
            task_type=metadata.get("introspection_task_type") or metadata.get("category", "other"),
            timestamp=metadata.get("created_at", ""),
            context={"path": str(header.path.name)},
            source_kind=source_kind,  # type: ignore[arg-type]
            outcome=outcome,  # type: ignore[arg-type]
            metrics={"importance": int(metadata.get("importance", 0))},
            lessons=[body.strip()],
            tools_used=[],
            evidence=[],
            confidence=float(
                metadata.get("introspection_confidence")
                or min(0.7 + max(int(metadata.get("importance", 1)) - 1, 0) * 0.05, 0.95)
            ),
            use_count=int(metadata.get("use_count", 0)),
            last_used=metadata.get("last_used_at"),
        )
