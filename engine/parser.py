"""Strict model output parser."""

from __future__ import annotations

from dataclasses import dataclass
import re


_REASONING_BLOCK_PATTERNS = (
    re.compile(r"(?is)<thinking>.*?</thinking>"),
    re.compile(r"(?is)<think>.*?</think>"),
)
_REASONING_TAG_PATTERN = re.compile(r"(?i)</?(thinking|think)>")
_CHAT_TOKEN_PATTERN = re.compile(r"<\|[^>\n]{1,128}\|>")


@dataclass
class ParseResult:
    raw_output: str
    normalized_output: str
    action: str | None
    valid: bool
    error: str | None = None
    fix_thinking_applied: bool = False


def sanitize_model_output(raw_output: str) -> str:
    normalized = raw_output.replace("\r\n", "\n").replace("\r", "\n")

    for pattern in _REASONING_BLOCK_PATTERNS:
        normalized = pattern.sub("", normalized)

    normalized = _REASONING_TAG_PATTERN.sub("", normalized)
    normalized = _CHAT_TOKEN_PATTERN.sub("", normalized)

    return normalized.strip()


def _match_allowed_action(
    normalized: str,
    allowed_actions: list[str],
    case_mode: str,
) -> str | None:
    if case_mode == "case_insensitive":
        allowed_lookup = {action.casefold(): action for action in allowed_actions}
        return allowed_lookup.get(normalized.casefold())

    if case_mode != "case_sensitive":
        raise ValueError(f"unsupported parser case_mode: {case_mode}")

    if normalized in allowed_actions:
        return normalized
    return None


def _is_action_boundary(text: str, start: int, end: int) -> bool:
    if start > 0 and text[start - 1].isalnum():
        return False
    if end < len(text) and text[end].isalnum():
        return False
    return True


def _extract_last_allowed_action(
    normalized: str,
    allowed_actions: list[str],
    case_mode: str,
) -> str | None:
    if case_mode == "case_insensitive":
        haystack = normalized.casefold()
        needles = [(action, action.casefold()) for action in allowed_actions]
    elif case_mode == "case_sensitive":
        haystack = normalized
        needles = [(action, action) for action in allowed_actions]
    else:
        raise ValueError(f"unsupported parser case_mode: {case_mode}")

    last_match: tuple[int, str] | None = None
    for canonical, needle in needles:
        start = 0
        while True:
            idx = haystack.find(needle, start)
            if idx < 0:
                break
            end = idx + len(needle)
            if _is_action_boundary(haystack, idx, end):
                if last_match is None or idx >= last_match[0]:
                    last_match = (idx, canonical)
            start = idx + 1

    if last_match is None:
        return None
    return last_match[1]


def parse_action(
    raw_output: str,
    allowed_actions: list[str],
    case_mode: str = "case_sensitive",
    fix_thinking: bool = False,
) -> ParseResult:
    normalized = sanitize_model_output(raw_output)

    if not normalized:
        return ParseResult(
            raw_output=raw_output,
            normalized_output=normalized,
            action=None,
            valid=False,
            error="empty_output",
        )

    exact = _match_allowed_action(normalized, allowed_actions, case_mode)
    if exact is not None:
        return ParseResult(
            raw_output=raw_output,
            normalized_output=normalized,
            action=exact,
            valid=True,
        )

    if fix_thinking:
        extracted = _extract_last_allowed_action(normalized, allowed_actions, case_mode)
        if extracted is not None:
            return ParseResult(
                raw_output=raw_output,
                normalized_output=extracted,
                action=extracted,
                valid=True,
                fix_thinking_applied=True,
            )

    if "\n" in normalized:
        return ParseResult(
            raw_output=raw_output,
            normalized_output=normalized,
            action=None,
            valid=False,
            error="multiple_lines_not_allowed",
        )

    return ParseResult(
        raw_output=raw_output,
        normalized_output=normalized,
        action=None,
        valid=False,
        error="not_in_allowed_actions",
    )
