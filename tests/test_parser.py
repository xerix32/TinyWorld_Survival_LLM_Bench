from __future__ import annotations

from engine.parser import parse_action, sanitize_model_output


ALLOWED = ["move north", "move south", "gather"]


def test_parser_trims_and_normalizes_case_when_configured() -> None:
    result = parse_action("  Move North\r\n", ALLOWED, case_mode="case_insensitive")

    assert result.valid is True
    assert result.action == "move north"


def test_parser_rejects_multiple_lines() -> None:
    result = parse_action("move north\ngather", ALLOWED, case_mode="case_insensitive")

    assert result.valid is False
    assert result.error == "multiple_lines_not_allowed"


def test_parser_rejects_unknown_action() -> None:
    result = parse_action("dance", ALLOWED, case_mode="case_insensitive")

    assert result.valid is False
    assert result.error == "not_in_allowed_actions"


def test_parser_strips_thinking_block_and_accepts_action() -> None:
    raw = "<thinking>I should move.</thinking>\nmove north"
    result = parse_action(raw, ALLOWED, case_mode="case_insensitive")

    assert result.valid is True
    assert result.action == "move north"
    assert result.normalized_output == "move north"


def test_parser_strips_chat_tokens_and_accepts_action() -> None:
    raw = "move north<|im_end|>"
    result = parse_action(raw, ALLOWED, case_mode="case_insensitive")

    assert result.valid is True
    assert result.action == "move north"
    assert result.normalized_output == "move north"


def test_sanitize_model_output_removes_known_artifacts_only() -> None:
    raw = "<think>foo</think>\nmove south<|im_end|>"
    cleaned = sanitize_model_output(raw)

    assert cleaned == "move south"
