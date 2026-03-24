from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import yaml

from bench.common import load_yaml_file, run_match_once
from bench.run_compare import (
    _build_compatibility_report,
    _build_jobs,
    _build_from_logs,
    _compare_paths,
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


def test_build_jobs_stable_order() -> None:
    jobs = _build_jobs(["model_a", "model_b"], [11, 12])

    assert [job.job_index for job in jobs] == [1, 2, 3, 4]
    assert [(job.model_profile, job.seed) for job in jobs] == [
        ("model_a", 11),
        ("model_a", 12),
        ("model_b", 11),
        ("model_b", 12),
    ]


def test_compare_paths_supports_legacy_dirs_without_checkpoint(tmp_path: Path) -> None:
    results_dir = (tmp_path / "results").resolve()
    results_dir.mkdir(parents=True, exist_ok=True)
    paths = _compare_paths({"results": results_dir}, "abc123")
    assert paths["checkpoint_json"] == results_dir / "compare_state.json"


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


def test_build_compatibility_report_detects_mixed_versions() -> None:
    rows = [
        {
            "protocol_version": "AIB-0.1.1",
            "prompt_set_sha256": "hash_a",
            "bench_version": "0.1.20",
            "engine_version": "0.1.20",
        },
        {
            "protocol_version": "AIB-0.1.1",
            "prompt_set_sha256": "hash_b",
            "bench_version": "0.1.27",
            "engine_version": "0.1.27",
        },
    ]

    report = _build_compatibility_report(rows, fallback_protocol_version="AIB-0.1.1")
    assert report["status"] == "warning"
    warning_codes = {warning["code"] for warning in report["warnings"]}
    assert "mixed_prompt_hash" in warning_codes
    assert "mixed_bench_version" in warning_codes
    assert "mixed_engine_version" in warning_codes


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
            "--runs-root",
            str((tmp_path / "runs").resolve()),
            "--no-open-viewer",
            "--no-color",
        ],
    )

    main()

    run_roots = sorted((tmp_path / "runs").glob("*"))
    assert run_roots
    results_dir = run_roots[-1] / "results"
    replays_dir = run_roots[-1] / "replays"

    assert list(results_dir.glob("compare_runs_*.csv"))
    assert list(results_dir.glob("compare_models_*.csv"))
    assert list(results_dir.glob("compare_h2h_*.csv"))
    assert list(results_dir.glob("compare_*.json"))
    assert list(replays_dir.glob("compare_*_dashboard.html"))


def test_run_compare_from_logs_mode(tmp_path: Path, monkeypatch) -> None:
    benchmark_cfg = load_yaml_file("configs/benchmark.yaml")
    benchmark_cfg["logging"]["logs_dir"] = str((tmp_path / "logs").resolve())
    benchmark_cfg["logging"]["results_dir"] = str((tmp_path / "results").resolve())
    benchmark_cfg["logging"]["replays_dir"] = str((tmp_path / "replays").resolve())

    benchmark_cfg_path = tmp_path / "benchmark.test.yaml"
    benchmark_cfg_path.write_text(yaml.safe_dump(benchmark_cfg, sort_keys=False), encoding="utf-8")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    run_match_once(seed=1, model_name="dummy_v0_1", output_path=logs_dir / "run_seed1.json")
    run_match_once(seed=2, model_name="dummy_v0_1", output_path=logs_dir / "run_seed2.json")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_compare",
            "--from-logs-glob",
            "logs/run_seed*.json",
            "--benchmark-config",
            str(benchmark_cfg_path),
            "--scenarios-config",
            str(Path("configs/scenarios.yaml").resolve()),
            "--providers-config",
            str(Path("configs/providers.yaml").resolve()),
            "--prompts-dir",
            str(Path("prompts").resolve()),
            "--runs-root",
            str((tmp_path / "runs").resolve()),
            "--no-open-viewer",
            "--no-color",
        ],
    )

    main()

    run_roots = sorted((tmp_path / "runs").glob("*"))
    assert run_roots
    results_dir = run_roots[-1] / "results"
    replays_dir = run_roots[-1] / "replays"
    assert list(results_dir.glob("compare_runs_*.csv"))
    assert list(results_dir.glob("compare_models_*.csv"))
    assert list(results_dir.glob("compare_h2h_*.csv"))
    assert list(results_dir.glob("compare_*.json"))
    assert list(replays_dir.glob("compare_*_dashboard.html"))


