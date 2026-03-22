"""CLI entrypoint: human interactive play mode using benchmark engine rules."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from bench.common import DEFAULT_AGENT_ID, load_configs, resolve_artifact_dirs
from engine.actions import ActionOutcome, apply_action
from engine.observation import build_observation
from engine.parser import parse_action
from engine.rules import apply_end_of_turn, compute_allowed_actions
from engine.scoring import apply_score, score_action, score_survival
from engine.version import __version__
from engine.world import create_world
from renderers.human_renderer import render_turn_view


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Play TinyWorld manually in terminal")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--scenario", type=str, default=None)
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--benchmark-config", type=str, default="configs/benchmark.yaml")
    parser.add_argument("--scenarios-config", type=str, default="configs/scenarios.yaml")
    parser.add_argument("--replay-output", type=str, default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()

    benchmark_cfg, scenarios_cfg = load_configs(args.benchmark_config, args.scenarios_config)
    scenario_key = args.scenario or benchmark_cfg["default_scenario"]
    scenario = scenarios_cfg["scenarios"][scenario_key]

    artifact_dirs = resolve_artifact_dirs(benchmark_cfg, Path.cwd())

    rules_cfg = benchmark_cfg["rules"]
    scoring_cfg = benchmark_cfg["scoring"]
    parser_mode = benchmark_cfg["parser"]["case_mode"]
    protocol_version = benchmark_cfg["protocol_version"]
    run_max_turns = int(args.max_turns if args.max_turns is not None else benchmark_cfg["max_turns"])

    world = create_world(seed=args.seed, scenario_cfg=scenario, rules_cfg=rules_cfg, agent_id=DEFAULT_AGENT_ID)

    print("TinyWorld Survival Bench v0.1 - Human Mode")
    print("Use only benchmark commands. Stop with Ctrl+C.")

    replay_turns: list[dict[str, object]] = []
    invalid_actions = 0
    resources_gathered = 0
    turns_survived = 0

    for turn in range(1, run_max_turns + 1):
        agent = world.agents[DEFAULT_AGENT_ID]
        if not agent.alive:
            break

        world.turn = turn
        allowed_actions = compute_allowed_actions(world, DEFAULT_AGENT_ID, rules_cfg)
        observation = build_observation(world, DEFAULT_AGENT_ID, allowed_actions, protocol_version)

        print()
        print(render_turn_view(observation))

        raw_output = input("> ")
        parse_result = parse_action(raw_output=raw_output, allowed_actions=allowed_actions, case_mode=parser_mode)

        if parse_result.valid and parse_result.action is not None:
            action_outcome = apply_action(world, DEFAULT_AGENT_ID, parse_result.action, rules_cfg)
            action_score_delta, action_score_events = score_action(True, action_outcome, scoring_cfg)
            if action_outcome.useful_gather:
                resources_gathered += 1
        else:
            invalid_actions += 1
            action_outcome = ActionOutcome(
                action=parse_result.normalized_output,
                success=False,
                message="invalid action",
                invalid_reason=parse_result.error,
                world_delta={},
            )
            action_score_delta, action_score_events = score_action(False, None, scoring_cfg)

        survival_update = apply_end_of_turn(world, DEFAULT_AGENT_ID, rules_cfg)
        survival_score_delta, survival_score_events = score_survival(survival_update.alive_after, scoring_cfg)
        if survival_update.alive_after:
            turns_survived += 1

        total_score_delta = action_score_delta + survival_score_delta
        apply_score(world.agents[DEFAULT_AGENT_ID], total_score_delta)

        print(f"Result: {action_outcome.message}")
        print(f"Score delta: {total_score_delta}  Cumulative score: {world.agents[DEFAULT_AGENT_ID].score}")

        replay_turns.append(
            {
                "turn": turn,
                "observation": observation,
                "raw_input": raw_output,
                "parsed_action": parse_result.action,
                "validation": {
                    "is_valid": parse_result.valid,
                    "error": parse_result.error,
                },
                "action_result": {
                    "success": action_outcome.success,
                    "message": action_outcome.message,
                    "invalid_reason": action_outcome.invalid_reason,
                    "world_delta": action_outcome.world_delta,
                },
                "score_delta": {
                    "action": action_score_delta,
                    "survival": survival_score_delta,
                    "total": total_score_delta,
                    "events": action_score_events + survival_score_events,
                },
                "survival_delta": survival_update.as_delta(),
                "cumulative_score": world.agents[DEFAULT_AGENT_ID].score,
            }
        )

        if not world.agents[DEFAULT_AGENT_ID].alive:
            break

    final_agent = world.agents[DEFAULT_AGENT_ID]
    end_reason = "agent_dead" if not final_agent.alive else "max_turns_reached"

    summary = {
        "version": __version__,
        "seed": args.seed,
        "scenario": scenario_key,
        "max_turns": run_max_turns,
        "turns_played": len(replay_turns),
        "turns_survived": turns_survived,
        "final_score": final_agent.score,
        "resources_gathered": resources_gathered,
        "invalid_actions": invalid_actions,
        "alive": final_agent.alive,
        "end_reason": end_reason,
    }

    if args.replay_output is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        replay_path = artifact_dirs["replays"] / f"human_seed{args.seed}_{timestamp}.json"
    else:
        replay_path = Path(args.replay_output)
        if not replay_path.is_absolute():
            replay_path = Path.cwd() / replay_path

    replay_path.parent.mkdir(parents=True, exist_ok=True)
    with replay_path.open("w", encoding="utf-8") as handle:
        json.dump({"summary": summary, "turns": replay_turns}, handle, ensure_ascii=True, indent=2, sort_keys=True)

    print()
    print("Game over.")
    print(
        "Summary: "
        f"score={summary['final_score']} "
        f"turns_survived={summary['turns_survived']} "
        f"invalid_actions={summary['invalid_actions']} "
        f"end_reason={summary['end_reason']}"
    )
    print(f"Replay saved: {replay_path}")


if __name__ == "__main__":
    main()
