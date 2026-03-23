"""CLI entrypoint: run multi-run and multi-model TinyWorld comparisons."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import glob
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
import os
from pathlib import Path
import socket
from statistics import mean
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import quote
import webbrowser

from bench.cli_ui import StatusLine, colorize, format_eta, use_color
from bench.common import _build_run_analytics, load_yaml_file, resolve_artifact_dirs, run_match_once
from bench.pricing import estimate_cost_from_total_tokens, load_pricing_config, resolve_model_pricing
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
    "protocol_version",
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
    "avg_coverage_pct",
    "avg_revisit_ratio",
    "avg_conversion_efficiency_pct",
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


@dataclass(frozen=True)
class JobSpec:
    model_order: int
    model_profile: str
    seed_order: int
    seed: int
    job_index: int
    job_total: int


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


def _resolve_runs_root(raw_value: str) -> Path:
    root = Path(raw_value)
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    return root


def _build_run_dirs(runs_root: Path, run_id: str) -> dict[str, Path]:
    run_root = runs_root / run_id
    dirs = {
        "run_root": run_root,
        "logs": run_root / "logs",
        "results": run_root / "results",
        "replays": run_root / "replays",
        "checkpoint": run_root / "checkpoint",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


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


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalized_unique_strings(run_rows: list[dict[str, Any]], key: str) -> tuple[list[str], int]:
    values: set[str] = set()
    missing = 0
    for row in run_rows:
        raw = row.get(key)
        if raw is None:
            missing += 1
            continue
        text = str(raw).strip()
        if not text:
            missing += 1
            continue
        values.add(text)
    return sorted(values), missing


def _build_compatibility_report(run_rows: list[dict[str, Any]], fallback_protocol_version: str) -> dict[str, Any]:
    protocol_versions, protocol_missing = _normalized_unique_strings(run_rows, "protocol_version")
    if not protocol_versions and fallback_protocol_version:
        protocol_versions = [str(fallback_protocol_version)]

    prompt_hashes, prompt_missing = _normalized_unique_strings(run_rows, "prompt_set_sha256")
    bench_versions, bench_missing = _normalized_unique_strings(run_rows, "bench_version")
    engine_versions, engine_missing = _normalized_unique_strings(run_rows, "engine_version")

    warnings: list[dict[str, Any]] = []

    def add_mixed_warning(code: str, label: str, values: list[str]) -> None:
        if len(values) <= 1:
            return
        warnings.append(
            {
                "code": code,
                "message": f"Mixed {label}: {', '.join(values)}",
                "values": values,
            }
        )

    def add_missing_warning(code: str, label: str, missing_count: int) -> None:
        if missing_count <= 0:
            return
        warnings.append(
            {
                "code": code,
                "message": f"Missing {label} in {missing_count}/{len(run_rows)} runs.",
                "missing_runs": missing_count,
                "total_runs": len(run_rows),
            }
        )

    add_mixed_warning("mixed_protocol_version", "protocol versions", protocol_versions)
    add_mixed_warning("mixed_prompt_hash", "prompt hashes", prompt_hashes)
    add_mixed_warning("mixed_bench_version", "bench versions", bench_versions)
    add_mixed_warning("mixed_engine_version", "engine versions", engine_versions)

    add_missing_warning("missing_protocol_version", "protocol version", protocol_missing)
    add_missing_warning("missing_prompt_hash", "prompt hash", prompt_missing)
    add_missing_warning("missing_bench_version", "bench version", bench_missing)
    add_missing_warning("missing_engine_version", "engine version", engine_missing)

    return {
        "status": "warning" if warnings else "ok",
        "warnings": warnings,
        "protocol_versions": protocol_versions,
        "prompt_hashes": prompt_hashes,
        "bench_versions": bench_versions,
        "engine_versions": engine_versions,
    }


def _elapsed_seconds_from_run_rows(run_rows: list[dict[str, Any]]) -> float:
    total_ms = 0.0
    for row in run_rows:
        raw = row.get("latency_ms")
        if raw is None:
            continue
        try:
            total_ms += float(raw)
        except (TypeError, ValueError):
            continue
    return max(0.0, total_ms / 1000.0)


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

        coverage_values: list[float] = []
        revisit_values: list[float] = []
        conversion_values: list[float] = []
        for item in group:
            kpi = item.get("kpi")
            if not isinstance(kpi, dict):
                continue
            cov = _optional_float(kpi.get("coverage_pct"))
            rev = _optional_float(kpi.get("revisit_ratio"))
            conv = _optional_float(kpi.get("resource_conversion_efficiency_pct"))
            if cov is not None:
                coverage_values.append(cov)
            if rev is not None:
                revisit_values.append(rev)
            if conv is not None:
                conversion_values.append(conv)

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
                "avg_coverage_pct": round(mean(coverage_values), 4) if coverage_values else None,
                "avg_revisit_ratio": round(mean(revisit_values), 6) if revisit_values else None,
                "avg_conversion_efficiency_pct": round(mean(conversion_values), 4) if conversion_values else None,
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
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})
    tmp_path.replace(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
    tmp_path.replace(path)


def _compare_paths(dirs: dict[str, Path], compare_id: str) -> dict[str, Path]:
    checkpoint_dir = dirs.get("checkpoint", dirs["results"])
    return {
        "runs_csv": dirs["results"] / f"compare_runs_{compare_id}.csv",
        "models_csv": dirs["results"] / f"compare_models_{compare_id}.csv",
        "h2h_csv": dirs["results"] / f"compare_h2h_{compare_id}.csv",
        "compare_json": dirs["results"] / f"compare_{compare_id}.json",
        "checkpoint_json": checkpoint_dir / "compare_state.json",
    }


def _build_compare_payload(
    *,
    compare_id: str,
    run_rows: list[dict[str, Any]],
    run_payloads: list[dict[str, Any]],
    requested_models: list[str],
    seed_list: list[int],
    scenario: str,
    protocol_version: str,
    status: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    model_summaries = build_model_summaries(run_rows) if run_rows else []
    resolved_profiles = resolved_model_profiles(run_rows)
    pairwise_rows = build_pairwise_summary(run_rows, model_profiles=resolved_profiles, seed_list=seed_list)

    prompt_hashes = sorted({str(row.get("prompt_set_sha256")) for row in run_rows if row.get("prompt_set_sha256")})
    prompt_hash = prompt_hashes[0] if len(prompt_hashes) == 1 else ("mixed" if prompt_hashes else "not_available")
    compatibility = _build_compatibility_report(run_rows, fallback_protocol_version=protocol_version)

    compare_payload = {
        "meta": {
            "compare_id": compare_id,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "version": __version__,
            "bench_version": __version__,
            "engine_version": __version__,
            "protocol_version": protocol_version,
            "scenario": scenario,
            "seed_list": seed_list,
            "models": resolved_profiles,
            "requested_models": requested_models,
            "runs_per_model": len(seed_list),
            "total_runs_expected": len(requested_models) * len(seed_list),
            "total_runs": len(run_rows),
            "paired_seeds": True,
            "prompt_set_sha256": prompt_hash,
            "compatibility": compatibility,
            "status": status,
        },
        "models": model_summaries,
        "pairwise": pairwise_rows,
        "runs": run_payloads,
    }
    return compare_payload, model_summaries, pairwise_rows, resolved_profiles


def _persist_compare_outputs(
    *,
    paths: dict[str, Path],
    compare_id: str,
    requested_models: list[str],
    seed_list: list[int],
    scenario: str,
    protocol_version: str,
    status: str,
    run_rows: list[dict[str, Any]],
    run_payloads: list[dict[str, Any]],
    resume_context: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    compare_payload, model_summaries, pairwise_rows, resolved_profiles = _build_compare_payload(
        compare_id=compare_id,
        run_rows=run_rows,
        run_payloads=run_payloads,
        requested_models=requested_models,
        seed_list=seed_list,
        scenario=scenario,
        protocol_version=protocol_version,
        status=status,
    )

    _write_csv(paths["runs_csv"], COMPARE_RUN_FIELDS, run_rows)
    _write_csv(paths["models_csv"], MODEL_SUMMARY_FIELDS, model_summaries)
    _write_csv(paths["h2h_csv"], H2H_FIELDS, pairwise_rows)
    _write_json(paths["compare_json"], compare_payload)

    checkpoint_payload = {
        "schema": "tinyworld_compare_state_v1",
        "status": status,
        "compare_id": compare_id,
        "requested_models": requested_models,
        "seed_list": seed_list,
        "scenario": scenario,
        "protocol_version": protocol_version,
        "paths": {key: str(value) for key, value in paths.items()},
        "resume_context": resume_context,
        "run_rows": run_rows,
        "run_payloads": run_payloads,
    }
    _write_json(paths["checkpoint_json"], checkpoint_payload)
    return compare_payload, model_summaries, pairwise_rows, resolved_profiles


def _build_from_logs(
    *,
    compare_id: str,
    log_paths: list[Path],
    pricing_config_path: str | Path = "configs/pricing.yaml",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[int], str, str]:
    run_rows: list[dict[str, Any]] = []
    run_payloads: list[dict[str, Any]] = []

    profile_order: dict[str, int] = {}
    seed_order: dict[int, int] = {}
    protocol_version = "AIB-0.1"
    scenario = "-"
    pricing_cfg: dict[str, Any] | None = None
    pricing_path = Path(pricing_config_path)
    if not pricing_path.is_absolute():
        pricing_path = (Path.cwd() / pricing_path).resolve()
    if pricing_path.exists():
        pricing_cfg = load_pricing_config(pricing_path)

    for index, log_path in enumerate(log_paths, start=1):
        with log_path.open("r", encoding="utf-8") as handle:
            run_log = json.load(handle)

        summary = dict(run_log.get("run_summary", {}))
        if not summary:
            continue
        summary.setdefault("protocol_version", run_log.get("protocol_version"))

        if summary.get("estimated_cost") is None:
            provider_id = str(summary.get("provider_id", run_log.get("provider_id", "")))
            model_name = str(summary.get("model", run_log.get("model", "")))
            pricing = resolve_model_pricing(
                pricing_cfg=pricing_cfg,
                provider_id=provider_id,
                model=model_name,
            )
            estimated_cost = estimate_cost_from_total_tokens(
                pricing=pricing,
                total_tokens=summary.get("tokens_used"),
            )
            if estimated_cost is not None:
                summary["estimated_cost"] = round(estimated_cost, 6)
                summary["estimated_cost_source"] = "pricing_fallback_total_tokens"

        if (
            not isinstance(summary.get("kpi"), dict)
            or not summary.get("primary_failure_archetype")
            or not summary.get("short_summary")
        ):
            benchmark_rules = run_log.get("config_snapshot", {}).get("benchmark", {}).get("rules", {})
            initial_tiles = run_log.get("world_snapshots", {}).get("initial_tiles", [])
            analysis = _build_run_analytics(
                turn_logs=list(run_log.get("turn_logs", [])),
                run_summary=summary,
                rules_cfg=benchmark_rules if isinstance(benchmark_rules, dict) else {},
                initial_tiles=initial_tiles if isinstance(initial_tiles, list) else [],
                protocol_version=str(run_log.get("protocol_version", "AIB-0.1")),
            )
            summary["analysis_version"] = analysis["analysis_version"]
            summary["analysis_schema_version"] = analysis["analysis_schema_version"]
            summary["kpi"] = analysis["kpi"]
            summary["failure_archetypes"] = analysis["failure_archetypes"]
            summary["failure_archetypes_human"] = analysis["failure_archetypes_human"]
            summary["primary_failure_archetype"] = analysis["primary_failure_archetype"]
            summary["primary_failure_archetype_human"] = analysis["primary_failure_archetype_human"]
            summary["secondary_failure_archetypes"] = analysis["secondary_failure_archetypes"]
            summary["secondary_failure_archetypes_human"] = analysis["secondary_failure_archetypes_human"]
            summary["confidence_hint"] = analysis["confidence_hint"]
            summary["short_summary"] = analysis["short_summary"]
            summary["detailed_summary"] = analysis["detailed_summary"]

        profile = str(summary.get("model_profile", "unknown_profile"))
        seed = int(summary.get("seed", 0))

        if profile not in profile_order:
            profile_order[profile] = len(profile_order) + 1
        if seed not in seed_order:
            seed_order[seed] = len(seed_order) + 1

        run_id = f"{_safe_slug(profile)}__seed{seed}__log{index}"
        run_rows.append(
            {
                "compare_id": compare_id,
                "run_id": run_id,
                "job_index": index,
                "job_total": len(log_paths),
                "model_order": profile_order[profile],
                "seed_order": seed_order[seed],
                **summary,
            }
        )

        replay_payload = build_viewer_payload(run_log=run_log, source_log_path=log_path)
        run_payloads.append(
            {
                "run_id": run_id,
                "model_profile": summary.get("model_profile"),
                "provider_id": summary.get("provider_id"),
                "model": summary.get("model"),
                "seed": summary.get("seed"),
                "summary": summary,
                "replay": replay_payload,
            }
        )

        protocol_version = str(run_log.get("protocol_version", protocol_version))
        scenario = str(run_log.get("scenario", summary.get("scenario", scenario)))

    ordered_models = sorted(profile_order.keys(), key=lambda p: profile_order[p])
    ordered_seeds = sorted(seed_order.keys(), key=lambda s: seed_order[s])
    return run_rows, run_payloads, ordered_models, ordered_seeds, scenario, protocol_version


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not (1 <= port <= 65535):
        raise argparse.ArgumentTypeError("port must be in range 1..65535")
    return port


def _resolve_resume_checkpoint(resume_arg: str, runs_root: Path) -> Path:
    candidate = Path(resume_arg)
    if candidate.exists():
        return candidate.resolve()
    if not candidate.is_absolute():
        from_cwd = (Path.cwd() / candidate).resolve()
        if from_cwd.exists():
            return from_cwd

    run_id = resume_arg.strip()
    if not run_id:
        raise ValueError("resume value cannot be empty")
    checkpoint = runs_root / run_id / "checkpoint" / "compare_state.json"
    return checkpoint.resolve()


def _build_jobs(model_profiles: list[str], seed_list: list[int]) -> list[JobSpec]:
    total = len(model_profiles) * len(seed_list)
    jobs: list[JobSpec] = []
    idx = 0
    for model_order, model_profile in enumerate(model_profiles, start=1):
        for seed_order, seed in enumerate(seed_list, start=1):
            idx += 1
            jobs.append(
                JobSpec(
                    model_order=model_order,
                    model_profile=model_profile,
                    seed_order=seed_order,
                    seed=seed,
                    job_index=idx,
                    job_total=total,
                )
            )
    return jobs


def _compute_eta_text(
    *,
    completed_jobs: int,
    total_jobs: int,
    started_at: float,
    baseline_elapsed_seconds: float,
) -> str:
    if total_jobs <= 0:
        return "--"
    progress = completed_jobs / total_jobs
    if progress <= 0:
        return "--"
    elapsed = baseline_elapsed_seconds + max(0.0, time.monotonic() - started_at)
    remaining = max(0.0, (elapsed / progress) - elapsed)
    return format_eta(remaining)


def _job_log_path(logs_dir: Path, job: JobSpec) -> Path:
    return logs_dir / f"run_seed{job.seed}_{_safe_slug(job.model_profile)}.json"


def _execute_job(
    *,
    job: JobSpec,
    scenario: str,
    max_turns: int | None,
    benchmark_config_path: str,
    scenarios_config_path: str,
    providers_config_path: str,
    prompts_dir: str,
    output_logs_dir: Path,
    progress_callback: Any = None,
) -> dict[str, Any]:
    return run_match_once(
        seed=job.seed,
        model_name=job.model_profile,
        scenario_name=(None if scenario in {"", "-"} else scenario),
        max_turns=max_turns,
        benchmark_config_path=benchmark_config_path,
        scenarios_config_path=scenarios_config_path,
        providers_config_path=providers_config_path,
        prompts_dir=prompts_dir,
        output_path=_job_log_path(output_logs_dir, job),
        progress_callback=progress_callback,
    )


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
    parser.add_argument(
        "--runs-root",
        type=str,
        default="artifacts/runs",
        help="Root directory containing compare run folders (<runs-root>/<run_id>/...).",
    )
    parser.add_argument("--prompts-dir", type=str, default="prompts", help="Prompt templates directory.")
    parser.add_argument("--model-workers", type=int, default=1, help="Number of model pipelines running in parallel.")
    parser.add_argument("--seed-workers-per-model", type=int, default=1, help="Concurrent seeds per active model.")
    parser.add_argument(
        "--from-logs-glob",
        type=str,
        default=None,
        help="Build compare artifacts from existing run logs (glob pattern), without executing model calls.",
    )
    parser.add_argument(
        "--resume",
        type=str,
        default=None,
        help="Resume a previously interrupted compare run from checkpoint JSON.",
    )
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors in terminal output.")
    parser.add_argument("--no-viewer", action="store_true", help="Skip compare HTML generation.")
    parser.add_argument("--viewer-output", type=str, default=None, help="Output path for generated compare HTML report.")
    parser.add_argument("--viewer-title", type=str, default=None, help="Custom title for compare HTML report.")
    parser.add_argument("--open-browser", action="store_true", help="Open compare HTML in browser explicitly.")
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
    if args.open_browser and args.no_open_viewer:
        parser.error("--open-browser and --no-open-viewer are mutually exclusive.")
    if args.resume and args.from_logs_glob:
        parser.error("--resume and --from-logs-glob are mutually exclusive.")
    if args.model_workers < 1:
        parser.error("--model-workers must be >= 1")
    if args.seed_workers_per_model < 1:
        parser.error("--seed-workers-per-model must be >= 1")

    color_enabled = use_color(disable_color=args.no_color)
    status_line = StatusLine(enabled=True)

    print(colorize(f"TinyWorld Compare CLI v{__version__}", "1;36", color_enabled))

    benchmark_cfg = load_yaml_file(args.benchmark_config)
    # Keep legacy benchmark directories created for compatibility with existing tooling.
    resolve_artifact_dirs(benchmark_cfg, Path.cwd())

    runs_root = _resolve_runs_root(args.runs_root)
    runs_root.mkdir(parents=True, exist_ok=True)

    compare_started_at = time.monotonic()
    compare_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dirs = _build_run_dirs(runs_root, compare_id)
    paths = _compare_paths(run_dirs, compare_id)

    run_rows: list[dict[str, Any]] = []
    run_payloads: list[dict[str, Any]] = []
    scenario = str(args.scenario or benchmark_cfg.get("default_scenario", "-"))
    protocol_version = str(benchmark_cfg.get("protocol_version", "AIB-0.1"))
    model_profiles: list[str] = []
    seed_list: list[int] = []
    requested_models: list[str] = []
    eta_elapsed_baseline_seconds = 0.0
    effective_benchmark_config_path = str(Path(args.benchmark_config).resolve())
    effective_scenarios_config_path = str(Path(args.scenarios_config).resolve())
    effective_providers_config_path = str(Path(args.providers_config).resolve())
    effective_prompts_dir = str(Path(args.prompts_dir).resolve())
    effective_scenario_arg: str | None = args.scenario
    effective_max_turns = args.max_turns

    resume_context: dict[str, Any] = {
        "benchmark_config": effective_benchmark_config_path,
        "scenarios_config": effective_scenarios_config_path,
        "providers_config": effective_providers_config_path,
        "prompts_dir": effective_prompts_dir,
        "scenario_arg": effective_scenario_arg,
        "max_turns": effective_max_turns,
        "runs_root": str(runs_root),
        "run_id": compare_id,
        "model_workers": args.model_workers,
        "seed_workers_per_model": args.seed_workers_per_model,
    }

    if args.from_logs_glob:
        log_paths = sorted(Path(path).resolve() for path in glob.glob(args.from_logs_glob))
        if not log_paths:
            raise SystemExit(f"No logs matched pattern: {args.from_logs_glob}")

        run_rows, run_payloads, model_profiles, seed_list, scenario, protocol_version = _build_from_logs(
            compare_id=compare_id,
            log_paths=log_paths,
            pricing_config_path=str(benchmark_cfg.get("pricing_config_path", "configs/pricing.yaml")),
        )
        if not run_rows:
            raise SystemExit("Matched logs do not contain valid run_summary entries.")

        for idx, row in enumerate(run_rows, start=1):
            row["job_index"] = idx
            row["job_total"] = len(run_rows)

        requested_models = list(model_profiles)
        resume_context["from_logs_glob"] = args.from_logs_glob
        resume_context["run_id"] = compare_id

        compare_payload, model_summaries, pairwise_rows, resolved_profiles = _persist_compare_outputs(
            paths=paths,
            compare_id=compare_id,
            requested_models=requested_models,
            seed_list=seed_list,
            scenario=scenario,
            protocol_version=protocol_version,
            status="completed",
            run_rows=run_rows,
            run_payloads=run_payloads,
            resume_context=resume_context,
        )
    else:
        completed_keys: set[tuple[str, int]] = set()
        existing_by_key: dict[tuple[str, int], dict[str, Any]] = {}
        payload_by_key: dict[tuple[str, int], dict[str, Any]] = {}

        if args.resume:
            resume_path = _resolve_resume_checkpoint(args.resume, runs_root)
            if not resume_path.exists():
                raise SystemExit(f"Resume checkpoint not found: {resume_path}")

            with resume_path.open("r", encoding="utf-8") as handle:
                checkpoint = json.load(handle)

            if checkpoint.get("schema") != "tinyworld_compare_state_v1":
                raise SystemExit(f"Unsupported resume checkpoint schema in {resume_path}")

            compare_id = str(checkpoint.get("compare_id", compare_id))
            run_dirs = _build_run_dirs(runs_root, compare_id)
            paths = _compare_paths(run_dirs, compare_id)

            checkpoint_paths = checkpoint.get("paths")
            if isinstance(checkpoint_paths, dict):
                resolved_paths: dict[str, Path] = {}
                for key in {"runs_csv", "models_csv", "h2h_csv", "compare_json", "checkpoint_json"}:
                    if key in checkpoint_paths:
                        resolved_paths[key] = Path(str(checkpoint_paths[key])).resolve()
                if resolved_paths:
                    paths.update(resolved_paths)

            for file_path in paths.values():
                file_path.parent.mkdir(parents=True, exist_ok=True)

            model_profiles = [str(item) for item in checkpoint.get("requested_models", [])]
            seed_list = [int(item) for item in checkpoint.get("seed_list", [])]
            scenario = str(checkpoint.get("scenario", scenario))
            protocol_version = str(checkpoint.get("protocol_version", protocol_version))
            run_rows = list(checkpoint.get("run_rows", []))
            run_payloads = list(checkpoint.get("run_payloads", []))

            resume_context = dict(checkpoint.get("resume_context", resume_context))
            resume_context["resumed_from"] = str(resume_path)
            resume_context["run_id"] = compare_id
            resume_context["runs_root"] = str(runs_root)
            effective_benchmark_config_path = str(
                Path(str(resume_context.get("benchmark_config", effective_benchmark_config_path))).resolve()
            )
            effective_scenarios_config_path = str(
                Path(str(resume_context.get("scenarios_config", effective_scenarios_config_path))).resolve()
            )
            effective_providers_config_path = str(
                Path(str(resume_context.get("providers_config", effective_providers_config_path))).resolve()
            )
            effective_prompts_dir = str(Path(str(resume_context.get("prompts_dir", effective_prompts_dir))).resolve())
            resume_scenario = resume_context.get("scenario_arg", effective_scenario_arg)
            effective_scenario_arg = None if resume_scenario in {None, ""} else str(resume_scenario)
            resume_max_turns = resume_context.get("max_turns", effective_max_turns)
            effective_max_turns = None if resume_max_turns in {None, ""} else int(resume_max_turns)
            benchmark_cfg = load_yaml_file(effective_benchmark_config_path)

            requested_models = list(model_profiles)
            eta_elapsed_baseline_seconds = _elapsed_seconds_from_run_rows(run_rows)

            print(
                colorize(
                    f"Resuming compare {compare_id}: completed {len(run_rows)} runs, remaining runs will continue.",
                    "1;93",
                    color_enabled,
                )
            )
        else:
            model_profiles = parse_models(args.models)
            seed_list = resolve_seed_list(args.seeds, args.num_runs, args.seed_start)
            requested_models = list(model_profiles)

        if not model_profiles:
            raise SystemExit("No model profiles available for compare execution.")
        if not seed_list:
            raise SystemExit("No seeds available for compare execution.")

        jobs = _build_jobs(model_profiles, seed_list)
        jobs_by_key = {(job.model_profile, job.seed): job for job in jobs}

        for row in run_rows:
            key = (str(row.get("model_profile", "")), int(row.get("seed", 0)))
            job = jobs_by_key.get(key)
            if job is None:
                continue
            row["job_index"] = job.job_index
            row["job_total"] = job.job_total
            row["model_order"] = job.model_order
            row["seed_order"] = job.seed_order
            existing_by_key[key] = row
            completed_keys.add(key)

        for payload in run_payloads:
            summary = payload.get("summary", {})
            key = (str(summary.get("model_profile", payload.get("model_profile", ""))), int(summary.get("seed", payload.get("seed", 0))))
            if key in jobs_by_key:
                payload_by_key[key] = payload

        def _rebuild_ordered_collections() -> None:
            nonlocal run_rows, run_payloads
            ordered_keys = [(job.model_profile, job.seed) for job in jobs if (job.model_profile, job.seed) in existing_by_key]
            run_rows = [existing_by_key[key] for key in ordered_keys]
            run_payloads = [payload_by_key[key] for key in ordered_keys if key in payload_by_key]

        _rebuild_ordered_collections()
        completed_jobs = len(completed_keys)

        def _persist_running_state(status: str = "running") -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
            _rebuild_ordered_collections()
            return _persist_compare_outputs(
                paths=paths,
                compare_id=compare_id,
                requested_models=requested_models,
                seed_list=seed_list,
                scenario=scenario,
                protocol_version=protocol_version,
                status=status,
                run_rows=run_rows,
                run_payloads=run_payloads,
                resume_context=resume_context,
            )

        _persist_running_state(status="running")

        def _record_job_result(job: JobSpec, run_log: dict[str, Any]) -> dict[str, Any]:
            nonlocal scenario, protocol_version, completed_jobs

            summary = dict(run_log["run_summary"])
            scenario = str(run_log.get("scenario", scenario))
            protocol_version = str(run_log.get("protocol_version", protocol_version))
            summary.setdefault("protocol_version", run_log.get("protocol_version", protocol_version))

            run_row = {
                "compare_id": compare_id,
                "run_id": f"{_safe_slug(job.model_profile)}__seed{job.seed}",
                "job_index": job.job_index,
                "job_total": job.job_total,
                "model_order": job.model_order,
                "seed_order": job.seed_order,
                **summary,
            }
            key = (job.model_profile, job.seed)
            existing_by_key[key] = run_row
            completed_keys.add(key)
            completed_jobs = len(completed_keys)

            payload_by_key[key] = {
                "run_id": run_row["run_id"],
                "model_profile": summary["model_profile"],
                "provider_id": summary["provider_id"],
                "model": summary["model"],
                "seed": summary["seed"],
                "summary": summary,
                "replay": build_viewer_payload(run_log=run_log, source_log_path=Path(str(summary["log_path"]))),
            }

            _persist_running_state(status="running")
            return summary

        def _fail_and_exit(exc: Exception, job: JobSpec) -> None:
            _persist_running_state(status="failed")
            status_line.finish(colorize("[failed] Compare failed", "1;91", color_enabled))
            error_text = str(exc).strip() or exc.__class__.__name__
            print(
                colorize(
                    f"Compare failed during job {job.job_index}/{job.job_total} (model={job.model_profile}, seed={job.seed}): {error_text}",
                    "1;91",
                    color_enabled,
                )
            )
            print(colorize(f"Partial compare JSON: {_short_path(paths['compare_json'])}", "1;93", color_enabled))
            print(colorize(f"Resume: python -m bench.run_compare --resume {paths['checkpoint_json']}", "1;93", color_enabled))
            lowered = error_text.casefold()
            if "insufficient system resources" in lowered or "failed to load model" in lowered:
                print(
                    colorize(
                        "Hint: local model could not be loaded (RAM/VRAM guardrails). Use a smaller model or free resources in LM Studio.",
                        "1;93",
                        color_enabled,
                    )
                )
            raise SystemExit(1)

        total_jobs = len(jobs)
        parallel_enabled = not (args.model_workers == 1 and args.seed_workers_per_model == 1)

        if not parallel_enabled:
            for job in jobs:
                key = (job.model_profile, job.seed)
                if key in completed_keys:
                    continue

                run_progress = {
                    "max_turns": int(effective_max_turns if effective_max_turns is not None else benchmark_cfg.get("max_turns", 50)),
                }
                completed_before = completed_jobs

                def on_progress(event: dict[str, Any]) -> None:
                    event_type = str(event.get("event", ""))
                    if event_type == "run_started":
                        run_progress["max_turns"] = int(event.get("max_turns", run_progress["max_turns"]))
                        pct = (completed_before / total_jobs) * 100.0
                        status_line.write(
                            _render_turn_progress_line(
                                pct=pct,
                                job_index=job.job_index,
                                job_total=job.job_total,
                                turn=0,
                                max_turns=run_progress["max_turns"],
                                model_profile=job.model_profile,
                                seed=job.seed,
                                action="(initializing)",
                                protocol_valid=True,
                                effect_applied=False,
                                score=0,
                                invalid=0,
                                alive=True,
                                eta_text=_compute_eta_text(
                                    completed_jobs=completed_before,
                                    total_jobs=total_jobs,
                                    started_at=compare_started_at,
                                    baseline_elapsed_seconds=eta_elapsed_baseline_seconds,
                                ),
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
                    overall_fraction = (completed_before + run_fraction) / total_jobs
                    pct = overall_fraction * 100.0
                    eta_text = "--"
                    if overall_fraction > 0:
                        elapsed = eta_elapsed_baseline_seconds + max(0.0, time.monotonic() - compare_started_at)
                        remaining = max(0.0, (elapsed / overall_fraction) - elapsed)
                        eta_text = format_eta(remaining)

                    status_line.write(
                        _render_turn_progress_line(
                            pct=pct,
                            job_index=job.job_index,
                            job_total=job.job_total,
                            turn=turn,
                            max_turns=max_turns,
                            model_profile=job.model_profile,
                            seed=job.seed,
                            action=str(event.get("action") or "-"),
                            protocol_valid=bool(event.get("protocol_valid", False)),
                            effect_applied=bool(event.get("action_effect_applied", False)),
                            score=int(event.get("cumulative_score", 0)),
                            invalid=int(event.get("invalid_actions", 0)),
                            alive=bool(event.get("alive", True)),
                            eta_text=eta_text,
                            color_enabled=color_enabled,
                        )
                    )

                try:
                    run_log = _execute_job(
                        job=job,
                        scenario=scenario,
                        max_turns=effective_max_turns,
                        benchmark_config_path=effective_benchmark_config_path,
                        scenarios_config_path=effective_scenarios_config_path,
                        providers_config_path=effective_providers_config_path,
                        prompts_dir=effective_prompts_dir,
                        output_logs_dir=run_dirs["logs"],
                        progress_callback=on_progress,
                    )
                except KeyboardInterrupt:
                    _persist_running_state(status="interrupted")
                    status_line.finish(colorize("[interrupted] Compare canceled by user", "1;93", color_enabled))
                    print(colorize(f"Compare canceled (Ctrl+C) during job {job.job_index}/{job.job_total} (model={job.model_profile}, seed={job.seed}).", "1;93", color_enabled))
                    print(colorize(f"Resume: python -m bench.run_compare --resume {paths['checkpoint_json']}", "1;93", color_enabled))
                    raise SystemExit(130)
                except Exception as exc:
                    _fail_and_exit(exc, job)

                summary = _record_job_result(job, run_log)
                eta_text = _compute_eta_text(
                    completed_jobs=completed_jobs,
                    total_jobs=total_jobs,
                    started_at=compare_started_at,
                    baseline_elapsed_seconds=eta_elapsed_baseline_seconds,
                )
                pct_after = (completed_jobs / total_jobs) * 100.0
                status_line.write(
                    _render_job_done_line(
                        pct=pct_after,
                        job_index=job.job_index,
                        job_total=job.job_total,
                        model_profile=job.model_profile,
                        seed=job.seed,
                        score=int(summary["final_score"]),
                        status=("dead" if str(summary.get("end_reason")) == "agent_dead" else "finished"),
                        eta_text=eta_text,
                        color_enabled=color_enabled,
                    )
                )

            status_line.finish(colorize("[100.0%] compare run completed", "36", color_enabled))
        else:
            pending_jobs_by_model: dict[str, list[JobSpec]] = {
                profile: [job for job in jobs if job.model_profile == profile and (job.model_profile, job.seed) not in completed_keys]
                for profile in model_profiles
            }
            pending_model_order = [profile for profile in model_profiles if pending_jobs_by_model.get(profile)]
            if pending_model_order:
                status_line.write(
                    colorize(
                        f"Parallel mode: model_workers={args.model_workers}, seed_workers_per_model={args.seed_workers_per_model}",
                        "0;37",
                        color_enabled,
                    )
                )

            active_models: list[str] = []
            model_cursor = 0
            next_seed_index: dict[str, int] = {profile: 0 for profile in pending_model_order}
            running_per_model: dict[str, int] = {profile: 0 for profile in pending_model_order}
            progress_lock = threading.Lock()
            live_progress: dict[tuple[str, int], dict[str, Any]] = {}

            def activate_models() -> None:
                nonlocal model_cursor
                while len(active_models) < args.model_workers and model_cursor < len(pending_model_order):
                    model = pending_model_order[model_cursor]
                    model_cursor += 1
                    active_models.append(model)

            def _current_overall_fraction() -> float:
                partial = 0.0
                with progress_lock:
                    snapshots = list(live_progress.values())
                for snapshot in snapshots:
                    max_turns_local = int(snapshot.get("max_turns", 0))
                    turn_local = int(snapshot.get("turn", 0))
                    if max_turns_local > 0:
                        partial += max(0.0, min(1.0, float(turn_local) / float(max_turns_local)))
                if total_jobs <= 0:
                    return 0.0
                return max(0.0, min(1.0, (completed_jobs + partial) / total_jobs))

            def _render_parallel_heartbeat_line() -> str | None:
                with progress_lock:
                    if not live_progress:
                        return None
                    selected_key = max(
                        live_progress.keys(),
                        key=lambda key: (
                            float(live_progress[key].get("updated_at", 0.0)),
                            -jobs_by_key[key].job_index,
                        ),
                    )
                    selected = dict(live_progress[selected_key])

                selected_job = jobs_by_key[selected_key]
                fraction = _current_overall_fraction()
                pct = fraction * 100.0
                eta_text = "--"
                if fraction > 0:
                    elapsed = eta_elapsed_baseline_seconds + max(0.0, time.monotonic() - compare_started_at)
                    remaining = max(0.0, (elapsed / fraction) - elapsed)
                    eta_text = format_eta(remaining)

                return _render_turn_progress_line(
                    pct=pct,
                    job_index=selected_job.job_index,
                    job_total=selected_job.job_total,
                    turn=int(selected.get("turn", 0)),
                    max_turns=int(selected.get("max_turns", 1)),
                    model_profile=selected_job.model_profile,
                    seed=selected_job.seed,
                    action=str(selected.get("action") or "(initializing)"),
                    protocol_valid=bool(selected.get("protocol_valid", True)),
                    effect_applied=bool(selected.get("effect_applied", False)),
                    score=int(selected.get("score", 0)),
                    invalid=int(selected.get("invalid", 0)),
                    alive=bool(selected.get("alive", True)),
                    eta_text=eta_text,
                    color_enabled=color_enabled,
                )

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, args.model_workers * args.seed_workers_per_model)
            ) as executor:
                future_to_job: dict[concurrent.futures.Future[dict[str, Any]], JobSpec] = {}

                def submit_for_model(model_profile: str) -> None:
                    pending_jobs = pending_jobs_by_model[model_profile]
                    while running_per_model[model_profile] < args.seed_workers_per_model and next_seed_index[model_profile] < len(pending_jobs):
                        job = pending_jobs[next_seed_index[model_profile]]
                        next_seed_index[model_profile] += 1
                        key = (job.model_profile, job.seed)
                        default_max_turns = int(
                            effective_max_turns if effective_max_turns is not None else benchmark_cfg.get("max_turns", 50)
                        )
                        with progress_lock:
                            live_progress[key] = {
                                "turn": 0,
                                "max_turns": default_max_turns,
                                "action": "(initializing)",
                                "protocol_valid": True,
                                "effect_applied": False,
                                "score": 0,
                                "invalid": 0,
                                "alive": True,
                                "updated_at": time.monotonic(),
                            }

                        def on_progress(event: dict[str, Any], *, event_key: tuple[str, int] = key) -> None:
                            event_type = str(event.get("event", ""))
                            update: dict[str, Any] = {}
                            if event_type == "run_started":
                                update = {
                                    "turn": 0,
                                    "max_turns": int(event.get("max_turns", default_max_turns)),
                                    "action": "(initializing)",
                                    "protocol_valid": True,
                                    "effect_applied": False,
                                    "score": 0,
                                    "invalid": 0,
                                    "alive": True,
                                }
                            elif event_type == "turn_completed":
                                update = {
                                    "turn": int(event.get("turn", 0)),
                                    "max_turns": int(event.get("max_turns", default_max_turns)),
                                    "action": str(event.get("action") or "-"),
                                    "protocol_valid": bool(event.get("protocol_valid", False)),
                                    "effect_applied": bool(event.get("action_effect_applied", False)),
                                    "score": int(event.get("cumulative_score", 0)),
                                    "invalid": int(event.get("invalid_actions", 0)),
                                    "alive": bool(event.get("alive", True)),
                                }
                            if not update:
                                return
                            update["updated_at"] = time.monotonic()
                            with progress_lock:
                                if event_key in live_progress:
                                    live_progress[event_key].update(update)

                        future = executor.submit(
                            _execute_job,
                            job=job,
                            scenario=scenario,
                            max_turns=effective_max_turns,
                            benchmark_config_path=effective_benchmark_config_path,
                            scenarios_config_path=effective_scenarios_config_path,
                            providers_config_path=effective_providers_config_path,
                            prompts_dir=effective_prompts_dir,
                            output_logs_dir=run_dirs["logs"],
                            progress_callback=on_progress,
                        )
                        future_to_job[future] = job
                        running_per_model[model_profile] += 1

                activate_models()
                for model in list(active_models):
                    submit_for_model(model)

                while future_to_job:
                    try:
                        done, _ = concurrent.futures.wait(
                            set(future_to_job.keys()),
                            timeout=0.6,
                            return_when=concurrent.futures.FIRST_COMPLETED,
                        )
                    except KeyboardInterrupt:
                        for future in future_to_job:
                            future.cancel()
                        _persist_running_state(status="interrupted")
                        status_line.finish(colorize("[interrupted] Compare canceled by user", "1;93", color_enabled))
                        print(colorize("Compare canceled (Ctrl+C).", "1;93", color_enabled))
                        print(colorize(f"Resume: python -m bench.run_compare --resume {paths['checkpoint_json']}", "1;93", color_enabled))
                        sys.stdout.flush()
                        sys.stderr.flush()
                        os._exit(130)

                    if not done:
                        heartbeat_line = _render_parallel_heartbeat_line()
                        if heartbeat_line:
                            status_line.write(heartbeat_line)
                        continue

                    for future in done:
                        job = future_to_job.pop(future)
                        running_per_model[job.model_profile] -= 1
                        with progress_lock:
                            live_progress.pop((job.model_profile, job.seed), None)
                        try:
                            run_log = future.result()
                        except Exception as exc:
                            for pending_future in future_to_job:
                                pending_future.cancel()
                            _fail_and_exit(exc, job)
                        summary = _record_job_result(job, run_log)

                        pct_after = (completed_jobs / total_jobs) * 100.0
                        eta_text = _compute_eta_text(
                            completed_jobs=completed_jobs,
                            total_jobs=total_jobs,
                            started_at=compare_started_at,
                            baseline_elapsed_seconds=eta_elapsed_baseline_seconds,
                        )
                        status_line.write(
                            _render_job_done_line(
                                pct=pct_after,
                                job_index=job.job_index,
                                job_total=job.job_total,
                                model_profile=job.model_profile,
                                seed=job.seed,
                                score=int(summary["final_score"]),
                                status=("dead" if str(summary.get("end_reason")) == "agent_dead" else "finished"),
                                eta_text=eta_text,
                                color_enabled=color_enabled,
                            )
                        )

                    for model in list(active_models):
                        if running_per_model[model] == 0 and next_seed_index[model] >= len(pending_jobs_by_model[model]):
                            active_models.remove(model)
                    activate_models()
                    for model in list(active_models):
                        submit_for_model(model)

            status_line.finish(colorize("[100.0%] compare run completed", "36", color_enabled))

        compare_payload, model_summaries, pairwise_rows, resolved_profiles = _persist_running_state(status="completed")

    compare_json = paths["compare_json"]
    runs_csv = paths["runs_csv"]
    models_csv = paths["models_csv"]
    h2h_csv = paths["h2h_csv"]

    print()
    print(colorize("COMPARE SUMMARY", "1;32", color_enabled))

    _print_section("Identity", color_enabled)
    _print_row("Protocol", protocol_version, color_enabled=color_enabled)
    _print_row("Scenario", scenario, color_enabled=color_enabled)
    _print_row("Run ID", compare_id, color_enabled=color_enabled, value_color="1;93")
    _print_row("Run root", _short_path(run_dirs["run_root"]), color_enabled=color_enabled, value_color="1;94")
    _print_row("Models (requested)", ", ".join(requested_models), color_enabled=color_enabled)
    _print_row("Models (resolved)", ", ".join(resolved_profiles), color_enabled=color_enabled)
    _print_row("Seeds", ", ".join(str(s) for s in seed_list), color_enabled=color_enabled)
    _print_row("Fairness", "Paired seeds: same seeds for all models", color_enabled=color_enabled, value_color="1;92")

    compatibility = compare_payload.get("meta", {}).get("compatibility", {}) if isinstance(compare_payload, dict) else {}
    compatibility_warnings = compatibility.get("warnings", []) if isinstance(compatibility, dict) else []
    if compatibility_warnings:
        _print_section("Compatibility Warnings", color_enabled)
        for warning in compatibility_warnings:
            message = str(warning.get("message", "")).strip()
            if not message:
                continue
            _print_row("Warning", message, color_enabled=color_enabled, value_color="1;93")

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

    has_dummy = any(
        str(row.get("model_profile", "")).startswith("dummy") or str(row.get("model_profile", "")) == "legacy_dummy"
        for row in model_summaries
    )
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
    _print_row("Checkpoint", _short_path(paths["checkpoint_json"]), color_enabled=color_enabled, value_color="1;94")

    if not args.no_viewer:
        if args.viewer_output:
            viewer_output = Path(args.viewer_output)
            if not viewer_output.is_absolute():
                viewer_output = (Path.cwd() / viewer_output).resolve()
        else:
            viewer_output = run_dirs["replays"] / f"compare_{compare_id}_dashboard.html"

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

            should_open = args.open_browser or (not args.no_open_viewer)
            if should_open:
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