def test_run_compare_resume_from_checkpoint(tmp_path: Path, monkeypatch) -> None:
    benchmark_cfg = load_yaml_file("configs/benchmark.yaml")
    benchmark_cfg["logging"]["logs_dir"] = str((tmp_path / "logs").resolve())
    benchmark_cfg["logging"]["results_dir"] = str((tmp_path / "results").resolve())
    benchmark_cfg["logging"]["replays_dir"] = str((tmp_path / "replays").resolve())

    benchmark_cfg_path = tmp_path / "benchmark.test.yaml"
    benchmark_cfg_path.write_text(yaml.safe_dump(benchmark_cfg, sort_keys=False), encoding="utf-8")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    seed1_log = logs_dir / "run_seed1.json"
    run_match_once(seed=1, model_name="dummy_v0_1", output_path=seed1_log)

    compare_id = "resume_test"
    run_rows, run_payloads, _, _, scenario, protocol_version = _build_from_logs(compare_id=compare_id, log_paths=[seed1_log])
    for idx, row in enumerate(run_rows, start=1):
        row["job_index"] = idx
        row["job_total"] = 2

    run_root = (tmp_path / "runs" / compare_id).resolve()
    dirs = {
        "logs": run_root / "logs",
        "results": run_root / "results",
        "replays": run_root / "replays",
        "checkpoint": run_root / "checkpoint",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    paths = _compare_paths(dirs, compare_id)
    checkpoint_path = paths["checkpoint_json"]
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_payload = {
        "schema": "tinyworld_compare_state_v1",
        "status": "running",
        "compare_id": compare_id,
        "requested_models": ["dummy_v0_1"],
        "seed_list": [1, 2],
        "scenario": scenario,
        "protocol_version": protocol_version,
        "paths": {key: str(value) for key, value in paths.items()},
        "resume_context": {
            "benchmark_config": str(benchmark_cfg_path.resolve()),
            "scenarios_config": str(Path("configs/scenarios.yaml").resolve()),
            "providers_config": str(Path("configs/providers.yaml").resolve()),
            "prompts_dir": str(Path("prompts").resolve()),
            "scenario_arg": scenario,
            "max_turns": 8,
            "run_id": compare_id,
            "runs_root": str((tmp_path / "runs").resolve()),
        },
        "run_rows": run_rows,
        "run_payloads": run_payloads,
    }
    checkpoint_path.write_text(json.dumps(checkpoint_payload), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_compare",
            "--resume",
            str(checkpoint_path),
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
            "--runs-root",
            str((tmp_path / "runs").resolve()),
            "--no-open-viewer",
            "--no-color",
        ],
    )

    main()

    runs_csv = paths["runs_csv"]
    with runs_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2


def test_run_compare_adaptive_memory_smoke(tmp_path: Path, monkeypatch) -> None:
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
            "--adaptive-memory",
            "--benchmark-config",
            str(benchmark_cfg_path),
            "--scenarios-config",
            str(Path("configs/scenarios.yaml").resolve()),
            "--providers-config",
            str(Path("configs/providers.yaml").resolve()),
            "--prompts-dir",
            str(Path("prompts").resolve()),
            "--runs-root",
            str((tmp_path / "runs").resolve()),
            "--no-viewer",
            "--no-color",
        ],
    )

    main()

    run_roots = sorted((tmp_path / "runs").glob("*"))
    assert run_roots
    run_root = run_roots[-1]
    results_dir = run_root / "results"
    logs_dir = run_root / "logs"

    compare_json = next(results_dir.glob("compare_*.json"))
    payload = json.loads(compare_json.read_text(encoding="utf-8"))
    assert isinstance(payload.get("adaptive"), dict)
    assert payload["adaptive"].get("enabled") is True
    assert payload.get("meta", {}).get("adaptive_aggregate_score") is not None

    with next(results_dir.glob("compare_runs_*.csv")).open("r", encoding="utf-8", newline="") as handle:
        baseline_rows = list(csv.DictReader(handle))
    with next(results_dir.glob("compare_runs_adaptive_*.csv")).open("r", encoding="utf-8", newline="") as handle:
        adaptive_rows = list(csv.DictReader(handle))
    with next(results_dir.glob("compare_adaptive_pairs_*.csv")).open("r", encoding="utf-8", newline="") as handle:
        pair_rows = list(csv.DictReader(handle))

    assert len(baseline_rows) == 2
    assert len(adaptive_rows) == 2
    assert len(pair_rows) == 2
    assert len(list(logs_dir.glob("*_initial.json"))) == 2
    assert len(list(logs_dir.glob("*_adaptive.json"))) == 2


