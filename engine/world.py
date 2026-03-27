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
class NpcState:
    npc_id: str
    npc_type: str
    position: Position
    hp: int
    hostile: bool = False
    alive: bool = True


@dataclass
class WorldState:
    width: int
    height: int
    seed: int
    tiles: list[list[str]]
    agents: dict[str, AgentState]
    npcs: dict[str, NpcState] = field(default_factory=dict)
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


def get_alive_npc_at(world: WorldState, x: int, y: int) -> NpcState | None:
    for npc in world.npcs.values():
        if not npc.alive:
            continue
        if npc.position.x == x and npc.position.y == y:
            return npc
    return None


def serialize_npcs(world: WorldState) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for npc_id in sorted(world.npcs.keys()):
        npc = world.npcs[npc_id]
        result.append(
            {
                "npc_id": npc.npc_id,
                "npc_type": npc.npc_type,
                "position": {"x": npc.position.x, "y": npc.position.y},
                "hp": int(npc.hp),
                "hostile": bool(npc.hostile),
                "alive": bool(npc.alive),
            }
        )
    return result


def create_world(
    seed: int,
    scenario_cfg: dict[str, Any],
    rules_cfg: dict[str, Any],
    agent_id: str = "agent_1",
) -> WorldState:
    width = int(scenario_cfg["width"])
    height = int(scenario_cfg["height"])

    distribution = dict(scenario_cfg.get("tile_distribution", {}))
    npc_distribution = dict(scenario_cfg.get("npc_distribution", {}))
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

    npc_count = sum(int(v) for v in npc_distribution.values())
    remaining_empty_positions = [pos for pos in empty_positions if pos != (start_x, start_y)]
    if npc_count > len(remaining_empty_positions):
        raise ValueError("npc_distribution exceeds available empty tiles after agent start")

    rng.shuffle(remaining_empty_positions)
    npc_cursor = 0
    npcs: dict[str, NpcState] = {}
    npc_idx = 1
    npc_start_hp = int(rules_cfg.get("npc_start_hp", 6))
    for npc_type, count in sorted(npc_distribution.items()):
        if not str(npc_type).strip():
            raise ValueError("npc_distribution contains empty npc type")
        for _ in range(int(count)):
            x, y = remaining_empty_positions[npc_cursor]
            npc_cursor += 1
            npc_id = f"npc_{npc_idx}"
            npc_idx += 1
            npcs[npc_id] = NpcState(
                npc_id=npc_id,
                npc_type=str(npc_type),
                position=Position(x, y),
                hp=npc_start_hp,
                hostile=False,
                alive=True,
            )

    return WorldState(
        width=width,
        height=height,
        seed=seed,
        tiles=tiles,
        agents={agent_id: agent},
        npcs=npcs,
    )
