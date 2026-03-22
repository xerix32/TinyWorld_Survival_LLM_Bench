"""Rules for action availability and per-turn survival updates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.actions import ACTION_REFERENCE, MOVE_DELTAS
from engine.world import RESOURCE_TILE_TO_ITEM, WorldState, get_tile, is_in_bounds


@dataclass
class SurvivalUpdate:
    energy_before: int
    energy_after: int
    hunger_before: int
    hunger_after: int
    thirst_before: int
    thirst_after: int
    starvation_triggered: bool
    dehydration_triggered: bool
    alive_after: bool

    def as_delta(self) -> dict[str, Any]:
        return {
            "energy_before": self.energy_before,
            "energy_after": self.energy_after,
            "hunger_before": self.hunger_before,
            "hunger_after": self.hunger_after,
            "thirst_before": self.thirst_before,
            "thirst_after": self.thirst_after,
            "starvation_triggered": self.starvation_triggered,
            "dehydration_triggered": self.dehydration_triggered,
            "alive_after": self.alive_after,
        }


def compute_allowed_actions(
    world: WorldState,
    agent_id: str,
    rules_cfg: dict[str, Any],
) -> list[str]:
    del rules_cfg  # reserved for future scenario/rule-specific filtering

    agent = world.agents[agent_id]
    current_tile = get_tile(world, agent.position.x, agent.position.y)

    allowed: list[str] = []
    for action in ACTION_REFERENCE:
        if action in MOVE_DELTAS:
            dx, dy = MOVE_DELTAS[action]
            target_x = agent.position.x + dx
            target_y = agent.position.y + dy
            if is_in_bounds(world, target_x, target_y):
                allowed.append(action)
            continue

        if action == "gather":
            if current_tile in RESOURCE_TILE_TO_ITEM:
                allowed.append(action)
            continue

        if action == "eat":
            if agent.inventory.get("food", 0) > 0 and agent.hunger > 0:
                allowed.append(action)
            continue

        if action == "drink":
            if agent.inventory.get("water", 0) > 0 and agent.thirst > 0:
                allowed.append(action)
            continue

        if action in {"rest", "inspect"}:
            allowed.append(action)
            continue

    return allowed


def apply_end_of_turn(
    world: WorldState,
    agent_id: str,
    rules_cfg: dict[str, Any],
) -> SurvivalUpdate:
    agent = world.agents[agent_id]

    energy_before = agent.energy
    hunger_before = agent.hunger
    thirst_before = agent.thirst

    hunger_max = int(rules_cfg["hunger_max"])
    thirst_max = int(rules_cfg["thirst_max"])

    agent.hunger = min(hunger_max, agent.hunger + int(rules_cfg["passive_hunger_gain"]))
    agent.thirst = min(thirst_max, agent.thirst + int(rules_cfg["passive_thirst_gain"]))
    agent.energy = max(0, agent.energy - int(rules_cfg["passive_energy_loss"]))

    starvation_triggered = agent.hunger >= hunger_max
    dehydration_triggered = agent.thirst >= thirst_max

    if starvation_triggered:
        agent.energy = max(0, agent.energy - int(rules_cfg["starvation_energy_penalty"]))
    if dehydration_triggered:
        agent.energy = max(0, agent.energy - int(rules_cfg["dehydration_energy_penalty"]))

    if agent.energy <= 0:
        agent.alive = False

    return SurvivalUpdate(
        energy_before=energy_before,
        energy_after=agent.energy,
        hunger_before=hunger_before,
        hunger_after=agent.hunger,
        thirst_before=thirst_before,
        thirst_after=agent.thirst,
        starvation_triggered=starvation_triggered,
        dehydration_triggered=dehydration_triggered,
        alive_after=agent.alive,
    )
