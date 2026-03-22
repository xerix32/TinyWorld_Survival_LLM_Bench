"""Scoring helpers isolated from engine state transitions."""

from __future__ import annotations

from typing import Any

from engine.actions import ActionOutcome
from engine.world import AgentState


def score_action(
    parse_valid: bool,
    action_outcome: ActionOutcome | None,
    scoring_cfg: dict[str, Any],
) -> tuple[int, list[str]]:
    if not parse_valid:
        return int(scoring_cfg["invalid_action"]), ["invalid_action_penalty"]

    if action_outcome is None:
        return 0, []

    delta = 0
    events: list[str] = []

    if action_outcome.useful_gather:
        delta += int(scoring_cfg["gather_useful"])
        events.append("useful_gather")

    if action_outcome.useful_consume:
        delta += int(scoring_cfg["consume_useful"])
        events.append("useful_consume")

    return delta, events


def score_survival(alive_after_turn: bool, scoring_cfg: dict[str, Any]) -> tuple[int, list[str]]:
    if alive_after_turn:
        return int(scoring_cfg["survive_turn"]), ["survive_turn"]
    return int(scoring_cfg["death"]), ["death_penalty"]


def apply_score(agent: AgentState, score_delta: int) -> None:
    agent.score += int(score_delta)
