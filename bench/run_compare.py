"""CLI entrypoint: run multi-run and multi-model TinyWorld comparisons."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
import socket
from statistics import mean
import subprocess
import sys
import time
from typing import Any
from urllib.parse import quote
import webbrowser

from bench.cli_ui import StatusLine, colorize, format_eta, use_color
from bench.common import load_yaml_file, resolve_artifact_dirs, run_match_once
from bench.view_compare import generate_compare_viewer
from bench.view_log import build_viewer_payload
from engine.version import __version__


COMPARE_RUN_FIELDS = [
    "compare_id",
    "run_id",
    "job_index",
    "job_total",
    "model_order",
    "seed_order",
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

MODEL_SUMMARY_FIELDS = [
    "rank",
    "model_profile",
    "provider_id",
    "model",
    "runs",
    "avg_final_score",
    "avg_turns_survived",
    "avg_survival_pct",
    "avg_invalid_actions",
    "avg_resources_gathered",
    "death_rate_pct",
    "latency_ms_total",
    "latency_ms_avg",
    "latency_ms_per_turn",
    "best_final_score",
    "worst_final_score",
    "max_turns_survived",
    "tokens_used_total",
    "estimated_cost_total",
    "max_turns_avg",
]

H2H_FIELDS = [
    "model_a_profile",
    "model_b_profile",
    "paired_runs",
    "wins_a",
    "wins_b",
    "ties",
    "win_rate_a_vs_b",
    "avg_delta_a_minus_b",
]


def parse_models(raw: str) -> list[str]:
    models = [item.strip() for item in raw.split(",") if item.strip()]
    if not models:
        raise ValueError("--models must include at least one model profile")
    return models


def parse_seeds(raw: str) -> list[int]:
    seeds = [int(chunk.strip()) for chunk in raw.split(",") if chunk.strip()]
    if not seeds:
        raise ValueError("--seeds must include at least one integer")
    return seeds


def resolve_seed_list(seeds_raw: str | None, num_runs: int, seed_start: int) -> list[int]:
    if seeds_raw:
        return parse_seeds(seeds_raw)

    if num_runs < 1:
        raise ValueError("--num-runs must be >= 1")
    return list(range(seed_start, seed_start + num_runs))


def _short_path(path: str | Path) -> str:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved).resolve()

    cwd = Path.cwd().resolve()
    try:
        return str(resolved.relative_to(cwd))
    except ValueError:
        return str(resolved)


def _safe_slug(value: str) -> str:
    return value.replace("/", "_").replace(" ", "_").replace(":", "_")


def _format_number(value: int | float | None, digits: int = 0, fallback: str = "not available") -> str:
    if value is None:
        return fallback
    if digits <= 0:
        return f"{int(value):,}"
    return f"{float(value):,.{digits}f}"


def _format_duration_from_ms(duration_ms: float | int | None) -> str:
    if duration_ms is None:
        return "not available"

    ms = float(duration_ms)
    if ms < 10:
        return f"{ms:,.3f} ms"
    if ms < 1000:
        return f"{ms:,.1f} ms"

    seconds = ms / 1000.0
    if seconds < 60:
        return f"{seconds:,.2f} s"

    minutes = int(seconds // 60)
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m {secs:04.1f}s"

    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins:02d}m {secs:04.1f}s"


def _print_section(title: str, color_enabled: bool) -> None:
    print()
    print(colorize(title, "1;35", color_enabled))


def _print_row(
    label: str,
    value: str,
    *,
    color_enabled: bool,
    label_color: str = "1;36",
    value_color: str = "1;97",
) -> None:
    label_text = colorize(f"{label:<22}", label_color, color_enabled)
    value_text = colorize(value, value_color, color_enabled)
    print(f"  {label_text} {value_text}")


def _is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


def _ensure_http_server(port: int, root_dir: Path) -> tuple[int | None, bool]:
    if _is_port_open(port):
        return None, False

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "http.server",
            str(port),
            "--bind",
            "127.0.0.1",
            "--directory",
            str(root_dir),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(0.25)
    if process.poll() is not None:
        raise RuntimeError(f"failed to start local HTTP server on port {port}")
    return process.pid, True


def _build_http_viewer_url(viewer_path: Path, root_dir: Path, port: int) -> str:
    resolved_viewer = viewer_path.resolve()
    resolved_root = root_dir.resolve()

    try:
        relative_path = resolved_viewer.relative_to(resolved_root).as_posix()
    except ValueError:
        relative_path = resolved_viewer.name

    encoded_path = quote(relative_path, safe="/")
    return f"http://127.0.0.1:{port}/{encoded_path}"


def _optional_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(mean(values))


def _optional_sum(values: list[float | None]) -> float | None:
    present = [float(v) for v in values if v is not None]
    if not present:
        return None
    return float(sum(present))


def build_model_summaries(run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    order: list[str] = []
    for row in run_rows:
        profile = str(row["model_profile"])
        if profile not in grouped:
            order.append(profile)
        grouped[profile].append(row)

    summaries: list[dict[str, Any]] = []
    for profile in order:
        group = grouped[profile]
        ref = group[0]
        runs = len(group)

        scores = [float(item["final_score"]) for item in group]
        turns_survived = [float(item["turns_survived"]) for item in group]
        invalid_actions = [float(item["invalid_actions"]) for item in group]
        resources = [float(item["resources_gathered"]) for item in group]
        max_turns = [float(item["max_turns"]) for item in group if float(item["max_turns"]) > 0]

        survival_pct_values: list[float] = []
        for item in group:
            mt = float(item["max_turns"])
            ts = float(item["turns_survived"])
            if mt > 0:
                survival_pct_values.append((ts / mt) * 100.0)

        deaths = sum(1 for item in group if str(item.get("end_reason", "")) == "agent_dead")
        death_rate_pct = (deaths / runs) * 100.0 if runs else 0.0

        latencies = [float(item["latency_ms"]) for item in group if item.get("latency_ms") is not None]
        latency_total = _optional_sum([item.get("latency_ms") for item in group])
        latency_avg = _optional_mean(latencies)

        tokens_total = _optional_sum([item.get("tokens_used") for item in group])
        cost_total = _optional_sum([item.get("estimated_cost") for item in group])

        summaries.append(
            {
                "rank": 0,
                "model_profile": profile,
                "provider_id": ref["provider_id"],
                "model": ref["model"],
                "runs": runs,
                "avg_final_score": round(mean(scores), 4),
                "avg_turns_survived": round(mean(turns_survived), 4),
                "avg_survival_pct": round(mean(survival_pct_values), 4) if survival_pct_values else None,
                "avg_invalid_actions": round(mean(invalid_actions), 4),
                "avg_resources_gathered": round(mean(resources), 4),
                "death_rate_pct": round(death_rate_pct, 4),
                "best_final_score": max(scores) if scores else None,
                "worst_final_score": min(scores) if scores else None,
                "max_turns_survived": max(turns_survived) if turns_survived else None,
                "latency_ms_total": round(latency_total, 6) if latency_total is not None else None,
                "latency_ms_avg": round(latency_avg, 6) if latency_avg is not None else None,
                "latency_ms_per_turn": round(latency_total / sum(turns_survived), 6) if (latency_total is not None and sum(turns_survived) > 0) else None,
                "tokens_used_total": int(tokens_total) if tokens_total is not None else None,
                "estimated_cost_total": round(cost_total, 6) if cost_total is not None else None,
                "max_turns_avg": round(mean(max_turns), 4) if max_turns else None,
            }
        )

    summaries.sort(
        key=lambda item: (
            -float(item["avg_final_score"]),
            -float(item["avg_turns_survived"]),
            float(item["avg_invalid_actions"]),
            str(item["model_profile"]),
        )
    )

    for idx, row in enumerate(summaries, start=1):
        row["rank"] = idx

    return summaries


def build_pairwise_summary(
    run_rows: list[dict[str, Any]],
    model_profiles: list[str],
    seed_list: list[int],
) -> list[dict[str, Any]]:
    score_by_model_seed: dict[tuple[str, int], float] = {}
    for row in run_rows:
        score_by_model_seed[(str(row["model_profile"]), int(row["seed"]))] = float(row["final_score"])

    pairwise_rows: list[dict[str, Any]] = []
    for model_a, model_b in combinations(model_profiles, 2):
        deltas: list[float] = []
        wins_a = 0
        wins_b = 0
        ties = 0

        for seed in seed_list:
            key_a = (model_a, int(seed))
            key_b = (model_b, int(seed))
            if key_a not in score_by_model_seed or key_b not in score_by_model_seed:
                continue

            delta = score_by_model_seed[key_a] - score_by_model_seed[key_b]
            deltas.append(delta)
            if delta > 0:
                wins_a += 1
            elif delta < 0:
                wins_b += 1
            else:
                ties += 1

        paired_runs = len(deltas)
        win_rate = ((wins_a / paired_runs) * 100.0) if paired_runs > 0 else None
        avg_delta = mean(deltas) if paired_runs > 0 else None

        pairwise_rows.append(
            {
                "model_a_profile": model_a,
                "model_b_profile": model_b,
                "paired_runs": paired_runs,
                "wins_a": wins_a,
                "wins_b": wins_b,
                "ties": ties,
                "win_rate_a_vs_b": round(win_rate, 4) if win_rate is not None else None,
                "avg_delta_a_minus_b": round(avg_delta, 4) if avg_delta is not None else None,
            }
        )

    return pairwise_rows


def resolved_model_profiles(run_rows: list[dict[str, Any]]) -> list[str]:
    profiles: list[str] = []
    seen: set[str] = set()
    for row in run_rows:
        profile = str(row["model_profile"])
        if profile in seen:
            continue
        seen.add(profile)
        profiles.append(profile)
    return profiles


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not (1 <= port <= 65535):
        raise argparse.ArgumentTypeError("port must be in range 1..65535")
    return port


def _render_pct(pct: float, *, color_enabled: bool) -> str:
    if not color_enabled:
        return f"[{pct:5.1f}%]"
    left = colorize("[", "1;97", color_enabled)
    value = colorize(f"{pct:5.1f}%", "1;35", color_enabled)
    right = colorize("]", "1;97", color_enabled)
    return f"{left}{value}{right}"


def _render_progress_ratio(
    label: str,
    current: int,
    total: int,
    *,
    color_enabled: bool,
    done_color: str = "1;96",
) -> str:
    if not color_enabled:
        return f"{label} {current}/{total}"

    label_text = colorize(label, "0;37", color_enabled)
    current_color = done_color if current >= total else "1;97"
    current_text = colorize(str(current), current_color, color_enabled)
    slash_text = colorize("/", "0;37", color_enabled)
    total_text = colorize(str(total), done_color, color_enabled)
    return f"{label_text} {current_text}{slash_text}{total_text}"


def _render_turn_progress_line(
    *,
    pct: float,
    job_index: int,
    job_total: int,
    turn: int,
    max_turns: int,
    model_profile: str,
    seed: int,
    action: str,
    protocol_valid: bool,
    effect_applied: bool,
    score: int,
    invalid: int,
    alive: bool,
    eta_text: str,
    color_enabled: bool,
) -> str:
    protocol_text = "ok" if protocol_valid else "bad"
    if not protocol_valid:
        effect_text = "n/a"
    elif effect_applied:
        effect_text = "applied"
    else:
        effect_text = "no-op"

    if color_enabled:
        pct_text = _render_pct(pct, color_enabled=color_enabled)
        job_text = _render_progress_ratio("job", job_index, job_total, color_enabled=color_enabled)
        turn_text = _render_progress_ratio("turn", turn, max_turns, color_enabled=color_enabled)
        model_label = colorize("model:", "0;37", color_enabled)
        model_text = colorize(model_profile, "1;95", color_enabled)
        seed_label = colorize("seed:", "0;37", color_enabled)
        seed_text = colorize(str(seed), "1;33", color_enabled)
        action_label = colorize("action:", "0;37", color_enabled)
        action_text = colorize(f"{action[:22]:<22}", "1;36", color_enabled)

        protocol_color = "1;32" if protocol_valid else "1;31"
        effect_color = "0;37"
        if protocol_valid and effect_applied:
            effect_color = "1;32"
        elif protocol_valid and not effect_applied:
            effect_color = "1;93"

        score_text = colorize(f"{score:>4}", "1;93", color_enabled)
        invalid_color = "1;31" if invalid > 0 else "0;37"
        invalid_text = colorize(f"{invalid:>3}", invalid_color, color_enabled)
        alive_color = "1;32" if alive else "1;31"
        alive_text = colorize("yes" if alive else "no", alive_color, color_enabled)
        eta_label = colorize("eta:", "0;37", color_enabled)
        eta_value = colorize(eta_text, "1;97", color_enabled)

        return (
            f"{pct_text} {job_text} | {turn_text} | "
            f"{model_label} {model_text} | {seed_label} {seed_text} | "
            f"{action_label} {action_text} | "
            f"protocol: {colorize(protocol_text, protocol_color, color_enabled)} | "
            f"effect: {colorize(effect_text, effect_color, color_enabled)} | "
            f"score: {score_text} | invalid: {invalid_text} | alive: {alive_text} | {eta_label} {eta_value}"
        )

    return (
        f"[{pct:5.1f}%] job {job_index}/{job_total} | turn {turn}/{max_turns} | "
        f"model: {model_profile} | seed: {seed} | action: {action[:22]:<22} | "
        f"protocol: {protocol_text:<3} | effect: {effect_text:<7} | "
        f"score: {score:>4} | invalid: {invalid:>3} | alive: {'yes' if alive else 'no'} | eta: {eta_text}"
    )


def _render_job_done_line(
    *,
    pct: float,
    job_index: int,
    job_total: int,
    model_profile: str,
    seed: int,
    score: int,
    status: str,
    eta_text: str,
    color_enabled: bool,
) -> str:
    if color_enabled:
        pct_text = _render_pct(pct, color_enabled=color_enabled)
        job_text = _render_progress_ratio("job", job_index, job_total, color_enabled=color_enabled)
        model_text = colorize(model_profile, "1;95", color_enabled)
        seed_text = colorize(str(seed), "1;33", color_enabled)
        score_text = colorize(f"{score:>4}", "1;93", color_enabled)
        status_color = "1;31" if status == "dead" else "1;32"
        status_text = colorize(status, status_color, color_enabled)
        eta_label = colorize("eta:", "0;37", color_enabled)
        eta_value = colorize(eta_text, "1;97", color_enabled)
        return (
            f"{pct_text} {job_text} | model: {model_text} | seed: {seed_text} | "
            f"score: {score_text} | status: {status_text} | {eta_label} {eta_value}"
        )

    return (
        f"[{pct:5.1f}%] job {job_index}/{job_total} | model: {model_profile} | "
        f"seed: {seed} | score: {score:>4} | status: {status} | eta: {eta_text}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run TinyWorld multi-run and multi-model comparison with paired seeds.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Defaults:\n"
            "  --models dummy_v0_1\n"
            "  --num-runs 5\n"
            "  --seed-start 1\n"
            "  --providers-config configs/providers.yaml\n"
            "\n"
            "Examples:\n"
            "  python -m bench.run_compare\n"
            "  python -m bench.run_compare --models local_gpt_oss_20b,groq_gpt_oss_120b --num-runs 10 --seed-start 7 --providers-config configs/providers.local.yaml\n"
            "  python -m bench.run_compare --models dummy_v0_1,local_gpt_oss_20b --seeds 1,2,3 --serve 8877\n"
        ),
    )
    parser.add_argument(
        "--models",
        type=str,
        default="dummy_v0_1",
        help="Comma-separated model profiles from providers config, preserving order.",
    )
    parser.add_argument("--num-runs", type=int, default=5, help="Runs per model when --seeds is not provided.")
    parser.add_argument("--seed-start", type=int, default=1, help="Start seed for paired seed range.")
    parser.add_argument("--seeds", type=str, default=None, help="Optional explicit seed list (overrides --num-runs/--seed-start).")
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        help="Scenario key from scenarios config. If omitted, uses benchmark default scenario.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Turn limit override. If omitted, uses benchmark config value.",
    )
    parser.add_argument(
        "--benchmark-config",
        type=str,
        default="configs/benchmark.yaml",
        help="Benchmark settings file (rules, scoring, logging, parser mode).",
    )
    parser.add_argument(
        "--scenarios-config",
        type=str,
        default="configs/scenarios.yaml",
        help="Scenarios definition file.",
    )
    parser.add_argument(
        "--providers-config",
        type=str,
        default="configs/providers.yaml",
        help="Providers + model profiles file.",
    )
    parser.add_argument("--prompts-dir", type=str, default="prompts", help="Prompt templates directory.")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors in terminal output.")
    parser.add_argument("--no-viewer", action="store_true", help="Skip compare HTML generation.")
    parser.add_argument("--viewer-output", type=str, default=None, help="Output path for generated compare HTML report.")
    parser.add_argument("--viewer-title", type=str, default=None, help="Custom title for compare HTML report.")
    parser.add_argument("--no-open-viewer", action="store_true", help="Generate compare HTML but do not open browser.")
    parser.add_argument(
        "--serve",
        nargs="?",
        const=8765,
        type=_parse_port,
        default=None,
        metavar="PORT",
        help=(
            "Serve the generated compare HTML via local HTTP (http://127.0.0.1:PORT). "
            "If PORT is omitted, 8765 is used."
        ),
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.serve is not None and args.no_viewer:
        parser.error("--serve requires viewer generation; remove --no-viewer.")

    model_profiles = parse_models(args.models)
    seed_list = resolve_seed_list(args.seeds, args.num_runs, args.seed_start)

    color_enabled = use_color(disable_color=args.no_color)
    status_line = StatusLine(enabled=True)

    print(colorize(f"TinyWorld Compare CLI v{__version__}", "1;36", color_enabled))

    benchmark_cfg = load_yaml_file(args.benchmark_config)
    dirs = resolve_artifact_dirs(benchmark_cfg, Path.cwd())

    total_jobs = len(model_profiles) * len(seed_list)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    compare_started_at = time.monotonic()

    run_rows: list[dict[str, Any]] = []
    run_payloads: list[dict[str, Any]] = []
    run_logs: list[dict[str, Any]] = []

    current_job = 0
    for model_order, model_profile in enumerate(model_profiles, start=1):
        for seed_order, seed in enumerate(seed_list, start=1):
            current_job += 1
            run_progress = {
                "max_turns": int(args.max_turns if args.max_turns is not None else benchmark_cfg.get("max_turns", 50)),
            }

            def on_progress(event: dict[str, Any]) -> None:
                event_type = str(event.get("event", ""))
                if event_type == "run_started":
                    run_progress["max_turns"] = int(event.get("max_turns", run_progress["max_turns"]))
                    pct = ((current_job - 1) / total_jobs) * 100.0
                    status_line.write(
                        _render_turn_progress_line(
                            pct=pct,
                            job_index=current_job,
                            job_total=total_jobs,
                            turn=0,
                            max_turns=run_progress["max_turns"],
                            model_profile=model_profile,
                            seed=seed,
                            action="(initializing)",
                            protocol_valid=True,
                            effect_applied=False,
                            score=0,
                            invalid=0,
                            alive=True,
                            eta_text="--",
                            color_enabled=color_enabled,
                        )
                    )
                    return

                if event_type != "turn_completed":
                    return

                turn = int(event.get("turn", 0))
                max_turns = int(event.get("max_turns", run_progress["max_turns"]))
                run_progress["max_turns"] = max_turns
                run_fraction = (turn / max_turns) if max_turns > 0 else 0.0
                overall_fraction = ((current_job - 1) + run_fraction) / total_jobs
                pct = overall_fraction * 100.0
                eta_text = "--"
                if overall_fraction > 0:
                    elapsed = max(0.0, time.monotonic() - compare_started_at)
                    remaining = max(0.0, (elapsed / overall_fraction) - elapsed)
                    eta_text = format_eta(remaining)

                line = _render_turn_progress_line(
                    pct=pct,
                    job_index=current_job,
                    job_total=total_jobs,
                    turn=turn,
                    max_turns=max_turns,
                    model_profile=model_profile,
                    seed=seed,
                    action=str(event.get("action") or "-"),
                    protocol_valid=bool(event.get("protocol_valid", False)),
                    effect_applied=bool(event.get("action_effect_applied", False)),
                    score=int(event.get("cumulative_score", 0)),
                    invalid=int(event.get("invalid_actions", 0)),
                    alive=bool(event.get("alive", True)),
                    eta_text=eta_text,
                    color_enabled=color_enabled,
                )
                status_line.write(line)

            try:
                run_log = run_match_once(
                    seed=seed,
                    model_name=model_profile,
                    scenario_name=args.scenario,
                    max_turns=args.max_turns,
                    benchmark_config_path=args.benchmark_config,
                    scenarios_config_path=args.scenarios_config,
                    providers_config_path=args.providers_config,
                    prompts_dir=args.prompts_dir,
                    output_path=None,
                    progress_callback=on_progress,
                )
            except KeyboardInterrupt:
                status_line.finish(colorize("[interrupted] Compare canceled by user", "1;93", color_enabled))
                print(
                    colorize(
                        (
                            f"Compare canceled (Ctrl+C) during job {current_job}/{total_jobs} "
                            f"(model={model_profile}, seed={seed}). Exiting cleanly."
                        ),
                        "1;93",
                        color_enabled,
                    )
                )
                raise SystemExit(130)
            except Exception as exc:
                status_line.finish(colorize("[failed] Compare failed", "1;91", color_enabled))
                error_text = str(exc).strip() or exc.__class__.__name__
                print(
                    colorize(
                        (
                            f"Compare failed during job {current_job}/{total_jobs} "
                            f"(model={model_profile}, seed={seed}): {error_text}"
                        ),
                        "1;91",
                        color_enabled,
                    )
                )
                lowered = error_text.casefold()
                if "insufficient system resources" in lowered or "failed to load model" in lowered:
                    print(
                        colorize(
                            "Hint: local model could not be loaded (RAM/VRAM guardrails). "
                            "Use a smaller model or free resources in LM Studio.",
                            "1;93",
                            color_enabled,
                        )
                    )
                raise SystemExit(1)
            run_logs.append(run_log)
            summary = dict(run_log["run_summary"])

            run_id = f"{_safe_slug(model_profile)}__seed{seed}"
            run_row = {
                "compare_id": timestamp,
                "run_id": run_id,
                "job_index": current_job,
                "job_total": total_jobs,
                "model_order": model_order,
                "seed_order": seed_order,
                **summary,
            }
            run_rows.append(run_row)

            replay_payload = build_viewer_payload(run_log=run_log, source_log_path=Path(str(summary["log_path"])))
            run_payloads.append(
                {
                    "run_id": run_id,
                    "model_profile": summary["model_profile"],
                    "provider_id": summary["provider_id"],
                    "model": summary["model"],
                    "seed": summary["seed"],
                    "summary": summary,
                    "replay": replay_payload,
                }
            )

            pct_after = (current_job / total_jobs) * 100.0
            status = "dead" if str(summary.get("end_reason")) == "agent_dead" else "finished"
            eta_text = "--"
            if current_job < total_jobs:
                overall_fraction = current_job / total_jobs
                elapsed = max(0.0, time.monotonic() - compare_started_at)
                remaining = max(0.0, (elapsed / overall_fraction) - elapsed)
                eta_text = format_eta(remaining)
            status_line.write(
                _render_job_done_line(
                    pct=pct_after,
                    job_index=current_job,
                    job_total=total_jobs,
                    model_profile=model_profile,
                    seed=seed,
                    score=int(summary["final_score"]),
                    status=status,
                    eta_text=eta_text,
                    color_enabled=color_enabled,
                )
            )

    status_line.finish(colorize("[100.0%] compare run completed", "36", color_enabled))

    model_summaries = build_model_summaries(run_rows)
    resolved_profiles = resolved_model_profiles(run_rows)
    pairwise_rows = build_pairwise_summary(run_rows, model_profiles=resolved_profiles, seed_list=seed_list)

    first_log = run_logs[0]
    scenario = str(first_log.get("scenario", "-"))
    protocol_version = str(first_log.get("protocol_version", "AIB-0.1"))
    prompt_hashes = sorted({str(row.get("prompt_set_sha256")) for row in run_rows if row.get("prompt_set_sha256")})
    prompt_hash = prompt_hashes[0] if len(prompt_hashes) == 1 else "mixed"

    compare_payload = {
        "meta": {
            "compare_id": timestamp,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "version": __version__,
            "bench_version": __version__,
            "engine_version": __version__,
            "protocol_version": protocol_version,
            "scenario": scenario,
            "seed_list": seed_list,
            "models": resolved_profiles,
            "requested_models": model_profiles,
            "runs_per_model": len(seed_list),
            "total_runs": len(run_rows),
            "paired_seeds": True,
            "prompt_set_sha256": prompt_hash,
        },
        "models": model_summaries,
        "pairwise": pairwise_rows,
        "runs": run_payloads,
    }

    runs_csv = dirs["results"] / f"compare_runs_{timestamp}.csv"
    models_csv = dirs["results"] / f"compare_models_{timestamp}.csv"
    h2h_csv = dirs["results"] / f"compare_h2h_{timestamp}.csv"
    compare_json = dirs["results"] / f"compare_{timestamp}.json"

    _write_csv(runs_csv, COMPARE_RUN_FIELDS, run_rows)
    _write_csv(models_csv, MODEL_SUMMARY_FIELDS, model_summaries)
    _write_csv(h2h_csv, H2H_FIELDS, pairwise_rows)

    compare_json.parent.mkdir(parents=True, exist_ok=True)
    with compare_json.open("w", encoding="utf-8") as handle:
        json.dump(compare_payload, handle, ensure_ascii=True, indent=2, sort_keys=True)

    print()
    print(colorize("COMPARE SUMMARY", "1;32", color_enabled))

    _print_section("Identity", color_enabled)
    _print_row("Protocol", protocol_version, color_enabled=color_enabled)
    _print_row("Scenario", scenario, color_enabled=color_enabled)
    _print_row("Models (requested)", ", ".join(model_profiles), color_enabled=color_enabled)
    _print_row("Models (resolved)", ", ".join(resolved_profiles), color_enabled=color_enabled)
    _print_row("Seeds", ", ".join(str(s) for s in seed_list), color_enabled=color_enabled)
    _print_row("Fairness", "Paired seeds: same seeds for all models", color_enabled=color_enabled, value_color="1;92")

    _print_section("Ranking (by avg score)", color_enabled)
    for row in model_summaries:
        rank = int(row["rank"])
        line = (
            f"#{rank} {row['model_profile']} | avg score {float(row['avg_final_score']):.2f} "
            f"| avg survival {float(row['avg_turns_survived']):.2f}/{float(row['max_turns_avg'] or 0):.0f} "
            f"({float(row['avg_survival_pct'] or 0):.1f}%)"
        )
        color = "1;92" if rank == 1 else "1;97"
        _print_row(f"Rank {rank}", line, color_enabled=color_enabled, value_color=color)

    if pairwise_rows:
        _print_section("Head-to-Head", color_enabled)
        for row in pairwise_rows:
            delta = row["avg_delta_a_minus_b"]
            delta_text = "not available" if delta is None else f"{delta:+.2f}"
            wr = row["win_rate_a_vs_b"]
            wr_text = "not available" if wr is None else f"{wr:.1f}%"
            summary = (
                f"{row['model_a_profile']} vs {row['model_b_profile']} | "
                f"win rate: {wr_text} | avg delta: {delta_text} | "
                f"W/L/T: {row['wins_a']}/{row['wins_b']}/{row['ties']}"
            )
            _print_row("Pair", summary, color_enabled=color_enabled, value_color="1;97")

    has_dummy = any(str(row.get("model_profile", "")).startswith("dummy") or str(row.get("model_profile", "")) == "legacy_dummy" for row in model_summaries)
    if has_dummy and len(model_summaries) > 1:
        _print_section("Baseline Note", color_enabled)
        _print_row(
            "Scope",
            "dummy_v0_1 is random baseline only; use head-to-head rows for model-vs-model interpretation.",
            color_enabled=color_enabled,
            value_color="0;37",
        )

    total_latency = _optional_sum([row.get("latency_ms") for row in run_rows])
    avg_latency = None
    if total_latency is not None and run_rows:
        avg_latency = total_latency / len(run_rows)

    total_tokens = _optional_sum([row.get("tokens_used") for row in run_rows])
    total_cost = _optional_sum([row.get("estimated_cost") for row in run_rows])

    _print_section("Performance", color_enabled)
    _print_row("Model latency total", _format_duration_from_ms(total_latency), color_enabled=color_enabled)
    _print_row("Model latency avg", _format_duration_from_ms(avg_latency), color_enabled=color_enabled)
    _print_row(
        "Tokens used total",
        _format_number(int(total_tokens) if total_tokens is not None else None),
        color_enabled=color_enabled,
    )
    _print_row(
        "Estimated cost total",
        _format_number(total_cost, digits=6),
        color_enabled=color_enabled,
    )

    _print_section("Artifacts", color_enabled)
    _print_row("Compare JSON", _short_path(compare_json), color_enabled=color_enabled, value_color="1;94")
    _print_row("Runs CSV", _short_path(runs_csv), color_enabled=color_enabled, value_color="1;94")
    _print_row("Models CSV", _short_path(models_csv), color_enabled=color_enabled, value_color="1;94")
    _print_row("H2H CSV", _short_path(h2h_csv), color_enabled=color_enabled, value_color="1;94")

    if not args.no_viewer:
        if args.viewer_output:
            viewer_output = Path(args.viewer_output)
            if not viewer_output.is_absolute():
                viewer_output = Path.cwd() / viewer_output
        else:
            viewer_output = dirs["replays"] / f"compare_{timestamp}_dashboard.html"

        viewer_title = args.viewer_title or f"TinyWorld Compare Dashboard - {scenario}"

        try:
            viewer_path = generate_compare_viewer(compare_path=compare_json, output_path=viewer_output, title=viewer_title)
            _print_row("HTML report", _short_path(viewer_path), color_enabled=color_enabled, value_color="1;94")

            viewer_target = viewer_path.resolve().as_uri()
            if args.serve is not None:
                serve_port = int(args.serve)
                serve_root = Path.cwd().resolve()
                server_pid, started = _ensure_http_server(port=serve_port, root_dir=serve_root)
                if started:
                    _print_row(
                        "HTTP server",
                        f"started on 127.0.0.1:{serve_port} (pid {server_pid})",
                        color_enabled=color_enabled,
                        value_color="1;92",
                    )
                else:
                    _print_row(
                        "HTTP server",
                        f"using existing 127.0.0.1:{serve_port}",
                        color_enabled=color_enabled,
                        value_color="1;93",
                    )
                viewer_target = _build_http_viewer_url(viewer_path=viewer_path, root_dir=serve_root, port=serve_port)
                _print_row("Viewer URL", viewer_target, color_enabled=color_enabled, value_color="1;94")

            if not args.no_open_viewer:
                opened = webbrowser.open(viewer_target)
                if opened:
                    _print_row("Viewer", "Opened in your default browser", color_enabled=color_enabled, value_color="1;92")
                else:
                    _print_row(
                        "Viewer",
                        "Generated, but browser did not open automatically",
                        color_enabled=color_enabled,
                        value_color="1;93",
                    )
        except Exception as exc:
            _print_row("Viewer error", str(exc), color_enabled=color_enabled, value_color="1;91")


if __name__ == "__main__":
    main()
