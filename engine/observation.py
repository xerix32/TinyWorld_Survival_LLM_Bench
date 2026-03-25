"""Observation builder for benchmark prompts and logs."""

from __future__ import annotations

from typing import Any

from engine.world import WorldState, get_tile, is_in_bounds


UNKNOWN_TILE = "unknown"


def get_visible_tiles(
    world: WorldState,
    *,
    x: int,
    y: int,
) -> list[dict[str, Any]]:
    visible_tiles: list[dict[str, Any]] = []
    for tile_y in range(y - 1, y + 2):
        for tile_x in range(x - 1, x + 2):
            if not is_in_bounds(world, tile_x, tile_y):
                continue
            visible_tiles.append({"x": tile_x, "y": tile_y, "type": get_tile(world, tile_x, tile_y)})
    return visible_tiles


def _build_known_map(
    world: WorldState,
    *,
    discovered_tiles: dict[tuple[int, int], str] | None,
    visible_tiles: list[dict[str, Any]],
    agent_x: int,
    agent_y: int,
    path_last_steps: list[dict[str, int]] | None,
) -> dict[str, Any]:
    known_tiles = dict(discovered_tiles or {})
    for tile in visible_tiles:
        tile_x = int(tile["x"])
        tile_y = int(tile["y"])
        known_tiles[(tile_x, tile_y)] = str(tile["type"])

    grid: list[list[str]] = []
    known_cells = 0
    unknown_cells = 0
    for row_y in range(world.height):
        row: list[str] = []
        for col_x in range(world.width):
            tile_type = known_tiles.get((col_x, row_y), UNKNOWN_TILE)
            if tile_type == UNKNOWN_TILE:
                unknown_cells += 1
            else:
                known_cells += 1
            row.append(tile_type)
        grid.append(row)

    return {
        "width": world.width,
        "height": world.height,
        "agent_position": {"x": agent_x, "y": agent_y},
        "known_cells": known_cells,
        "unknown_cells": unknown_cells,
        "grid": grid,
        "path_last_steps": list(path_last_steps or []),
    }


def build_observation(
    world: WorldState,
    agent_id: str,
    allowed_actions: list[str],
    protocol_version: str,
    *,
    recent_turns: list[dict[str, Any]] | None = None,
    recent_discoveries: list[dict[str, Any]] | None = None,
    discovered_tiles: dict[tuple[int, int], str] | None = None,
    path_last_steps: list[dict[str, int]] | None = None,
    visible_tiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    agent = world.agents[agent_id]

    effective_visible_tiles = (
        list(visible_tiles)
        if visible_tiles is not None
        else get_visible_tiles(world, x=agent.position.x, y=agent.position.y)
    )

    inventory = {
        "wood": int(agent.inventory.get("wood", 0)),
        "stone": int(agent.inventory.get("stone", 0)),
        "food": int(agent.inventory.get("food", 0)),
        "water": int(agent.inventory.get("water", 0)),
    }

    known_map = _build_known_map(
        world,
        discovered_tiles=discovered_tiles,
        visible_tiles=effective_visible_tiles,
        agent_x=agent.position.x,
        agent_y=agent.position.y,
        path_last_steps=path_last_steps,
    )

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
        "visible_tiles": effective_visible_tiles,
        "recent_turns": list(recent_turns or []),
        "recent_discoveries": list(recent_discoveries or []),
        "known_map": known_map,
        "score": agent.score,
        "allowed_actions": list(allowed_actions),
    }
