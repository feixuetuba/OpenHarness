"""Shared tool use-scope restriction defaults and helpers."""

from __future__ import annotations

from typing import Any

DEFAULT_TOOL_RESTRICTIONS: dict[str, dict[str, Any]] = {
    "image_generation": {
        "restricted_keywords": [
            "证件照",
            "证件照片",
            "身份证照",
            "身份证照片",
            "护照照",
            "护照照片",
            "签证照",
            "签证照片",
            "id photo",
            "passport photo",
            "visa photo",
            "standard id",
            "professional id",
            "id/passport",
        ],
        "restriction_message": (
            "image_generation must not be used for ID/passport/visa photo workflows. "
            "Use the id-photo-generator skill instead and return the generated file with an [image: $UWEB/...] marker."
        ),
    }
}


def normalize_restricted_keywords(value: Any) -> list[str]:
    """Normalize keyword config from API/settings forms."""
    if isinstance(value, str):
        raw_items = value.replace("\n", ",").split(",")
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    keywords: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in keywords:
            keywords.append(text)
    return keywords


def tool_restriction_config(tool_name: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge default and user-configured restrictions for *tool_name*."""
    cfg = cfg or {}
    merged = dict(DEFAULT_TOOL_RESTRICTIONS.get(tool_name, {}))
    for key in ("restricted_keywords", "restriction_message"):
        if key in cfg:
            merged[key] = cfg[key]
    return {
        "restricted_keywords": normalize_restricted_keywords(merged.get("restricted_keywords", [])),
        "restriction_message": str(merged.get("restriction_message") or "").strip(),
        "uses_default": "restricted_keywords" not in cfg and "restriction_message" not in cfg,
    }
