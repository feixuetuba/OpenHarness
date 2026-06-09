"""Session quality analyzer for introspection."""

from __future__ import annotations

import logging
from typing import Any

from openharness.introspection.types import AnalysisResult, IntrospectionSource

log = logging.getLogger("openharness.introspection.analyzer")


class SessionAnalyzer:
    """Analyze session quality and extract key metrics."""

    def analyze(self, source: IntrospectionSource) -> AnalysisResult:
        """Analyze a session source and return structured results."""
        completion = self._calculate_completion(source)
        tool_efficiency = self._evaluate_tools(source)
        error_patterns = self._identify_errors(source)
        success_patterns = self._extract_success_patterns(source)
        failure_patterns = self._extract_failure_patterns(source)
        tool_calls_count = len(source.tool_events)
        duration = float(source.usage.get("duration_seconds", 0))
        total_tokens = int(source.usage.get("total_tokens", 0))

        return AnalysisResult(
            completion=completion,
            tool_efficiency=tool_efficiency,
            error_patterns=error_patterns,
            patterns_identified=success_patterns + failure_patterns,
            success_patterns=success_patterns,
            failure_patterns=failure_patterns,
            tool_calls_count=tool_calls_count,
            duration_seconds=duration,
            total_tokens=total_tokens,
        )

    def _calculate_completion(self, source: IntrospectionSource) -> float:
        """Estimate task completion ratio (0.0-1.0)."""
        outcome = source.metadata.get("outcome", "")
        if outcome == "success":
            return 1.0
        if outcome == "partial":
            return 0.5
        if outcome in ("failure", "abandoned"):
            return 0.0

        # Heuristic: check if there were errors
        error_count = sum(
            1 for evt in source.tool_events
            if not evt.get("success", True)
        )
        total = len(source.tool_events)
        if total == 0:
            return 0.5  # unknown

        success_ratio = (total - error_count) / total
        return round(success_ratio, 2)

    def _evaluate_tools(self, source: IntrospectionSource) -> dict[str, float]:
        """Evaluate efficiency per tool (0.0-1.0)."""
        tool_stats: dict[str, dict[str, int]] = {}

        for evt in source.tool_events:
            tool_name = evt.get("tool_name", "unknown")
            if tool_name not in tool_stats:
                tool_stats[tool_name] = {"success": 0, "total": 0}
            tool_stats[tool_name]["total"] += 1
            if evt.get("success", True):
                tool_stats[tool_name]["success"] += 1

        efficiency = {}
        for tool_name, stats in tool_stats.items():
            if stats["total"] > 0:
                efficiency[tool_name] = round(stats["success"] / stats["total"], 2)
            else:
                efficiency[tool_name] = 0.0

        return efficiency

    def _identify_errors(self, source: IntrospectionSource) -> list[dict[str, Any]]:
        """Identify errors from tool events."""
        errors = []
        for evt in source.tool_events:
            if not evt.get("success", True):
                error_info = {
                    "type": evt.get("error_type", "tool_error"),
                    "message": str(evt.get("error", ""))[:200],
                    "tool": evt.get("tool_name", "unknown"),
                    "resolved": evt.get("resolved", False),
                }
                errors.append(error_info)
        return errors

    def _extract_success_patterns(self, source: IntrospectionSource) -> list[str]:
        """Extract patterns from successful operations."""
        patterns = []

        # Check for tools that succeeded consistently
        tool_stats: dict[str, int] = {}
        for evt in source.tool_events:
            if evt.get("success", True):
                tool_name = evt.get("tool_name", "unknown")
                tool_stats[tool_name] = tool_stats.get(tool_name, 0) + 1

        for tool_name, count in tool_stats.items():
            if count >= 3:
                patterns.append(f"{tool_name} used effectively ({count} successful calls)")

        # Check for fast completion
        duration = source.usage.get("duration_seconds", 0)
        if duration and duration < 30:
            patterns.append("Task completed quickly")

        return patterns

    def _extract_failure_patterns(self, source: IntrospectionSource) -> list[str]:
        """Extract patterns from failed operations."""
        patterns = []

        # Group errors by type
        error_types: dict[str, int] = {}
        for evt in source.tool_events:
            if not evt.get("success", True):
                error_type = evt.get("error_type", "unknown")
                error_types[error_type] = error_types.get(error_type, 0) + 1

        for error_type, count in error_types.items():
            if count >= 2:
                patterns.append(f"Repeated {error_type} errors ({count} occurrences)")

        # Check for timeout patterns
        timeout_count = sum(
            1 for evt in source.tool_events
            if evt.get("error_type") == "timeout"
        )
        if timeout_count > 0:
            patterns.append(f"Timeout issues detected ({timeout_count} timeouts)")

        return patterns
