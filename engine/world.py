"""World state and deterministic world generation."""

from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Any

TILE_EMPTY = "empty"
RESOURCE_TILE_TO_ITEM = {
    "tree": "wood",
    "rock": "stone",
    "food": "food",
    "water": "water",
}


@dataclass(frozen=True)
class Position:
    x: int
    y: int


@dataclass
class AgentState:
    agent_id: str
    position: Position
    energy: int
    hunger: int
    thirst: int
    inventory: dict[str, int] = field(default_factory=dict)
    score: int = 0
    alive: bool = True


@dataclass
class WorldState:
    width: int
    height: int
    seed: int
    tiles: list[list[str]]
    agents: dict[str, AgentState]
    turn: int = 0


def default_inventory() -> dict[str, int]:
    return {"wood": 0, "stone": 0, "food": 0, "water": 0}


def is_in_bounds(world: WorldState, x: int, y: int) -> bool:
    return 0 <= x < world.width and 0 <= y < world.height


def get_tile(world: WorldState, x: int, y: int) -> str:
    return world.tiles[y][x]


def set_tile(world: WorldState, x: int, y: int, tile_type: str) -> None:
    world.tiles[y][x] = tile_type


def serialize_tiles(world: WorldState) -> list[list[str]]:
    return [row[:] for row in world.tiles]


def count_tiles(world: WorldState) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in world.tiles:
        for tile_type in row:
            counts[tile_type] = counts.get(tile_type, 0) + 1
    return counts


def create_world(
    seed: int,
    scenario_cfg: dict[str, Any],
    rules_cfg: dict[str, Any],
    agent_id: str = "agent_1",
) -> WorldState:
    width = int(scenario_cfg["width"])
    height = int(scenario_cfg["height"])

    distribution = dict(scenario_cfg.get("tile_distribution", {}))
    total_cells = width * height
    total_resources = sum(int(v) for v in distribution.values())
    if total_resources > total_cells:
        raise ValueError("tile_distribution exceeds map size")

    invalid_tile_types = [tile for tile in distribution if tile not in RESOURCE_TILE_TO_ITEM]
    if invalid_tile_types:
        raise ValueError(f"unsupported tile types in distribution: {invalid_tile_types}")

    tiles = [[TILE_EMPTY for _ in range(width)] for _ in range(height)]
    positions = [(x, y) for y in range(height) for x in range(width)]

    rng = random.Random(seed)
    rng.shuffle(positions)

    cursor = 0
    for tile_type, count in distribution.items():
        for _ in range(int(count)):
            if cursor >= len(positions):
                raise ValueError("not enough map cells for distribution")
            x, y = positions[cursor]
            cursor += 1
            tiles[y][x] = tile_type

    empty_positions = [(x, y) for y in range(height) for x in range(width) if tiles[y][x] == TILE_EMPTY]
    if not empty_positions:
        raise ValueError("no empty tile available for agent start")

    start_x, start_y = rng.choice(empty_positions)
    agent = AgentState(
        agent_id=agent_id,
        position=Position(start_x, start_y),
        energy=int(rules_cfg["start_energy"]),
        hunger=int(rules_cfg["start_hunger"]),
        thirst=int(rules_cfg["start_thirst"]),
        inventory=default_inventory(),
    )

    return WorldState(
        width=width,
        height=height,
        seed=seed,
        tiles=tiles,
        agents={agent_id: agent},
    )
