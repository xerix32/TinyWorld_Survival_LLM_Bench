"""Observation builder for benchmark prompts and logs."""

from __future__ import annotations

from typing import Any

from engine.world import WorldState, get_tile, is_in_bounds


def build_observation(
    world: WorldState,
    agent_id: str,
    allowed_actions: list[str],
    protocol_version: str,
) -> dict[str, Any]:
    agent = world.agents[agent_id]

    visible_tiles: list[dict[str, Any]] = []
    for y in range(agent.position.y - 1, agent.position.y + 2):
        for x in range(agent.position.x - 1, agent.position.x + 2):
            if not is_in_bounds(world, x, y):
                continue
            visible_tiles.append({"x": x, "y": y, "type": get_tile(world, x, y)})

    inventory = {
        "wood": int(agent.inventory.get("wood", 0)),
        "stone": int(agent.inventory.get("stone", 0)),
        "food": int(agent.inventory.get("food", 0)),
        "water": int(agent.inventory.get("water", 0)),
    }

    return {
        "protocol_version": protocol_version,
        "turn": world.turn,
        "agent_id": agent.agent_id,
        "alive": agent.alive,
        "position": {"x": agent.position.x, "y": agent.position.y},
        "energy": agent.energy,
        "hunger": agent.hunger,
        "thirst": agent.thirst,
        "inventory": inventory,
        "visible_tiles": visible_tiles,
        "score": agent.score,
        "allowed_actions": list(allowed_actions),
    }
