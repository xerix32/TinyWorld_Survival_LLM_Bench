"""Session-local adaptive memory helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DEFAULT_PROMPT_MEMORY_MAX_ITEMS = 6
DEFAULT_NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.82
DEFAULT_MAX_LESSONS_PER_TOPIC = 2
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_TOPIC_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "before",
    "by",
    "for",
    "from",
    "if",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "then",
    "to",
    "when",
    "with",
}


def normalize_lesson_text(value: str) -> str:
    return " ".join(str(value).strip().split())


def _tokenize_lesson(value: str) -> set[str]:
    normalized = normalize_lesson_text(value).casefold()
    return set(_TOKEN_RE.findall(normalized))


def _lesson_topic_key(value: str) -> str:
    tokens = [token for token in _TOKEN_RE.findall(normalize_lesson_text(value).casefold()) if token]
    for token in tokens:
        if token not in _TOPIC_STOPWORDS:
            return token
    return "__generic__"


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return intersection / union


def _append_unique_lessons(
    *,
    source_lessons: list[str],
    selected_lessons: list[str],
    selected_token_sets: list[set[str]],
    selected_keys: set[str],
    topic_counts: dict[str, int],
    near_duplicate_threshold: float,
    max_lessons_per_topic: int,
) -> tuple[int, int]:
    removed_exact = 0
    removed_near = 0
    removed_topic = 0

    for raw in source_lessons:
        normalized = normalize_lesson_text(raw)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in selected_keys:
            removed_exact += 1
            continue

        token_set = _tokenize_lesson(normalized)
        is_near_duplicate = any(
            _jaccard_similarity(token_set, existing) >= near_duplicate_threshold
            for existing in selected_token_sets
        )
        if is_near_duplicate:
            removed_near += 1
            continue

        topic_key = _lesson_topic_key(normalized)
        if topic_counts.get(topic_key, 0) >= max_lessons_per_topic:
            removed_topic += 1
            continue

        selected_lessons.append(normalized)
        selected_token_sets.append(token_set)
        selected_keys.add(key)
        topic_counts[topic_key] = topic_counts.get(topic_key, 0) + 1

    return removed_exact, removed_near, removed_topic


def build_prompt_memory_lessons(
    session_lessons: list[str] | None,
    current_seed_lessons: list[str] | None,
    *,
    max_items: int = DEFAULT_PROMPT_MEMORY_MAX_ITEMS,
    near_duplicate_threshold: float = DEFAULT_NEAR_DUPLICATE_JACCARD_THRESHOLD,
    max_lessons_per_topic: int = DEFAULT_MAX_LESSONS_PER_TOPIC,
) -> dict[str, Any]:
    """Build deterministic prompt-memory payload with dedupe and cap.

    Priority order:
    1) current-seed lessons
    2) session lessons
    """
    session_source = [normalize_lesson_text(item) for item in (session_lessons or []) if normalize_lesson_text(item)]
    current_source = [normalize_lesson_text(item) for item in (current_seed_lessons or []) if normalize_lesson_text(item)]

    selected_lessons: list[str] = []
    selected_token_sets: list[set[str]] = []
    selected_keys: set[str] = set()
    topic_counts: dict[str, int] = {}

    current_exact_removed, current_near_removed, current_topic_removed = _append_unique_lessons(
        source_lessons=current_source,
        selected_lessons=selected_lessons,
        selected_token_sets=selected_token_sets,
        selected_keys=selected_keys,
        topic_counts=topic_counts,
        near_duplicate_threshold=near_duplicate_threshold,
        max_lessons_per_topic=max_lessons_per_topic,
    )
    current_count_before_cap = len(selected_lessons)

    session_exact_removed, session_near_removed, session_topic_removed = _append_unique_lessons(
        source_lessons=session_source,
        selected_lessons=selected_lessons,
        selected_token_sets=selected_token_sets,
        selected_keys=selected_keys,
        topic_counts=topic_counts,
        near_duplicate_threshold=near_duplicate_threshold,
        max_lessons_per_topic=max_lessons_per_topic,
    )
    total_before_cap = len(selected_lessons)

    effective_max = max(0, int(max_items))
    truncated = selected_lessons[:effective_max]
    removed_by_cap = max(0, total_before_cap - len(truncated))

    final_current_count = min(current_count_before_cap, len(truncated))
    final_current = truncated[:final_current_count]
    final_session = truncated[final_current_count:]

    stats = {
        "input_session_count": len(session_source),
        "input_current_seed_count": len(current_source),
        "current_removed_exact_count": current_exact_removed,
        "current_removed_near_count": current_near_removed,
        "current_removed_topic_count": current_topic_removed,
        "session_removed_exact_count": session_exact_removed,
        "session_removed_near_count": session_near_removed,
        "session_removed_topic_count": session_topic_removed,
        "removed_by_cap_count": removed_by_cap,
        "max_items": effective_max,
        "near_duplicate_threshold": near_duplicate_threshold,
        "max_lessons_per_topic": max_lessons_per_topic,
        "final_current_seed_count": len(final_current),
        "final_session_count": len(final_session),
        "final_total_count": len(truncated),
    }

    return {
        "current_seed_lessons": final_current,
        "session_lessons": final_session,
        "all_lessons": truncated,
        "stats": stats,
    }


def merge_lessons(existing_lessons: list[str], new_lessons: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()

    for raw in list(existing_lessons) + list(new_lessons):
        normalized = normalize_lesson_text(raw)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append(normalized)
    return merged


def lessons_to_prompt_items(lessons: list[str]) -> list[dict[str, str]]:
    return [{"text": normalize_lesson_text(item)} for item in lessons if normalize_lesson_text(item)]


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
    tmp_path.replace(path)
