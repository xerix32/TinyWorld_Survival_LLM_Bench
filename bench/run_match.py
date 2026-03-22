"""CLI entrypoint: run one benchmark match."""

from __future__ import annotations

import argparse
import csv
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
from bench.common import load_yaml_file, run_match_once
from bench.view_log import generate_viewer
from engine.version import __version__


def _short_path(path: str | Path) -> str:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved).resolve()

    cwd = Path.cwd().resolve()
    try:
        return str(resolved.relative_to(cwd))
    except ValueError:
        return str(resolved)


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


def _end_reason_text(end_reason: str, turns_played: int, max_turns: int) -> str:
    if end_reason == "agent_dead":
        return f"The agent died on turn {turns_played}."
    if end_reason == "max_turns_reached":
        return f"Reached the configured turn limit ({max_turns})."
    return f"Run ended with status: {end_reason}."


def _format_resource_breakdown(breakdown: dict[str, int] | None) -> str:
    if not breakdown:
        return "none"

    ordered = ["wood", "stone", "food", "water"]
    parts: list[str] = []
    for key in ordered:
        amount = int(breakdown.get(key, 0))
        parts.append(f"{key} {amount}")
    return ", ".join(parts)


def _header_model_name(model_profile: str) -> str:
    if model_profile.startswith("local_"):
        return "local:" + model_profile[len("local_") :]
    return model_profile


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not (1 <= port <= 65535):
        raise argparse.ArgumentTypeError("port must be in range 1..65535")
    return port


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


