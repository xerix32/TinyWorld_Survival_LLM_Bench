"""Adaptive self-reflection helpers."""

from __future__ import annotations

import json
from typing import Any

from engine.prompt_loader import PromptLoader
from models.base import BaseModelWrapper, ModelResponse, RenderedPrompts

from memory.session import normalize_lesson_text


_CONFIDENCE_VALUES = {"low", "medium", "high"}


def _unwrap_single_json_fence(text: str) -> str:
    lines = text.splitlines()
    if len(lines) < 3:
        return text

    opening = lines[0].strip()
    closing = lines[-1].strip()
    if not opening.startswith("```") or closing != "```":
        return text

    # Accept only a single fenced payload block, optionally language-tagged.
    lang = opening[3:].strip().lower()
    if lang not in {"", "json"}:
        return text
    return "\n".join(lines[1:-1]).strip()


def _normalize_confidence(value: Any) -> str:
    normalized = normalize_lesson_text(str(value or "")).casefold()
    if normalized in _CONFIDENCE_VALUES:
        return normalized
    return "medium"


def _with_terminal_period(value: str) -> str:
    normalized = normalize_lesson_text(value)
    if not normalized:
        return ""
    if normalized.endswith((".", "!", "?")):
        return normalized
    return f"{normalized}."


def _strip_leading_when(value: str) -> str:
    normalized = normalize_lesson_text(value)
    if normalized.casefold().startswith("when "):
        return normalize_lesson_text(normalized[5:])
    if normalized.casefold().startswith("if "):
        return normalize_lesson_text(normalized[3:])
    return normalized


def _lesson_item_to_text(item: dict[str, str]) -> str:
    rule = normalize_lesson_text(item.get("rule", ""))
    trigger = normalize_lesson_text(item.get("trigger", ""))
    risk = normalize_lesson_text(item.get("risk_if_overapplied", ""))
    confidence_raw = normalize_lesson_text(item.get("confidence", ""))
    confidence = _normalize_confidence(confidence_raw) if confidence_raw else ""

    pieces: list[str] = []
    rule_no_punct = normalize_lesson_text(rule.rstrip(".!?"))
    rule_no_prefix = _strip_leading_when(rule_no_punct)
    trigger_clause = _strip_leading_when(trigger)

    if rule.casefold().startswith("when "):
        pieces.append(_with_terminal_period(rule))
    elif trigger_clause:
        pieces.append(_with_terminal_period(f"When {trigger_clause}, {rule_no_prefix}"))
    else:
        pieces.append(_with_terminal_period(rule))

    if risk:
        if risk.casefold().startswith("overapply risk:"):
            pieces.append(_with_terminal_period(risk))
        else:
            pieces.append(_with_terminal_period(f"Overapply risk: {risk}"))
    if confidence:
        pieces.append(_with_terminal_period(f"Confidence: {confidence}"))
    return normalize_lesson_text(" ".join(pieces))


def _build_lesson_item_from_mapping(raw: dict[str, Any]) -> tuple[dict[str, str] | None, str | None]:
    rule = normalize_lesson_text(str(raw.get("rule", "")))
    if not rule:
        return None, "missing_rule"
    trigger = normalize_lesson_text(str(raw.get("trigger", "")))
    risk = normalize_lesson_text(str(raw.get("risk_if_overapplied", "")))
    confidence = _normalize_confidence(raw.get("confidence"))
    return {
        "rule": rule,
        "trigger": trigger,
        "risk_if_overapplied": risk,
        "confidence": confidence,
    }, None


def _build_lesson_item_from_string(raw: str) -> dict[str, str] | None:
    rule = normalize_lesson_text(raw)
    if not rule:
        return None
    return {
        "rule": rule,
        "trigger": "",
        "risk_if_overapplied": "",
        "confidence": "",
    }


