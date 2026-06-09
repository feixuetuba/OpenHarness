"""Prompt templates for introspection."""

from __future__ import annotations

REFLECTION_PROMPT = """You are an introspection engine analyzing an AI assistant's session performance.

Analyze the following session data and produce a structured reflection report.

## Session Summary
{session_summary}

## Analysis Results
{analysis}

## Instructions
1. Evaluate the task completion quality
2. Identify successful patterns worth repeating
3. Identify failure patterns to avoid
4. Extract concrete, actionable lessons (1-3 lessons)
5. Rate tool efficiency (0-1 for each tool used)
6. Generate thinking steps showing your reasoning

Output STRICT JSON matching this schema:
{{
  "task_summary": "brief summary of what was attempted",
  "outcome": "success|partial|failure|abandoned|unknown",
  "tools_efficiency": {{"tool_name": 0.95}},
  "errors": [{{"type": "...", "message": "...", "resolved": true}}],
  "patterns_identified": ["pattern1", "pattern2"],
  "recommendations": ["recommendation1"],
  "thinking_steps": [{{"step": "evidence_review", "display_text": "..."}}],
  "experience_candidates": [{{"lesson": "...", "confidence": 0.8, "evidence": ["..."]}}]
}}

Rules:
- Only output valid JSON, no markdown fences
- Keep display_text under 300 characters
- Confidence should be 0.0-1.0
- Lessons should be specific and actionable
"""

EXPERIENCE_INJECTION_PROMPT = """The following are relevant past experiences that may help with the current task. Use them as reference only.

## Past Experiences
{experiences}

## Current Task
{task_text}

Consider these experiences when planning your approach, but verify they still apply to the current context.
"""

TASK_TYPE_CLASSIFICATION_PROMPT = """Classify the following task into one of these categories:
- code_review: Reviewing code for quality, security, or best practices
- bug_fix: Fixing a bug or error
- feature_dev: Developing a new feature
- refactoring: Restructuring existing code
- documentation: Writing or updating documentation
- testing: Writing or running tests
- debugging: Investigating and diagnosing issues
- maintenance: Routine maintenance or updates
- configuration: Setting up or changing configuration
- other: Anything else

Task: {task_text}

Output ONLY the category name (one word with underscore).
"""