def _load_baseline_reference(current_score: float) -> dict[str, Any] | None:
    official_cfg_path = Path("configs/official_benchmark_v0_1.yaml")
    if not official_cfg_path.exists():
        return None

    try:
        official_cfg = load_yaml_file(official_cfg_path)
    except Exception:
        return None

    official_section = official_cfg.get("official_benchmark", {})
    baseline_csv = official_section.get("baseline_csv")
    if not baseline_csv:
        return None

    baseline_path = Path(str(baseline_csv))
    if not baseline_path.is_absolute():
        baseline_path = (Path.cwd() / baseline_path).resolve()

    if not baseline_path.exists():
        return None

    scores: list[float] = []
    try:
        with baseline_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                raw_score = row.get("final_score")
                if raw_score is None or raw_score == "":
                    continue
                scores.append(float(raw_score))
    except Exception:
        return None

    if not scores:
        return None

    count = len(scores)
    avg_score = mean(scores)
    min_score = min(scores)
    max_score = max(scores)
    percentile = (sum(1 for s in scores if s <= current_score) / count) * 100.0

    return {
        "count": count,
        "avg": avg_score,
        "min": min_score,
        "max": max_score,
        "percentile": percentile,
        "path": baseline_path,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one TinyWorld benchmark match with human-readable terminal output and HTML report.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Defaults (if you run without args):\n"
            "  --seed 7\n"
            "  --model local_gpt_oss_20b\n"
            "  --providers-config configs/providers.local.yaml\n"
            "\n"
            "Examples:\n"
            "  python -m bench.run_match\n"
            "  python -m bench.run_match --seed 11 --model groq_gpt_oss_120b --providers-config configs/providers.local.yaml\n"
            "  python -m bench.run_match --serve 8877\n"
            "  python -m bench.run_match --no-viewer --no-color\n"
        ),
    )
    parser.add_argument("--seed", type=int, default=7, help="Deterministic world seed.")
    parser.add_argument(
        "--model",
        type=str,
        default="local_gpt_oss_20b",
        help="Model profile name from providers config.",
    )
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
    parser.add_argument("--output", type=str, default=None, help="Output path for run JSON log.")
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
        default="configs/providers.local.yaml",
        help="Providers + model profiles file. Default points to local profiles.",
    )
    parser.add_argument("--prompts-dir", type=str, default="prompts", help="Prompt templates directory.")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors in terminal output.")
    parser.add_argument("--no-viewer", action="store_true", help="Skip HTML report generation.")
    parser.add_argument("--viewer-output", type=str, default=None, help="Output path for generated HTML report.")
    parser.add_argument("--viewer-title", type=str, default=None, help="Custom title for HTML report.")
    parser.add_argument("--no-open-viewer", action="store_true", help="Generate HTML report but do not open browser.")
    parser.add_argument(
        "--serve",
        nargs="?",
        const=8765,
        type=_parse_port,
        default=None,
        metavar="PORT",
        help=(
            "Serve the generated HTML via local HTTP (http://127.0.0.1:PORT). "
            "If PORT is omitted, 8765 is used."
        ),
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.serve is not None and args.no_viewer:
        parser.error("--serve requires viewer generation; remove --no-viewer.")

    color_enabled = use_color(disable_color=args.no_color)
    status_line = StatusLine(enabled=True)
    run_started_at: float | None = None

    print(colorize(f"TinyWorld Survival Bench CLI v{__version__}", "1;36", color_enabled))

    def on_progress(event: dict[str, Any]) -> None:
        nonlocal run_started_at
        event_type = event.get("event")

        if event_type == "run_started":
            run_started_at = time.monotonic()
            protocol_value = colorize(str(event.get("protocol_version", "AIB-0.1")), "1;96", color_enabled)
            model_value = colorize(str(event["model"]), "1;97", color_enabled)
            profile_value = colorize(str(event["model_profile"]), "1;95", color_enabled)
            provider_value = colorize(str(event["provider_id"]), "1;94", color_enabled)
            seed_value = colorize(str(event["seed"]), "1;33", color_enabled)
            scenario_name = str(event["scenario"])
            if bool(event.get("scenario_is_default", False)):
                scenario_name = f"{scenario_name} (default)"
            scenario_value = colorize(scenario_name, "1;97", color_enabled)

            print(f"Protocol: {protocol_value}")
            print(f"Model: {model_value} | Profile: {profile_value} | Provider: {provider_value}")
            print(f"Seed: {seed_value} | Scenario: {scenario_value}")

            line = (
                f"[  0.0%] Initializing | turn 0/{event['max_turns']} | "
                f"provider: {event['provider_id']} | profile: {event['model_profile']} | eta: --"
            )
            status_line.write(colorize(line, "36", color_enabled))
            return

        if event_type == "turn_completed":
            turn = int(event["turn"])
            max_turns = int(event["max_turns"])
            pct = (turn / max_turns) * 100.0
            action = str(event.get("action") or "-")
            protocol_valid = bool(event.get("protocol_valid", event.get("action_valid", False)))
            effect_applied = bool(event.get("action_effect_applied", False))
            score = int(event.get("cumulative_score", 0))
            invalid = int(event.get("invalid_actions", 0))
            alive = bool(event.get("alive", True))
            eta_text = "--"
            if run_started_at is not None and max_turns > 0 and turn > 0:
                elapsed = max(0.0, time.monotonic() - run_started_at)
                progress = turn / max_turns
                if progress > 0:
                    remaining = max(0.0, (elapsed / progress) - elapsed)
                    eta_text = format_eta(remaining)

            protocol_text = "ok" if protocol_valid else "bad"
            if not protocol_valid:
                effect_text = "n/a"
            elif effect_applied:
                effect_text = "applied"
            else:
                effect_text = "no-op"

            if status_line.enabled and color_enabled:
                pct_text = colorize(f"[{pct:5.1f}%]", "1;35", color_enabled)
                turn_text = colorize(f"Turn {turn}/{max_turns}", "1;97", color_enabled)
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

                line = (
                    f"{pct_text} {turn_text} | "
                    f"action: {action_text} | "
                    f"protocol: {colorize(protocol_text, protocol_color, color_enabled)} | "
                    f"effect: {colorize(effect_text, effect_color, color_enabled)} | "
                    f"score: {score_text} | "
                    f"invalid: {invalid_text} | "
                    f"alive: {alive_text} | {eta_label} {eta_value}"
                )
                status_line.write(line)
            else:
                line = (
                    f"[{pct:5.1f}%] Turn {turn}/{max_turns} | action: {action[:22]:<22} | "
                    f"protocol: {protocol_text:<3} | effect: {effect_text:<7} | "
                    f"score: {score:>4} | invalid: {invalid:>3} | alive: {'yes' if alive else 'no'} | eta: {eta_text}"
                )
                status_line.write(line)
            return

        if event_type == "run_completed":
            status_line.finish(colorize("[100.0%] Run completed", "36", color_enabled))

    try:
        run_log = run_match_once(
            seed=args.seed,
            model_name=args.model,
            scenario_name=args.scenario,
            max_turns=args.max_turns,
            benchmark_config_path=args.benchmark_config,
            scenarios_config_path=args.scenarios_config,
            providers_config_path=args.providers_config,
            prompts_dir=args.prompts_dir,
            output_path=args.output,
            progress_callback=on_progress,
        )
    except KeyboardInterrupt:
        status_line.finish(colorize("[interrupted] Run canceled by user", "1;93", color_enabled))
        print(colorize("Run canceled (Ctrl+C). Exiting cleanly.", "1;93", color_enabled))
        raise SystemExit(130)
    except Exception as exc:
        status_line.finish(colorize("[failed] Run failed", "1;91", color_enabled))
        error_text = str(exc).strip() or exc.__class__.__name__
        print(colorize(f"Run failed: {error_text}", "1;91", color_enabled))
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

    summary = run_log["run_summary"]

    max_turns = int(summary["max_turns"])
    turns_survived = int(summary["turns_survived"])
    turns_played = int(summary["turns_played"])
    final_score = float(summary["final_score"])
    invalid_actions = int(summary["invalid_actions"])

    survival_pct = (turns_survived / max_turns) * 100.0 if max_turns else 0.0

    total_latency_ms = float(summary["latency_ms"]) if summary.get("latency_ms") is not None else None
    avg_latency_ms = (total_latency_ms / turns_played) if (total_latency_ms is not None and turns_played > 0) else None

    baseline = _load_baseline_reference(final_score)
    print()
    print(colorize("RUN SUMMARY", "1;32", color_enabled))

    _print_section("Identity", color_enabled)
    _print_row("Model", str(summary["model"]), color_enabled=color_enabled)
    _print_row("Model profile", str(summary["model_profile"]), color_enabled=color_enabled)
    _print_row("Provider", str(summary["provider_id"]), color_enabled=color_enabled)

    _print_section("Outcome", color_enabled)
    _print_row("Final score", f"{_format_number(final_score)} points", color_enabled=color_enabled, value_color="1;92")
    _print_row("Score scale", "Open-ended (no fixed maximum)", color_enabled=color_enabled, value_color="0;37")
    _print_row(
        "Turns survived",
        f"{turns_survived}/{max_turns} ({survival_pct:.1f}%)",
        color_enabled=color_enabled,
        value_color="1;97",
    )

    end_reason_text = _end_reason_text(str(summary["end_reason"]), turns_played, max_turns)
    end_reason_color = "1;91" if str(summary["end_reason"]) == "agent_dead" else "1;92"
    _print_row("Run status", end_reason_text, color_enabled=color_enabled, value_color=end_reason_color)
    invalid_color = "1;92" if invalid_actions == 0 else "1;91"
    _print_row("Invalid actions", str(invalid_actions), color_enabled=color_enabled, value_color=invalid_color)

    if baseline is not None:
        delta_vs_avg = final_score - float(baseline["avg"])
        delta_sign = "+" if delta_vs_avg >= 0 else ""
        delta_color = "1;92" if delta_vs_avg >= 0 else "1;91"
        _print_section("Baseline (dummy v0.1, seeds 1-20)", color_enabled)
        _print_row(
            "Comparison scope",
            "Against random baseline dummy_v0_1 only (not against other LLMs)",
            color_enabled=color_enabled,
            value_color="0;37",
        )
        _print_row("Baseline avg", f"{baseline['avg']:.2f} points", color_enabled=color_enabled)
        _print_row(
            "Baseline range",
            f"{baseline['min']:.0f} .. {baseline['max']:.0f} points (n={baseline['count']})",
            color_enabled=color_enabled,
        )
        _print_row(
            "Your delta vs avg",
            f"{delta_sign}{delta_vs_avg:.2f} points",
            color_enabled=color_enabled,
            value_color=delta_color,
        )
        _print_row(
            "Percentile",
            f"{baseline['percentile']:.1f}th percentile",
            color_enabled=color_enabled,
            value_color="1;93",
        )

    breakdown = summary.get("resources_gathered_breakdown")
    _print_section("Resources", color_enabled)
    _print_row("Gathered total", f"{_format_number(summary['resources_gathered'])}", color_enabled=color_enabled)
    _print_row("Breakdown", _format_resource_breakdown(breakdown), color_enabled=color_enabled)

    _print_section("Performance", color_enabled)
    _print_row("Model latency total", _format_duration_from_ms(total_latency_ms), color_enabled=color_enabled)
    _print_row(
        "Model latency avg",
        _format_duration_from_ms(avg_latency_ms),
        color_enabled=color_enabled,
    )
    _print_row("Tokens used", _format_number(summary.get("tokens_used"), fallback="not available"), color_enabled=color_enabled)

    est_cost = summary.get("estimated_cost")
    est_cost_value = "not available" if est_cost is None else _format_number(est_cost, digits=6)
    _print_row("Estimated cost", est_cost_value, color_enabled=color_enabled)

    log_path = Path(str(summary["log_path"]))
    _print_section("Artifacts", color_enabled)
    _print_row("Run log", _short_path(log_path), color_enabled=color_enabled, value_color="1;94")

    if not args.no_viewer:
        if args.viewer_output:
            viewer_output = Path(args.viewer_output)
            if not viewer_output.is_absolute():
                viewer_output = Path.cwd() / viewer_output
        else:
            viewer_output = Path("artifacts/replays") / (log_path.stem + "_dashboard.html")
            viewer_output = Path.cwd() / viewer_output

        viewer_title = args.viewer_title or f"TinyWorld Report - seed {summary['seed']} - {summary['model_profile']}"

        try:
            viewer_path = generate_viewer(log_path=log_path, output_path=viewer_output, title=viewer_title)
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
