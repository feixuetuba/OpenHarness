"""web_config readable introspection event query helpers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("openharness.introspection.web")


@dataclass
class IntrospectionEvent:
    """A single introspection event for web display."""

    timestamp: str
    level: str
    event: str
    reflection_id: str | None = None
    source_id: str | None = None
    source_kind: str | None = None
    display_text: str | None = None
    summary: str | None = None
    memory_id: str | None = None
    metadata: dict[str, Any] | None = None


def load_events(
    events_path: Path,
    *,
    limit: int = 200,
    source_kind: str | None = None,
    reflection_id: str | None = None,
    level: str | None = None,
) -> list[IntrospectionEvent]:
    """Load introspection events from the JSONL file with optional filters."""
    if not events_path.exists():
        return []

    events: list[IntrospectionEvent] = []
    try:
        with open(events_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Apply filters
                if source_kind and data.get("source_kind") != source_kind:
                    continue
                if reflection_id and data.get("reflection_id") != reflection_id:
                    continue
                if level and data.get("level") != level:
                    continue

                event = IntrospectionEvent(
                    timestamp=data.get("timestamp", ""),
                    level=data.get("level", "INFO"),
                    event=data.get("event", ""),
                    reflection_id=data.get("reflection_id"),
                    source_id=data.get("source_id"),
                    source_kind=data.get("source_kind"),
                    display_text=data.get("display_text"),
                    summary=data.get("summary"),
                    memory_id=data.get("memory_id"),
                    metadata=data.get("metadata"),
                )
                events.append(event)
    except OSError as exc:
        log.warning("Failed to read events file: %s", exc)
        return []

    # Return most recent events first, limited
    events.reverse()
    return events[:limit]


def get_reflection_summaries(
    events_path: Path,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get summary of recent reflection runs."""
    events = load_events(events_path, limit=1000)
    chronological = list(reversed(events))

    # Group by reflection_id
    reflections: dict[str, dict[str, Any]] = {}
    for evt in chronological:
        if not evt.reflection_id:
            continue
        if evt.reflection_id not in reflections:
            reflections[evt.reflection_id] = {
                "reflection_id": evt.reflection_id,
                "source_id": evt.source_id,
                "source_kind": evt.source_kind,
                "start_time": evt.timestamp,
                "end_time": evt.timestamp,
                "status": "running",
                "memory_count": 0,
                "outcome": None,
                "summary": evt.summary,
            }

        ref = reflections[evt.reflection_id]
        ref["end_time"] = evt.timestamp
        if evt.source_id:
            ref["source_id"] = evt.source_id
        if evt.source_kind:
            ref["source_kind"] = evt.source_kind
        if evt.summary:
            ref["summary"] = evt.summary

        if evt.event == "reflection_completed":
            ref["status"] = "completed"
            ref["outcome"] = evt.metadata.get("outcome") if evt.metadata else None
            ref["memory_count"] = len(evt.metadata.get("memory_ids", [])) if evt.metadata else 0
        elif evt.event == "reflection_error":
            ref["status"] = "error"
        elif evt.event == "reflection_timeout":
            ref["status"] = "timeout"
        elif evt.event == "reflection_skipped":
            ref["status"] = "skipped"

    # Convert to list, most recent first
    summaries = list(reflections.values())
    summaries.sort(key=lambda x: x["end_time"], reverse=True)
    return summaries[:limit]


def get_introspection_memories(
    events_path: Path,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List memories written by introspection."""
    events = load_events(events_path, limit=1000)

    memories = []
    for evt in events:
        if evt.event == "memory_written" and evt.memory_id:
            memories.append({
                "memory_id": evt.memory_id,
                "reflection_id": evt.reflection_id,
                "source_id": evt.source_id,
                "summary": evt.summary,
                "timestamp": evt.timestamp,
            })

    memories.sort(key=lambda x: x["timestamp"], reverse=True)
    return memories[:limit]


def get_reflection_detail(
    events_path: Path,
    reflection_id: str,
) -> dict[str, Any] | None:
    """Get detailed view of a single reflection run."""
    events = load_events(events_path, reflection_id=reflection_id, limit=1000)
    if not events:
        return None

    # Reverse to chronological order
    events.reverse()

    thinking_steps = []
    experience_candidates = []
    memory_writes = []

    for evt in events:
        if evt.event == "reflection_reasoning":
            thinking_steps.append({
                "step": evt.metadata.get("step", "") if evt.metadata else "",
                "display_text": evt.display_text,
                "timestamp": evt.timestamp,
            })
        elif evt.event == "experience_candidate":
            experience_candidates.append({
                "lesson": evt.display_text,
                "confidence": evt.metadata.get("confidence", 0) if evt.metadata else 0,
                "timestamp": evt.timestamp,
            })
        elif evt.event == "memory_written":
            memory_writes.append({
                "memory_id": evt.memory_id,
                "summary": evt.summary,
                "timestamp": evt.timestamp,
            })

    # Find summary events
    started = next((e for e in events if e.event == "reflection_started"), None)
    completed = next((e for e in events if e.event == "reflection_completed"), None)

    return {
        "reflection_id": reflection_id,
        "source_id": started.source_id if started else None,
        "source_kind": started.source_kind if started else None,
        "start_time": started.timestamp if started else None,
        "end_time": completed.timestamp if completed else None,
        "status": "completed" if completed else "unknown",
        "outcome": completed.metadata.get("outcome") if completed and completed.metadata else None,
        "thinking_steps": thinking_steps,
        "experience_candidates": experience_candidates,
        "memory_writes": memory_writes,
        "event_count": len(events),
    }
