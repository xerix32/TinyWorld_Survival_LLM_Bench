"""Human-readable rendering for manual CLI play."""

from __future__ import annotations

from typing import Any


def render_turn_view(observation: dict[str, Any]) -> str:
    pos = observation["position"]
    inventory = observation["inventory"]

    tile_lookup = {(tile["x"], tile["y"]): tile["type"] for tile in observation["visible_tiles"]}

    def nearby(dx: int, dy: int) -> str:
        x = pos["x"] + dx
        y = pos["y"] + dy
        return tile_lookup.get((x, y), "wall")

    lines = [
        f"Turn {observation['turn']}",
        f"You are at ({pos['x']},{pos['y']})",
        f"Energy: {observation['energy']}  Hunger: {observation['hunger']}  Thirst: {observation['thirst']}",
        (
            "Inventory: "
            f"wood={inventory.get('wood', 0)} "
            f"stone={inventory.get('stone', 0)} "
            f"food={inventory.get('food', 0)} "
            f"water={inventory.get('water', 0)}"
        ),
        "",
        "Nearby:",
        f"north: {nearby(0, -1)}",
        f"east: {nearby(1, 0)}",
        f"south: {nearby(0, 1)}",
        f"west: {nearby(-1, 0)}",
        "",
        "Allowed actions:",
    ]

    lines.extend(observation["allowed_actions"])
    return "\n".join(lines)
