from __future__ import annotations

import json
from pathlib import Path

from bench.common import _build_run_analytics, run_match_once


def test_run_analysis_is_deterministic_and_persisted(tmp_path: Path) -> None:
    run_a_path = tmp_path / "run_a.json"

    run_a = run_match_once(seed=7, model_name="dummy_v0_1", output_path=run_a_path)

    analysis_a = run_a.get("run_analysis")
    assert isinstance(analysis_a, dict)

    benchmark_cfg = run_a.get("config_snapshot", {}).get("benchmark", {})
    recomputed = _build_run_analytics(
        turn_logs=list(run_a.get("turn_logs", [])),
        run_summary=dict(run_a.get("run_summary", {})),
        rules_cfg=benchmark_cfg.get("rules", {}) if isinstance(benchmark_cfg, dict) else {},
        initial_tiles=run_a.get("world_snapshots", {}).get("initial_tiles", []),
        protocol_version=str(run_a.get("protocol_version", "AIB-0.1.1")),
    )
    assert recomputed.get("run_analysis") == analysis_a

    for key in [
        "final_facts",
        "behavior_metrics",
        "resource_metrics",
        "state_pressure_metrics",
        "outcome_helpers",
        "classification",
        "summaries",
    ]:
        assert key in analysis_a

    summary = run_a["run_summary"]
    analysis_path = Path(str(summary.get("analysis_path", "")))
    assert analysis_path.exists()

    sidecar = json.loads(analysis_path.read_text(encoding="utf-8"))
    assert isinstance(sidecar.get("run_analysis"), dict)
    assert sidecar["run_analysis"] == analysis_a
