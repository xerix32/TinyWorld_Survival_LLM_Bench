from __future__ import annotations

import json
from pathlib import Path

from bench.view_compare import generate_compare_viewer


def test_generate_compare_viewer_html(tmp_path: Path) -> None:
    compare_payload = {
        "meta": {
            "compare_id": "20260322T000000Z",
            "protocol_version": "AIB-0.1.1",
            "bench_version": "0.1.14",
            "engine_version": "0.1.14",
            "scenario": "v0_1_basic",
            "seed_list": [1],
            "models": ["dummy_v0_1"],
            "runs_per_model": 1,
            "total_runs": 1,
            "paired_seeds": True,
            "prompt_set_sha256": "abc123",
            "adaptive_aggregate_score": 12,
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
                            "action_result": {"requested": "wait", "message": "waited", "success": True},
                            "validation_result": {"is_valid": True},
                            "score_delta": {"total": 1, "events": ["survive_turn"]},
                            "cumulative_score": 1,
                            "metrics": {"latency_ms": 1000, "tokens_used": 100, "estimated_cost": None},
                            "raw_model_output": "wait",
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
    assert "adaptive total score" in rendered


def test_generate_compare_viewer_html_with_duel_view(tmp_path: Path) -> None:
    compare_payload = {
        "meta": {
            "compare_id": "20260327T000000Z",
            "protocol_version": "AIB-0.2.2",
            "bench_version": "0.2.43",
            "engine_version": "0.2.43",
            "scenario": "v0_2_pvp_duel",
            "seed_list": [1],
            "models": ["model_alpha", "model_beta"],
            "runs_per_model": 1,
            "total_runs": 2,
            "paired_seeds": True,
            "prompt_set_sha256": "def456",
            "compatibility": {"status": "ok", "warnings": []},
        },
        "models": [],
        "pairwise": [],
        "runs": [
            {
                "run_id": "model_alpha__seed1",
                "model_profile": "model_alpha",
                "provider_id": "dummy_provider",
                "model": "dummy_alpha",
                "seed": 1,
                "attempt_kind": "initial",
                "summary": {
                    "final_score": 12,
                    "turns_survived": 10,
                    "max_turns": 50,
                    "invalid_actions": 0,
                    "resources_gathered": 2,
                    "latency_ms": 1000,
                    "tokens_used": 100,
                    "end_reason": "max_turns_reached",
                    "pvp_duel": True,
                    "opponent_model_profile": "model_beta",
                },
                "replay": {
                    "meta": {"map_coverage": "full"},
                    "protocol": {"rules": {"energy_max": 100, "hunger_max": 100, "thirst_max": 100, "pvp_duel": True}},
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
                            "map_snapshot": [["empty", "water"], ["tree", "rock"]],
                            "path_prefix": [{"x": 0, "y": 0}],
                            "action_result": {"requested": "move east", "message": "move applied", "success": True},
                            "validation_result": {"is_valid": True},
                            "score_delta": {"total": 1, "events": ["survive_turn"]},
                            "cumulative_score": 1,
                            "metrics": {"latency_ms": 1000, "tokens_used": 100},
                            "raw_model_output": "move east",
                            "opponent_steps": [
                                {
                                    "model_profile": "model_beta",
                                    "parsed_action": "wait",
                                    "position_after": {"x": 1, "y": 1},
                                    "energy_after": 79,
                                    "alive_after": True,
                                    "inventory_after": {"wood": 0, "stone": 0, "food": 0, "water": 0},
                                    "validation_result": {"is_valid": True},
                                    "action_result": {"requested": "wait", "success": True, "message": "waited"},
                                    "raw_model_output": "wait",
                                }
                            ],
                        }
                    ],
                },
            },
            {
                "run_id": "model_beta__seed1",
                "model_profile": "model_beta",
                "provider_id": "dummy_provider",
                "model": "dummy_beta",
                "seed": 1,
                "attempt_kind": "initial",
                "summary": {
                    "final_score": 9,
                    "turns_survived": 8,
                    "max_turns": 50,
                    "invalid_actions": 1,
                    "resources_gathered": 1,
                    "latency_ms": 900,
                    "tokens_used": 90,
                    "end_reason": "agent_dead",
                    "pvp_duel": True,
                    "opponent_model_profile": "model_alpha",
                },
                "replay": {"meta": {"map_coverage": "full"}, "protocol": {"rules": {"pvp_duel": True}}, "world": {"width": 2, "height": 2}, "frames": []},
            },
        ],
        "duel_view": {
            "timeline_selection_rule": "lexicographic_model_profile_min",
            "duels": [
                {
                    "duel_key": "seed1::initial::model_alpha::model_beta",
                    "seed": 1,
                    "attempt_kind": "initial",
                    "pair_key": "model_alpha::model_beta",
                    "model_a": "model_alpha",
                    "model_b": "model_beta",
                    "timeline_source_run_id": "model_alpha__seed1",
                    "run_id_by_model": {"model_alpha": "model_alpha__seed1", "model_beta": "model_beta__seed1"},
                    "summary_by_model": {
                        "model_alpha": {"final_score": 12, "turns_survived": 10, "max_turns": 50, "status": "finished"},
                        "model_beta": {"final_score": 9, "turns_survived": 8, "max_turns": 50, "status": "dead"},
                    },
                    "warnings": [],
                }
            ],
        },
    }

    compare_path = tmp_path / "compare_duel.json"
    compare_path.write_text(json.dumps(compare_payload), encoding="utf-8")
    output_html = tmp_path / "compare_duel_dashboard.html"
    generate_compare_viewer(compare_path=compare_path, output_path=output_html, title="Compare Duel Viewer Test")

    rendered = output_html.read_text(encoding="utf-8")
    assert '"duel_view"' in rendered
    assert "Focus:" in rendered
    assert "timeline_source_run_id" in rendered
