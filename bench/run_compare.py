"""CLI entrypoint: run multi-run and multi-model TinyWorld comparisons."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import glob
import heapq
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
import os
from pathlib import Path
import shlex
import socket
from statistics import mean
import math
import re as _re
import subprocess
import sys
import threading
import time
import textwrap
from typing import Any
from urllib.parse import quote
import webbrowser

from bench.cli_ui import StatusLine, colorize, format_eta, use_color
from bench.common import (
    _build_run_analytics,
    create_model_wrapper,
    load_yaml_file,
    resolve_artifact_dirs,
    run_match_once,
)
from bench.pricing import estimate_cost_from_total_tokens, load_pricing_config, resolve_model_pricing
from bench.view_compare import generate_compare_viewer
from bench.view_log import build_viewer_payload
from engine.prompt_loader import PromptLoader
from engine.version import __version__
from memory.filter import filter_lessons
from memory.reflection import run_cross_seed_refinement, run_seed_reflection
from memory.session import lessons_to_prompt_items, merge_lessons, normalize_lesson_text, save_json

ADAPTIVE_MEMORY_PROMOTION_MIN_DELTA = -3


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
    "attempt_kind",
    "memory_injected",
    "memory_lesson_count",
    "adaptive_pair_key",
    "log_path",
]

ADAPTIVE_RUN_FIELDS = COMPARE_RUN_FIELDS

ADAPTIVE_PAIR_FIELDS = [
    "compare_id",
    "model_profile",
    "seed",
    "adaptive_pair_key",
    "initial_score",
    "control_score",
    "adaptive_score",
    "control_delta",
    "adaptive_delta",
    "memory_effect",
    "initial_turns_survived",
    "control_turns_survived",
    "adaptive_turns_survived",
    "control_delta_turns",
    "adaptive_delta_turns",
    "initial_invalid_actions",
    "control_invalid_actions",
    "adaptive_invalid_actions",
    "initial_resources_gathered",
    "control_resources_gathered",
    "adaptive_resources_gathered",
    "lessons_before_count",
    "lessons_added_count",
    "lessons_after_count",
    "memory_promoted",
    "reflection_parse_error",
    "reflection_path",
    "memory_snapshot_path",
]

ADAPTIVE_MODEL_FIELDS = [
    "model_profile",
    "runs",
    "baseline_score_total",
    "adaptive_score_total",
    "delta_score_total",
    "baseline_score_avg",
    "adaptive_score_avg",
    "delta_score_avg",
    "baseline_turns_survived_avg",
    "adaptive_turns_survived_avg",
    "delta_turns_survived_avg",
    "baseline_invalid_actions_avg",
    "adaptive_invalid_actions_avg",
    "delta_invalid_actions_avg",
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
    "prompt_tokens_total",
    "completion_tokens_total",
    "estimated_cost_total",
    "estimated_cost_adaptive",
    "estimated_cost_grand_total",
    "tokens_used_adaptive",
    "tokens_used_grand_total",
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


@dataclass(frozen=True)
class AdaptiveFutureSpec:
    kind: str  # "initial" | "adaptive_followup"
    job: JobSpec


def parse_models(raw: str | list[str]) -> list[str]:
    if isinstance(raw, list):
        raw_text = " ".join(str(item).strip() for item in raw if str(item).strip())
    else:
        raw_text = str(raw).strip()
    models = [item.strip() for item in raw_text.split(",") if item.strip()]
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


def _providers_config_from_argv(argv: list[str], default: str = "configs/providers.yaml") -> str:
    for index, token in enumerate(argv):
        if token == "--providers-config" and index + 1 < len(argv):
            value = str(argv[index + 1]).strip()
            if value:
                return value
        if token.startswith("--providers-config="):
            value = token.split("=", 1)[1].strip()
            if value:
                return value
    return default


def _available_identity_from_config(
    config_path: str,
) -> tuple[list[str], dict[str, list[str]], dict[str, dict[str, list[str]]]]:
    try:
        cfg = load_yaml_file(config_path)
    except Exception:
        return [], {}, {}

    profiles_cfg = cfg.get("model_profiles", {})
    providers_cfg = cfg.get("providers", {})
    if not isinstance(profiles_cfg, dict):
        profiles_cfg = {}
    if not isinstance(providers_cfg, dict):
        providers_cfg = {}

    profiles = sorted(str(name).strip() for name in profiles_cfg.keys() if str(name).strip())
    grouped: dict[str, list[str]] = {}
    grouped_by_family: dict[str, dict[str, list[str]]] = {}
    for profile in profiles:
        profile_cfg = profiles_cfg.get(profile, {})
        provider_id = (
            str(profile_cfg.get("provider", "")).strip()
            if isinstance(profile_cfg, dict)
            else ""
        )
        if not provider_id:
            provider_id = "unknown"
        grouped.setdefault(provider_id, []).append(profile)

        model_name = ""
        if isinstance(profile_cfg, dict):
            model_name = str(profile_cfg.get("model", profile_cfg.get("model_name", ""))).strip()
        if provider_id == "dummy_provider":
            family = "dummy"
        elif "/" in model_name:
            family = model_name.split("/", 1)[0].strip().lower() or "other"
        elif model_name:
            family = "other"
        elif provider_id == "local_lmstudio":
            family = "local"
        else:
            family = "other"
        grouped_by_family.setdefault(provider_id, {}).setdefault(family, []).append(profile)

    for provider_id in list(grouped.keys()):
        grouped[provider_id] = sorted(grouped[provider_id])
    for provider_id, family_map in list(grouped_by_family.items()):
        normalized: dict[str, list[str]] = {}
        for family, family_profiles in family_map.items():
            normalized[family] = sorted(family_profiles)
        grouped_by_family[provider_id] = dict(sorted(normalized.items(), key=lambda item: item[0]))

    # Keep provider order stable by provider name for deterministic output.
    grouped = dict(sorted(grouped.items(), key=lambda item: item[0]))
    grouped_by_family = dict(sorted(grouped_by_family.items(), key=lambda item: item[0]))
    return profiles, grouped, grouped_by_family


def _wrap_items_for_cli(items: list[str], *, indent: str, width: int = 110) -> list[str]:
    if not items:
        return []
    payload = ", ".join(str(item).strip() for item in items if str(item).strip())
    if not payload:
        return []
    return textwrap.wrap(
        payload,
        width=width,
        initial_indent=indent,
        subsequent_indent=indent,
        break_long_words=False,
        break_on_hyphens=False,
    )


class _CompareArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # noqa: D401 - argparse API
        disable_color = "--no-color" in sys.argv
        color_enabled = use_color(disable_color=disable_color)

        sys.stderr.write(colorize(f"TinyWorld Compare CLI v{__version__}", "1;34", color_enabled) + "\n")
        self.print_usage(sys.stderr)

        argv = list(sys.argv[1:])
        providers_cfg_path = _providers_config_from_argv(argv)
        model_profiles, grouped_profiles, grouped_by_family = _available_identity_from_config(providers_cfg_path)

        error_prefix = colorize(f"{self.prog}: error:", "1;31", color_enabled)
        if message.startswith("unrecognized arguments:"):
            unknown = message.split("unrecognized arguments:", 1)[1].strip()
            unknown_tokens = [token for token in unknown.split(" ") if token]
            unknown_colored = " ".join(colorize(token, "1;33", color_enabled) for token in unknown_tokens)
            msg_colored = colorize("unrecognized arguments:", "1;31", color_enabled)
            sys.stderr.write(f"{error_prefix} {msg_colored} {unknown_colored}\n")
        else:
            sys.stderr.write(f"{error_prefix} {colorize(message, '1;31', color_enabled)}\n")
        if "unrecognized arguments" in message:
            sys.stderr.write("\n")
            sys.stderr.write(
                "Hint: pass --models as one argument, e.g. --models model_a,model_b "
                "(if you use spaces, wrap with quotes).\n"
            )

        if model_profiles:
            sys.stderr.write("\nAvailable model profiles (grouped by provider):\n")
            for provider_id in sorted(grouped_profiles.keys()):
                items = grouped_profiles.get(provider_id, [])
                if not items:
                    continue
                provider_name = colorize(provider_id, "1;36", color_enabled)
                sys.stderr.write(f"  {provider_name} ({len(items)}):\n")
                families = grouped_by_family.get(provider_id, {})
                if families:
                    for family_name, family_profiles in families.items():
                        family_colored = colorize(family_name, "1;95", color_enabled)
                        sys.stderr.write(f"    {family_colored} ({len(family_profiles)}):\n")
                        for line in _wrap_items_for_cli(family_profiles, indent="      "):
                            sys.stderr.write(f"{line}\n")
                else:
                    for line in _wrap_items_for_cli(items, indent="    "):
                        sys.stderr.write(f"{line}\n")

        raise SystemExit(2)


def _short_path(path: str | Path) -> str:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved).resolve()

    cwd = Path.cwd().resolve()
    try:
        return str(resolved.relative_to(cwd))
    except ValueError:
        return str(resolved)


def _format_run_id_with_started(run_id: str) -> str:
    raw = str(run_id).strip()
    parsed: datetime | None = None
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S"):
        try:
            parsed = datetime.strptime(raw, pattern)
            break
        except ValueError:
            continue
    if parsed is None:
        return raw
    human_started = parsed.strftime("Started: %H:%M:%S - %d/%m/%Y")
    return f"{raw} ({human_started})"


def _render_run_id_value(run_id: str, *, color_enabled: bool) -> str:
    raw = str(run_id).strip()
    parsed: datetime | None = None
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S"):
        try:
            parsed = datetime.strptime(raw, pattern)
            break
        except ValueError:
            continue
    if parsed is None:
        return colorize(raw, "1;93", color_enabled)
    human_started = parsed.strftime("Started: %H:%M:%S - %d/%m/%Y")
    if not color_enabled:
        return f"{raw} ({human_started})"
    run_text = colorize(raw, "1;93", color_enabled)
    started_text = colorize(human_started, "1;97", color_enabled)
    return f"{run_text} ({started_text})"


def _resume_command(checkpoint_path: str | Path) -> str:
    resume_path = _short_path(checkpoint_path)
    return f"python -m bench.run_compare --resume {shlex.quote(resume_path)}"


def _render_models_value(models_text: str, *, color_enabled: bool) -> str:
    raw_items = [part.strip() for part in str(models_text).split(",") if part.strip()]
    if not raw_items:
        return colorize("-", "1;97", color_enabled)
    if not color_enabled:
        return ", ".join(raw_items)

    palette = ("1;96", "1;95", "1;92", "1;94", "1;93")
    rendered: list[str] = []
    for item in raw_items:
        color = palette[abs(hash(item)) % len(palette)]
        rendered.append(colorize(item, color, color_enabled))
    sep = colorize(", ", "1;97", color_enabled)
    return sep.join(rendered)


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
        "memory": run_root / "memory",
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
    value_already_colored: bool = False,
) -> None:
    label_text = colorize(f"{label:<22}", label_color, color_enabled)
    value_text = value if value_already_colored else colorize(value, value_color, color_enabled)
    print(f"  {label_text} {value_text}")


def _print_start_identity(
    *,
    color_enabled: bool,
    protocol_version: str,
    scenario: str,
    run_id: str,
    resume_time_human: str | None,
    run_root: Path,
    model_profiles: list[str],
    models_text: str,
    providers_text: str,
    routing_text: str,
    model_workers: int,
    seed_workers_per_model: int,
    moral_mode: bool,
) -> None:
    _print_section("Identity", color_enabled)
    _print_row("Protocol", protocol_version, color_enabled=color_enabled)
    _print_row("Scenario", scenario, color_enabled=color_enabled)
    _print_row(
        "Run ID",
        _render_run_id_value(run_id, color_enabled=color_enabled),
        color_enabled=color_enabled,
        value_already_colored=True,
    )
    if resume_time_human:
        _print_row("Resume time", resume_time_human, color_enabled=color_enabled)
    _print_row("Run root", _short_path(run_root), color_enabled=color_enabled, value_color="1;94")
    _print_row("Models (requested)", ", ".join(model_profiles), color_enabled=color_enabled)
    _print_row("Models (resolved)", ", ".join(model_profiles), color_enabled=color_enabled)
    _print_row(
        "Model(s)",
        _render_models_value(models_text, color_enabled=color_enabled),
        color_enabled=color_enabled,
        value_already_colored=True,
    )
    _print_row("Provider(s)", providers_text, color_enabled=color_enabled)
    _print_row("Routing", routing_text, color_enabled=color_enabled, value_color="1;93")
    _print_row("Parallel Per Model", str(model_workers), color_enabled=color_enabled)
    _print_row("Parallel per Seed", str(seed_workers_per_model), color_enabled=color_enabled)
    _print_row("Moral framing", ("on" if moral_mode else "off"), color_enabled=color_enabled)
    print()


def _resolve_models_and_providers_for_identity(
    model_profiles: list[str],
    providers_config_path: str,
) -> tuple[str, str, str]:
    default_models_text = ", ".join(model_profiles) if model_profiles else "-"
    default_providers_text = "-"
    default_routing_text = "-"
    if not model_profiles:
        return default_models_text, default_providers_text, default_routing_text

    try:
        providers_cfg = load_yaml_file(providers_config_path)
    except Exception:
        return default_models_text, default_providers_text, default_routing_text

    profiles_cfg = providers_cfg.get("model_profiles", {})
    if not isinstance(profiles_cfg, dict):
        return default_models_text, default_providers_text, default_routing_text

    resolved_models: list[str] = []
    resolved_providers: list[str] = []
    routing_hints: list[str] = []

    for profile in model_profiles:
        profile_cfg = profiles_cfg.get(profile)
        if not isinstance(profile_cfg, dict):
            continue

        provider_id = profile_cfg.get("provider")
        if provider_id is not None:
            provider_text = str(provider_id).strip()
            if provider_text and provider_text not in resolved_providers:
                resolved_providers.append(provider_text)

        model_name = profile_cfg.get("model", profile_cfg.get("model_name"))
        if model_name is not None:
            model_text = str(model_name).strip()
            if model_text and model_text not in resolved_models:
                resolved_models.append(model_text)

        provider_options = profile_cfg.get("provider_options", {})
        gateway_options = provider_options.get("gateway", {}) if isinstance(provider_options, dict) else {}

        only_raw = gateway_options.get("only") if isinstance(gateway_options, dict) else None
        order_raw = gateway_options.get("order") if isinstance(gateway_options, dict) else None
        only_list = [str(item).strip() for item in only_raw] if isinstance(only_raw, list) else []
        order_list = [str(item).strip() for item in order_raw] if isinstance(order_raw, list) else []
        only_list = [item for item in only_list if item]
        order_list = [item for item in order_list if item]

        provider_text = str(provider_id).strip() if provider_id is not None else ""
        if provider_text == "vercel_gateway":
            if only_list:
                route = f"{profile} -> gateway only: {', '.join(only_list)}"
                if order_list:
                    route += f" (order: {', '.join(order_list)})"
            elif order_list:
                route = f"{profile} -> gateway order: {', '.join(order_list)}"
            else:
                route = f"{profile} -> gateway default routing"
        elif provider_text:
            route = f"{profile} -> {provider_text}"
        else:
            route = f"{profile} -> unknown"

        if route not in routing_hints:
            routing_hints.append(route)

    models_text = ", ".join(resolved_models) if resolved_models else default_models_text
    providers_text = ", ".join(resolved_providers) if resolved_providers else default_providers_text
    routing_text = "; ".join(routing_hints) if routing_hints else default_routing_text
    return models_text, providers_text, routing_text


def _print_adaptive_live_snapshot(
    *,
    status_line: StatusLine,
    color_enabled: bool,
    model_profiles: list[str],
    seed_list: list[int],
    initial_rows_by_key: dict[tuple[str, int], dict[str, Any]],
    control_rows_by_key: dict[tuple[str, int], dict[str, Any]],
    adaptive_rows_by_key: dict[tuple[str, int], dict[str, Any]],
    adaptive_pairs_by_key: dict[tuple[str, int], dict[str, Any]] | None = None,
    live_attempt_scores_by_key: dict[tuple[str, int, str], int] | None = None,
    active_attempts_by_key: dict[tuple[str, int], str] | None = None,
    previous_line_count: int,
) -> int:
    def _maybe_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _render_field(
        name: str,
        raw_value: int | str,
        *,
        pending: bool,
        active: bool,
        color_by_sign: bool = False,
    ) -> str:
        text = f"{name}={raw_value}"
        if not color_enabled:
            return text
        if active:
            return colorize(text, "1;96", color_enabled)
        if pending:
            return colorize(text, "0;37", color_enabled)
        if color_by_sign:
            raw_text = str(raw_value).strip()
            if raw_text.startswith("+"):
                return colorize(text, "1;92", color_enabled)
            if raw_text.startswith("-"):
                return colorize(text, "1;91", color_enabled)
            return colorize(text, "0;37", color_enabled)
        return colorize(text, "1;97", color_enabled)

    status_line.clear()
    lines: list[str] = [
        "",
        colorize("Adaptive Session (live)", "1;35", color_enabled),
    ]
    single_model = len(model_profiles) <= 1
    for model_profile in model_profiles:
        for seed in seed_list:
            key = (model_profile, int(seed))
            pair_row = dict((adaptive_pairs_by_key or {}).get(key, {}))
            initial_score = _maybe_int(dict(initial_rows_by_key.get(key, {})).get("final_score"))
            control_score = _maybe_int(dict(control_rows_by_key.get(key, {})).get("final_score"))
            adaptive_score = _maybe_int(dict(adaptive_rows_by_key.get(key, {})).get("final_score"))
            if initial_score is None:
                initial_score = _maybe_int(pair_row.get("initial_score"))
            if control_score is None:
                control_score = _maybe_int(pair_row.get("control_score"))
            if adaptive_score is None:
                adaptive_score = _maybe_int(pair_row.get("adaptive_score"))
            if control_score is None and live_attempt_scores_by_key is not None:
                control_score = _maybe_int(
                    live_attempt_scores_by_key.get((model_profile, int(seed), "control_rerun"))
                )
            if adaptive_score is None and live_attempt_scores_by_key is not None:
                adaptive_score = _maybe_int(
                    live_attempt_scores_by_key.get((model_profile, int(seed), "adaptive_rerun"))
                )

            variance_text = "--"
            memory_text = "--"

            if initial_score is not None and control_score is not None:
                variance_delta = int(control_score) - int(initial_score)
                variance_text = f"{variance_delta:+d}"

            if control_score is not None and adaptive_score is not None:
                no_mem_avg = (int(initial_score) + int(control_score)) / 2 if initial_score is not None else int(control_score)
                memory_effect = int(adaptive_score) - no_mem_avg
                memory_text = f"{memory_effect:+.1f}"

            active_attempt = str((active_attempts_by_key or {}).get(key, "")).strip()
            baseline_field = _render_field(
                "baseline",
                initial_score if initial_score is not None else "--",
                pending=(initial_score is None),
                active=(active_attempt == "initial"),
            )
            rerun_field = _render_field(
                "rerun",
                control_score if control_score is not None else "--",
                pending=(control_score is None),
                active=(active_attempt == "control_rerun"),
            )
            rerun_mem_field = _render_field(
                "rerun+mem",
                adaptive_score if adaptive_score is not None else "--",
                pending=(adaptive_score is None),
                active=(active_attempt == "adaptive_rerun"),
            )
            variance_field = _render_field(
                "variance",
                variance_text,
                pending=(variance_text == "--"),
                active=False,
            )
            memory_field = _render_field(
                "memory",
                memory_text,
                pending=(memory_text == "--"),
                active=False,
                color_by_sign=True,
            )

            label = f"Seed {seed}" if single_model else f"{model_profile} seed {seed}"
            value = f"{baseline_field}  {rerun_field}  {rerun_mem_field}  {variance_field}  {memory_field}"
            label_text = colorize(f"{label:<22}", "1;36", color_enabled)
            lines.append(f"  {label_text} {value}")
    lines.append("")

    supports_inplace = sys.stdout.isatty()
    if not supports_inplace and previous_line_count > 0:
        # Non-interactive output: avoid appending a full panel snapshot every update.
        return previous_line_count

    if supports_inplace and previous_line_count > 0:
        sys.stdout.write(f"\x1b[{previous_line_count}A")
        for _ in range(previous_line_count):
            sys.stdout.write("\x1b[2K\x1b[1B")
        sys.stdout.write(f"\x1b[{previous_line_count}A")

    for line in lines:
        sys.stdout.write(line + "\n")
    sys.stdout.flush()
    return len(lines)


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


def _assert_adaptive_prompt_hash_consistency(
    *,
    adaptive_enabled: bool,
    run_rows: list[dict[str, Any]],
    adaptive_run_rows: list[dict[str, Any]],
) -> None:
    if not adaptive_enabled:
        return
    prompt_hashes, _ = _normalized_unique_strings(
        list(run_rows) + list(adaptive_run_rows),
        "prompt_set_sha256",
    )
    if len(prompt_hashes) <= 1:
        return
    raise RuntimeError(
        "adaptive compare aborted: mixed prompt_set_sha256 detected within the same compare run: "
        + ", ".join(prompt_hashes)
        + ". Keep prompt files stable while compare is running."
    )


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


def build_model_summaries(
    run_rows: list[dict[str, Any]],
    adaptive_run_rows: list[dict[str, Any]] | None = None,
    adaptive_pair_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    order: list[str] = []
    for row in run_rows:
        profile = str(row["model_profile"])
        if profile not in grouped:
            order.append(profile)
        grouped[profile].append(row)

    # Collect adaptive run costs/tokens per model for grand totals
    adaptive_costs: dict[str, list[float | None]] = defaultdict(list)
    adaptive_tokens: dict[str, list[int | None]] = defaultdict(list)
    for row in (adaptive_run_rows or []):
        profile = str(row.get("model_profile", ""))
        adaptive_costs[profile].append(row.get("estimated_cost"))
        adaptive_tokens[profile].append(row.get("tokens_used"))

    # Compute no-memory avg (initial + control) per model from adaptive pairs
    # This is statistically more robust than initial-only (10 data points vs 5)
    no_mem_avg_by_profile: dict[str, float] = {}
    for pair in (adaptive_pair_rows or []):
        mp = str(pair.get("model_profile", ""))
        initial_s = pair.get("initial_score")
        control_s = pair.get("control_score")
        if initial_s is not None and control_s is not None:
            no_mem_avg_by_profile.setdefault(mp, [])
            no_mem_avg_by_profile[mp].append(float(initial_s))
            no_mem_avg_by_profile[mp].append(float(control_s))
    no_mem_avg_by_profile = {
        mp: round(mean(scores), 4) for mp, scores in no_mem_avg_by_profile.items() if scores
    }

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
        prompt_tokens_total = _optional_sum([
            (item.get("token_breakdown") or {}).get("prompt_tokens") for item in group
        ])
        completion_tokens_total = _optional_sum([
            (item.get("token_breakdown") or {}).get("completion_tokens") for item in group
        ])
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
                "avg_final_score": no_mem_avg_by_profile.get(profile, round(mean(scores), 4)),
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
                "prompt_tokens_total": int(prompt_tokens_total) if prompt_tokens_total is not None else None,
                "completion_tokens_total": int(completion_tokens_total) if completion_tokens_total is not None else None,
                "estimated_cost_total": round(cost_total, 6) if cost_total is not None else None,
                "estimated_cost_adaptive": round(_optional_sum(adaptive_costs.get(profile, [])) or 0, 6) if adaptive_costs.get(profile) else None,
                "estimated_cost_grand_total": round(
                    (cost_total or 0) + (_optional_sum(adaptive_costs.get(profile, [])) or 0), 6
                ) if (cost_total is not None or _optional_sum(adaptive_costs.get(profile, [])) is not None) else None,
                "tokens_used_adaptive": int(_optional_sum(adaptive_tokens.get(profile, [])) or 0) if adaptive_tokens.get(profile) else None,
                "tokens_used_grand_total": int(
                    (tokens_total or 0) + (_optional_sum(adaptive_tokens.get(profile, [])) or 0)
                ) if (tokens_total is not None or _optional_sum(adaptive_tokens.get(profile, [])) is not None) else None,
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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_adaptive_feedback(
    *,
    initial_summary: dict[str, Any],
    adaptive_summary: dict[str, Any],
) -> dict[str, Any]:
    initial_score = _safe_int(initial_summary.get("final_score"))
    adaptive_score = _safe_int(adaptive_summary.get("final_score"))
    initial_turns = _safe_int(initial_summary.get("turns_survived"))
    adaptive_turns = _safe_int(adaptive_summary.get("turns_survived"))
    initial_invalid = _safe_int(initial_summary.get("invalid_actions"))
    adaptive_invalid = _safe_int(adaptive_summary.get("invalid_actions"))
    initial_resources = _safe_int(initial_summary.get("resources_gathered"))
    adaptive_resources = _safe_int(adaptive_summary.get("resources_gathered"))
    return {
        "score": {"initial": initial_score, "adaptive": adaptive_score, "delta": adaptive_score - initial_score},
        "turns_survived": {
            "initial": initial_turns,
            "adaptive": adaptive_turns,
            "delta": adaptive_turns - initial_turns,
        },
        "invalid_actions": {
            "initial": initial_invalid,
            "adaptive": adaptive_invalid,
            "delta": adaptive_invalid - initial_invalid,
        },
        "resources_gathered": {
            "initial": initial_resources,
            "adaptive": adaptive_resources,
            "delta": adaptive_resources - initial_resources,
        },
        "end_reason": {
            "initial": str(initial_summary.get("end_reason", "")),
            "adaptive": str(adaptive_summary.get("end_reason", "")),
        },
        "death_cause": {
            "initial": str(initial_summary.get("death_cause", "") or ""),
            "adaptive": str(adaptive_summary.get("death_cause", "") or ""),
        },
    }


def _build_reflection_trace_context(
    *,
    run_log: dict[str, Any],
    history_window: int = 10,
) -> dict[str, Any]:
    turn_logs = list(run_log.get("turn_logs", []))
    recent_turns: list[dict[str, Any]] = []
    for turn_log in turn_logs[-history_window:]:
        action_result = turn_log.get("action_result", {}) if isinstance(turn_log, dict) else {}
        validation = turn_log.get("validation_result", {}) if isinstance(turn_log, dict) else {}
        score_delta = turn_log.get("score_delta", {}) if isinstance(turn_log, dict) else {}
        survival_delta = (
            turn_log.get("world_result_delta", {}).get("survival_delta", {})
            if isinstance(turn_log, dict)
            else {}
        )
        recent_turns.append(
            {
                "turn": int(turn_log.get("turn", 0)),
                "action": str(action_result.get("applied") or action_result.get("requested") or ""),
                "valid": bool(validation.get("is_valid", False)),
                "result": str(action_result.get("message") or ""),
                "score_delta_total": int(score_delta.get("total", 0)),
                "energy_after": int(survival_delta.get("energy_after", 0)),
                "hunger_after": int(survival_delta.get("hunger_after", 0)),
                "thirst_after": int(survival_delta.get("thirst_after", 0)),
            }
        )

    latest_observation = {}
    if turn_logs:
        latest_observation = dict(turn_logs[-1].get("observation", {}))
    known_map = latest_observation.get("known_map", {})
    recent_discoveries = latest_observation.get("recent_discoveries", [])

    return {
        "history_window": int(history_window),
        "recent_turns": recent_turns,
        "recent_discoveries": list(recent_discoveries or []),
        "known_map": dict(known_map) if isinstance(known_map, dict) else {},
    }


def _adaptive_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    score_total = sum(_safe_int(row.get("final_score")) for row in rows)
    turns_survived_total = sum(_safe_int(row.get("turns_survived")) for row in rows)
    invalid_total = sum(_safe_int(row.get("invalid_actions")) for row in rows)
    resources_total = sum(_safe_int(row.get("resources_gathered")) for row in rows)
    runs = len(rows)
    return {
        "runs": runs,
        "score_total": score_total,
        "score_avg": (score_total / runs) if runs > 0 else None,
        "turns_survived_total": turns_survived_total,
        "turns_survived_avg": (turns_survived_total / runs) if runs > 0 else None,
        "invalid_actions_total": invalid_total,
        "invalid_actions_avg": (invalid_total / runs) if runs > 0 else None,
        "resources_gathered_total": resources_total,
        "resources_gathered_avg": (resources_total / runs) if runs > 0 else None,
    }


def _build_adaptive_model_rows(
    baseline_rows: list[dict[str, Any]],
    adaptive_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    baseline_by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    adaptive_by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in baseline_rows:
        baseline_by_model[str(row.get("model_profile", ""))].append(row)
    for row in adaptive_rows:
        adaptive_by_model[str(row.get("model_profile", ""))].append(row)

    model_names = sorted(set(baseline_by_model.keys()) | set(adaptive_by_model.keys()))
    result: list[dict[str, Any]] = []
    for model in model_names:
        baseline_totals = _adaptive_totals(baseline_by_model.get(model, []))
        adaptive_totals = _adaptive_totals(adaptive_by_model.get(model, []))
        result.append(
            {
                "model_profile": model,
                "runs": adaptive_totals["runs"],
                "baseline_score_total": baseline_totals["score_total"],
                "adaptive_score_total": adaptive_totals["score_total"],
                "delta_score_total": adaptive_totals["score_total"] - baseline_totals["score_total"],
                "baseline_score_avg": baseline_totals["score_avg"],
                "adaptive_score_avg": adaptive_totals["score_avg"],
                "delta_score_avg": (
                    None
                    if baseline_totals["score_avg"] is None or adaptive_totals["score_avg"] is None
                    else adaptive_totals["score_avg"] - baseline_totals["score_avg"]
                ),
                "baseline_turns_survived_avg": baseline_totals["turns_survived_avg"],
                "adaptive_turns_survived_avg": adaptive_totals["turns_survived_avg"],
                "delta_turns_survived_avg": (
                    None
                    if baseline_totals["turns_survived_avg"] is None or adaptive_totals["turns_survived_avg"] is None
                    else adaptive_totals["turns_survived_avg"] - baseline_totals["turns_survived_avg"]
                ),
                "baseline_invalid_actions_avg": baseline_totals["invalid_actions_avg"],
                "adaptive_invalid_actions_avg": adaptive_totals["invalid_actions_avg"],
                "delta_invalid_actions_avg": (
                    None
                    if baseline_totals["invalid_actions_avg"] is None or adaptive_totals["invalid_actions_avg"] is None
                    else adaptive_totals["invalid_actions_avg"] - baseline_totals["invalid_actions_avg"]
                ),
            }
        )
    return result


def _policy_ngrams(text: str, n: int = 3) -> list[tuple[str, ...]]:
    words = _re.findall(r"\w+", text.lower())
    return [tuple(words[i : i + n]) for i in range(len(words) - n + 1)]


def _jaccard(a: list[tuple[str, ...]], b: list[tuple[str, ...]]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 1.0


def _compute_adaptive_kpis(
    adaptive_pair_rows: list[dict[str, Any]],
    memory_dir: Path | None,
) -> list[dict[str, Any]]:
    """Compute Adaptive Learning KPIs (PDI, MPR, SMER, CCS) per model."""
    if not adaptive_pair_rows:
        return []

    models_seeds: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in adaptive_pair_rows:
        models_seeds[str(row.get("model_profile", ""))].append(row)

    # Load seed reflection policies if memory_dir available
    policies: dict[tuple[str, int], str] = {}
    confidences: dict[tuple[str, int], str] = {}
    session_lessons_before: dict[tuple[str, int], list[str]] = {}
    if memory_dir:
        seed_ref_dir = memory_dir / "seed_reflections"
        if seed_ref_dir.is_dir():
            for ref_file in seed_ref_dir.glob("*.json"):
                try:
                    data = json.loads(ref_file.read_text(encoding="utf-8"))
                    model = str(data.get("model_profile", ""))
                    seed = int(data.get("seed", 0))
                    key = (model, seed)
                    fl = data.get("filtered_lessons", [])
                    policies[key] = fl[0] if fl else ""
                    raw = data.get("raw_output", "")
                    conf_match = _re.search(r'"confidence"\s*:\s*"(\w+)"', raw)
                    confidences[key] = conf_match.group(1).lower() if conf_match else "medium"
                    session_lessons_before[key] = [
                        str(l).strip()[:80] for l in data.get("session_lessons_before", [])
                    ]
                except (json.JSONDecodeError, ValueError, KeyError):
                    continue

    conf_map = {"low": 1, "medium": 2, "high": 3}
    results: list[dict[str, Any]] = []

    for model, rows in sorted(models_seeds.items()):
        seeds = sorted(rows, key=lambda r: int(r.get("seed", 0)))
        n_seeds = len(seeds)

        # --- PDI: Policy Diversity Index ---
        model_policies = []
        for r in seeds:
            key = (model, int(r.get("seed", 0)))
            model_policies.append(policies.get(key, ""))
        pdi = 0.0
        if len(model_policies) >= 2:
            sims = []
            for i, j in combinations(range(len(model_policies)), 2):
                ng_i = _policy_ngrams(model_policies[i])
                ng_j = _policy_ngrams(model_policies[j])
                sims.append(_jaccard(ng_i, ng_j))
            pdi = 1.0 - (sum(sims) / len(sims)) if sims else 0.0

        # --- MPR: Memory Promotion Rate ---
        promoted = sum(1 for r in seeds if str(r.get("memory_promoted", "")).lower() == "true")
        mpr = promoted / n_seeds if n_seeds else 0.0

        # --- SMER: Session Memory Evolution Rate ---
        changes = 0
        transitions = 0
        prev_set: set[str] | None = None
        for r in seeds:
            key = (model, int(r.get("seed", 0)))
            curr_set = set(session_lessons_before.get(key, []))
            if prev_set is not None:
                transitions += 1
                changes += len(curr_set - prev_set) + len(prev_set - curr_set)
            prev_set = curr_set
        smer = changes / transitions if transitions else 0.0

        # --- CCS: Confidence Calibration Score ---
        confs_vals = []
        effects_vals = []
        for r in seeds:
            key = (model, int(r.get("seed", 0)))
            conf = confidences.get(key)
            me = r.get("memory_effect")
            if conf and me is not None:
                confs_vals.append(conf_map.get(conf, 2))
                effects_vals.append(float(me))
        ccs = 0.0
        if len(confs_vals) >= 3:
            mean_c = sum(confs_vals) / len(confs_vals)
            mean_e = sum(effects_vals) / len(effects_vals)
            num = sum((confs_vals[i] - mean_c) * (effects_vals[i] - mean_e) for i in range(len(confs_vals)))
            den_c = math.sqrt(sum((c - mean_c) ** 2 for c in confs_vals))
            den_e = math.sqrt(sum((e - mean_e) ** 2 for e in effects_vals))
            if den_c > 0 and den_e > 0:
                ccs = num / (den_c * den_e)

        # --- Memory effect stats ---
        mem_effects = [float(r.get("memory_effect", 0)) for r in seeds]
        avg_mem = sum(mem_effects) / len(mem_effects) if mem_effects else 0.0
        mem_per_seed = [float(r.get("memory_effect", 0)) for r in seeds]

        results.append({
            "model_profile": model,
            "seeds": n_seeds,
            "pdi": round(pdi, 3),
            "mpr": round(mpr, 2),
            "smer": round(smer, 1),
            "ccs": round(ccs, 3),
            "avg_memory_effect": round(avg_mem, 1),
            "memory_effects": mem_per_seed,
        })

    # Normalize and compute composite score
    if results:
        pdi_vals = [r["pdi"] for r in results]
        smer_vals = [r["smer"] for r in results]
        pdi_min, pdi_max = min(pdi_vals), max(pdi_vals)
        smer_min, smer_max = min(smer_vals), max(smer_vals)
        mpr_min, mpr_max = min(r["mpr"] for r in results), max(r["mpr"] for r in results)

        for r in results:
            pdi_n = (r["pdi"] - pdi_min) / (pdi_max - pdi_min) if pdi_max > pdi_min else 0.5
            mpr_n = (r["mpr"] - mpr_min) / (mpr_max - mpr_min) if mpr_max > mpr_min else 0.5
            smer_n = (r["smer"] - smer_min) / (smer_max - smer_min) if smer_max > smer_min else 0.5
            ccs_n = (r["ccs"] + 1) / 2  # map [-1, 1] to [0, 1]
            # Empirical weights: PDI 60%, MPR 30%, SMER 10%, CCS 0%
            r["composite_score"] = round(0.6 * pdi_n + 0.3 * mpr_n + 0.1 * smer_n, 3)

        results.sort(key=lambda r: r["composite_score"], reverse=True)

    return results


def _build_adaptive_section(
    *,
    baseline_rows: list[dict[str, Any]],
    adaptive_rows: list[dict[str, Any]],
    adaptive_pair_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_totals = _adaptive_totals(baseline_rows)
    adaptive_totals = _adaptive_totals(adaptive_rows)
    model_rows = _build_adaptive_model_rows(baseline_rows, adaptive_rows)

    return {
        "enabled": True,
        "aggregate_adaptive_score": adaptive_totals["score_total"],
        "baseline_totals": baseline_totals,
        "adaptive_totals": adaptive_totals,
        "delta_totals": {
            "score_total": adaptive_totals["score_total"] - baseline_totals["score_total"],
            "turns_survived_total": adaptive_totals["turns_survived_total"] - baseline_totals["turns_survived_total"],
            "invalid_actions_total": adaptive_totals["invalid_actions_total"] - baseline_totals["invalid_actions_total"],
            "resources_gathered_total": adaptive_totals["resources_gathered_total"] - baseline_totals["resources_gathered_total"],
        },
        "models": model_rows,
        "pairs": adaptive_pair_rows,
    }


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
        "adaptive_runs_csv": dirs["results"] / f"compare_runs_adaptive_{compare_id}.csv",
        "adaptive_models_csv": dirs["results"] / f"compare_adaptive_models_{compare_id}.csv",
        "adaptive_pairs_csv": dirs["results"] / f"compare_adaptive_pairs_{compare_id}.csv",
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
    adaptive_section: dict[str, Any] | None = None,
    adaptive_run_rows: list[dict[str, Any]] | None = None,
    adaptive_pair_rows: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    model_summaries = build_model_summaries(run_rows, adaptive_run_rows=adaptive_run_rows, adaptive_pair_rows=adaptive_pair_rows) if run_rows else []
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
            "adaptive_mode": adaptive_section is not None,
        },
        "models": model_summaries,
        "pairwise": pairwise_rows,
        "runs": run_payloads,
    }
    if adaptive_section is not None:
        compare_payload["adaptive"] = adaptive_section
        compare_payload["meta"]["adaptive_aggregate_score"] = adaptive_section.get("aggregate_adaptive_score")
    return compare_payload, model_summaries, pairwise_rows, resolved_profiles


def _apply_pricing_fallback(rows: list[dict[str, Any]]) -> None:
    """Apply retroactive pricing to rows missing estimated_cost."""
    if not rows:
        return
    pricing_cfg: dict[str, Any] | None = None
    pricing_path = Path("configs/pricing.yaml")
    if not pricing_path.is_absolute():
        pricing_path = (Path.cwd() / pricing_path).resolve()
    if pricing_path.exists():
        pricing_cfg = load_pricing_config(pricing_path)
    if not pricing_cfg:
        return
    for row in rows:
        if row.get("estimated_cost") is not None:
            continue
        tokens = row.get("tokens_used")
        if tokens is None:
            continue
        provider_id = str(row.get("provider_id", ""))
        model_name = str(row.get("model", ""))
        pricing = resolve_model_pricing(
            pricing_cfg=pricing_cfg,
            provider_id=provider_id,
            model=model_name,
        )
        cost = estimate_cost_from_total_tokens(pricing=pricing, total_tokens=tokens)
        if cost is not None:
            row["estimated_cost"] = round(cost, 6)
            row["estimated_cost_source"] = "pricing_fallback_retroactive"


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
    adaptive_run_rows: list[dict[str, Any]] | None = None,
    adaptive_pair_rows: list[dict[str, Any]] | None = None,
    adaptive_memory_by_model: dict[str, list[str]] | None = None,
    memory_dir: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    adaptive_run_rows = adaptive_run_rows or []
    adaptive_pair_rows = adaptive_pair_rows or []

    # Retroactive pricing fallback for rows missing estimated_cost
    _apply_pricing_fallback(run_rows + adaptive_run_rows)

    adaptive_section = None
    adaptive_model_rows: list[dict[str, Any]] = []
    if adaptive_run_rows or adaptive_pair_rows:
        adaptive_section = _build_adaptive_section(
            baseline_rows=run_rows,
            adaptive_rows=adaptive_run_rows,
            adaptive_pair_rows=adaptive_pair_rows,
        )
        adaptive_model_rows = list(adaptive_section.get("models", []))
        if status == "completed":
            kpi_rows = _compute_adaptive_kpis(adaptive_pair_rows, memory_dir)
            if kpi_rows:
                adaptive_section["learning_kpis"] = kpi_rows

    compare_payload, model_summaries, pairwise_rows, resolved_profiles = _build_compare_payload(
        compare_id=compare_id,
        run_rows=run_rows,
        run_payloads=run_payloads,
        requested_models=requested_models,
        seed_list=seed_list,
        scenario=scenario,
        protocol_version=protocol_version,
        status=status,
        adaptive_section=adaptive_section,
        adaptive_run_rows=adaptive_run_rows,
        adaptive_pair_rows=adaptive_pair_rows,
    )

    _write_csv(paths["runs_csv"], COMPARE_RUN_FIELDS, run_rows)
    _write_csv(paths["models_csv"], MODEL_SUMMARY_FIELDS, model_summaries)
    _write_csv(paths["h2h_csv"], H2H_FIELDS, pairwise_rows)
    if adaptive_run_rows:
        _write_csv(paths["adaptive_runs_csv"], ADAPTIVE_RUN_FIELDS, adaptive_run_rows)
    if adaptive_model_rows:
        _write_csv(paths["adaptive_models_csv"], ADAPTIVE_MODEL_FIELDS, adaptive_model_rows)
    if adaptive_pair_rows:
        _write_csv(paths["adaptive_pairs_csv"], ADAPTIVE_PAIR_FIELDS, adaptive_pair_rows)
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
        "adaptive_run_rows": adaptive_run_rows,
        "adaptive_pair_rows": adaptive_pair_rows,
        "adaptive_memory_by_model": adaptive_memory_by_model or {},
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
    adaptive_run_rows: list[dict[str, Any]] = []
    adaptive_pair_rows: list[dict[str, Any]] = []
    adaptive_memory_by_model: dict[str, list[str]] = {}

    profile_order: dict[str, int] = {}
    seed_order: dict[int, int] = {}
    protocol_version = "AIB-0.2.1"
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
                protocol_version=str(run_log.get("protocol_version", "AIB-0.2.1")),
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
                "attempt_kind": summary.get("attempt_kind"),
                "memory_injected": summary.get("memory_injected"),
                "summary": summary,
                "replay": replay_payload,
            }
        )

        protocol_version = str(run_log.get("protocol_version", protocol_version))
        scenario = str(run_log.get("scenario", summary.get("scenario", scenario)))

    ordered_models = sorted(profile_order.keys(), key=lambda p: profile_order[p])
    ordered_seeds = sorted(seed_order.keys(), key=lambda s: seed_order[s])
    return run_rows, run_payloads, ordered_models, ordered_seeds, scenario, protocol_version


def _split_attempt_rows(
    run_rows: list[dict[str, Any]],
    run_payloads: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    baseline_rows: list[dict[str, Any]] = []
    baseline_payloads: list[dict[str, Any]] = []
    control_rows: list[dict[str, Any]] = []
    adaptive_rows: list[dict[str, Any]] = []

    for idx, row in enumerate(run_rows):
        attempt_kind = str(row.get("attempt_kind") or "initial").strip()
        payload = run_payloads[idx] if idx < len(run_payloads) else None
        if attempt_kind == "adaptive_rerun":
            adaptive_rows.append(row)
            continue
        if attempt_kind == "control_rerun":
            control_rows.append(row)
            continue
        baseline_rows.append(row)
        if isinstance(payload, dict):
            baseline_payloads.append(payload)

    adaptive_pairs: list[dict[str, Any]] = []
    initial_by_pair: dict[tuple[str, int], dict[str, Any]] = {}
    control_by_pair: dict[tuple[str, int], dict[str, Any]] = {}
    adaptive_by_pair: dict[tuple[str, int], dict[str, Any]] = {}
    for row in baseline_rows:
        key = (str(row.get("model_profile", "")), _safe_int(row.get("seed")))
        initial_by_pair[key] = row
    for row in control_rows:
        key = (str(row.get("model_profile", "")), _safe_int(row.get("seed")))
        control_by_pair[key] = row
    for row in adaptive_rows:
        key = (str(row.get("model_profile", "")), _safe_int(row.get("seed")))
        adaptive_by_pair[key] = row

    for key, row in adaptive_by_pair.items():
        initial = initial_by_pair.get(key)
        if initial is None:
            continue
        control = control_by_pair.get(key)

        initial_score = _safe_int(initial.get("final_score"))
        adaptive_score = _safe_int(row.get("final_score"))
        control_score = _safe_int(control.get("final_score")) if control is not None else None
        control_delta = (control_score - initial_score) if control_score is not None else None
        adaptive_delta = adaptive_score - initial_score
        if control_score is not None:
            memory_effect = round(adaptive_score - (initial_score + control_score) / 2, 1)
        else:
            memory_effect = round(adaptive_score - initial_score, 1)

        control_turns = _safe_int(control.get("turns_survived")) if control is not None else None
        adaptive_turns = _safe_int(row.get("turns_survived"))
        initial_turns = _safe_int(initial.get("turns_survived"))
        control_invalid = _safe_int(control.get("invalid_actions")) if control is not None else None
        adaptive_invalid = _safe_int(row.get("invalid_actions"))
        initial_invalid = _safe_int(initial.get("invalid_actions"))
        control_resources = _safe_int(control.get("resources_gathered")) if control is not None else None
        adaptive_resources = _safe_int(row.get("resources_gathered"))
        initial_resources = _safe_int(initial.get("resources_gathered"))

        adaptive_pairs.append(
            {
                "compare_id": str(row.get("compare_id", "")),
                "model_profile": key[0],
                "seed": key[1],
                "adaptive_pair_key": str(row.get("adaptive_pair_key") or f"{key[0]}__seed{key[1]}"),
                "initial_score": initial_score,
                "control_score": control_score,
                "adaptive_score": adaptive_score,
                "control_delta": control_delta,
                "adaptive_delta": adaptive_delta,
                "memory_effect": memory_effect,
                "initial_turns_survived": initial_turns,
                "control_turns_survived": control_turns,
                "adaptive_turns_survived": adaptive_turns,
                "control_delta_turns": (control_turns - initial_turns) if control_turns is not None else None,
                "adaptive_delta_turns": adaptive_turns - initial_turns,
                "initial_invalid_actions": initial_invalid,
                "control_invalid_actions": control_invalid,
                "adaptive_invalid_actions": adaptive_invalid,
                "initial_resources_gathered": initial_resources,
                "control_resources_gathered": control_resources,
                "adaptive_resources_gathered": adaptive_resources,
                "lessons_before_count": None,
                "lessons_added_count": None,
                "lessons_after_count": None,
                "memory_promoted": None,
                "reflection_parse_error": None,
                "reflection_path": None,
                "memory_snapshot_path": None,
            }
        )

    return baseline_rows, baseline_payloads, (control_rows + adaptive_rows), adaptive_pairs


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


def _attempt_index(attempt_kind: str) -> int:
    return 2 if str(attempt_kind) == "adaptive_rerun" else 1


def _attempt_label(attempt_kind: str) -> str:
    if attempt_kind == "control_rerun":
        return "rerun (control)"
    if attempt_kind == "adaptive_rerun":
        return "rerun (adaptive mem.)"
    return "initial"


def _display_job_position(
    *,
    job_index: int,
    job_total: int,
    adaptive_enabled: bool,
    attempt_kind: str,
) -> tuple[int, int]:
    if not adaptive_enabled:
        return job_index, job_total
    attempt_idx = _attempt_index(attempt_kind)
    return ((job_index - 1) * 2) + attempt_idx, job_total * 2


def _job_log_path(logs_dir: Path, job: JobSpec) -> Path:
    return logs_dir / f"run_seed{job.seed}_{_safe_slug(job.model_profile)}.json"


def _job_log_path_adaptive(logs_dir: Path, job: JobSpec, attempt_kind: str) -> Path:
    return logs_dir / f"run_seed{job.seed}_{_safe_slug(job.model_profile)}_{attempt_kind}.json"


def _load_run_log_from_summary(summary_row: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(summary_row.get("log_path", "")).strip()
    if not raw_path:
        raise RuntimeError("missing log_path for completed initial attempt")
    log_path = Path(raw_path).resolve()
    if not log_path.exists():
        raise RuntimeError(f"initial log not found for adaptive resume: {log_path}")
    with log_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or "run_summary" not in payload:
        raise RuntimeError(f"invalid run log payload for adaptive resume: {log_path}")
    return payload


def _extract_prompt_rules(
    *,
    parsed_lesson_items: list[Any] | None,
    parsed_lessons: list[Any] | None,
) -> list[str]:
    rules_from_items = [
        normalize_lesson_text(str(item.get("rule", "")))
        for item in (parsed_lesson_items or [])
        if isinstance(item, dict) and normalize_lesson_text(str(item.get("rule", "")))
    ]
    if rules_from_items:
        return merge_lessons([], rules_from_items)

    # Backward-compatibility fallback for legacy payloads/tests that provide only parsed_lessons.
    fallback_rules = [
        normalize_lesson_text(str(raw))
        for raw in (parsed_lessons or [])
        if normalize_lesson_text(str(raw))
    ]
    return merge_lessons([], fallback_rules)


def _should_promote_cross_seed_memory(
    *,
    initial_score: int,
    adaptive_score: int,
    min_delta: int = ADAPTIVE_MEMORY_PROMOTION_MIN_DELTA,
) -> bool:
    return int(adaptive_score) - int(initial_score) >= int(min_delta)


def _execute_job(
    *,
    job: JobSpec,
    scenario: str,
    max_turns: int | None,
    benchmark_config_path: str,
    scenarios_config_path: str,
    providers_config_path: str,
    prompts_dir: str,
    history_window: int | None,
    output_logs_dir: Path,
    progress_callback: Any = None,
    fix_thinking: bool = False,
    moral_mode: bool = False,
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
        history_window=history_window,
        output_path=_job_log_path(output_logs_dir, job),
        progress_callback=progress_callback,
        fix_thinking=fix_thinking,
        moral_mode=moral_mode,
    )


def _execute_adaptive_initial(
    *,
    job: JobSpec,
    scenario: str,
    max_turns: int | None,
    benchmark_config_path: str,
    scenarios_config_path: str,
    providers_config_path: str,
    prompts_dir: str,
    history_window: int | None,
    output_logs_dir: Path,
    memory_dir: Path,
    session_lessons: list[str],
    progress_callback: Any = None,
    fix_thinking: bool = False,
    moral_mode: bool = False,
) -> dict[str, Any]:
    pair_key = f"{job.model_profile}__seed{job.seed}"
    initial_log = run_match_once(
        seed=job.seed,
        model_name=job.model_profile,
        scenario_name=(None if scenario in {"", "-"} else scenario),
        max_turns=max_turns,
        benchmark_config_path=benchmark_config_path,
        scenarios_config_path=scenarios_config_path,
        providers_config_path=providers_config_path,
        prompts_dir=prompts_dir,
        history_window=history_window,
        output_path=_job_log_path_adaptive(output_logs_dir, job, "initial"),
        progress_callback=progress_callback,
        fix_thinking=fix_thinking,
        include_memory=True,
        # Baseline attempt in adaptive mode must stay clean:
        # no carry-over session memory injected into `initial`.
        session_lessons=[],
        current_seed_lessons=[],
        attempt_kind="initial",
        adaptive_pair_key=pair_key,
        moral_mode=moral_mode,
    )
    return {"initial_run_log": initial_log}


def _execute_adaptive_followup(
    *,
    job: JobSpec,
    scenario: str,
    max_turns: int | None,
    benchmark_config_path: str,
    scenarios_config_path: str,
    providers_config_path: str,
    prompts_dir: str,
    history_window: int | None,
    output_logs_dir: Path,
    memory_dir: Path,
    session_lessons: list[str],
    initial_log: dict[str, Any],
    progress_callback: Any = None,
    fix_thinking: bool = False,
    moral_mode: bool = False,
) -> dict[str, Any]:
    pair_key = f"{job.model_profile}__seed{job.seed}"
    initial_score_reference = _safe_int(
        dict(initial_log.get("run_summary", {})).get("final_score")
    )

    def _emit_progress_with_extras(event: dict[str, Any]) -> None:
        if progress_callback is None:
            return
        payload = dict(event)
        payload["baseline_score_reference"] = int(initial_score_reference)
        progress_callback(payload)

    def _emit_adaptive_stage(action_label: str) -> None:
        _emit_progress_with_extras(
            {
                "event": "adaptive_stage",
                "attempt_kind": "adaptive_rerun",
                "action": action_label,
            }
        )

    # --- Control rerun: same seed, no memory (measures LLM variance) ---
    # Resume-safe behavior: if control log already exists (interrupted mid-followup),
    # reuse it instead of running the control attempt again.
    control_log_path = _job_log_path_adaptive(output_logs_dir, job, "control")
    control_log: dict[str, Any] | None = None
    if control_log_path.exists():
        try:
            with control_log_path.open("r", encoding="utf-8") as handle:
                recovered = json.load(handle)
            if isinstance(recovered, dict) and isinstance(recovered.get("run_summary"), dict):
                control_log = recovered
                _emit_adaptive_stage("(resuming: control rerun recovered)")
        except Exception:
            control_log = None

    if control_log is None:
        control_log = run_match_once(
            seed=job.seed,
            model_name=job.model_profile,
            scenario_name=(None if scenario in {"", "-"} else scenario),
            max_turns=max_turns,
            benchmark_config_path=benchmark_config_path,
            scenarios_config_path=scenarios_config_path,
            providers_config_path=providers_config_path,
            prompts_dir=prompts_dir,
            history_window=history_window,
            output_path=control_log_path,
            progress_callback=_emit_progress_with_extras,
            fix_thinking=fix_thinking,
            include_memory=True,
            session_lessons=[],
            current_seed_lessons=[],
            attempt_kind="control_rerun",
            adaptive_pair_key=pair_key,
            moral_mode=moral_mode,
        )

    _emit_adaptive_stage("(computing memory: seed reflection)")

    providers_cfg = load_yaml_file(providers_config_path)
    model_binding = create_model_wrapper(model_name=job.model_profile, seed=job.seed, providers_cfg=providers_cfg)
    prompt_loader = PromptLoader(prompts_dir)

    seed_reflection = run_seed_reflection(
        model_wrapper=model_binding.wrapper,
        prompt_loader=prompt_loader,
        run_summary=dict(initial_log.get("run_summary", {})),
        run_analysis=initial_log.get("run_analysis"),
        run_trace_context=_build_reflection_trace_context(run_log=initial_log, history_window=10),
        existing_lessons=lessons_to_prompt_items(session_lessons),
        metadata={
            "mode": "adaptive_seed_reflection",
            "seed": job.seed,
            "model_profile": job.model_profile,
            "adaptive_pair_key": pair_key,
        },
    )
    parsed_seed_lessons = list(seed_reflection.get("parsed_lessons") or [])
    parsed_seed_lesson_items = list(seed_reflection.get("parsed_lesson_items") or [])
    parsed_seed_rules = _extract_prompt_rules(
        parsed_lesson_items=parsed_seed_lesson_items,
        parsed_lessons=parsed_seed_lessons,
    )
    filtered_seed_lessons = filter_lessons(
        parsed_seed_rules,
        context={
            "seed": job.seed,
            "model_profile": job.model_profile,
            "adaptive_pair_key": pair_key,
            "stage": "seed_reflection",
        },
    )
    pair_lessons = merge_lessons([], filtered_seed_lessons)

    seed_reflections_dir = memory_dir / "seed_reflections"
    cross_refinements_dir = memory_dir / "cross_seed_refinements"
    legacy_reflections_dir = memory_dir / "reflections"
    snapshots_dir = memory_dir / "snapshots"
    seed_reflection_path = seed_reflections_dir / f"{_safe_slug(job.model_profile)}__seed{job.seed}.json"
    cross_refinement_path = cross_refinements_dir / f"{_safe_slug(job.model_profile)}__seed{job.seed}.json"
    reflection_manifest_path = legacy_reflections_dir / f"{_safe_slug(job.model_profile)}__seed{job.seed}.json"
    memory_snapshot_path = snapshots_dir / f"{_safe_slug(job.model_profile)}__after_seed{job.seed}.json"

    seed_reflection_payload = {
        "stage": "seed_reflection",
        "model_profile": job.model_profile,
        "seed": job.seed,
        "adaptive_pair_key": pair_key,
        "session_lessons_before": list(session_lessons),
        "parsed_lessons": parsed_seed_lessons,
        "parsed_lesson_items": parsed_seed_lesson_items,
        "filtered_lessons": filtered_seed_lessons,
        "pair_lessons": pair_lessons,
        "parse_error": seed_reflection.get("parse_error"),
        "raw_output": seed_reflection.get("raw_output"),
        "metrics": {
            "tokens_used": seed_reflection.get("tokens_used"),
            "latency_ms": seed_reflection.get("latency_ms"),
            "estimated_cost": seed_reflection.get("estimated_cost"),
        },
    }
    save_json(seed_reflection_path, seed_reflection_payload)

    # Pass discovered tiles from initial run to adaptive rerun
    initial_discovered = initial_log.get("discovered_tiles")
    if not isinstance(initial_discovered, dict):
        initial_discovered = None

    adaptive_log = run_match_once(
        seed=job.seed,
        model_name=job.model_profile,
        scenario_name=(None if scenario in {"", "-"} else scenario),
        max_turns=max_turns,
        benchmark_config_path=benchmark_config_path,
        scenarios_config_path=scenarios_config_path,
        providers_config_path=providers_config_path,
        prompts_dir=prompts_dir,
        history_window=history_window,
        output_path=_job_log_path_adaptive(output_logs_dir, job, "adaptive"),
        progress_callback=_emit_progress_with_extras,
        fix_thinking=fix_thinking,
        include_memory=True,
        session_lessons=session_lessons,
        current_seed_lessons=pair_lessons,
        prior_discovered_tiles=initial_discovered,
        attempt_kind="adaptive_rerun",
        adaptive_pair_key=pair_key,
        moral_mode=moral_mode,
    )

    initial_summary = dict(initial_log.get("run_summary", {}))
    adaptive_summary = dict(adaptive_log.get("run_summary", {}))
    adaptive_feedback = _build_adaptive_feedback(
        initial_summary=initial_summary,
        adaptive_summary=adaptive_summary,
    )
    _emit_adaptive_stage("(computing memory: cross-seed refinement)")
    cross_refinement = run_cross_seed_refinement(
        model_wrapper=model_binding.wrapper,
        prompt_loader=prompt_loader,
        initial_run_summary=initial_summary,
        initial_run_analysis=initial_log.get("run_analysis"),
        initial_run_trace_context=_build_reflection_trace_context(run_log=initial_log, history_window=10),
        rerun_summary=adaptive_summary,
        rerun_analysis=adaptive_log.get("run_analysis"),
        rerun_trace_context=_build_reflection_trace_context(run_log=adaptive_log, history_window=10),
        existing_lessons=lessons_to_prompt_items(session_lessons),
        seed_lessons=lessons_to_prompt_items(pair_lessons),
        adaptive_feedback=adaptive_feedback,
        metadata={
            "mode": "adaptive_cross_seed_refinement",
            "seed": job.seed,
            "model_profile": job.model_profile,
            "adaptive_pair_key": pair_key,
        },
    )
    parsed_cross_lessons = list(cross_refinement.get("parsed_lessons") or [])
    parsed_cross_lesson_items = list(cross_refinement.get("parsed_lesson_items") or [])
    parsed_cross_rules = _extract_prompt_rules(
        parsed_lesson_items=parsed_cross_lesson_items,
        parsed_lessons=parsed_cross_lessons,
    )
    filtered_cross_lessons = filter_lessons(
        parsed_cross_rules,
        context={
            "seed": job.seed,
            "model_profile": job.model_profile,
            "adaptive_pair_key": pair_key,
            "stage": "cross_seed_refinement",
        },
    )
    initial_score = _safe_int(initial_summary.get("final_score"))
    adaptive_score = _safe_int(adaptive_summary.get("final_score"))
    adaptive_delta_score = adaptive_score - initial_score
    promote_cross_seed_memory = _should_promote_cross_seed_memory(
        initial_score=initial_score,
        adaptive_score=adaptive_score,
    )

    # Cross-seed refinement acts as model-driven synthesis for next-session memory.
    # If output is empty/invalid, or adaptive result is below promotion threshold, keep prior session memory.
    merged_session_lessons = (
        merge_lessons([], filtered_cross_lessons)
        if (filtered_cross_lessons and promote_cross_seed_memory)
        else list(session_lessons)
    )

    cross_refinement_payload = {
        "stage": "cross_seed_refinement",
        "model_profile": job.model_profile,
        "seed": job.seed,
        "adaptive_pair_key": pair_key,
        "session_lessons_before": list(session_lessons),
        "pair_lessons": pair_lessons,
        "adaptive_feedback": adaptive_feedback,
        "adaptive_delta_score": adaptive_delta_score,
        "memory_promotion_threshold": ADAPTIVE_MEMORY_PROMOTION_MIN_DELTA,
        "memory_promoted": promote_cross_seed_memory,
        "parsed_lessons": parsed_cross_lessons,
        "parsed_lesson_items": parsed_cross_lesson_items,
        "filtered_lessons": filtered_cross_lessons,
        "session_lessons_after": merged_session_lessons,
        "parse_error": cross_refinement.get("parse_error"),
        "raw_output": cross_refinement.get("raw_output"),
        "metrics": {
            "tokens_used": cross_refinement.get("tokens_used"),
            "latency_ms": cross_refinement.get("latency_ms"),
            "estimated_cost": cross_refinement.get("estimated_cost"),
        },
    }
    save_json(cross_refinement_path, cross_refinement_payload)

    reflection_manifest_payload = {
        "model_profile": job.model_profile,
        "seed": job.seed,
        "adaptive_pair_key": pair_key,
        "seed_reflection_path": str(seed_reflection_path),
        "cross_seed_refinement_path": str(cross_refinement_path),
        "seed_reflection_parse_error": seed_reflection.get("parse_error"),
        "cross_seed_refinement_parse_error": cross_refinement.get("parse_error"),
        "session_lessons_before_count": len(session_lessons),
        "pair_lessons_count": len(pair_lessons),
        "session_lessons_after_count": len(merged_session_lessons),
    }
    save_json(reflection_manifest_path, reflection_manifest_payload)

    save_json(
        memory_snapshot_path,
        {
            "model_profile": job.model_profile,
            "seed": job.seed,
            "adaptive_pair_key": pair_key,
            "session_lessons": merged_session_lessons,
            "session_lesson_count": len(merged_session_lessons),
            "pair_lessons": pair_lessons,
            "pair_lesson_count": len(pair_lessons),
        },
    )

    seed_parse_error = seed_reflection.get("parse_error")
    cross_parse_error = cross_refinement.get("parse_error")
    combined_parse_error: str | None = None
    if seed_parse_error and cross_parse_error:
        combined_parse_error = f"seed:{seed_parse_error};cross:{cross_parse_error}"
    elif seed_parse_error:
        combined_parse_error = f"seed:{seed_parse_error}"
    elif cross_parse_error:
        combined_parse_error = f"cross:{cross_parse_error}"

    control_summary = dict(control_log.get("run_summary", {}))
    initial_s = _safe_int(initial_summary.get("final_score"))
    control_s = _safe_int(control_summary.get("final_score"))
    adaptive_s = _safe_int(adaptive_summary.get("final_score"))

    pair_row = {
        "compare_id": "",
        "model_profile": job.model_profile,
        "seed": job.seed,
        "adaptive_pair_key": pair_key,
        "initial_score": initial_s,
        "control_score": control_s,
        "adaptive_score": adaptive_s,
        "control_delta": control_s - initial_s,
        "adaptive_delta": adaptive_s - initial_s,
        "memory_effect": round(adaptive_s - (initial_s + control_s) / 2, 1),
        "initial_turns_survived": _safe_int(initial_summary.get("turns_survived")),
        "control_turns_survived": _safe_int(control_summary.get("turns_survived")),
        "adaptive_turns_survived": _safe_int(adaptive_summary.get("turns_survived")),
        "control_delta_turns": _safe_int(control_summary.get("turns_survived")) - _safe_int(initial_summary.get("turns_survived")),
        "adaptive_delta_turns": _safe_int(adaptive_summary.get("turns_survived")) - _safe_int(initial_summary.get("turns_survived")),
        "initial_invalid_actions": _safe_int(initial_summary.get("invalid_actions")),
        "control_invalid_actions": _safe_int(control_summary.get("invalid_actions")),
        "adaptive_invalid_actions": _safe_int(adaptive_summary.get("invalid_actions")),
        "initial_resources_gathered": _safe_int(initial_summary.get("resources_gathered")),
        "control_resources_gathered": _safe_int(control_summary.get("resources_gathered")),
        "adaptive_resources_gathered": _safe_int(adaptive_summary.get("resources_gathered")),
        "lessons_before_count": len(session_lessons),
        "lessons_added_count": max(0, len(merged_session_lessons) - len(session_lessons)),
        "lessons_after_count": len(merged_session_lessons),
        "reflection_parse_error": combined_parse_error,
        "memory_promoted": promote_cross_seed_memory,
        "reflection_path": str(reflection_manifest_path),
        "memory_snapshot_path": str(memory_snapshot_path),
    }

    return {
        "initial_run_log": initial_log,
        "control_run_log": control_log,
        "adaptive_run_log": adaptive_log,
        "updated_lessons": merged_session_lessons,
        "pair_row": pair_row,
        "reflection_path": str(reflection_manifest_path),
        "memory_snapshot_path": str(memory_snapshot_path),
    }


def _execute_adaptive_pair(
    *,
    job: JobSpec,
    scenario: str,
    max_turns: int | None,
    benchmark_config_path: str,
    scenarios_config_path: str,
    providers_config_path: str,
    prompts_dir: str,
    history_window: int | None,
    output_logs_dir: Path,
    memory_dir: Path,
    session_lessons: list[str],
    progress_callback: Any = None,
    fix_thinking: bool = False,
    moral_mode: bool = False,
) -> dict[str, Any]:
    initial_result = _execute_adaptive_initial(
        job=job,
        scenario=scenario,
        max_turns=max_turns,
        benchmark_config_path=benchmark_config_path,
        scenarios_config_path=scenarios_config_path,
        providers_config_path=providers_config_path,
        prompts_dir=prompts_dir,
        history_window=history_window,
        output_logs_dir=output_logs_dir,
        memory_dir=memory_dir,
        session_lessons=session_lessons,
        progress_callback=progress_callback,
        fix_thinking=fix_thinking,
        moral_mode=moral_mode,
    )
    followup_result = _execute_adaptive_followup(
        job=job,
        scenario=scenario,
        max_turns=max_turns,
        benchmark_config_path=benchmark_config_path,
        scenarios_config_path=scenarios_config_path,
        providers_config_path=providers_config_path,
        prompts_dir=prompts_dir,
        history_window=history_window,
        output_logs_dir=output_logs_dir,
        memory_dir=memory_dir,
        session_lessons=session_lessons,
        initial_log=dict(initial_result["initial_run_log"]),
        progress_callback=progress_callback,
        fix_thinking=fix_thinking,
        moral_mode=moral_mode,
    )
    return {
        "initial_run_log": dict(initial_result["initial_run_log"]),
        **followup_result,
    }


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
    baseline_score_reference: int | None,
    invalid: int,
    alive: bool,
    energy: int | None,
    energy_max: int | None,
    eta_text: str,
    attempt_label: str | None,
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
        attempt_text = (
            f"attempt: {colorize(attempt_label, '1;94', color_enabled)}"
            if attempt_label
            else None
        )

        protocol_color = "1;32" if protocol_valid else "1;31"
        effect_color = "0;37"
        if protocol_valid and effect_applied:
            effect_color = "1;32"
        elif protocol_valid and not effect_applied:
            effect_color = "1;93"

        score_value = (
            f"{score:>4}({int(baseline_score_reference)})"
            if baseline_score_reference is not None
            else f"{score:>4}"
        )
        score_text = colorize(score_value, "1;93", color_enabled)
        invalid_color = "1;31" if invalid > 0 else "0;37"
        invalid_text = colorize(f"{invalid:>3}", invalid_color, color_enabled)
        energy_text = None
        if energy is not None and energy_max is not None and energy_max > 0:
            ratio = float(energy) / float(energy_max)
            energy_color = "1;32"
            if ratio <= 0.30:
                energy_color = "1;31"
            elif ratio <= 0.60:
                energy_color = "1;93"
            energy_text = colorize(f"{int(energy)}/{int(energy_max)}", energy_color, color_enabled)
        elif energy is not None:
            energy_text = colorize(str(int(energy)), "1;97", color_enabled)
        else:
            energy_text = colorize("--", "0;37", color_enabled)
        eta_label = colorize("eta:", "0;37", color_enabled)
        eta_value = colorize(eta_text, "1;97", color_enabled)

        parts = [
            f"{pct_text} {job_text}",
            turn_text,
        ]
        if attempt_text:
            parts.append(attempt_text)
        parts.extend(
            [
                f"{model_label} {model_text}",
                f"{seed_label} {seed_text}",
                f"{action_label} {action_text}",
            ]
        )
        if not protocol_valid:
            parts.append(f"protocol: {colorize(protocol_text, protocol_color, color_enabled)}")
            parts.append(f"effect: {colorize(effect_text, effect_color, color_enabled)}")
        elif not effect_applied:
            parts.append(f"effect: {colorize(effect_text, effect_color, color_enabled)}")
        parts.extend(
            [
                f"score: {score_text}",
                *( [f"invalid: {invalid_text}"] if invalid > 0 else [] ),
                f"energy: {energy_text}",
                f"{eta_label} {eta_value}",
            ]
        )
        return " | ".join(parts)

    parts_plain = [
        f"[{pct:5.1f}%] job {job_index}/{job_total}",
        f"turn {turn}/{max_turns}",
    ]
    if attempt_label:
        parts_plain.append(f"attempt: {attempt_label}")
    parts_plain.extend(
        [
            f"model: {model_profile}",
            f"seed: {seed}",
            f"action: {action[:22]:<22}",
        ]
    )
    if not protocol_valid:
        parts_plain.append(f"protocol: {protocol_text:<3}")
        parts_plain.append(f"effect: {effect_text:<7}")
    elif not effect_applied:
        parts_plain.append(f"effect: {effect_text:<7}")
    score_plain = (
        f"{score:>4}({int(baseline_score_reference)})"
        if baseline_score_reference is not None
        else f"{score:>4}"
    )
    parts_plain.extend(
        [
            f"score: {score_plain}",
            *( [f"invalid: {invalid:>3}"] if invalid > 0 else [] ),
            (
                f"energy: {int(energy)}/{int(energy_max)}"
                if (energy is not None and energy_max is not None and energy_max > 0)
                else (
                    f"energy: {int(energy)}"
                    if energy is not None
                    else "energy: --"
                )
            ),
            f"eta: {eta_text}",
        ]
    )
    return " | ".join(parts_plain)


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
    parser = _CompareArgumentParser(
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
        nargs="+",
        default=["dummy_v0_1"],
        help=(
            "Comma-separated model profiles from providers config, preserving order. "
            "Supports both '--models a,b' and '--models a, b'."
        ),
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
        "--history-window",
        type=int,
        default=None,
        help=(
            "Override observation history window (recent turns injected in observation). "
            "Use 0 to disable; if omitted, uses benchmark config default."
        ),
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
    parser.add_argument(
        "--fix-thinking",
        action="store_true",
        help="Optional parser recovery: extract the last valid allowed action from verbose model output.",
    )
    parser.add_argument(
        "--moral",
        action="store_true",
        help="Enable optional moral framing in the system prompt (default: off).",
    )
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
    parser.add_argument(
        "--adaptive-memory",
        action="store_true",
        help="Enable adaptive mode: initial run -> reflection -> same-seed rerun with session memory.",
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
    if args.history_window is not None and args.history_window < 0:
        parser.error("--history-window must be >= 0")

    color_enabled = use_color(disable_color=args.no_color)
    status_line = StatusLine(enabled=True)

    print(colorize(f"TinyWorld Compare CLI v{__version__}", "1;34", color_enabled))

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
    adaptive_run_rows: list[dict[str, Any]] = []
    adaptive_pair_rows: list[dict[str, Any]] = []
    adaptive_memory_by_model: dict[str, list[str]] = {}
    scenario = str(args.scenario or benchmark_cfg.get("default_scenario", "-"))
    protocol_version = str(benchmark_cfg.get("protocol_version", "AIB-0.2.1"))
    model_profiles: list[str] = []
    seed_list: list[int] = []
    requested_models: list[str] = []
    identity_models_text = "-"
    identity_providers_text = "-"
    identity_routing_text = "-"
    eta_elapsed_baseline_seconds = 0.0
    effective_benchmark_config_path = str(Path(args.benchmark_config).resolve())
    effective_scenarios_config_path = str(Path(args.scenarios_config).resolve())
    effective_providers_config_path = str(Path(args.providers_config).resolve())
    effective_prompts_dir = str(Path(args.prompts_dir).resolve())
    effective_scenario_arg: str | None = args.scenario
    effective_max_turns = args.max_turns
    effective_history_window = args.history_window
    effective_fix_thinking = bool(args.fix_thinking)
    effective_moral_mode = bool(args.moral)
    adaptive_enabled = bool(args.adaptive_memory)
    effective_seed_workers_per_model = int(args.seed_workers_per_model)
    resume_time_human: str | None = None

    resume_context: dict[str, Any] = {
        "benchmark_config": effective_benchmark_config_path,
        "scenarios_config": effective_scenarios_config_path,
        "providers_config": effective_providers_config_path,
        "prompts_dir": effective_prompts_dir,
        "scenario_arg": effective_scenario_arg,
        "max_turns": effective_max_turns,
        "history_window": effective_history_window,
        "fix_thinking": effective_fix_thinking,
        "moral_mode": effective_moral_mode,
        "adaptive_memory": adaptive_enabled,
        "runs_root": str(runs_root),
        "run_id": compare_id,
        "model_workers": args.model_workers,
        "seed_workers_per_model": effective_seed_workers_per_model,
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

        baseline_rows, _baseline_payloads, adaptive_rows_from_logs, adaptive_pairs_from_logs = _split_attempt_rows(
            run_rows,
            run_payloads,
        )
        run_rows = baseline_rows
        adaptive_run_rows = adaptive_rows_from_logs
        adaptive_pair_rows = adaptive_pairs_from_logs

        _assert_adaptive_prompt_hash_consistency(
            adaptive_enabled=adaptive_enabled,
            run_rows=run_rows,
            adaptive_run_rows=adaptive_run_rows,
        )

        for idx, row in enumerate(run_rows, start=1):
            row["job_index"] = idx
            row["job_total"] = len(run_rows)

        requested_models = list(model_profiles)
        resume_context["from_logs_glob"] = args.from_logs_glob
        resume_context["run_id"] = compare_id
        identity_models_text, identity_providers_text, identity_routing_text = _resolve_models_and_providers_for_identity(
            model_profiles=model_profiles,
            providers_config_path=effective_providers_config_path,
        )

        _print_start_identity(
            color_enabled=color_enabled,
            protocol_version=protocol_version,
            scenario=scenario,
            run_id=compare_id,
            resume_time_human=None,
            run_root=run_dirs["run_root"],
            model_profiles=model_profiles,
            models_text=identity_models_text,
            providers_text=identity_providers_text,
            routing_text=identity_routing_text,
            model_workers=args.model_workers,
            seed_workers_per_model=effective_seed_workers_per_model,
            moral_mode=effective_moral_mode,
        )

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
            adaptive_run_rows=adaptive_run_rows,
            adaptive_pair_rows=adaptive_pair_rows,
            adaptive_memory_by_model=adaptive_memory_by_model,
            memory_dir=run_dirs.get("memory"),
        )
    else:
        completed_initial_keys: set[tuple[str, int]] = set()
        completed_keys: set[tuple[str, int]] = set()
        completed_jobs = 0
        completed_units = 0
        existing_by_key: dict[tuple[str, int], dict[str, Any]] = {}
        payload_by_key: dict[tuple[str, int, str], dict[str, Any]] = {}
        control_by_key: dict[tuple[str, int], dict[str, Any]] = {}
        adaptive_by_key: dict[tuple[str, int], dict[str, Any]] = {}
        adaptive_pair_by_key: dict[tuple[str, int], dict[str, Any]] = {}

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
                for key in {
                    "runs_csv",
                    "models_csv",
                    "h2h_csv",
                    "adaptive_runs_csv",
                    "adaptive_models_csv",
                    "adaptive_pairs_csv",
                    "compare_json",
                    "checkpoint_json",
                }:
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
            adaptive_run_rows = list(checkpoint.get("adaptive_run_rows", []))
            adaptive_pair_rows = list(checkpoint.get("adaptive_pair_rows", []))
            adaptive_memory_by_model = {
                str(key): [str(item) for item in value]
                for key, value in dict(checkpoint.get("adaptive_memory_by_model", {})).items()
                if isinstance(value, list)
            }

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
            resume_history_window = resume_context.get("history_window", effective_history_window)
            effective_history_window = (
                None
                if resume_history_window in {None, ""}
                else int(resume_history_window)
            )
            effective_fix_thinking = bool(resume_context.get("fix_thinking", effective_fix_thinking))
            effective_moral_mode = bool(resume_context.get("moral_mode", effective_moral_mode))
            adaptive_enabled = bool(resume_context.get("adaptive_memory", adaptive_enabled))
            effective_seed_workers_per_model = int(resume_context.get("seed_workers_per_model", effective_seed_workers_per_model))
            resume_context["history_window"] = effective_history_window
            resume_context["fix_thinking"] = effective_fix_thinking
            resume_context["moral_mode"] = effective_moral_mode
            resume_context["adaptive_memory"] = adaptive_enabled
            resume_context["seed_workers_per_model"] = effective_seed_workers_per_model
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
            resume_time_human = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
        else:
            model_profiles = parse_models(args.models)
            seed_list = resolve_seed_list(args.seeds, args.num_runs, args.seed_start)
            requested_models = list(model_profiles)

        if not model_profiles:
            raise SystemExit("No model profiles available for compare execution.")
        if not seed_list:
            raise SystemExit("No seeds available for compare execution.")

        identity_models_text, identity_providers_text, identity_routing_text = _resolve_models_and_providers_for_identity(
            model_profiles=model_profiles,
            providers_config_path=effective_providers_config_path,
        )

        _print_start_identity(
            color_enabled=color_enabled,
            protocol_version=protocol_version,
            scenario=scenario,
            run_id=compare_id,
            resume_time_human=resume_time_human,
            run_root=run_dirs["run_root"],
            model_profiles=model_profiles,
            models_text=identity_models_text,
            providers_text=identity_providers_text,
            routing_text=identity_routing_text,
            model_workers=args.model_workers,
            seed_workers_per_model=effective_seed_workers_per_model,
            moral_mode=effective_moral_mode,
        )

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

        for payload in run_payloads:
            summary = payload.get("summary", {})
            key = (
                str(summary.get("model_profile", payload.get("model_profile", ""))),
                int(summary.get("seed", payload.get("seed", 0))),
                str(summary.get("attempt_kind", payload.get("attempt_kind", "initial"))),
            )
            if (key[0], key[1]) in jobs_by_key:
                payload_by_key[key] = payload

        for row in adaptive_run_rows:
            key = (str(row.get("model_profile", "")), int(row.get("seed", 0)))
            if key in jobs_by_key:
                attempt_kind = str(row.get("attempt_kind", "")).strip()
                if attempt_kind == "control_rerun":
                    control_by_key[key] = row
                elif attempt_kind == "adaptive_rerun":
                    adaptive_by_key[key] = row
                else:
                    # Backward-compatibility fallback for legacy artifacts.
                    adaptive_by_key[key] = row
        for row in adaptive_pair_rows:
            key = (str(row.get("model_profile", "")), int(row.get("seed", 0)))
            if key in jobs_by_key:
                adaptive_pair_by_key[key] = row

        def _hydrate_missing_control_rows_from_logs() -> None:
            for key, job in jobs_by_key.items():
                if key not in existing_by_key:
                    continue
                if key in control_by_key:
                    continue
                log_path = _job_log_path_adaptive(run_dirs["logs"], job, "control")
                if not log_path.exists():
                    continue
                try:
                    with log_path.open("r", encoding="utf-8") as handle:
                        payload = json.load(handle)
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                summary = payload.get("run_summary")
                if not isinstance(summary, dict):
                    continue
                control_summary = dict(summary)
                control_summary.setdefault("protocol_version", payload.get("protocol_version", protocol_version))
                control_by_key[key] = {
                    "compare_id": compare_id,
                    "run_id": f"{_safe_slug(job.model_profile)}__seed{job.seed}__control",
                    "job_index": job.job_index,
                    "job_total": job.job_total,
                    "model_order": job.model_order,
                    "seed_order": job.seed_order,
                    **control_summary,
                }

        _hydrate_missing_control_rows_from_logs()

        def _rebuild_ordered_collections() -> None:
            nonlocal run_rows, run_payloads, adaptive_run_rows, adaptive_pair_rows
            ordered_keys = [(job.model_profile, job.seed) for job in jobs if (job.model_profile, job.seed) in existing_by_key]
            run_rows = [existing_by_key[key] for key in ordered_keys]
            run_payloads = []
            for model_profile, seed in ordered_keys:
                for attempt_kind in ("initial", "control_rerun", "adaptive_rerun"):
                    payload = payload_by_key.get((model_profile, seed, attempt_kind))
                    if isinstance(payload, dict):
                        run_payloads.append(payload)
            control_rows = [control_by_key[key] for key in ordered_keys if key in control_by_key]
            adaptive_only_rows = [adaptive_by_key[key] for key in ordered_keys if key in adaptive_by_key]
            adaptive_run_rows = control_rows + adaptive_only_rows
            adaptive_pair_rows = [adaptive_pair_by_key[key] for key in ordered_keys if key in adaptive_pair_by_key]

        def _refresh_completion_counters() -> None:
            nonlocal completed_initial_keys, completed_keys, completed_jobs, completed_units
            completed_initial_keys = set(existing_by_key.keys())
            if adaptive_enabled:
                completed_keys = {
                    key for key in completed_initial_keys
                    if key in adaptive_by_key and key in adaptive_pair_by_key
                }
                completed_units = len(completed_initial_keys) + len(completed_keys)
            else:
                completed_keys = set(completed_initial_keys)
                completed_units = len(completed_keys)
            completed_jobs = len(completed_keys)

        _rebuild_ordered_collections()
        _refresh_completion_counters()
        _assert_adaptive_prompt_hash_consistency(
            adaptive_enabled=adaptive_enabled,
            run_rows=run_rows,
            adaptive_run_rows=adaptive_run_rows,
        )

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
                adaptive_run_rows=adaptive_run_rows,
                adaptive_pair_rows=adaptive_pair_rows,
                adaptive_memory_by_model=adaptive_memory_by_model,
                memory_dir=run_dirs.get("memory"),
            )

        adaptive_live_line_count = 0
        live_attempt_scores_by_key: dict[tuple[str, int, str], int] = {}
        live_attempt_scores_lock = threading.Lock()
        active_attempts_by_key: dict[tuple[str, int], str] = {}
        active_attempts_lock = threading.Lock()

        def _refresh_adaptive_live_panel() -> None:
            nonlocal adaptive_live_line_count
            if not adaptive_enabled:
                return
            with live_attempt_scores_lock:
                live_attempt_scores_snapshot = dict(live_attempt_scores_by_key)
            with active_attempts_lock:
                active_attempts_snapshot = dict(active_attempts_by_key)
            adaptive_live_line_count = _print_adaptive_live_snapshot(
                status_line=status_line,
                color_enabled=color_enabled,
                model_profiles=model_profiles,
                seed_list=seed_list,
                initial_rows_by_key=existing_by_key,
                control_rows_by_key=control_by_key,
                adaptive_rows_by_key=adaptive_by_key,
                adaptive_pairs_by_key=adaptive_pair_by_key,
                live_attempt_scores_by_key=live_attempt_scores_snapshot,
                active_attempts_by_key=active_attempts_snapshot,
                previous_line_count=adaptive_live_line_count,
            )

        if adaptive_enabled:
            save_json(
                run_dirs["memory"] / "session_memory.json",
                {
                    "compare_id": compare_id,
                    "adaptive_memory": adaptive_memory_by_model,
                },
            )

        _persist_running_state(status="running")
        _refresh_adaptive_live_panel()

        observed_initial_seconds_by_model: dict[str, list[float]] = defaultdict(list)
        observed_followup_seconds_by_model: dict[str, list[float]] = defaultdict(list)
        prior_initial_seconds_by_model: dict[str, list[float]] = defaultdict(list)
        prior_followup_seconds_by_model: dict[str, list[float]] = defaultdict(list)

        def _row_latency_seconds(row: dict[str, Any]) -> float | None:
            raw = row.get("latency_ms")
            if raw is None:
                return None
            try:
                value = float(raw) / 1000.0
            except (TypeError, ValueError):
                return None
            if value <= 0:
                return None
            return value

        for key, initial_row in existing_by_key.items():
            model_profile = str(initial_row.get("model_profile", key[0]))
            initial_seconds = _row_latency_seconds(initial_row)
            if initial_seconds is not None:
                prior_initial_seconds_by_model[model_profile].append(initial_seconds)

            control_row = control_by_key.get(key)
            adaptive_row = adaptive_by_key.get(key)
            control_seconds = _row_latency_seconds(control_row) if control_row is not None else None
            adaptive_seconds = _row_latency_seconds(adaptive_row) if adaptive_row is not None else None
            if control_seconds is not None and adaptive_seconds is not None:
                prior_followup_seconds_by_model[model_profile].append(control_seconds + adaptive_seconds)

        def _mean(values: list[float]) -> float | None:
            if not values:
                return None
            return float(sum(values) / len(values))

        def _estimate_stage_seconds(model_profile: str) -> tuple[float, float]:
            init_est = (
                _mean(observed_initial_seconds_by_model.get(model_profile, []))
                or _mean(prior_initial_seconds_by_model.get(model_profile, []))
            )
            follow_est = (
                _mean(observed_followup_seconds_by_model.get(model_profile, []))
                or _mean(prior_followup_seconds_by_model.get(model_profile, []))
            )

            global_init = (
                _mean([value for values in observed_initial_seconds_by_model.values() for value in values])
                or _mean([value for values in prior_initial_seconds_by_model.values() for value in values])
                or 60.0
            )
            global_follow = (
                _mean([value for values in observed_followup_seconds_by_model.values() for value in values])
                or _mean([value for values in prior_followup_seconds_by_model.values() for value in values])
                or max(8.0, global_init * 2.2)
            )

            init_value = max(1.0, float(init_est if init_est is not None else global_init))
            follow_value = max(init_value * 1.5, float(follow_est if follow_est is not None else global_follow))
            return init_value, follow_value

        def _record_initial_result(
            job: JobSpec,
            run_log: dict[str, Any],
            *,
            persist_state: bool = True,
        ) -> dict[str, Any]:
            nonlocal scenario, protocol_version

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

            payload_by_key[(job.model_profile, job.seed, "initial")] = {
                "run_id": run_row["run_id"],
                "model_profile": summary["model_profile"],
                "provider_id": summary["provider_id"],
                "model": summary["model"],
                "seed": summary["seed"],
                "attempt_kind": summary.get("attempt_kind", "initial"),
                "memory_injected": summary.get("memory_injected"),
                "summary": summary,
                "replay": build_viewer_payload(run_log=run_log, source_log_path=Path(str(summary["log_path"]))),
            }

            _refresh_completion_counters()
            _assert_adaptive_prompt_hash_consistency(
                adaptive_enabled=adaptive_enabled,
                run_rows=run_rows,
                adaptive_run_rows=adaptive_run_rows,
            )
            if persist_state:
                _persist_running_state(status="running")
            _refresh_adaptive_live_panel()
            return summary

        def _record_adaptive_result(
            job: JobSpec,
            *,
            control_run_log: dict[str, Any] | None = None,
            adaptive_run_log: dict[str, Any],
            adaptive_pair_row: dict[str, Any] | None,
            updated_lessons: list[str] | None,
            persist_state: bool = True,
        ) -> None:
            key = (job.model_profile, job.seed)

            if control_run_log is not None:
                control_summary = dict(control_run_log.get("run_summary", {}))
                control_summary.setdefault("protocol_version", control_run_log.get("protocol_version", protocol_version))
                control_row = {
                    "compare_id": compare_id,
                    "run_id": f"{_safe_slug(job.model_profile)}__seed{job.seed}__control",
                    "job_index": job.job_index,
                    "job_total": job.job_total,
                    "model_order": job.model_order,
                    "seed_order": job.seed_order,
                    **control_summary,
                }
                control_by_key[key] = control_row
                payload_by_key[(job.model_profile, job.seed, "control_rerun")] = {
                    "run_id": control_row["run_id"],
                    "model_profile": control_summary.get("model_profile"),
                    "provider_id": control_summary.get("provider_id"),
                    "model": control_summary.get("model"),
                    "seed": control_summary.get("seed"),
                    "attempt_kind": control_summary.get("attempt_kind", "control_rerun"),
                    "memory_injected": control_summary.get("memory_injected"),
                    "summary": control_summary,
                    "replay": build_viewer_payload(
                        run_log=control_run_log,
                        source_log_path=Path(str(control_summary["log_path"])),
                    ),
                }

            adaptive_summary = dict(adaptive_run_log.get("run_summary", {}))
            adaptive_summary.setdefault("protocol_version", adaptive_run_log.get("protocol_version", protocol_version))
            adaptive_row = {
                "compare_id": compare_id,
                "run_id": f"{_safe_slug(job.model_profile)}__seed{job.seed}__adaptive",
                "job_index": job.job_index,
                "job_total": job.job_total,
                "model_order": job.model_order,
                "seed_order": job.seed_order,
                **adaptive_summary,
            }
            adaptive_by_key[key] = adaptive_row
            payload_by_key[(job.model_profile, job.seed, "adaptive_rerun")] = {
                "run_id": adaptive_row["run_id"],
                "model_profile": adaptive_summary.get("model_profile"),
                "provider_id": adaptive_summary.get("provider_id"),
                "model": adaptive_summary.get("model"),
                "seed": adaptive_summary.get("seed"),
                "attempt_kind": adaptive_summary.get("attempt_kind", "adaptive_rerun"),
                "memory_injected": adaptive_summary.get("memory_injected"),
                "summary": adaptive_summary,
                "replay": build_viewer_payload(
                    run_log=adaptive_run_log,
                    source_log_path=Path(str(adaptive_summary["log_path"])),
                ),
            }

            if adaptive_pair_row is not None:
                pair_row = dict(adaptive_pair_row)
                pair_row["compare_id"] = compare_id
                adaptive_pair_by_key[key] = pair_row

            if updated_lessons is not None:
                adaptive_memory_by_model[job.model_profile] = list(updated_lessons)
                save_json(
                    run_dirs["memory"] / "session_memory.json",
                    {
                        "compare_id": compare_id,
                        "adaptive_memory": adaptive_memory_by_model,
                    },
                )

            _refresh_completion_counters()
            _assert_adaptive_prompt_hash_consistency(
                adaptive_enabled=adaptive_enabled,
                run_rows=run_rows,
                adaptive_run_rows=adaptive_run_rows,
            )
            if persist_state:
                _persist_running_state(status="running")
            _refresh_adaptive_live_panel()

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
            print(colorize(f"Partial compare JSON: {_short_path(paths['compare_json'])}", "1;96", color_enabled))
            print(colorize(f"Resume: {_resume_command(paths['checkpoint_json'])}", "1;93", color_enabled))
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
        total_progress_units = total_jobs * (2 if adaptive_enabled else 1)
        parallel_enabled = not (args.model_workers == 1 and effective_seed_workers_per_model == 1)

        if not parallel_enabled:
            for job in jobs:
                key = (job.model_profile, job.seed)
                if key in completed_keys:
                    continue

                def _build_progress_callback(*, completed_units_before: int) -> Any:
                    run_progress = {
                        "max_turns": int(
                            effective_max_turns if effective_max_turns is not None else benchmark_cfg.get("max_turns", 50)
                        ),
                        "attempt_kind": "initial",
                        "baseline_score_reference": None,
                        "energy": None,
                        "energy_max": None,
                    }

                    def on_progress(event: dict[str, Any]) -> None:
                        event_type = str(event.get("event", ""))
                        if event_type == "run_started":
                            run_progress["max_turns"] = int(event.get("max_turns", run_progress["max_turns"]))
                            run_progress["attempt_kind"] = str(event.get("attempt_kind", run_progress["attempt_kind"]))
                            with active_attempts_lock:
                                active_attempts_by_key[(job.model_profile, int(job.seed))] = str(run_progress["attempt_kind"])
                            run_progress["energy"] = None
                            run_progress["energy_max"] = None
                            if "baseline_score_reference" in event:
                                run_progress["baseline_score_reference"] = _safe_int(event.get("baseline_score_reference"))
                            attempt_kind = str(run_progress["attempt_kind"])
                            display_job_index, display_job_total = _display_job_position(
                                job_index=job.job_index,
                                job_total=job.job_total,
                                adaptive_enabled=adaptive_enabled,
                                attempt_kind=attempt_kind,
                            )
                            pct = (completed_units_before / max(1, total_progress_units)) * 100.0
                            status_line.write(
                                _render_turn_progress_line(
                                    pct=pct,
                                    job_index=display_job_index,
                                    job_total=display_job_total,
                                    turn=0,
                                    max_turns=run_progress["max_turns"],
                                    model_profile=job.model_profile,
                                    seed=job.seed,
                                    action="(initializing)",
                                    protocol_valid=True,
                                    effect_applied=False,
                                    score=0,
                                    baseline_score_reference=run_progress.get("baseline_score_reference"),
                                    invalid=0,
                                    alive=True,
                                    energy=run_progress.get("energy"),
                                    energy_max=run_progress.get("energy_max"),
                                    eta_text=_compute_eta_text(
                                        completed_jobs=completed_units_before,
                                        total_jobs=total_progress_units,
                                        started_at=compare_started_at,
                                        baseline_elapsed_seconds=eta_elapsed_baseline_seconds,
                                    ),
                                    attempt_label=(_attempt_label(attempt_kind) if adaptive_enabled else None),
                                    color_enabled=color_enabled,
                                )
                            )
                            return
                        if event_type == "run_completed":
                            summary = event.get("summary")
                            if isinstance(summary, dict):
                                attempt_kind = str(summary.get("attempt_kind", run_progress.get("attempt_kind", "initial")))
                                final_score = _safe_int(summary.get("final_score"))
                                seed_value = _safe_int(summary.get("seed"))
                                model_profile_value = str(summary.get("model_profile", job.model_profile))
                                if final_score is not None and seed_value is not None:
                                    with live_attempt_scores_lock:
                                        live_attempt_scores_by_key[
                                            (model_profile_value, int(seed_value), attempt_kind)
                                        ] = int(final_score)
                            with active_attempts_lock:
                                active_attempts_by_key.pop((job.model_profile, int(job.seed)), None)
                            return

                        if event_type != "turn_completed":
                            return

                        turn = int(event.get("turn", 0))
                        max_turns = int(event.get("max_turns", run_progress["max_turns"]))
                        run_progress["max_turns"] = max_turns
                        if "baseline_score_reference" in event:
                            run_progress["baseline_score_reference"] = _safe_int(event.get("baseline_score_reference"))
                        if "energy" in event:
                            run_progress["energy"] = _safe_int(event.get("energy"))
                        if "energy_max" in event:
                            run_progress["energy_max"] = _safe_int(event.get("energy_max"))
                        attempt_kind = str(run_progress.get("attempt_kind", "initial"))
                        display_job_index, display_job_total = _display_job_position(
                            job_index=job.job_index,
                            job_total=job.job_total,
                            adaptive_enabled=adaptive_enabled,
                            attempt_kind=attempt_kind,
                        )
                        run_fraction = (turn / max_turns) if max_turns > 0 else 0.0
                        overall_fraction = (completed_units_before + run_fraction) / max(1, total_progress_units)
                        pct = overall_fraction * 100.0
                        eta_text = "--"
                        if overall_fraction > 0:
                            elapsed = eta_elapsed_baseline_seconds + max(0.0, time.monotonic() - compare_started_at)
                            remaining = max(0.0, (elapsed / overall_fraction) - elapsed)
                            eta_text = format_eta(remaining)

                        status_line.write(
                            _render_turn_progress_line(
                                pct=pct,
                                job_index=display_job_index,
                                job_total=display_job_total,
                                turn=turn,
                                max_turns=max_turns,
                                model_profile=job.model_profile,
                                seed=job.seed,
                                action=str(event.get("action") or "-"),
                                protocol_valid=bool(event.get("protocol_valid", False)),
                                effect_applied=bool(event.get("action_effect_applied", False)),
                                score=int(event.get("cumulative_score", 0)),
                                baseline_score_reference=run_progress.get("baseline_score_reference"),
                                invalid=int(event.get("invalid_actions", 0)),
                                alive=bool(event.get("alive", True)),
                                energy=run_progress.get("energy"),
                                energy_max=run_progress.get("energy_max"),
                                eta_text=eta_text,
                                attempt_label=(_attempt_label(attempt_kind) if adaptive_enabled else None),
                                color_enabled=color_enabled,
                            )
                        )

                    return on_progress

                try:
                    if adaptive_enabled:
                        if key in completed_initial_keys:
                            run_log = _load_run_log_from_summary(existing_by_key[key])
                        else:
                            initial_result = _execute_adaptive_initial(
                                job=job,
                                scenario=scenario,
                                max_turns=effective_max_turns,
                                benchmark_config_path=effective_benchmark_config_path,
                                scenarios_config_path=effective_scenarios_config_path,
                                providers_config_path=effective_providers_config_path,
                                prompts_dir=effective_prompts_dir,
                                history_window=effective_history_window,
                                output_logs_dir=run_dirs["logs"],
                                memory_dir=run_dirs["memory"],
                                session_lessons=[],
                                progress_callback=_build_progress_callback(completed_units_before=completed_units),
                                fix_thinking=effective_fix_thinking,
                                moral_mode=effective_moral_mode,
                            )
                            run_log = dict(initial_result["initial_run_log"])
                            _record_initial_result(job, run_log)

                        session_lessons = list(adaptive_memory_by_model.get(job.model_profile, []))
                        adaptive_result = _execute_adaptive_followup(
                            job=job,
                            scenario=scenario,
                            max_turns=effective_max_turns,
                            benchmark_config_path=effective_benchmark_config_path,
                            scenarios_config_path=effective_scenarios_config_path,
                            providers_config_path=effective_providers_config_path,
                            prompts_dir=effective_prompts_dir,
                            history_window=effective_history_window,
                            output_logs_dir=run_dirs["logs"],
                            memory_dir=run_dirs["memory"],
                            session_lessons=session_lessons,
                            initial_log=run_log,
                            progress_callback=_build_progress_callback(completed_units_before=completed_units),
                            fix_thinking=effective_fix_thinking,
                            moral_mode=effective_moral_mode,
                        )
                        _record_adaptive_result(
                            job,
                            control_run_log=adaptive_result.get("control_run_log"),
                            adaptive_run_log=dict(adaptive_result.get("adaptive_run_log", {})),
                            adaptive_pair_row=adaptive_result.get("pair_row"),
                            updated_lessons=adaptive_result.get("updated_lessons"),
                        )
                        summary = dict(run_log["run_summary"])
                    else:
                        run_log = _execute_job(
                            job=job,
                            scenario=scenario,
                            max_turns=effective_max_turns,
                            benchmark_config_path=effective_benchmark_config_path,
                            scenarios_config_path=effective_scenarios_config_path,
                            providers_config_path=effective_providers_config_path,
                            prompts_dir=effective_prompts_dir,
                            history_window=effective_history_window,
                            output_logs_dir=run_dirs["logs"],
                            progress_callback=_build_progress_callback(completed_units_before=completed_units),
                            fix_thinking=effective_fix_thinking,
                            moral_mode=effective_moral_mode,
                        )
                        summary = _record_initial_result(job, run_log)
                except KeyboardInterrupt:
                    _persist_running_state(status="interrupted")
                    status_line.finish(colorize("[interrupted] Compare canceled by user", "1;93", color_enabled))
                    print(colorize(f"Compare canceled (Ctrl+C) during job {job.job_index}/{job.job_total} (model={job.model_profile}, seed={job.seed}).", "1;93", color_enabled))
                    print(colorize(f"Resume: {_resume_command(paths['checkpoint_json'])}", "1;93", color_enabled))
                    raise SystemExit(130)
                except Exception as exc:
                    _fail_and_exit(exc, job)

                eta_text = _compute_eta_text(
                    completed_jobs=completed_units,
                    total_jobs=total_progress_units,
                    started_at=compare_started_at,
                    baseline_elapsed_seconds=eta_elapsed_baseline_seconds,
                )
                pct_after = (completed_units / max(1, total_progress_units)) * 100.0
                status_line.write(
                    _render_job_done_line(
                        pct=pct_after,
                        job_index=completed_units,
                        job_total=total_progress_units,
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
                profile: [job for job in jobs if job.model_profile == profile]
                for profile in model_profiles
            }
            pending_model_order = [
                profile
                for profile in model_profiles
                if any((job.model_profile, job.seed) not in completed_keys for job in pending_jobs_by_model.get(profile, []))
            ]
            if pending_model_order:
                status_line.write(
                    colorize(
                        f"Parallel mode: model_workers={args.model_workers}, seed_workers_per_model={effective_seed_workers_per_model}",
                        "0;37",
                        color_enabled,
                    )
                )

            active_models: list[str] = []
            model_cursor = 0
            next_seed_index: dict[str, int] = {profile: 0 for profile in pending_model_order}
            running_initial_per_model: dict[str, int] = {profile: 0 for profile in pending_model_order}
            running_tasks_per_model: dict[str, int] = {profile: 0 for profile in pending_model_order}
            adaptive_next_index: dict[str, int] = {profile: 0 for profile in pending_model_order}
            adaptive_running_per_model: dict[str, bool] = {profile: False for profile in pending_model_order}
            progress_lock = threading.Lock()
            live_progress: dict[tuple[str, int, str], dict[str, Any]] = {}

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
                    attempt_kind = str(snapshot.get("attempt_kind", "initial"))
                    if max_turns_local > 0:
                        if adaptive_enabled and attempt_kind == "adaptive_rerun" and turn_local <= 0:
                            # Adaptive followup has a deterministic pre-run reflection stage
                            # with no turn events; assign a small fixed progress credit
                            # to avoid massively inflated ETA during that stage.
                            partial += 0.15
                        else:
                            run_fraction = max(0.0, min(1.0, float(turn_local) / float(max_turns_local)))
                            partial += run_fraction
                if total_progress_units <= 0:
                    return 0.0
                return max(0.0, min(1.0, (completed_units + partial) / total_progress_units))

            def _render_parallel_heartbeat_line() -> str | None:
                with progress_lock:
                    if not live_progress:
                        return None
                    selected_key = max(
                        live_progress.keys(),
                        key=lambda key: (
                            float(live_progress[key].get("updated_at", 0.0)),
                            -jobs_by_key[(key[0], key[1])].job_index,
                        ),
                    )
                    selected = dict(live_progress[selected_key])

                selected_job = jobs_by_key[(selected_key[0], selected_key[1])]
                selected_attempt_kind = str(selected.get("attempt_kind", "initial"))
                display_job_index, display_job_total = _display_job_position(
                    job_index=selected_job.job_index,
                    job_total=selected_job.job_total,
                    adaptive_enabled=adaptive_enabled,
                    attempt_kind=selected_attempt_kind,
                )
                fraction = _current_overall_fraction()
                pct = fraction * 100.0
                eta_text = _compute_parallel_eta_text()

                return _render_turn_progress_line(
                    pct=pct,
                    job_index=display_job_index,
                    job_total=display_job_total,
                    turn=int(selected.get("turn", 0)),
                    max_turns=int(selected.get("max_turns", 1)),
                    model_profile=selected_job.model_profile,
                    seed=selected_job.seed,
                    action=str(selected.get("action") or "(initializing)"),
                    protocol_valid=bool(selected.get("protocol_valid", True)),
                    effect_applied=bool(selected.get("effect_applied", False)),
                    score=int(selected.get("score", 0)),
                    baseline_score_reference=(
                        _safe_int(selected.get("baseline_score_reference"))
                        if (
                            selected_attempt_kind == "adaptive_rerun"
                            and selected.get("baseline_score_reference") is not None
                        )
                        else None
                    ),
                    invalid=int(selected.get("invalid", 0)),
                    alive=bool(selected.get("alive", True)),
                    energy=_safe_int(selected.get("energy")),
                    energy_max=_safe_int(selected.get("energy_max")),
                    eta_text=eta_text,
                    attempt_label=(_attempt_label(selected_attempt_kind) if adaptive_enabled else None),
                    color_enabled=color_enabled,
                )

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, args.model_workers * effective_seed_workers_per_model)
            ) as executor:
                future_to_spec: dict[concurrent.futures.Future[dict[str, Any]], AdaptiveFutureSpec] = {}
                future_started_at: dict[concurrent.futures.Future[dict[str, Any]], float] = {}

                def _model_has_pending_work(model_profile: str) -> bool:
                    pending_jobs = pending_jobs_by_model[model_profile]
                    return any((job.model_profile, job.seed) not in completed_keys for job in pending_jobs)

                def _advance_adaptive_cursor(model_profile: str) -> None:
                    pending_jobs = pending_jobs_by_model[model_profile]
                    while adaptive_next_index[model_profile] < len(pending_jobs):
                        job = pending_jobs[adaptive_next_index[model_profile]]
                        key = (job.model_profile, job.seed)
                        if key in completed_keys:
                            adaptive_next_index[model_profile] += 1
                            continue
                        break

                def _estimate_remaining_from_snapshot(
                    *,
                    snapshot: dict[str, Any],
                    estimated_total_seconds: float,
                    now_ts: float,
                ) -> float:
                    started_at = float(snapshot.get("started_at", now_ts))
                    elapsed = max(0.0, now_ts - started_at)
                    turn_value = int(snapshot.get("turn", 0))
                    max_turns_value = int(snapshot.get("max_turns", 0))
                    attempt_kind = str(snapshot.get("attempt_kind", "initial"))
                    action_text = str(snapshot.get("action", "")).lower()

                    progress = 0.0
                    if max_turns_value > 0 and turn_value > 0:
                        run_progress = max(0.0, min(1.0, float(turn_value) / float(max_turns_value)))
                        if attempt_kind == "control_rerun":
                            progress = min(0.49, 0.49 * run_progress)
                        elif attempt_kind == "adaptive_rerun":
                            progress = min(0.97, 0.52 + 0.43 * run_progress)
                        else:
                            progress = run_progress
                    elif attempt_kind == "control_rerun":
                        progress = 0.05
                    elif attempt_kind == "adaptive_rerun":
                        if "cross-seed refinement" in action_text:
                            progress = 0.97
                        elif "seed reflection" in action_text:
                            progress = 0.50
                        elif "computing memory" in action_text:
                            progress = 0.60
                        else:
                            progress = 0.52

                    progress = max(0.0, min(0.98, progress))
                    if progress > 0:
                        inferred_total = elapsed / max(progress, 0.01)
                        estimated_total_seconds = max(float(estimated_total_seconds), inferred_total)

                    remaining = float(estimated_total_seconds) - elapsed
                    return max(1.0, remaining)

                def _estimate_model_remaining_seconds(model_profile: str, now_ts: float) -> float:
                    pending_jobs = pending_jobs_by_model.get(model_profile, [])
                    if not pending_jobs:
                        return 0.0
                    if not any((job.model_profile, job.seed) not in completed_keys for job in pending_jobs):
                        return 0.0

                    init_est_seconds, follow_est_seconds = _estimate_stage_seconds(model_profile)

                    with progress_lock:
                        snapshots = dict(live_progress)

                    initial_completion_seconds: dict[tuple[str, int], float] = {}
                    running_initial_remaining: list[float] = []
                    running_initial_keys: set[tuple[str, int]] = set()

                    for job in pending_jobs:
                        key = (job.model_profile, job.seed)
                        if key in completed_initial_keys:
                            initial_completion_seconds[key] = 0.0
                            continue
                        initial_snapshot = snapshots.get((job.model_profile, job.seed, "initial"))
                        if isinstance(initial_snapshot, dict):
                            remaining = _estimate_remaining_from_snapshot(
                                snapshot=initial_snapshot,
                                estimated_total_seconds=init_est_seconds,
                                now_ts=now_ts,
                            )
                            initial_completion_seconds[key] = remaining
                            running_initial_remaining.append(remaining)
                            running_initial_keys.add(key)

                    worker_slots = max(1, int(effective_seed_workers_per_model))
                    initial_worker_heap: list[float] = []
                    for remaining in running_initial_remaining:
                        heapq.heappush(initial_worker_heap, remaining)
                    while len(initial_worker_heap) < worker_slots:
                        heapq.heappush(initial_worker_heap, 0.0)

                    for job in pending_jobs:
                        key = (job.model_profile, job.seed)
                        if key in initial_completion_seconds:
                            continue
                        worker_free_at = heapq.heappop(initial_worker_heap)
                        complete_at = worker_free_at + init_est_seconds
                        initial_completion_seconds[key] = complete_at
                        heapq.heappush(initial_worker_heap, complete_at)

                    if not adaptive_enabled:
                        return max(initial_completion_seconds.values(), default=0.0)

                    running_followup_key: tuple[str, int] | None = None
                    running_followup_remaining = 0.0
                    for job in pending_jobs:
                        follow_snapshot = snapshots.get((job.model_profile, job.seed, "adaptive_rerun"))
                        if not isinstance(follow_snapshot, dict):
                            continue
                        running_followup_key = (job.model_profile, job.seed)
                        running_followup_remaining = _estimate_remaining_from_snapshot(
                            snapshot=follow_snapshot,
                            estimated_total_seconds=follow_est_seconds,
                            now_ts=now_ts,
                        )
                        break

                    followup_tail_seconds = 0.0
                    for job in pending_jobs:
                        key = (job.model_profile, job.seed)
                        if key in completed_keys:
                            continue
                        initial_ready_at = initial_completion_seconds.get(key, 0.0)
                        if running_followup_key is not None and key == running_followup_key:
                            followup_tail_seconds = max(followup_tail_seconds, running_followup_remaining)
                            continue
                        followup_start_at = max(followup_tail_seconds, initial_ready_at)
                        followup_tail_seconds = followup_start_at + follow_est_seconds

                    return max(
                        max(initial_completion_seconds.values(), default=0.0),
                        followup_tail_seconds,
                    )

                def _estimate_parallel_eta_seconds() -> float:
                    active_pending = [model for model in active_models if _model_has_pending_work(model)]
                    queued_pending = [
                        model
                        for model in pending_model_order
                        if model not in active_pending and _model_has_pending_work(model)
                    ]
                    if not active_pending and not queued_pending:
                        return 0.0

                    now_ts = time.monotonic()
                    model_remaining: dict[str, float] = {}
                    for model in active_pending + queued_pending:
                        model_remaining[model] = max(0.0, _estimate_model_remaining_seconds(model, now_ts))

                    slots = max(1, int(args.model_workers))
                    slot_heap: list[float] = []
                    for model in active_pending[:slots]:
                        heapq.heappush(slot_heap, model_remaining.get(model, 0.0))
                    while len(slot_heap) < slots:
                        heapq.heappush(slot_heap, 0.0)

                    for model in queued_pending:
                        available_at = heapq.heappop(slot_heap)
                        heapq.heappush(slot_heap, available_at + model_remaining.get(model, 0.0))

                    return max(slot_heap) if slot_heap else 0.0

                def _compute_parallel_eta_text() -> str:
                    remaining_seconds = _estimate_parallel_eta_seconds()
                    return format_eta(remaining_seconds)

                def _register_live_slot(*, job: JobSpec, attempt_kind: str) -> tuple[str, int, str]:
                    key = (job.model_profile, job.seed, attempt_kind)
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
                            "energy": None,
                            "energy_max": None,
                            "baseline_score_reference": None,
                            "attempt_kind": attempt_kind,
                            "started_at": time.monotonic(),
                            "updated_at": time.monotonic(),
                        }
                    return key

                def _make_progress_callback(
                    *,
                    live_key: tuple[str, int, str],
                    default_max_turns: int,
                ) -> Any:
                    def on_progress(event: dict[str, Any], *, event_key: tuple[str, int, str] = live_key) -> None:
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
                                "energy": None,
                                "energy_max": None,
                                "attempt_kind": str(event.get("attempt_kind", "initial")),
                            }
                            with active_attempts_lock:
                                active_attempts_by_key[(event_key[0], int(event_key[1]))] = str(update["attempt_kind"])
                            if "baseline_score_reference" in event:
                                update["baseline_score_reference"] = _safe_int(event.get("baseline_score_reference"))
                        elif event_type == "adaptive_stage":
                            update = {
                                "action": str(event.get("action") or "(computing memory)"),
                                "attempt_kind": str(event.get("attempt_kind", "adaptive_rerun")),
                                "protocol_valid": True,
                                "effect_applied": True,
                            }
                            if "baseline_score_reference" in event:
                                update["baseline_score_reference"] = _safe_int(event.get("baseline_score_reference"))
                            with active_attempts_lock:
                                active_attempts_by_key[(event_key[0], int(event_key[1]))] = str(
                                    update["attempt_kind"]
                                )
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
                                "energy": _safe_int(event.get("energy")),
                                "energy_max": _safe_int(event.get("energy_max")),
                            }
                            if "baseline_score_reference" in event:
                                update["baseline_score_reference"] = _safe_int(event.get("baseline_score_reference"))
                        elif event_type == "run_completed":
                            summary = event.get("summary")
                            if isinstance(summary, dict):
                                attempt_kind = str(
                                    summary.get(
                                        "attempt_kind",
                                        live_progress.get(event_key, {}).get("attempt_kind", "initial"),
                                    )
                                )
                                final_score = _safe_int(summary.get("final_score"))
                                seed_value = _safe_int(summary.get("seed"))
                                model_profile_value = str(summary.get("model_profile", event_key[0]))
                                if final_score is not None and seed_value is not None:
                                    with live_attempt_scores_lock:
                                        live_attempt_scores_by_key[
                                            (model_profile_value, int(seed_value), attempt_kind)
                                        ] = int(final_score)
                                elif final_score is not None:
                                    with live_attempt_scores_lock:
                                        live_attempt_scores_by_key[
                                            (event_key[0], int(event_key[1]), attempt_kind)
                                        ] = int(final_score)
                            with active_attempts_lock:
                                active_attempts_by_key.pop((event_key[0], int(event_key[1])), None)
                            return
                        if not update:
                            return
                        update["updated_at"] = time.monotonic()
                        with progress_lock:
                            if event_key in live_progress:
                                live_progress[event_key].update(update)

                    return on_progress

                def submit_initial_for_model(model_profile: str) -> None:
                    pending_jobs = pending_jobs_by_model[model_profile]
                    while (
                        running_initial_per_model[model_profile] < effective_seed_workers_per_model
                        and next_seed_index[model_profile] < len(pending_jobs)
                    ):
                        job = pending_jobs[next_seed_index[model_profile]]
                        next_seed_index[model_profile] += 1
                        key = (job.model_profile, job.seed)
                        if key in completed_initial_keys:
                            continue
                        default_max_turns = int(
                            effective_max_turns if effective_max_turns is not None else benchmark_cfg.get("max_turns", 50)
                        )
                        live_key = _register_live_slot(job=job, attempt_kind="initial")
                        callback = _make_progress_callback(
                            live_key=live_key,
                            default_max_turns=default_max_turns,
                        )
                        if adaptive_enabled:
                            future = executor.submit(
                                _execute_adaptive_initial,
                                job=job,
                                scenario=scenario,
                                max_turns=effective_max_turns,
                                benchmark_config_path=effective_benchmark_config_path,
                                scenarios_config_path=effective_scenarios_config_path,
                                providers_config_path=effective_providers_config_path,
                                prompts_dir=effective_prompts_dir,
                                history_window=effective_history_window,
                                output_logs_dir=run_dirs["logs"],
                                memory_dir=run_dirs["memory"],
                                session_lessons=[],
                                progress_callback=callback,
                                fix_thinking=effective_fix_thinking,
                                moral_mode=effective_moral_mode,
                            )
                        else:
                            future = executor.submit(
                                _execute_job,
                                job=job,
                                scenario=scenario,
                                max_turns=effective_max_turns,
                                benchmark_config_path=effective_benchmark_config_path,
                                scenarios_config_path=effective_scenarios_config_path,
                                providers_config_path=effective_providers_config_path,
                                prompts_dir=effective_prompts_dir,
                                history_window=effective_history_window,
                                output_logs_dir=run_dirs["logs"],
                                progress_callback=callback,
                                fix_thinking=effective_fix_thinking,
                                moral_mode=effective_moral_mode,
                            )
                        future_to_spec[future] = AdaptiveFutureSpec(
                            kind="initial",
                            job=job,
                        )
                        future_started_at[future] = time.monotonic()
                        running_initial_per_model[model_profile] += 1
                        running_tasks_per_model[model_profile] += 1

                def submit_adaptive_for_model(model_profile: str) -> None:
                    if not adaptive_enabled:
                        return
                    if adaptive_running_per_model[model_profile]:
                        return
                    _advance_adaptive_cursor(model_profile)
                    pending_jobs = pending_jobs_by_model[model_profile]
                    if adaptive_next_index[model_profile] >= len(pending_jobs):
                        return
                    job = pending_jobs[adaptive_next_index[model_profile]]
                    key = (job.model_profile, job.seed)
                    if key not in completed_initial_keys or key in completed_keys:
                        return
                    default_max_turns = int(
                        effective_max_turns if effective_max_turns is not None else benchmark_cfg.get("max_turns", 50)
                    )
                    live_key = _register_live_slot(job=job, attempt_kind="adaptive_rerun")
                    session_lessons = list(adaptive_memory_by_model.get(model_profile, []))
                    initial_log = _load_run_log_from_summary(existing_by_key[key])
                    future = executor.submit(
                        _execute_adaptive_followup,
                        job=job,
                        scenario=scenario,
                        max_turns=effective_max_turns,
                        benchmark_config_path=effective_benchmark_config_path,
                        scenarios_config_path=effective_scenarios_config_path,
                                providers_config_path=effective_providers_config_path,
                                prompts_dir=effective_prompts_dir,
                                history_window=effective_history_window,
                                output_logs_dir=run_dirs["logs"],
                        memory_dir=run_dirs["memory"],
                        session_lessons=session_lessons,
                        initial_log=initial_log,
                        progress_callback=_make_progress_callback(
                            live_key=live_key,
                            default_max_turns=default_max_turns,
                        ),
                        fix_thinking=effective_fix_thinking,
                        moral_mode=effective_moral_mode,
                    )
                    future_to_spec[future] = AdaptiveFutureSpec(
                        kind="adaptive_followup",
                        job=job,
                    )
                    future_started_at[future] = time.monotonic()
                    adaptive_running_per_model[model_profile] = True
                    running_tasks_per_model[model_profile] += 1

                activate_models()
                for model in list(active_models):
                    submit_initial_for_model(model)
                    submit_adaptive_for_model(model)

                while future_to_spec:
                    try:
                        done, _ = concurrent.futures.wait(
                            set(future_to_spec.keys()),
                            timeout=0.6,
                            return_when=concurrent.futures.FIRST_COMPLETED,
                        )
                    except KeyboardInterrupt:
                        for future in future_to_spec:
                            future.cancel()
                        _persist_running_state(status="interrupted")
                        status_line.finish(colorize("[interrupted] Compare canceled by user", "1;93", color_enabled))
                        print(colorize("Compare canceled (Ctrl+C).", "1;93", color_enabled))
                        print(colorize(f"Resume: {_resume_command(paths['checkpoint_json'])}", "1;93", color_enabled))
                        sys.stdout.flush()
                        sys.stderr.flush()
                        os._exit(130)

                    if not done:
                        _refresh_adaptive_live_panel()
                        heartbeat_line = _render_parallel_heartbeat_line()
                        if heartbeat_line:
                            status_line.write(heartbeat_line)
                        continue

                    for future in done:
                        spec = future_to_spec.pop(future)
                        started_at = future_started_at.pop(future, None)
                        job = spec.job
                        model_profile = job.model_profile
                        running_tasks_per_model[model_profile] = max(0, running_tasks_per_model[model_profile] - 1)
                        if spec.kind == "initial":
                            running_initial_per_model[model_profile] = max(0, running_initial_per_model[model_profile] - 1)
                        elif spec.kind == "adaptive_followup":
                            adaptive_running_per_model[model_profile] = False
                        with progress_lock:
                            live_progress.pop((job.model_profile, job.seed, "initial"), None)
                            live_progress.pop((job.model_profile, job.seed, "adaptive_rerun"), None)
                        with active_attempts_lock:
                            active_attempts_by_key.pop((job.model_profile, int(job.seed)), None)
                        try:
                            result_payload = future.result()
                        except Exception as exc:
                            for pending_future in future_to_spec:
                                pending_future.cancel()
                            for pending_future in list(future_started_at.keys()):
                                if pending_future in future_to_spec:
                                    future_started_at.pop(pending_future, None)
                            _fail_and_exit(exc, job)
                        finally:
                            if started_at is not None:
                                duration_seconds = max(0.0, time.monotonic() - started_at)
                                if spec.kind == "initial":
                                    observed_initial_seconds_by_model[model_profile].append(duration_seconds)
                                elif spec.kind == "adaptive_followup":
                                    observed_followup_seconds_by_model[model_profile].append(duration_seconds)

                        try:
                            if spec.kind == "initial":
                                if adaptive_enabled:
                                    run_log = dict(result_payload.get("initial_run_log", {}))
                                    summary = _record_initial_result(job, run_log)
                                else:
                                    run_log = dict(result_payload)
                                    summary = _record_initial_result(job, run_log)
                            else:
                                adaptive_result = dict(result_payload)
                                summary = dict(existing_by_key[(job.model_profile, job.seed)])
                                _record_adaptive_result(
                                    job,
                                    control_run_log=adaptive_result.get("control_run_log"),
                                    adaptive_run_log=dict(adaptive_result.get("adaptive_run_log", {})),
                                    adaptive_pair_row=adaptive_result.get("pair_row"),
                                    updated_lessons=adaptive_result.get("updated_lessons"),
                                )
                                adaptive_next_index[model_profile] += 1

                            eta_text = _compute_parallel_eta_text()
                            pct_after = (completed_units / max(1, total_progress_units)) * 100.0
                            if not adaptive_enabled or spec.kind == "adaptive_followup":
                                status_line.write(
                                    _render_job_done_line(
                                        pct=pct_after,
                                        job_index=completed_units,
                                        job_total=total_progress_units,
                                        model_profile=job.model_profile,
                                        seed=job.seed,
                                        score=int(summary["final_score"]),
                                        status=("dead" if str(summary.get("end_reason")) == "agent_dead" else "finished"),
                                        eta_text=eta_text,
                                        color_enabled=color_enabled,
                                    )
                                )
                            else:
                                status_line.write(
                                    _render_job_done_line(
                                        pct=pct_after,
                                        job_index=completed_units,
                                        job_total=total_progress_units,
                                        model_profile=job.model_profile,
                                        seed=job.seed,
                                        score=int(summary["final_score"]),
                                        status="initial_done",
                                        eta_text=eta_text,
                                        color_enabled=color_enabled,
                                    )
                                )
                        except Exception as exc:
                            for pending_future in future_to_spec:
                                pending_future.cancel()
                            for pending_future in list(future_started_at.keys()):
                                if pending_future in future_to_spec:
                                    future_started_at.pop(pending_future, None)
                            _fail_and_exit(exc, job)

                    for model in list(active_models):
                        submit_initial_for_model(model)
                        submit_adaptive_for_model(model)
                        if running_tasks_per_model[model] == 0 and not _model_has_pending_work(model):
                            active_models.remove(model)
                    activate_models()
                    for model in list(active_models):
                        submit_initial_for_model(model)
                        submit_adaptive_for_model(model)

            status_line.finish(colorize("[100.0%] compare run completed", "36", color_enabled))

        compare_payload, model_summaries, pairwise_rows, resolved_profiles = _persist_running_state(status="completed")

    compare_json = paths["compare_json"]
    runs_csv = paths["runs_csv"]
    models_csv = paths["models_csv"]
    h2h_csv = paths["h2h_csv"]
    adaptive_runs_csv = paths["adaptive_runs_csv"]
    adaptive_models_csv = paths["adaptive_models_csv"]
    adaptive_pairs_csv = paths["adaptive_pairs_csv"]

    print()
    print(colorize("COMPARE SUMMARY", "1;32", color_enabled))

    _print_section("Identity", color_enabled)
    _print_row("Protocol", protocol_version, color_enabled=color_enabled)
    _print_row("Scenario", scenario, color_enabled=color_enabled)
    _print_row(
        "Run ID",
        _render_run_id_value(compare_id, color_enabled=color_enabled),
        color_enabled=color_enabled,
        value_already_colored=True,
    )
    _print_row("Run root", _short_path(run_dirs["run_root"]), color_enabled=color_enabled, value_color="1;94")
    _print_row("Models (requested)", ", ".join(requested_models), color_enabled=color_enabled)
    _print_row("Models (resolved)", ", ".join(resolved_profiles), color_enabled=color_enabled)
    _print_row(
        "Model(s)",
        _render_models_value(identity_models_text, color_enabled=color_enabled),
        color_enabled=color_enabled,
        value_already_colored=True,
    )
    _print_row("Provider(s)", identity_providers_text, color_enabled=color_enabled)
    _print_row("Routing", identity_routing_text, color_enabled=color_enabled, value_color="1;93")
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

    adaptive_section = compare_payload.get("adaptive") if isinstance(compare_payload, dict) else None
    if isinstance(adaptive_section, dict):
        baseline_totals = dict(adaptive_section.get("baseline_totals", {}))
        adaptive_totals = dict(adaptive_section.get("adaptive_totals", {}))
        delta_totals = dict(adaptive_section.get("delta_totals", {}))
        adaptive_pairs = list(adaptive_section.get("pairs", []))
        _print_section("Adaptive Memory (per seed)", color_enabled)
        pair_model_count = len({str(pair.get("model_profile", "")) for pair in adaptive_pairs})
        for pair in sorted(
            adaptive_pairs,
            key=lambda item: (
                str(item.get("model_profile", "")),
                _safe_int(item.get("seed"), default=0),
                str(item.get("adaptive_pair_key", "")),
            ),
        ):
            seed = _safe_int(pair.get("seed"), default=0)
            model_profile = str(pair.get("model_profile", "")).strip()
            baseline_score = _safe_int(pair.get("initial_score"))
            control_score = _safe_int(pair.get("control_score"))
            adaptive_score = _safe_int(pair.get("adaptive_score"))
            variance_delta = control_score - baseline_score
            no_mem_avg = (baseline_score + control_score) / 2
            mem_effect = adaptive_score - no_mem_avg
            label = f"Seed {seed}" if pair_model_count <= 1 else f"{model_profile} seed {seed}"
            value = (
                f"baseline={baseline_score}  rerun={control_score}  avg_no_mem={no_mem_avg:.0f}  rerun+mem={adaptive_score}  "
                f"memory={mem_effect:+.1f}"
            )
            value_color = "1;92" if mem_effect > 0 else ("1;91" if mem_effect < 0 else "1;97")
            _print_row(
                label,
                value,
                color_enabled=color_enabled,
                value_color=value_color,
            )

        # --- Summary and statistical power warning ---
        _print_section("Adaptive Memory (summary)", color_enabled)
        control_deltas = [_safe_int(p.get("control_delta")) for p in adaptive_pairs if p.get("control_score") is not None]
        memory_effects = [_safe_int(p.get("memory_effect")) for p in adaptive_pairs if p.get("control_score") is not None]
        if control_deltas:
            avg_control = sum(control_deltas) / len(control_deltas)
            avg_mem_effect = sum(memory_effects) / len(memory_effects) if memory_effects else 0.0
            variance = sum((d - avg_control) ** 2 for d in control_deltas) / len(control_deltas) if len(control_deltas) > 1 else 0.0
            std_control = variance ** 0.5
            _print_row(
                "Avg variance (no memory)",
                f"{avg_control:+.1f}  (stdev {std_control:.1f})",
                color_enabled=color_enabled,
            )
            mem_color = "1;92" if avg_mem_effect > 0 else ("1;91" if avg_mem_effect < 0 else "1;97")
            _print_row(
                "Avg memory effect",
                f"{avg_mem_effect:+.1f}",
                color_enabled=color_enabled,
                value_color=mem_color,
            )
            if len(control_deltas) >= 2 and std_control > 0 and abs(avg_mem_effect) < 2 * std_control:
                _print_row(
                    "WARNING",
                    f"Low statistical power: |memory effect| ({abs(avg_mem_effect):.1f}) < 2x variance stdev ({2*std_control:.1f})",
                    color_enabled=color_enabled,
                    value_color="1;93",
                )

    # --- Adaptive Learning Leaderboard ---
    if isinstance(adaptive_section, dict):
        kpi_rows = adaptive_section.get("learning_kpis", [])
        if kpi_rows:
            _print_section("Adaptive Learning Leaderboard", color_enabled)
            hdr = (
                f"{'Model':<30} {'PDI':>5} {'MPR':>5} {'SMER':>5} {'CCS':>6} "
                f"{'Score':>6}  {'Mem':>6}  {'Per seed'}"
            )
            print(f"  {colorize(hdr, '0;37', color_enabled)}")
            for kpi in kpi_rows:
                m = str(kpi.get("model_profile", ""))
                short_m = m.replace("vercel_", "")
                pdi_v = kpi.get("pdi", 0)
                mpr_v = kpi.get("mpr", 0)
                smer_v = kpi.get("smer", 0)
                ccs_v = kpi.get("ccs", 0)
                comp = kpi.get("composite_score", 0)
                avg_me = kpi.get("avg_memory_effect", 0)
                per_seed = ", ".join(f"{e:+.0f}" for e in kpi.get("memory_effects", []))
                me_color = "1;92" if avg_me > 0 else ("1;91" if avg_me < 0 else "1;97")
                bar_len = int(round(comp * 20))
                bar = colorize("█" * bar_len, me_color, color_enabled) + "░" * (20 - bar_len)
                line = (
                    f"{short_m:<30} {pdi_v:>5.3f} {mpr_v:>5.2f} {smer_v:>5.1f} {ccs_v:>+6.3f} "
                    f"{bar} {colorize(f'{comp:.3f}', '1;97', color_enabled)}  "
                    f"{colorize(f'{avg_me:+.1f}', me_color, color_enabled)}  "
                    f"[{per_seed}]"
                )
                print(f"  {line}")
            print()

    _print_section("Artifacts", color_enabled)
    _print_row("Compare JSON", _short_path(compare_json), color_enabled=color_enabled, value_color="1;94")
    _print_row("Runs CSV", _short_path(runs_csv), color_enabled=color_enabled, value_color="1;94")
    _print_row("Models CSV", _short_path(models_csv), color_enabled=color_enabled, value_color="1;94")
    _print_row("H2H CSV", _short_path(h2h_csv), color_enabled=color_enabled, value_color="1;94")
    if adaptive_runs_csv.exists():
        _print_row("Adaptive runs CSV", _short_path(adaptive_runs_csv), color_enabled=color_enabled, value_color="1;94")
    if adaptive_models_csv.exists():
        _print_row("Adaptive models CSV", _short_path(adaptive_models_csv), color_enabled=color_enabled, value_color="1;94")
    if adaptive_pairs_csv.exists():
        _print_row("Adaptive pairs CSV", _short_path(adaptive_pairs_csv), color_enabled=color_enabled, value_color="1;94")
    session_memory_path = run_dirs["memory"] / "session_memory.json"
    if session_memory_path.exists():
        _print_row("Session memory", _short_path(session_memory_path), color_enabled=color_enabled, value_color="1;94")
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
