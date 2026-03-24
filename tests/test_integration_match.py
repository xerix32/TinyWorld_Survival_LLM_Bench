from __future__ import annotations

from pathlib import Path

from bench.common import run_match_once


# Expected values for deterministic seed/model/config in v0.1.
EXPECTED_FINAL_SCORE = 16
EXPECTED_TURNS_SURVIVED = 21
EXPECTED_INVALID_ACTIONS = 0


def test_run_match_is_reproducible_for_fixed_seed(tmp_path: Path) -> None:
    run_a = run_match_once(seed=7, model_name="dummy", output_path=tmp_path / "run_a.json")
    run_b = run_match_once(seed=7, model_name="dummy", output_path=tmp_path / "run_b.json")

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
    assert summary_a.get("analysis_version") == "AIB-AN-AIB-0.1.1-v1"
    assert summary_a.get("analysis_schema_version") == "AIB-RA-AIB-0.1.1-v1"
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
