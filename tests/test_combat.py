from __future__ import annotations

from bench.common import load_yaml_file
from engine.actions import apply_action
from engine.rules import compute_allowed_actions
from engine.world import Position, create_world, get_alive_npc_at


def _combat_world(seed: int = 7):
    benchmark_cfg = load_yaml_file("configs/benchmark.yaml")
    scenarios_cfg = load_yaml_file("configs/scenarios.yaml")
    scenario = scenarios_cfg["scenarios"]["v0_2_hunt"]
    rules_cfg = benchmark_cfg["rules"]
    world = create_world(seed=seed, scenario_cfg=scenario, rules_cfg=rules_cfg)
    return world, rules_cfg


def test_attack_allowed_only_when_npc_on_current_tile() -> None:
    world, rules_cfg = _combat_world(seed=3)
    agent = world.agents["agent_1"]

    # Agent starts on empty tile with no NPC.
    allowed_start = compute_allowed_actions(world, "agent_1", rules_cfg)
    assert "attack" not in allowed_start

    # Move agent onto first NPC tile.
    npc = next(iter(world.npcs.values()))
    agent.position = Position(npc.position.x, npc.position.y)
    allowed_on_npc = compute_allowed_actions(world, "agent_1", rules_cfg)
    assert "attack" in allowed_on_npc


def test_attack_two_hits_kills_npc_and_drops_food() -> None:
    world, rules_cfg = _combat_world(seed=5)
    agent = world.agents["agent_1"]
    npc = next(iter(world.npcs.values()))
    agent.position = Position(npc.position.x, npc.position.y)

    assert agent.energy == int(rules_cfg["start_energy"])
    assert npc.hp == int(rules_cfg["npc_start_hp"])

    first = apply_action(world, "agent_1", "attack", rules_cfg)
    assert first.success is True
    assert first.world_delta["npc_killed"] is False
    assert first.world_delta["counter_applied"] is True
    assert first.world_delta["npc_hp_after"] == int(rules_cfg["npc_start_hp"]) - int(rules_cfg["attack_damage"])
    assert agent.energy == int(rules_cfg["start_energy"]) - int(rules_cfg["attack_energy_cost"]) - int(
        rules_cfg["npc_counter_damage"]
    )

    second = apply_action(world, "agent_1", "attack", rules_cfg)
    assert second.success is True
    assert second.world_delta["npc_killed"] is True
    assert second.world_delta["counter_applied"] is False
    assert second.world_delta["npc_hp_after"] == 0
    assert agent.inventory["food"] >= int(rules_cfg["npc_drop_food"])

    npc_after = get_alive_npc_at(world, agent.position.x, agent.position.y)
    assert npc_after is None


def test_attack_fails_cleanly_when_no_npc_present() -> None:
    world, rules_cfg = _combat_world(seed=11)
    agent = world.agents["agent_1"]

    assert get_alive_npc_at(world, agent.position.x, agent.position.y) is None
    outcome = apply_action(world, "agent_1", "attack", rules_cfg)
    assert outcome.success is False
    assert outcome.message == "no npc on current tile"
