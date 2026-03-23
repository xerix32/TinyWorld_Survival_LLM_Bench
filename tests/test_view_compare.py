from __future__ import annotations

import json
from pathlib import Path

from bench.view_compare import generate_compare_viewer


def test_generate_compare_viewer_html(tmp_path: Path) -> None:
    compare_payload = {
        "meta": {
            "compare_id": "20260322T000000Z",
            "protocol_version": "AIB-0.1",
            "bench_version": "0.1.14",
            "engine_version": "0.1.14",
            "scenario": "v0_1_basic",
            "seed_list": [1],
            "models": ["dummy_v0_1"],
            "runs_per_model": 1,
            "total_runs": 1,
            "paired_seeds": True,
            "prompt_set_sha256": "abc123",
            "compatibility": {
                "status": "warning",
                "warnings": [
                    {"code": "mixed_engine_version", "message": "Mixed engine versions: 0.1.20, 0.1.27"}
                ],
            },
        },
        "models": [
            {
                "rank": 1,
                "model_profile": "dummy_v0_1",
                "provider_id": "dummy_provider",
                "model": "dummy_random_v0_1",
                "runs": 1,
                "avg_final_score": 10.0,
                "avg_turns_survived": 8.0,
                "avg_survival_pct": 16.0,
                "avg_invalid_actions": 0.0,
                "avg_resources_gathered": 1.0,
                "death_rate_pct": 0.0,
                "latency_ms_total": 1000.0,
                "latency_ms_avg": 1000.0,
                "tokens_used_total": 100,
                "estimated_cost_total": None,
                "max_turns_avg": 50,
            }
        ],
        "pairwise": [],
        "runs": [
            {
                "run_id": "dummy_v0_1__seed1",
                "model_profile": "dummy_v0_1",
                "provider_id": "dummy_provider",
                "model": "dummy_random_v0_1",
                "seed": 1,
                "summary": {
                    "final_score": 10,
                    "turns_survived": 8,
                    "max_turns": 50,
                    "invalid_actions": 0,
                    "resources_gathered": 1,
                    "latency_ms": 1000,
                    "tokens_used": 100,
                    "end_reason": "max_turns_reached",
                    "end_reason_human": "Reached the configured turn limit (50).",
                },
                "replay": {
                    "meta": {"map_coverage": "full"},
                    "protocol": {"rules": {"energy_max": 100, "hunger_max": 100, "thirst_max": 100}},
                    "world": {"width": 2, "height": 2},
                    "frames": [
                        {
                            "turn": 1,
                            "observation": {
                                "energy": 80,
                                "hunger": 20,
                                "thirst": 20,
                                "inventory": {"wood": 0, "stone": 0, "food": 0, "water": 0},
                            },
                            "agent_position_before": {"x": 0, "y": 0},
                            "agent_position_after": {"x": 0, "y": 0},
                            "map_snapshot": [["empty", "tree"], ["rock", "water"]],
                            "path_prefix": [{"x": 0, "y": 0}],
                            "action_result": {"requested": "inspect", "message": "inspected", "success": True},
                            "validation_result": {"is_valid": True},
                            "score_delta": {"total": 1, "events": ["survive_turn"]},
                            "cumulative_score": 1,
                            "metrics": {"latency_ms": 1000, "tokens_used": 100, "estimated_cost": None},
                            "raw_model_output": "inspect",
                        }
                    ],
                },
            }
        ],
    }

    compare_path = tmp_path / "compare.json"
    compare_path.write_text(json.dumps(compare_payload), encoding="utf-8")

    output_html = tmp_path / "compare_dashboard.html"
    generated = generate_compare_viewer(compare_path=compare_path, output_path=output_html, title="Compare Viewer Test")

    assert generated == output_html
    assert output_html.exists()

    rendered = output_html.read_text(encoding="utf-8")
    assert "Compare Dashboard" in rendered
    assert "Compare Viewer Test" in rendered
    assert "Run Browser" in rendered
    assert "Turn Timeline" in rendered
    assert "dummy_v0_1" in rendered
    assert "Mixed engine versions" in rendered
