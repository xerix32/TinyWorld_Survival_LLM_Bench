"""Action declarations and state transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.world import (
    RESOURCE_TILE_TO_ITEM,
    WorldState,
    get_tile,
    is_in_bounds,
    set_tile,
)

ACTION_REFERENCE = [
    "move north",
    "move south",
    "move east",
    "move west",
    "gather",
    "eat",
    "drink",
    "rest",
    "wait",
]

MOVE_DELTAS = {
    "move north": (0, -1),
    "move south": (0, 1),
    "move east": (1, 0),
    "move west": (-1, 0),
}


@dataclass
class ActionOutcome:
    action: str
    success: bool
    message: str
    world_delta: dict[str, Any] = field(default_factory=dict)
    useful_gather: bool = False
    useful_consume: bool = False
    invalid_reason: str | None = None


def apply_action(
    world: WorldState,
    agent_id: str,
    action: str,
    rules_cfg: dict[str, Any],
) -> ActionOutcome:
    agent = world.agents[agent_id]

    if action in MOVE_DELTAS:
        dx, dy = MOVE_DELTAS[action]
        before = (agent.position.x, agent.position.y)
        after_x = before[0] + dx
        after_y = before[1] + dy
        if not is_in_bounds(world, after_x, after_y):
            return ActionOutcome(
                action=action,
                success=False,
                message="move blocked by boundary",
                world_delta={"position_before": before, "position_after": before},
            )
        agent.position = type(agent.position)(after_x, after_y)
        return ActionOutcome(
            action=action,
            success=True,
            message="move applied",
            world_delta={"position_before": before, "position_after": (after_x, after_y)},
        )

    if action == "gather":
        x, y = agent.position.x, agent.position.y
        tile_type = get_tile(world, x, y)
        if tile_type not in RESOURCE_TILE_TO_ITEM:
            return ActionOutcome(
                action=action,
                success=False,
                message="no gatherable resource on current tile",
                world_delta={"tile_before": tile_type, "tile_after": tile_type},
            )

        item = RESOURCE_TILE_TO_ITEM[tile_type]
        before_amount = agent.inventory.get(item, 0)
        agent.inventory[item] = before_amount + 1
        set_tile(world, x, y, "empty")
        return ActionOutcome(
            action=action,
            success=True,
            message=f"gathered {item}",
            world_delta={
                "tile_before": tile_type,
                "tile_after": "empty",
                "inventory_delta": {item: 1},
            },
            useful_gather=True,
        )

    if action == "eat":
        if agent.inventory.get("food", 0) <= 0:
            return ActionOutcome(
                action=action,
                success=False,
                message="no food in inventory",
            )

        before_hunger = agent.hunger
        agent.inventory["food"] -= 1
        reduction = int(rules_cfg["eat_hunger_reduction"])
        agent.hunger = max(0, agent.hunger - reduction)
        useful = before_hunger > agent.hunger
        return ActionOutcome(
            action=action,
            success=True,
            message="consumed food",
            world_delta={
                "hunger_before": before_hunger,
                "hunger_after": agent.hunger,
                "inventory_delta": {"food": -1},
            },
            useful_consume=useful,
        )

    if action == "drink":
        if agent.inventory.get("water", 0) <= 0:
            return ActionOutcome(
                action=action,
                success=False,
                message="no water in inventory",
            )

        before_thirst = agent.thirst
        agent.inventory["water"] -= 1
        reduction = int(rules_cfg["drink_thirst_reduction"])
        agent.thirst = max(0, agent.thirst - reduction)
        useful = before_thirst > agent.thirst
        return ActionOutcome(
            action=action,
            success=True,
            message="consumed water",
            world_delta={
                "thirst_before": before_thirst,
                "thirst_after": agent.thirst,
                "inventory_delta": {"water": -1},
            },
            useful_consume=useful,
        )

    if action == "rest":
        before_energy = agent.energy
        gain = int(rules_cfg["rest_energy_gain"])
        energy_max = int(rules_cfg["energy_max"])
        agent.energy = min(energy_max, agent.energy + gain)
        return ActionOutcome(
            action=action,
            success=True,
            message="rested",
            world_delta={"energy_before": before_energy, "energy_after": agent.energy},
        )

    if action == "wait":
        return ActionOutcome(
            action=action,
            success=True,
            message="waited",
            world_delta={},
        )

    raise ValueError(f"unsupported action: {action}")
