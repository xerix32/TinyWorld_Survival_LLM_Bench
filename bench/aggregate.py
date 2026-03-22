"""Aggregate existing run logs into a CSV summary."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from bench.common import load_yaml_file, resolve_artifact_dirs


AGGREGATE_FIELDS = [
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
    "tokens_used",
    "latency_ms",
    "estimated_cost",
    "log_path",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggregate TinyWorld run logs")
    parser.add_argument("--logs-glob", type=str, default="artifacts/logs/*.json")
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--benchmark-config", type=str, default="configs/benchmark.yaml")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    benchmark_cfg = load_yaml_file(args.benchmark_config)
    dirs = resolve_artifact_dirs(benchmark_cfg, Path.cwd())

    log_paths = sorted(Path.cwd().glob(args.logs_glob))
    if not log_paths:
        raise SystemExit(f"No logs matched pattern: {args.logs_glob}")

    rows: list[dict[str, object]] = []
    for log_path in log_paths:
        with log_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        summary = dict(payload.get("run_summary", {}))
        summary["log_path"] = str(log_path)
        rows.append(summary)

    if args.output is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = dirs["results"] / f"aggregate_{timestamp}.csv"
    else:
        output = Path(args.output)
        if not output.is_absolute():
            output = Path.cwd() / output

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AGGREGATE_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in AGGREGATE_FIELDS})

    print(f"Aggregate complete: {output}")
    print(f"Logs processed: {len(rows)}")


if __name__ == "__main__":
    main()
