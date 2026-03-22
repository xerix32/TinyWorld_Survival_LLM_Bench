from __future__ import annotations

from bench.common import load_yaml_file
from engine.world import count_tiles, create_world, serialize_tiles


def _scenario_and_rules() -> tuple[dict, dict]:
    benchmark_cfg = load_yaml_file("configs/benchmark.yaml")
    scenarios_cfg = load_yaml_file("configs/scenarios.yaml")
    scenario = scenarios_cfg["scenarios"]["v0_1_basic"]
    return scenario, benchmark_cfg["rules"]


def test_world_generation_is_deterministic_for_same_seed() -> None:
    scenario, rules_cfg = _scenario_and_rules()

    world_a = create_world(seed=42, scenario_cfg=scenario, rules_cfg=rules_cfg)
    world_b = create_world(seed=42, scenario_cfg=scenario, rules_cfg=rules_cfg)

    assert serialize_tiles(world_a) == serialize_tiles(world_b)
    assert world_a.agents["agent_1"].position == world_b.agents["agent_1"].position


def test_world_generation_changes_with_different_seed() -> None:
    scenario, rules_cfg = _scenario_and_rules()

    world_a = create_world(seed=42, scenario_cfg=scenario, rules_cfg=rules_cfg)
    world_b = create_world(seed=43, scenario_cfg=scenario, rules_cfg=rules_cfg)

    map_changed = serialize_tiles(world_a) != serialize_tiles(world_b)
    start_changed = world_a.agents["agent_1"].position != world_b.agents["agent_1"].position
    assert map_changed or start_changed


def test_world_distribution_matches_config() -> None:
    scenario, rules_cfg = _scenario_and_rules()
    world = create_world(seed=7, scenario_cfg=scenario, rules_cfg=rules_cfg)

    counts = count_tiles(world)

    assert counts["tree"] == 6
    assert counts["rock"] == 6
    assert counts["food"] == 4
    assert counts["water"] == 4
    assert counts["empty"] == 16
