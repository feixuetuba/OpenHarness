"""Tests for skill recall indexing."""

from __future__ import annotations

from openharness.skills.index import SkillIndex
from openharness.skills.types import SkillDefinition


def test_skill_index_excludes_public_skill_names():
    chart = SkillDefinition(
        name="Chart",
        description="Draw data charts.",
        content="# Chart",
        source="user",
        command_name="chart",
        aliases=("plot",),
        keywords=("chart", "plot"),
    )
    deploy = SkillDefinition(
        name="Deploy",
        description="Deploy services.",
        content="# Deploy",
        source="user",
        command_name="deploy",
        keywords=("deploy",),
    )
    index = SkillIndex()
    index.build([chart, deploy])

    candidates = index.search("chart plot", exclude_names={"chart", "plot"})

    assert all(candidate.skill_name != "chart" for candidate in candidates)


def test_skill_index_exact_slash_match_has_highest_priority():
    deploy = SkillDefinition(
        name="Deploy",
        description="Deploy services.",
        content="# Deploy",
        source="user",
        command_name="deploy",
        keywords=("service",),
    )
    docs = SkillDefinition(
        name="Docs",
        description="Write deployment documentation.",
        content="# Docs",
        source="user",
        command_name="docs",
        keywords=("deploy",),
    )
    index = SkillIndex()
    index.build([docs, deploy])

    candidates = index.recall("/deploy")

    assert candidates[0].skill_name == "deploy"
    assert candidates[0].match_type == "exact"
    assert candidates[0].score == 100.0


def test_skill_index_alias_match():
    skill = SkillDefinition(
        name="generate_chart",
        description="Generate charts.",
        content="# Chart",
        source="user",
        command_name="generate_chart",
        aliases=("plot",),
    )
    index = SkillIndex()
    index.build([skill])

    candidates = index.recall("plot")

    assert candidates[0].skill_name == "generate_chart"
    assert candidates[0].match_type == "alias"


def test_skill_index_bm25_keyword_recall_orders_by_relevance():
    chart = SkillDefinition(
        name="chart",
        description="Visualize structured data.",
        content="# Chart",
        source="user",
        command_name="chart",
        keywords=("chart", "chart", "csv", "visualization"),
    )
    deploy = SkillDefinition(
        name="deploy",
        description="Deploy services.",
        content="# Deploy",
        source="user",
        command_name="deploy",
        keywords=("deploy",),
    )
    index = SkillIndex()
    index.build([deploy, chart])

    candidates = index.recall("make chart from csv")

    assert candidates[0].skill_name == "chart"
    assert candidates[0].match_type == "bm25"


def test_skill_index_filters_disable_model_invocation():
    hidden = SkillDefinition(
        name="hidden",
        description="Hidden deployment workflow.",
        content="# Hidden",
        source="user",
        command_name="hidden",
        keywords=("deploy",),
        disable_model_invocation=True,
    )
    visible = SkillDefinition(
        name="visible",
        description="Visible deployment workflow.",
        content="# Visible",
        source="user",
        command_name="visible",
        keywords=("deploy",),
    )
    index = SkillIndex()
    index.build([hidden, visible])

    candidates = index.recall("deploy")

    assert [candidate.skill_name for candidate in candidates] == ["visible"]


def test_skill_index_limit_caps_results():
    skills = [
        SkillDefinition(
            name=f"skill-{index}",
            description="Shared recall target.",
            content=f"# Skill {index}",
            source="user",
            command_name=f"skill-{index}",
            keywords=("shared",),
        )
        for index in range(4)
    ]
    index = SkillIndex()
    index.build(skills)

    candidates = index.search("shared", limit=2)

    assert len(candidates) == 2


def test_skill_index_uses_trigger_and_negative_trigger_for_candidates():
    skill = SkillDefinition(
        name="generate_chart",
        description="Generate charts from structured data.",
        content="# Chart",
        source="user",
        command_name="generate_chart",
        keywords=("chart",),
        trigger="Use for structured data visualization.",
        negative_trigger="Do not use for artistic images.",
    )
    index = SkillIndex()
    index.build([skill])

    candidates = index.recall("chart")

    assert candidates[0].description == "Use for structured data visualization."
    assert candidates[0].negative_trigger == "Do not use for artistic images."
