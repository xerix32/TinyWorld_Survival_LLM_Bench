from __future__ import annotations

from pathlib import Path

import yaml

from bench.common import load_yaml_file, run_match_once


# Expected values for deterministic seed/model/config in v0.1.
EXPECTED_FINAL_SCORE = 16
EXPECTED_TURNS_SURVIVED = 21
EXPECTED_INVALID_ACTIONS = 0


def test_run_match_is_reproducible_for_fixed_seed(tmp_path: Path) -> None:
    run_a = run_match_once(
        seed=7,
        model_name="dummy",
        scenario_name="v0_1_basic",
        output_path=tmp_path / "run_a.json",
    )
    run_b = run_match_once(
        seed=7,
        model_name="dummy",
        scenario_name="v0_1_basic",
        output_path=tmp_path / "run_b.json",
    )

    summary_a = run_a["run_summary"]
    summary_b = run_b["run_summary"]

    assert summary_a["final_score"] == EXPECTED_FINAL_SCORE
    assert summary_a["turns_survived"] == EXPECTED_TURNS_SURVIVED
    assert summary_a["invalid_actions"] == EXPECTED_INVALID_ACTIONS

    assert summary_b["final_score"] == EXPECTED_FINAL_SCORE
    assert summary_b["turns_survived"] == EXPECTED_TURNS_SURVIVED
    assert summary_b["invalid_actions"] == EXPECTED_INVALID_ACTIONS

    identity_a = run_a.get("benchmark_identity", {})
    assert identity_a.get("engine_version") == run_a.get("engine_version")
    assert identity_a.get("bench_version") == run_a.get("version")
    assert isinstance(identity_a.get("prompt_set_sha256"), str)
    assert len(identity_a["prompt_set_sha256"]) == 64

    assert summary_a.get("end_reason_human")
    assert summary_a.get("prompt_set_sha256") == identity_a.get("prompt_set_sha256")
    assert summary_a.get("death_cause") is not None
    assert summary_a.get("death_cause_human") is not None
    assert summary_a.get("analysis_version") == "AIB-AN-AIB-0.2.1-v1"
    assert summary_a.get("analysis_schema_version") == "AIB-RA-AIB-0.2.1-v1"
    assert isinstance(summary_a.get("kpi"), dict)
    assert isinstance(summary_a.get("failure_archetypes"), list)
    assert summary_a.get("primary_failure_archetype")
    assert summary_a.get("primary_failure_archetype_human")
    assert summary_a.get("short_summary")
    assert summary_a.get("detailed_summary")
    assert summary_a.get("analysis_path")
    assert isinstance(summary_a.get("token_breakdown"), dict)
    assert isinstance(summary_a.get("pricing_ref"), dict)
    assert summary_a["pricing_ref"].get("provider_id") == "dummy_provider"

    kpi_a = summary_a["kpi"]
    assert "unique_cells_visited" in kpi_a
    assert "coverage_pct" in kpi_a
    assert "revisit_ratio" in kpi_a
    assert "resource_conversion_efficiency_pct" in kpi_a
    assert "distance_per_useful_gain" in kpi_a
    assert kpi_a.get("moral_kpi_enabled") is False
    assert kpi_a.get("moral_aggression_index") is None


def test_run_match_pvp_duel_smoke(tmp_path: Path) -> None:
    run_log = run_match_once(
        seed=5,
        model_name="dummy",
        scenario_name="v0_2_pvp_duel",
        max_turns=12,
        output_path=tmp_path / "run_pvp.json",
    )

    summary = run_log["run_summary"]
    assert summary.get("pvp_duel") is True
    assert int(summary.get("opponent_agent_count") or 0) >= 1
    assert summary.get("opponent_model_profile") is not None
    assert summary.get("opponent_model") is not None
    assert int(summary.get("attack_npc_count") or 0) >= 0
    assert int(summary.get("attack_rival_count") or 0) >= 0
    assert int(summary.get("rival_kills") or 0) >= 0
    initial_npcs = run_log.get("world_snapshots", {}).get("initial_npcs", [])
    assert isinstance(initial_npcs, list)
    assert len(initial_npcs) >= 1
    assert summary.get("end_reason") in {"agent_dead", "opponent_defeated", "max_turns_reached"}
    assert summary.get("end_reason_human")


def test_run_match_moral_kpi_enabled(tmp_path: Path) -> None:
    run_log = run_match_once(
        seed=9,
        model_name="dummy_v0_1",
        scenario_name="v0_2_pvp_duel",
        max_turns=10,
        output_path=tmp_path / "run_pvp_moral.json",
        moral_mode=True,
    )
    summary = run_log["run_summary"]
    kpi = summary.get("kpi") or {}
    assert bool(summary.get("moral_mode")) is True
    assert bool(kpi.get("moral_kpi_enabled")) is True
    assert kpi.get("moral_aggression_index") is not None
    assert kpi.get("moral_restraint_score") is not None
    assert isinstance(kpi.get("moral_aggression_band"), str)


def test_run_match_pvp_supports_opponent_model_override(tmp_path: Path) -> None:
    providers_cfg = load_yaml_file("configs/providers.yaml")
    profiles = dict(providers_cfg.get("model_profiles", {}))
    profiles["dummy_v0_1_b"] = {
        "provider": "dummy_provider",
        "model_name": "dummy_random_v0_1_b",
    }
    providers_cfg["model_profiles"] = profiles
    providers_cfg_path = tmp_path / "providers.test.yaml"
    providers_cfg_path.write_text(yaml.safe_dump(providers_cfg, sort_keys=False), encoding="utf-8")

    run_log = run_match_once(
        seed=11,
        model_name="dummy_v0_1",
        opponent_model_name="dummy_v0_1_b",
        scenario_name="v0_2_pvp_duel",
        max_turns=8,
        providers_config_path=providers_cfg_path,
        output_path=tmp_path / "run_pvp_vs.json",
    )
    summary = run_log["run_summary"]
    assert summary.get("model_profile") == "dummy_v0_1"
    assert summary.get("opponent_model_profile") == "dummy_v0_1_b"