def test_adaptive_initial_attempt_stays_memory_clean(tmp_path: Path, monkeypatch) -> None:
    benchmark_cfg = load_yaml_file("configs/benchmark.yaml")
    benchmark_cfg["logging"]["logs_dir"] = str((tmp_path / "logs").resolve())
    benchmark_cfg["logging"]["results_dir"] = str((tmp_path / "results").resolve())
    benchmark_cfg["logging"]["replays_dir"] = str((tmp_path / "replays").resolve())

    benchmark_cfg_path = tmp_path / "benchmark.test.yaml"
    benchmark_cfg_path.write_text(yaml.safe_dump(benchmark_cfg, sort_keys=False), encoding="utf-8")

    def _fake_seed_reflection(*, metadata: dict[str, object] | None = None, **_: object) -> dict[str, object]:
        seed = int((metadata or {}).get("seed", 0))
        return {
            "raw_output": f'["seed_{seed}_lesson"]',
            "parsed_lessons": [f"seed_{seed}_lesson"],
            "parse_error": None,
            "tokens_used": 1,
            "latency_ms": 1.0,
            "estimated_cost": None,
        }

    def _fake_cross_refinement(*, metadata: dict[str, object] | None = None, **_: object) -> dict[str, object]:
        seed = int((metadata or {}).get("seed", 0))
        return {
            "raw_output": f'["carry_{seed}_lesson"]',
            "parsed_lessons": [f"carry_{seed}_lesson"],
            "parse_error": None,
            "tokens_used": 1,
            "latency_ms": 1.0,
            "estimated_cost": None,
        }

    monkeypatch.setattr("bench.run_compare.run_seed_reflection", _fake_seed_reflection)
    monkeypatch.setattr("bench.run_compare.run_cross_seed_refinement", _fake_cross_refinement)

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
            "--adaptive-memory",
            "--benchmark-config",
            str(benchmark_cfg_path),
            "--scenarios-config",
            str(Path("configs/scenarios.yaml").resolve()),
            "--providers-config",
            str(Path("configs/providers.yaml").resolve()),
            "--prompts-dir",
            str(Path("prompts").resolve()),
            "--runs-root",
            str((tmp_path / "runs").resolve()),
            "--no-viewer",
            "--no-color",
        ],
    )

    main()

    run_roots = sorted((tmp_path / "runs").glob("*"))
    assert run_roots
    logs_dir = run_roots[-1] / "logs"

    seed2_initial = json.loads(
        (logs_dir / "run_seed2_dummy_v0_1_initial.json").read_text(encoding="utf-8")
    )
    seed2_adaptive = json.loads(
        (logs_dir / "run_seed2_dummy_v0_1_adaptive.json").read_text(encoding="utf-8")
    )

    initial_identity = dict(seed2_initial.get("benchmark_identity", {}))
    adaptive_identity = dict(seed2_adaptive.get("benchmark_identity", {}))
    assert int(initial_identity.get("memory_session_lesson_count") or 0) == 0
    assert int(initial_identity.get("memory_current_seed_lesson_count") or 0) == 0
    assert int(adaptive_identity.get("memory_session_lesson_count") or 0) >= 1
    assert int(adaptive_identity.get("memory_current_seed_lesson_count") or 0) >= 1


