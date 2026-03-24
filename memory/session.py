"""Session-local adaptive memory helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DEFAULT_PROMPT_MEMORY_MAX_ITEMS = 3
DEFAULT_NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.82
DEFAULT_MAX_LESSONS_PER_TOPIC = 1
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
_TOPIC_KEYWORD_CLUSTERS: tuple[tuple[str, set[str]], ...] = (
    (
        "protocol",
        {
            "action",
            "actions",
            "allowed",
            "allowed_actions",
            "format",
            "invalid",
            "output",
            "parser",
            "protocol",
            "valid",
        },
    ),
    (
        "water_pressure",
        {
            "dehydration",
            "drink",
            "thirst",
            "water",
        },
    ),
    (
        "food_pressure",
        {
            "eat",
            "food",
            "hunger",
            "starvation",
        },
    ),
    (
        "energy_pressure",
        {
            "energy",
            "idle",
            "rest",
            "wait",
        },
    ),
    (
        "movement_efficiency",
        {
            "coverage",
            "exploration",
            "loop",
            "move",
            "movement",
            "path",
            "revisit",
            "wandering",
        },
    ),
)
_TOPIC_TIE_BREAK_RANK: dict[str, int] = {
    "water_pressure": 5,
    "food_pressure": 5,
    "energy_pressure": 4,
    "movement_efficiency": 3,
    "protocol": 1,
}


def normalize_lesson_text(value: str) -> str:
    return " ".join(str(value).strip().split())


def _tokenize_lesson(value: str) -> set[str]:
    normalized = normalize_lesson_text(value).casefold()
    return set(_TOKEN_RE.findall(normalized))


def _lesson_topic_key(value: str) -> str:
    tokens = [token for token in _TOKEN_RE.findall(normalize_lesson_text(value).casefold()) if token]
    token_set = set(tokens)

    best_cluster = ""
    best_score = 0
    best_rank = -1
    for cluster_key, keywords in _TOPIC_KEYWORD_CLUSTERS:
        score = len(token_set & keywords)
        if score <= 0:
            continue
        rank = _TOPIC_TIE_BREAK_RANK.get(cluster_key, 0)
        if score > best_score or (score == best_score and rank > best_rank):
            best_cluster = cluster_key
            best_score = score
            best_rank = rank
    if best_cluster:
        return best_cluster

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

    Selection order:
    1) current-seed lessons (exclusive when present)
    2) session lessons (used only when current-seed lessons are absent)
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

    use_session_source = not bool(current_source)
    if use_session_source:
        session_exact_removed, session_near_removed, session_topic_removed = _append_unique_lessons(
            source_lessons=session_source,
            selected_lessons=selected_lessons,
            selected_token_sets=selected_token_sets,
            selected_keys=selected_keys,
            topic_counts=topic_counts,
            near_duplicate_threshold=near_duplicate_threshold,
            max_lessons_per_topic=max_lessons_per_topic,
        )
    else:
        session_exact_removed, session_near_removed, session_topic_removed = 0, 0, 0
    total_before_cap = len(selected_lessons)

    effective_max = max(0, int(max_items))
    truncated = selected_lessons[:effective_max]
    removed_by_cap = max(0, total_before_cap - len(truncated))

    source_for_diversity = current_source if current_source else session_source
    available_topic_order: list[str] = []
    available_topic_set: set[str] = set()
    for raw in source_for_diversity:
        topic = _lesson_topic_key(raw)
        if topic in available_topic_set:
            continue
        available_topic_set.add(topic)
        available_topic_order.append(topic)

    selected_topic_order: list[str] = []
    selected_topic_set: set[str] = set()
    for lesson in truncated:
        topic = _lesson_topic_key(lesson)
        if topic in selected_topic_set:
            continue
        selected_topic_set.add(topic)
        selected_topic_order.append(topic)

    diversity_override_applied = False
    if (
        effective_max >= 2
        and len(available_topic_set) >= 2
        and len(selected_topic_set) < 2
        and source_for_diversity
    ):
        seen_lessons = {item.casefold() for item in truncated}
        selected_token_sets_for_diversity = [_tokenize_lesson(item) for item in truncated]
        primary_topic = selected_topic_order[0] if selected_topic_order else ""
        replacement: str | None = None
        for raw in source_for_diversity:
            candidate = normalize_lesson_text(raw)
            if not candidate:
                continue
            if candidate.casefold() in seen_lessons:
                continue
            candidate_topic = _lesson_topic_key(candidate)
            if candidate_topic == primary_topic:
                continue
            candidate_tokens = _tokenize_lesson(candidate)
            is_near_duplicate = any(
                _jaccard_similarity(candidate_tokens, existing) >= near_duplicate_threshold
                for existing in selected_token_sets_for_diversity
            )
            if is_near_duplicate:
                continue
            replacement = candidate
            break

        if replacement is not None:
            if len(truncated) < effective_max:
                truncated.append(replacement)
            elif truncated:
                truncated[-1] = replacement
            diversity_override_applied = True
            selected_topic_order = []
            selected_topic_set = set()
            for lesson in truncated:
                topic = _lesson_topic_key(lesson)
                if topic in selected_topic_set:
                    continue
                selected_topic_set.add(topic)
                selected_topic_order.append(topic)

    final_current_count = min(current_count_before_cap, len(truncated))
    final_current = truncated[:final_current_count]
    final_session = truncated[final_current_count:]

    selected_topic_counts: dict[str, int] = {}
    for lesson in truncated:
        topic = _lesson_topic_key(lesson)
        selected_topic_counts[topic] = selected_topic_counts.get(topic, 0) + 1

    stats = {
        "input_session_count": len(session_source),
        "input_current_seed_count": len(current_source),
        "session_skipped_due_to_current_seed_count": (len(session_source) if not use_session_source else 0),
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
        "available_topic_count": len(available_topic_set),
        "selected_topic_counts": selected_topic_counts,
        "diversity_override_applied": diversity_override_applied,
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
