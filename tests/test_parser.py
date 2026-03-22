from __future__ import annotations

from engine.parser import parse_action


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
