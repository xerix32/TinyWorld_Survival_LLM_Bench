from __future__ import annotations

import sys
from pathlib import Path

import yaml

from bench.common import load_yaml_file
from bench.run_compare import (
    build_model_summaries,
    build_pairwise_summary,
    main,
    resolve_seed_list,
)


def _row(
    *,
    model_profile: str,
    seed: int,
    final_score: int,
    turns_survived: int,
    invalid_actions: int,
    end_reason: str,
) -> dict[str, object]:
    return {
        "model_profile": model_profile,
        "provider_id": "provider_x",
        "model": f"model_{model_profile}",
        "seed": seed,
        "final_score": final_score,
        "turns_survived": turns_survived,
        "invalid_actions": invalid_actions,
        "resources_gathered": 3,
        "max_turns": 50,
        "end_reason": end_reason,
        "latency_ms": 1000.0,
        "tokens_used": 100,
        "estimated_cost": None,
    }


def test_resolve_seed_list_explicit_overrides_range() -> None:
    explicit = resolve_seed_list("7,8,9", num_runs=5, seed_start=1)
    assert explicit == [7, 8, 9]

    ranged = resolve_seed_list(None, num_runs=4, seed_start=3)
    assert ranged == [3, 4, 5, 6]


def test_build_model_summaries_ranking_tiebreaks() -> None:
    rows = [
        _row(model_profile="z_model", seed=1, final_score=10, turns_survived=8, invalid_actions=0, end_reason="max_turns_reached"),
        _row(model_profile="z_model", seed=2, final_score=10, turns_survived=8, invalid_actions=0, end_reason="max_turns_reached"),
        _row(model_profile="a_model", seed=1, final_score=10, turns_survived=7, invalid_actions=0, end_reason="max_turns_reached"),
        _row(model_profile="a_model", seed=2, final_score=10, turns_survived=7, invalid_actions=0, end_reason="max_turns_reached"),
    ]

    summaries = build_model_summaries(rows)

    assert summaries[0]["model_profile"] == "z_model"
    assert summaries[0]["rank"] == 1
    assert summaries[1]["model_profile"] == "a_model"
    assert summaries[1]["rank"] == 2


def test_build_pairwise_summary_on_paired_seeds() -> None:
    rows = [
        _row(model_profile="model_a", seed=1, final_score=10, turns_survived=8, invalid_actions=0, end_reason="max_turns_reached"),
        _row(model_profile="model_a", seed=2, final_score=8, turns_survived=7, invalid_actions=0, end_reason="max_turns_reached"),
        _row(model_profile="model_b", seed=1, final_score=9, turns_survived=8, invalid_actions=0, end_reason="max_turns_reached"),
        _row(model_profile="model_b", seed=2, final_score=9, turns_survived=7, invalid_actions=0, end_reason="max_turns_reached"),
    ]

    pairwise = build_pairwise_summary(rows, model_profiles=["model_a", "model_b"], seed_list=[1, 2])

    assert len(pairwise) == 1
    row = pairwise[0]
    assert row["model_a_profile"] == "model_a"
    assert row["model_b_profile"] == "model_b"
    assert row["paired_runs"] == 2
    assert row["wins_a"] == 1
    assert row["wins_b"] == 1
    assert row["ties"] == 0
    assert row["win_rate_a_vs_b"] == 50.0
    assert row["avg_delta_a_minus_b"] == 0.0


def test_run_compare_smoke_dummy_cli(tmp_path: Path, monkeypatch) -> None:
    benchmark_cfg = load_yaml_file("configs/benchmark.yaml")
    benchmark_cfg["logging"]["logs_dir"] = str((tmp_path / "logs").resolve())
    benchmark_cfg["logging"]["results_dir"] = str((tmp_path / "results").resolve())
    benchmark_cfg["logging"]["replays_dir"] = str((tmp_path / "replays").resolve())

    benchmark_cfg_path = tmp_path / "benchmark.test.yaml"
    benchmark_cfg_path.write_text(yaml.safe_dump(benchmark_cfg, sort_keys=False), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_compare",
            "--models",
            "dummy_v0_1",
            "--num-runs",
            "2",
            "--seed-start",
            "1",
            "--max-turns",
            "8",
            "--benchmark-config",
            str(benchmark_cfg_path),
            "--scenarios-config",
            str(Path("configs/scenarios.yaml").resolve()),
            "--providers-config",
            str(Path("configs/providers.yaml").resolve()),
            "--prompts-dir",
            str(Path("prompts").resolve()),
            "--no-open-viewer",
            "--no-color",
        ],
    )

    main()

    results_dir = tmp_path / "results"
    replays_dir = tmp_path / "replays"

    assert list(results_dir.glob("compare_runs_*.csv"))
    assert list(results_dir.glob("compare_models_*.csv"))
    assert list(results_dir.glob("compare_h2h_*.csv"))
    assert list(results_dir.glob("compare_*.json"))
    assert list(replays_dir.glob("compare_*_dashboard.html"))
