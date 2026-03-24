"""Deterministic lesson filter scaffold for adaptive memory v2."""

from __future__ import annotations

import re
from typing import Any

from memory.session import normalize_lesson_text


_COORDINATE_RE = re.compile(r"\(\s*\d+\s*,\s*\d+\s*\)")
_SEED_NUMBER_RE = re.compile(r"\bseed\s*\d+\b", flags=re.IGNORECASE)
_EPISODE_SPECIFIC_MARKERS = (
    "this map",
    "this seed",
    "in this run",
    "on this map",
    "on this seed",
    "tile ",
)


def _sanitize_lesson(raw: str) -> str:
    return normalize_lesson_text(raw)


def _is_inter_seed_safe_lesson(lesson: str) -> bool:
    text = lesson.strip()
    lower = text.casefold()
    if not text:
        return False
    if _COORDINATE_RE.search(text):
        return False
    if _SEED_NUMBER_RE.search(text):
        return False
    return not any(marker in lower for marker in _EPISODE_SPECIFIC_MARKERS)


def filter_lessons(
    lessons: list[str],
    *,
    context: dict[str, Any] | None = None,
) -> list[str]:
    """Deterministic hygiene filter.

    The hygiene check is applied only for cross-seed transferable memory.
    Intra-seed lessons are preserved (except normalization + dedupe).
    """
    stage = str((context or {}).get("stage", "")).strip().lower()
    enforce_cross_seed_hygiene = stage == "cross_seed_refinement"

    filtered: list[str] = []
    seen: set[str] = set()
    for lesson in lessons:
        normalized = _sanitize_lesson(str(lesson))
        if not normalized:
            continue
        if enforce_cross_seed_hygiene and not _is_inter_seed_safe_lesson(normalized):
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        filtered.append(normalized)
    return filtered