def test_run_compare_adaptive_resume_from_checkpoint(tmp_path: Path, monkeypatch) -> None:
    benchmark_cfg = load_yaml_file("configs/benchmark.yaml")
    benchmark_cfg["logging"]["logs_dir"] = str((tmp_path / "logs").resolve())
    benchmark_cfg["logging"]["results_dir"] = str((tmp_path / "results").resolve())
    benchmark_cfg["logging"]["replays_dir"] = str((tmp_path / "replays").resolve())
    benchmark_cfg_path = tmp_path / "benchmark.test.yaml"
    benchmark_cfg_path.write_text(yaml.safe_dump(benchmark_cfg, sort_keys=False), encoding="utf-8")

    compare_id = "adaptive_resume_test"
    run_root = (tmp_path / "runs" / compare_id).resolve()
    dirs = {
        "logs": run_root / "logs",
        "results": run_root / "results",
        "replays": run_root / "replays",
        "checkpoint": run_root / "checkpoint",
        "memory": run_root / "memory",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)

    seed1_pair_key = "dummy_v0_1__seed1"
    seed1_initial_log = dirs["logs"] / "run_seed1_dummy_v0_1_initial.json"
    seed1_adaptive_log = dirs["logs"] / "run_seed1_dummy_v0_1_adaptive.json"
    run_match_once(
        seed=1,
        model_name="dummy_v0_1",
        output_path=seed1_initial_log,
        attempt_kind="initial",
        adaptive_pair_key=seed1_pair_key,
    )
    run_match_once(
        seed=1,
        model_name="dummy_v0_1",
        output_path=seed1_adaptive_log,
        include_memory=True,
        memory_lessons=["Prioritize water when thirst pressure rises."],
        attempt_kind="adaptive_rerun",
        adaptive_pair_key=seed1_pair_key,
    )

    initial_rows, initial_payloads, _, _, scenario, protocol_version = _build_from_logs(
        compare_id=compare_id,
        log_paths=[seed1_initial_log],
    )
    adaptive_rows, _, _, _, _, _ = _build_from_logs(
        compare_id=compare_id,
        log_paths=[seed1_adaptive_log],
    )
    for row in initial_rows:
        row["job_index"] = 1
        row["job_total"] = 2
    for row in adaptive_rows:
        row["job_index"] = 1
        row["job_total"] = 2

    adaptive_pair_rows = [
        {
            "compare_id": compare_id,
            "model_profile": "dummy_v0_1",
            "seed": 1,
            "adaptive_pair_key": seed1_pair_key,
            "initial_score": int(initial_rows[0]["final_score"]),
            "adaptive_score": int(adaptive_rows[0]["final_score"]),
            "delta_score": int(adaptive_rows[0]["final_score"]) - int(initial_rows[0]["final_score"]),
            "initial_turns_survived": int(initial_rows[0]["turns_survived"]),
            "adaptive_turns_survived": int(adaptive_rows[0]["turns_survived"]),
            "delta_turns_survived": int(adaptive_rows[0]["turns_survived"]) - int(initial_rows[0]["turns_survived"]),
            "initial_invalid_actions": int(initial_rows[0]["invalid_actions"]),
            "adaptive_invalid_actions": int(adaptive_rows[0]["invalid_actions"]),
            "delta_invalid_actions": int(adaptive_rows[0]["invalid_actions"]) - int(initial_rows[0]["invalid_actions"]),
            "initial_resources_gathered": int(initial_rows[0]["resources_gathered"]),
            "adaptive_resources_gathered": int(adaptive_rows[0]["resources_gathered"]),
            "delta_resources_gathered": int(adaptive_rows[0]["resources_gathered"]) - int(initial_rows[0]["resources_gathered"]),
            "lessons_before_count": 0,
            "lessons_added_count": 1,
            "lessons_after_count": 1,
            "reflection_parse_error": None,
            "reflection_path": None,
            "memory_snapshot_path": None,
        }
    ]

    paths = _compare_paths(dirs, compare_id)
    checkpoint_payload = {
        "schema": "tinyworld_compare_state_v1",
        "status": "running",
        "compare_id": compare_id,
        "requested_models": ["dummy_v0_1"],
        "seed_list": [1, 2],
        "scenario": scenario,
        "protocol_version": protocol_version,
        "paths": {key: str(value) for key, value in paths.items()},
        "resume_context": {
            "benchmark_config": str(benchmark_cfg_path.resolve()),
            "scenarios_config": str(Path("configs/scenarios.yaml").resolve()),
            "providers_config": str(Path("configs/providers.yaml").resolve()),
            "prompts_dir": str(Path("prompts").resolve()),
            "scenario_arg": scenario,
            "max_turns": 8,
            "fix_thinking": False,
            "adaptive_memory": True,
            "seed_workers_per_model": 1,
            "run_id": compare_id,
            "runs_root": str((tmp_path / "runs").resolve()),
        },
        "run_rows": initial_rows,
        "run_payloads": initial_payloads,
        "adaptive_run_rows": adaptive_rows,
        "adaptive_pair_rows": adaptive_pair_rows,
        "adaptive_memory_by_model": {"dummy_v0_1": ["Prioritize water when thirst pressure rises."]},
    }
    paths["checkpoint_json"].write_text(json.dumps(checkpoint_payload), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_compare",
            "--resume",
            str(paths["checkpoint_json"]),
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
            "--runs-root",
            str((tmp_path / "runs").resolve()),
            "--no-viewer",
            "--no-color",
        ],
    )

    main()

    with paths["adaptive_pairs_csv"].open("r", encoding="utf-8", newline="") as handle:
        pair_rows = list(csv.DictReader(handle))
    assert len(pair_rows) == 2
