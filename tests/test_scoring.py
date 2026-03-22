from __future__ import annotations

from engine.actions import ActionOutcome
from engine.scoring import apply_score, score_action, score_survival
from engine.world import AgentState, Position, default_inventory


SCORING_CFG = {
    "survive_turn": 1,
    "gather_useful": 3,
    "consume_useful": 2,
    "invalid_action": -2,
    "death": -10,
}


def test_score_action_invalid_applies_penalty_once() -> None:
    delta, events = score_action(parse_valid=False, action_outcome=None, scoring_cfg=SCORING_CFG)

    assert delta == -2
    assert events == ["invalid_action_penalty"]


def test_score_action_useful_gather() -> None:
    outcome = ActionOutcome(action="gather", success=True, message="ok", useful_gather=True)
    delta, events = score_action(parse_valid=True, action_outcome=outcome, scoring_cfg=SCORING_CFG)

    assert delta == 3
    assert events == ["useful_gather"]


def test_score_action_useful_consume() -> None:
    outcome = ActionOutcome(action="eat", success=True, message="ok", useful_consume=True)
    delta, events = score_action(parse_valid=True, action_outcome=outcome, scoring_cfg=SCORING_CFG)

    assert delta == 2
    assert events == ["useful_consume"]


def test_score_survival_alive_and_death() -> None:
    alive_delta, alive_events = score_survival(alive_after_turn=True, scoring_cfg=SCORING_CFG)
    dead_delta, dead_events = score_survival(alive_after_turn=False, scoring_cfg=SCORING_CFG)

    assert alive_delta == 1
    assert alive_events == ["survive_turn"]
    assert dead_delta == -10
    assert dead_events == ["death_penalty"]


def test_apply_score_updates_agent_total() -> None:
    agent = AgentState(
        agent_id="agent_1",
        position=Position(0, 0),
        energy=10,
        hunger=10,
        thirst=10,
        inventory=default_inventory(),
    )

    apply_score(agent, 5)
    apply_score(agent, -2)

    assert agent.score == 3
