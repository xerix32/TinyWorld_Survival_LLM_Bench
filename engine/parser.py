"""Strict model output parser."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParseResult:
    raw_output: str
    normalized_output: str
    action: str | None
    valid: bool
    error: str | None = None


def parse_action(
    raw_output: str,
    allowed_actions: list[str],
    case_mode: str = "case_sensitive",
) -> ParseResult:
    normalized = raw_output.replace("\r\n", "\n").replace("\r", "\n").strip()

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