def parse_reflection_lesson_items(
    raw_text: str,
    *,
    min_lessons: int = 3,
    max_lessons: int = 5,
) -> tuple[list[dict[str, str]], str | None]:
    text = str(raw_text or "").strip()
    if not text:
        return [], "empty_output"
    text = _unwrap_single_json_fence(text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [], "invalid_json"

    if not isinstance(parsed, list):
        return [], "not_array"

    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_item in parsed:
        normalized_item: dict[str, str] | None
        error: str | None = None
        if isinstance(raw_item, dict):
            normalized_item, error = _build_lesson_item_from_mapping(raw_item)
        elif isinstance(raw_item, str):
            normalized_item = _build_lesson_item_from_string(raw_item)
        else:
            return [], "non_supported_item"

        if error is not None:
            return [], f"invalid_item_{error}"
        if normalized_item is None:
            continue

        key = _lesson_item_to_text(normalized_item).casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(normalized_item)

    if len(items) < min_lessons:
        return [], "too_few_lessons"
    if len(items) > max_lessons:
        return [], "too_many_lessons"
    return items, None


def parse_reflection_lessons(
    raw_text: str,
    *,
    min_lessons: int = 3,
    max_lessons: int = 5,
) -> tuple[list[str], str | None]:
    items, error = parse_reflection_lesson_items(
        raw_text,
        min_lessons=min_lessons,
        max_lessons=max_lessons,
    )
    if error is not None:
        return [], error
    return [_lesson_item_to_text(item) for item in items], None


def parse_seed_reflection_policy(
    raw_text: str,
) -> tuple[list[str], str | None]:
    """Parse the new policy-based seed reflection format.

    Returns a list of lesson strings (policy + hints) and an optional error.
    """
    text = str(raw_text or "").strip()
    if not text:
        return [], "empty_output"
    text = _unwrap_single_json_fence(text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [], "invalid_json"

    if isinstance(parsed, list):
        # Fallback: model returned old array format — use legacy parser
        items, error = parse_reflection_lesson_items(raw_text)
        if error is not None:
            return [], error
        return [_lesson_item_to_text(item) for item in items], None

    if not isinstance(parsed, dict):
        return [], "not_object"

    policy = normalize_lesson_text(str(parsed.get("policy", "")))
    if not policy:
        return [], "missing_policy"

    lessons: list[str] = [policy]
    hints = parsed.get("hints", [])
    if isinstance(hints, list):
        for hint in hints:
            h = normalize_lesson_text(str(hint))
            if h:
                lessons.append(h)

    return lessons, None


def _run_reflection_call(
    *,
    model_wrapper: BaseModelWrapper,
    system_prompt: str,
    user_prompt: str,
    metadata: dict[str, Any] | None = None,
    parse_as_policy: bool = False,
) -> dict[str, Any]:
    response: ModelResponse = model_wrapper.generate(
        prompts=RenderedPrompts(system_prompt=system_prompt, user_prompt=user_prompt),
        metadata=metadata or {},
    )
    if parse_as_policy:
        lessons, parse_error = parse_seed_reflection_policy(response.raw_text)
        lesson_items: list[dict[str, str]] = []
    else:
        lesson_items, parse_error = parse_reflection_lesson_items(response.raw_text)
        lessons = [_lesson_item_to_text(item) for item in lesson_items] if parse_error is None else []
    return {
        "raw_output": response.raw_text,
        "parsed_lessons": lessons,
        "parsed_lesson_items": lesson_items,
        "parse_error": parse_error,
        "tokens_used": response.tokens_used,
        "latency_ms": response.latency_ms,
        "estimated_cost": response.estimated_cost,
        "metadata": response.metadata if isinstance(response.metadata, dict) else {},
    }


def run_seed_reflection(
    *,
    model_wrapper: BaseModelWrapper,
    prompt_loader: PromptLoader,
    run_summary: dict[str, Any],
    run_analysis: dict[str, Any] | None,
    run_trace_context: dict[str, Any] | None = None,
    existing_lessons: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    system_prompt = prompt_loader.render_reflection_system_prompt({})
    user_prompt = prompt_loader.render_seed_reflection_prompt(
        run_summary=run_summary,
        run_analysis=run_analysis,
        run_trace_context=run_trace_context,
        existing_lessons=existing_lessons or [],
    )
    return _run_reflection_call(
        model_wrapper=model_wrapper,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        metadata=metadata,
        parse_as_policy=True,
    )


def run_cross_seed_refinement(
    *,
    model_wrapper: BaseModelWrapper,
    prompt_loader: PromptLoader,
    initial_run_summary: dict[str, Any],
    initial_run_analysis: dict[str, Any] | None,
    initial_run_trace_context: dict[str, Any] | None,
    rerun_summary: dict[str, Any],
    rerun_analysis: dict[str, Any] | None,
    rerun_trace_context: dict[str, Any] | None,
    existing_lessons: list[dict[str, Any]] | None = None,
    seed_lessons: list[dict[str, Any]] | None = None,
    adaptive_feedback: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    system_prompt = prompt_loader.render_reflection_system_prompt({})
    user_prompt = prompt_loader.render_cross_seed_refinement_prompt(
        initial_run_summary=initial_run_summary,
        initial_run_analysis=initial_run_analysis,
        initial_run_trace_context=initial_run_trace_context,
        rerun_summary=rerun_summary,
        rerun_analysis=rerun_analysis,
        rerun_trace_context=rerun_trace_context,
        existing_lessons=existing_lessons or [],
        seed_lessons=seed_lessons or [],
        adaptive_feedback=adaptive_feedback or {},
    )
    return _run_reflection_call(
        model_wrapper=model_wrapper,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        metadata=metadata,
    )


def run_self_reflection(
    *,
    model_wrapper: BaseModelWrapper,
    prompt_loader: PromptLoader,
    run_summary: dict[str, Any],
    run_analysis: dict[str, Any] | None,
    existing_lessons: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Backward-compatible alias for older callsites.
    return run_seed_reflection(
        model_wrapper=model_wrapper,
        prompt_loader=prompt_loader,
        run_summary=run_summary,
        run_analysis=run_analysis,
        existing_lessons=existing_lessons,
        metadata=metadata,
    )
