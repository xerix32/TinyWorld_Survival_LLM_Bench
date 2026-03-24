"""CLI entrypoint: run multiple seeded matches and emit CSV summary."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from bench.cli_ui import StatusLine, colorize, use_color
from bench.common import load_yaml_file, resolve_artifact_dirs, run_match_once
from engine.version import __version__


SUITE_FIELDS = [
    "version",
    "bench_version",
    "engine_version",
    "prompt_set_sha256",
    "seed",
    "scenario",
    "provider_id",
    "model_profile",
    "model",
    "max_turns",
    "turns_played",
    "turns_survived",
    "final_score",
    "resources_gathered",
    "invalid_actions",
    "alive",
    "end_reason",
    "end_reason_human",
    "death_cause",
    "death_cause_human",
    "tokens_used",
    "latency_ms",
    "estimated_cost",
    "log_path",
]


def parse_seeds(raw: str) -> list[int]:
    seeds = [int(chunk.strip()) for chunk in raw.split(",") if chunk.strip()]
    if not seeds:
        raise ValueError("--seeds must include at least one integer")
    return seeds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run TinyWorld benchmark suite")
    parser.add_argument("--seeds", type=str, default="1,2,3")
    parser.add_argument(
        "--model",
        type=str,
        default="dummy_v0_1",
        help="Model profile from providers config (or legacy alias: dummy, anthropic, local)",
    )
    parser.add_argument("--scenario", type=str, default=None)
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--benchmark-config", type=str, default="configs/benchmark.yaml")
    parser.add_argument("--scenarios-config", type=str, default="configs/scenarios.yaml")
    parser.add_argument("--providers-config", type=str, default="configs/providers.yaml")
    parser.add_argument("--prompts-dir", type=str, default="prompts")
    parser.add_argument(
        "--fix-thinking",
        action="store_true",
        help="Optional parser recovery: extract the last valid allowed action from verbose model output.",
    )
    parser.add_argument("--no-color", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    seeds = parse_seeds(args.seeds)

    color_enabled = use_color(disable_color=args.no_color)
    status_line = StatusLine(enabled=True)

    print(colorize(f"TinyWorld Survival Bench Suite v{__version__}", "1;36", color_enabled))
    print(colorize(f"model={args.model} seeds={len(seeds)}", "2", color_enabled))

    benchmark_cfg = load_yaml_file(args.benchmark_config)
    dirs = resolve_artifact_dirs(benchmark_cfg, Path.cwd())

    rows: list[dict[str, object]] = []
    total = len(seeds)

    for index, seed in enumerate(seeds, start=1):
        pct_before = ((index - 1) / total) * 100.0
        status_line.write(
            colorize(
                f"[{pct_before:5.1f}%] step=seed {index}/{total} running seed={seed}",
                "36",
                color_enabled,
            )
        )

        run_log = run_match_once(
            seed=seed,
            model_name=args.model,
            scenario_name=args.scenario,
            max_turns=args.max_turns,
            benchmark_config_path=args.benchmark_config,
            scenarios_config_path=args.scenarios_config,
            providers_config_path=args.providers_config,
            prompts_dir=args.prompts_dir,
            output_path=None,
            progress_callback=None,
            fix_thinking=args.fix_thinking,
        )
        rows.append(run_log["run_summary"])

        pct_after = (index / total) * 100.0
        summary = run_log["run_summary"]
        status_line.write(
            colorize(
                (
                    f"[{pct_after:5.1f}%] step=seed {index}/{total} done seed={seed} "
                    f"score={summary['final_score']} turns={summary['turns_survived']}"
                ),
                "32",
                color_enabled,
            )
        )

    status_line.finish(colorize("[100.0%] step=done", "36", color_enabled))

    if args.output is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_model = args.model.replace("/", "_")
        output = dirs["results"] / f"suite_{safe_model}_{timestamp}.csv"
    else:
        output = Path(args.output)
        if not output.is_absolute():
            output = Path.cwd() / output

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUITE_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in SUITE_FIELDS})

    scores = [int(row["final_score"]) for row in rows]
    survived = [int(row["turns_survived"]) for row in rows]
    invalid_total = sum(int(row["invalid_actions"]) for row in rows)

    print(colorize("Suite Summary", "1;32", color_enabled))
    print(
        f"runs={len(rows)} "
        f"avg_score={mean(scores):.2f} "
        f"avg_turns_survived={mean(survived):.2f} "
        f"total_invalid_actions={invalid_total}"
    )
    print(colorize(f"suite_csv={output}", "34", color_enabled))


if __name__ == "__main__":
    main()
