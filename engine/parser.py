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


def sanitize_model_output(raw_output: str) -> str:
    normalized = raw_output.replace("\r\n", "\n").replace("\r", "\n")

    for pattern in _REASONING_BLOCK_PATTERNS:
        normalized = pattern.sub("", normalized)

    normalized = _REASONING_TAG_PATTERN.sub("", normalized)
    normalized = _CHAT_TOKEN_PATTERN.sub("", normalized)

    return normalized.strip()


def parse_action(
    raw_output: str,
    allowed_actions: list[str],
    case_mode: str = "case_sensitive",
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

    if "\n" in normalized:
        return ParseResult(
            raw_output=raw_output,
            normalized_output=normalized,
            action=None,
            valid=False,
            error="multiple_lines_not_allowed",
        )

    if case_mode == "case_insensitive":
        allowed_lookup = {action.casefold(): action for action in allowed_actions}
        matched = allowed_lookup.get(normalized.casefold())
        if matched is not None:
            return ParseResult(
                raw_output=raw_output,
                normalized_output=normalized,
                action=matched,
                valid=True,
            )
        return ParseResult(
            raw_output=raw_output,
            normalized_output=normalized,
            action=None,
            valid=False,
            error="not_in_allowed_actions",
        )

    if case_mode != "case_sensitive":
        raise ValueError(f"unsupported parser case_mode: {case_mode}")

    if normalized in allowed_actions:
        return ParseResult(
            raw_output=raw_output,
            normalized_output=normalized,
            action=normalized,
            valid=True,
        )

    return ParseResult(
        raw_output=raw_output,
        normalized_output=normalized,
        action=None,
        valid=False,
        error="not_in_allowed_actions",
    )
