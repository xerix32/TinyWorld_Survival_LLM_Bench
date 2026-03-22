"""Generate an interactive HTML dashboard from a benchmark run log."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_dimensions(run_log: dict[str, Any]) -> tuple[int, int]:
    scenario = run_log.get("config_snapshot", {}).get("scenario", {})
    width = _as_int(scenario.get("width"), 0)
    height = _as_int(scenario.get("height"), 0)

    if width > 0 and height > 0:
        return width, height

    snapshots = run_log.get("world_snapshots", {})
    initial_tiles = snapshots.get("initial_tiles")
    if isinstance(initial_tiles, list) and initial_tiles:
        inferred_height = len(initial_tiles)
        inferred_width = len(initial_tiles[0]) if isinstance(initial_tiles[0], list) else 0
        if inferred_width > 0 and inferred_height > 0:
            return inferred_width, inferred_height

    max_x = 0
    max_y = 0
    for turn in run_log.get("turn_logs", []):
        obs = turn.get("observation", {})
        pos = obs.get("position", {})
        max_x = max(max_x, _as_int(pos.get("x"), 0))
        max_y = max(max_y, _as_int(pos.get("y"), 0))
        for tile in obs.get("visible_tiles", []):
            max_x = max(max_x, _as_int(tile.get("x"), 0))
            max_y = max(max_y, _as_int(tile.get("y"), 0))

    return max_x + 1, max_y + 1


def _coerce_position(value: Any) -> dict[str, int] | None:
    if isinstance(value, dict):
        return {"x": _as_int(value.get("x"), 0), "y": _as_int(value.get("y"), 0)}
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return {"x": _as_int(value[0], 0), "y": _as_int(value[1], 0)}
    return None


def _valid_map_shape(tiles: Any, width: int, height: int) -> bool:
    if not isinstance(tiles, list) or len(tiles) != height:
        return False
    for row in tiles:
        if not isinstance(row, list) or len(row) != width:
            return False
    return True


def _copy_tiles(tiles: list[list[str]]) -> list[list[str]]:
    return [row[:] for row in tiles]


def _initial_map_state(run_log: dict[str, Any], width: int, height: int) -> tuple[list[list[str]], str]:
    snapshots = run_log.get("world_snapshots", {})
    initial_tiles = snapshots.get("initial_tiles")

    if _valid_map_shape(initial_tiles, width, height):
        return _copy_tiles(initial_tiles), "full"

    return [["unknown" for _ in range(width)] for _ in range(height)], "partial"


def _apply_visible_tiles(
    map_state: list[list[str]],
    visible_tiles: list[dict[str, Any]],
    width: int,
    height: int,
) -> None:
    for tile in visible_tiles:
        x = _as_int(tile.get("x"), -1)
        y = _as_int(tile.get("y"), -1)
        tile_type = str(tile.get("type", "unknown"))
        if 0 <= x < width and 0 <= y < height:
            map_state[y][x] = tile_type


def _build_frames(run_log: dict[str, Any], width: int, height: int) -> tuple[list[dict[str, Any]], str]:
    map_state, map_coverage = _initial_map_state(run_log, width, height)
    frames: list[dict[str, Any]] = []
    path_prefix: list[dict[str, int]] = []

    for turn in run_log.get("turn_logs", []):
        observation = turn.get("observation", {})
        visible_tiles = observation.get("visible_tiles", [])
        _apply_visible_tiles(map_state, visible_tiles, width, height)

        before_position = _coerce_position(observation.get("position")) or {"x": 0, "y": 0}

        action_delta = turn.get("world_result_delta", {}).get("action_delta", {})
        tile_after = action_delta.get("tile_after")
        if isinstance(tile_after, str):
            bx = before_position["x"]
            by = before_position["y"]
            if 0 <= bx < width and 0 <= by < height:
                map_state[by][bx] = tile_after

        after_position = _coerce_position(action_delta.get("position_after")) or before_position
        path_prefix.append(after_position)

        frames.append(
            {
                "turn": _as_int(turn.get("turn"), len(frames) + 1),
                "observation": observation,
                "agent_position_before": before_position,
                "agent_position_after": after_position,
                "map_snapshot": _copy_tiles(map_state),
                "path_prefix": path_prefix[:],
                "action_result": turn.get("action_result", {}),
                "validation_result": turn.get("validation_result", {}),
                "score_delta": turn.get("score_delta", {}),
                "cumulative_score": turn.get("cumulative_score"),
                "metrics": turn.get("metrics", {}),
                "raw_model_output": turn.get("raw_model_output"),
                "survival_delta": turn.get("world_result_delta", {}).get("survival_delta", {}),
            }
        )

    return frames, map_coverage


def _initial_gatherable_totals(run_log: dict[str, Any], width: int, height: int) -> tuple[int | None, dict[str, int] | None]:
    snapshots = run_log.get("world_snapshots", {})
    initial_tiles = snapshots.get("initial_tiles")
    if not _valid_map_shape(initial_tiles, width, height):
        return None, None

    counts = {"tree": 0, "rock": 0, "food": 0, "water": 0}
    for row in initial_tiles:
        for tile in row:
            tile_name = str(tile)
            if tile_name in counts:
                counts[tile_name] += 1

    total = counts["tree"] + counts["rock"] + counts["food"] + counts["water"]
    return total, counts


def build_viewer_payload(run_log: dict[str, Any], source_log_path: Path) -> dict[str, Any]:
    width, height = _extract_dimensions(run_log)
    frames, map_coverage = _build_frames(run_log, width, height)
    gatherable_total, gatherable_breakdown = _initial_gatherable_totals(run_log, width, height)
    summary = run_log.get("run_summary", {})
    identity = run_log.get("benchmark_identity", {})
    prompt_versions = run_log.get("prompt_versions", {})
    benchmark_cfg = run_log.get("config_snapshot", {}).get("benchmark", {})
    parser_cfg = benchmark_cfg.get("parser", {})

    return {
        "meta": {
            "source_log_path": str(source_log_path),
            "version": run_log.get("version"),
            "bench_version": identity.get("bench_version", run_log.get("version")),
            "engine_version": identity.get("engine_version", run_log.get("engine_version", run_log.get("version"))),
            "prompt_set_sha256": identity.get("prompt_set_sha256", prompt_versions.get("prompt_set_sha256")),
            "protocol_version": run_log.get("protocol_version"),
            "seed": run_log.get("seed"),
            "scenario": run_log.get("scenario"),
            "provider_id": run_log.get("provider_id"),
            "model_profile": run_log.get("model_profile"),
            "model": run_log.get("model"),
            "map_coverage": map_coverage,
        },
        "summary": summary,
        "world": {
            "width": width,
            "height": height,
            "gatherable_total": gatherable_total,
            "gatherable_breakdown": gatherable_breakdown,
        },
        "protocol": {
            "protocol_version": run_log.get("protocol_version"),
            "invalid_action_policy": benchmark_cfg.get("invalid_action_policy"),
            "parser_case_mode": parser_cfg.get("case_mode"),
            "rules": benchmark_cfg.get("rules", {}),
            "scoring": benchmark_cfg.get("scoring", {}),
        },
        "frames": frames,
    }


def render_html(payload: dict[str, Any], page_title: str) -> str:
    safe_title = html.escape(page_title)
    payload_json = json.dumps(payload, ensure_ascii=False)
    # Prevent accidental </script> termination if model output contains that literal.
    payload_json = payload_json.replace("</", "<\\/")

    html_head = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>""" + safe_title + """</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700;800&family=Inter:wght@400;500;600;700;800&display=swap');

    :root {
      --bg: #0a0a0b;
      --bg-raised: #111113;
      --bg-card: #161619;
      --bg-card-hover: #1c1c20;
      --border: #27272a;
      --border-bright: #3f3f46;
      --text: #fafafa;
      --text-secondary: #a1a1aa;
      --text-dim: #71717a;
      --accent: #22d3ee;
      --accent-dim: rgba(34, 211, 238, 0.15);
      --accent-glow: rgba(34, 211, 238, 0.08);
      --green: #4ade80;
      --green-dim: rgba(74, 222, 128, 0.15);
      --red: #f87171;
      --red-dim: rgba(248, 113, 113, 0.15);
      --orange: #fb923c;
      --orange-dim: rgba(251, 146, 60, 0.12);
      --purple: #a78bfa;
      --radius: 12px;
      --radius-sm: 8px;
      --font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
      --font-sans: 'Inter', -apple-system, 'Segoe UI', sans-serif;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-sans);
      line-height: 1.5;
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
    }

    .wrap {
      max-width: 1320px;
      margin: 0 auto;
      padding: 16px 20px;
      display: grid;
      gap: 12px;
    }

    /* ── OUTCOME HEADER ── */
    .outcome-hero {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px 24px;
      display: grid;
      gap: 16px;
    }

    .outcome-header-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }

    .outcome-identity {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }

    .outcome-model {
      font-family: var(--font-mono);
      font-size: 0.95rem;
      font-weight: 700;
      color: var(--accent);
    }

    .outcome-separator {
      color: var(--text-dim);
      font-size: 0.85rem;
    }

    .outcome-scenario {
      font-family: var(--font-mono);
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--text-secondary);
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 2px 10px;
    }

    .outcome-badge {
      font-family: var(--font-mono);
      font-size: 0.82rem;
      font-weight: 700;
      border-radius: 6px;
      padding: 5px 14px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .outcome-badge.survived {
      background: var(--green-dim);
      color: var(--green);
      border: 1px solid rgba(74, 222, 128, 0.3);
    }

    .outcome-badge.died {
      background: var(--red-dim);
      color: var(--red);
      border: 1px solid rgba(248, 113, 113, 0.3);
    }

    .outcome-metrics {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 1px;
      background: var(--border);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      overflow: hidden;
    }

    .outcome-metric {
      background: var(--bg-raised);
      padding: 12px 16px;
      text-align: center;
    }

    .outcome-metric .metric-value {
      font-family: var(--font-mono);
      font-size: 1.5rem;
      font-weight: 800;
      color: var(--text);
      line-height: 1.1;
    }

    .outcome-metric .metric-value.score-value {
      color: var(--accent);
      font-size: 1.8rem;
    }

    .outcome-metric .metric-value.score-negative {
      color: var(--red);
    }

    .outcome-metric .metric-label {
      font-size: 0.7rem;
      font-weight: 600;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-top: 2px;
    }

    .outcome-why {
      font-family: var(--font-mono);
      font-size: 0.8rem;
      color: var(--text-dim);
      border-left: 2px solid var(--border-bright);
      padding-left: 12px;
    }

    /* ── TECH ACCORDION ── */
    .tech-accordion {
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow: hidden;
      background: var(--bg-card);
    }

    .tech-toggle {
      width: 100%;
      background: var(--bg-card);
      border: none;
      padding: 10px 16px;
      font-family: var(--font-mono);
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--text-dim);
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      align-items: center;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      transition: color 0.15s;
    }

    .tech-toggle:hover { color: var(--text-secondary); }

    .tech-body {
      display: none;
      padding: 12px 16px;
      border-top: 1px solid var(--border);
    }

    .tech-body.open {
      display: grid;
      gap: 10px;
    }

    .chip-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .chip {
      border: 1px solid var(--border);
      background: var(--bg-raised);
      border-radius: 6px;
      padding: 3px 10px;
      font-family: var(--font-mono);
      font-size: 0.72rem;
      color: var(--text-secondary);
      white-space: nowrap;
    }

    .chip .chip-key {
      color: var(--text-dim);
      margin-right: 4px;
    }

    .chip .chip-value {
      color: var(--text-secondary);
      font-weight: 600;
    }

    .chip.chip-model .chip-value {
      color: var(--accent);
      font-weight: 700;
    }

    .chip-btn {
      cursor: pointer;
      font: inherit;
      font-family: var(--font-mono);
      font-size: 0.72rem;
      transition: border-color 0.15s;
    }

    .chip-btn:hover {
      border-color: var(--accent);
      color: var(--accent);
    }

    .protocol-panel {
      display: none;
      gap: 10px;
      margin-top: 8px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--bg-raised);
      padding: 12px;
    }

    .protocol-panel.open {
      display: grid;
    }

    .protocol-head {
      font-family: var(--font-mono);
      font-size: 0.78rem;
      font-weight: 700;
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    .protocol-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(220px, 1fr));
      gap: 8px;
    }

    .protocol-block {
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--bg-card);
      padding: 10px 12px;
      font-family: var(--font-mono);
      font-size: 0.75rem;
      color: var(--text-secondary);
      display: grid;
      gap: 2px;
    }

    .protocol-block strong {
      color: var(--accent);
      font-size: 0.68rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .protocol-note {
      color: var(--text-dim);
      font-size: 0.75rem;
      font-family: var(--font-mono);
    }

    /* ── LAYOUT ── */
    .layout {
      display: grid;
      grid-template-columns: 1.6fr 1fr;
      gap: 12px;
      align-items: start;
    }

    .panel {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px;
      display: grid;
      gap: 12px;
    }

    .panel h2 {
      margin: 0;
      font-family: var(--font-mono);
      font-size: 0.78rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--text-dim);
      font-weight: 700;
    }

    /* ── MAP CONTROLS ── */
    .control-bar {
      display: grid;
      grid-template-columns: auto auto auto 1fr auto;
      gap: 8px;
      align-items: center;
    }

    .btn {
      border: 1px solid var(--border);
      background: var(--bg-raised);
      color: var(--text-secondary);
      border-radius: 6px;
      padding: 5px 10px;
      font-family: var(--font-mono);
      font-size: 0.78rem;
      font-weight: 600;
      cursor: pointer;
      transition: border-color 0.15s, color 0.15s;
    }

    .btn:hover {
      border-color: var(--accent);
      color: var(--accent);
    }

    input[type='range'] {
      width: 100%;
      accent-color: var(--accent);
      height: 4px;
    }

    .turn-meta {
      font-family: var(--font-mono);
      font-size: 0.78rem;
      color: var(--text-dim);
    }

    /* ── MAP ── */
    .map {
      display: grid;
      gap: 3px;
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 8px;
    }

    .tile {
      position: relative;
      border: 1px solid var(--border);
      border-radius: 6px;
      min-height: 60px;
      display: grid;
      place-items: center;
      font-size: 1.35rem;
      background: var(--bg-card);
      transition: transform 0.1s ease;
      overflow: hidden;
    }

    .tile .tile-emoji {
      filter: drop-shadow(0 1px 3px rgba(0,0,0,0.5));
      line-height: 1;
    }

    .tile .tile-type {
      position: absolute;
      top: 2px;
      left: 4px;
      font-family: var(--font-mono);
      font-size: 0.52rem;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      pointer-events: none;
    }

    .tile.unknown .tile-type { color: #555; }
    .tile.empty .tile-type   { color: #444; }
    .tile.tree .tile-type    { color: #4ade80; }
    .tile.rock .tile-type    { color: #9ca3af; }
    .tile.food .tile-type    { color: #fb923c; }
    .tile.water .tile-type   { color: #38bdf8; }

    .tile.path::after {
      content: "";
      position: absolute;
      inset: 2px;
      border: 1px dashed rgba(34, 211, 238, 0.35);
      border-radius: 4px;
      pointer-events: none;
    }

    .tile.agent {
      transform: scale(1.04);
      box-shadow:
        inset 0 0 0 2px rgba(34, 211, 238, 0.7),
        0 0 16px rgba(34, 211, 238, 0.25),
        0 0 32px rgba(34, 211, 238, 0.08);
      z-index: 1;
    }

    .tile.unknown { background: #1c1c20; }
    .tile.empty   { background: #1e1e22; border-color: #2a2a2e; }
    .tile.tree    { background: #132b18; border-color: #245a30; }
    .tile.rock    { background: #22222a; border-color: #3a3a44; }
    .tile.food    { background: #2a1c0a; border-color: #4a3018; }
    .tile.water   { background: #0c2030; border-color: #184060; }

    .coord {
      position: absolute;
      top: 2px;
      right: 4px;
      font-size: 0.56rem;
      color: #888;
      font-family: var(--font-mono);
    }

    .agent-mark {
      position: absolute;
      left: 2px;
      right: 2px;
      bottom: 2px;
      display: flex;
      align-items: center;
      gap: 3px;
      font-size: 0.6rem;
      line-height: 1;
      padding: 2px 4px;
      border-radius: 4px;
      background: rgba(34, 211, 238, 0.2);
      border: 1px solid rgba(34, 211, 238, 0.45);
      color: var(--accent);
      pointer-events: none;
      font-weight: 700;
      backdrop-filter: blur(4px);
    }

    .agent-mark .name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-family: var(--font-mono);
      font-size: 0.54rem;
    }

    /* ── TURN DETAILS ── */
    .action-line {
      display: grid;
      gap: 6px;
    }

    .action-line .action-row {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    .action-line .score-delta {
      font-family: var(--font-mono);
      font-weight: 700;
      font-size: 0.88rem;
    }

    .action-line .score-delta.delta-positive { color: var(--green); }
    .action-line .score-delta.delta-negative { color: var(--red); }

    .tag-ok,
    .tag-bad {
      border-radius: 4px;
      font-family: var(--font-mono);
      font-size: 0.68rem;
      padding: 2px 8px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    .tag-ok {
      background: var(--green-dim);
      color: var(--green);
      border: 1px solid rgba(74, 222, 128, 0.3);
    }

    .tag-bad {
      background: var(--red-dim);
      color: var(--red);
      border: 1px solid rgba(248, 113, 113, 0.3);
    }

    .cmd-action {
      font-family: var(--font-mono);
      color: var(--accent);
      font-weight: 700;
      font-size: 0.82rem;
      background: var(--accent-dim);
      border: 1px solid rgba(34, 211, 238, 0.2);
      border-radius: 4px;
      padding: 1px 8px;
    }

    /* ── METERS ── */
    .state-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
    }

    .meter {
      display: grid;
      gap: 4px;
      font-family: var(--font-mono);
      font-size: 0.76rem;
      color: var(--text-secondary);
    }

    .meter .bar {
      width: 100%;
      height: 6px;
      border-radius: 999px;
      background: var(--border);
      overflow: hidden;
    }

    .meter .fill {
      height: 100%;
      border-radius: 999px;
      background: var(--accent);
      transition: width 0.3s ease;
    }

    .meter.warn .fill {
      background: var(--orange);
    }

    .meter.bad .fill {
      background: var(--red);
    }

    /* ── INVENTORY ── */
    .inventory {
      display: grid;
      grid-template-columns: repeat(2, minmax(100px, 1fr));
      gap: 6px;
      margin-top: 4px;
    }

    .pill {
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 6px 10px;
      font-family: var(--font-mono);
      font-size: 0.78rem;
      display: flex;
      justify-content: space-between;
      background: var(--bg-raised);
      color: var(--text-secondary);
    }

    .pill strong {
      color: var(--text);
    }

    /* ── DETAILS / SUMMARY ── */
    details > summary {
      cursor: pointer;
      font-family: var(--font-mono);
      font-size: 0.76rem;
      font-weight: 600;
      color: var(--text-dim);
      padding: 4px 0;
      list-style: none;
      transition: color 0.15s;
    }

    details > summary::-webkit-details-marker { display: none; }

    details > summary::before {
      content: "\\25B8  ";
      font-size: 0.65rem;
      color: var(--text-dim);
    }

    details[open] > summary::before {
      content: "\\25BE  ";
    }

    details > summary:hover { color: var(--text-secondary); }

    .mono {
      font-family: var(--font-mono);
      font-size: 0.78rem;
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 10px;
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
      color: var(--text-secondary);
    }

    .mono.raw-command {
      color: var(--accent);
      font-weight: 600;
      background: rgba(34, 211, 238, 0.05);
      border-color: rgba(34, 211, 238, 0.15);
    }

    /* ── TIMELINE ── */
    .timeline {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px;
      overflow: hidden;
    }

    .timeline h2 {
      margin: 0;
      font-family: var(--font-mono);
      font-size: 0.78rem;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-weight: 700;
    }

    .table-wrap {
      max-height: 300px;
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
    }

    /* Scrollbar styling */
    .table-wrap::-webkit-scrollbar {
      width: 6px;
      height: 6px;
    }
    .table-wrap::-webkit-scrollbar-track {
      background: var(--bg-raised);
    }
    .table-wrap::-webkit-scrollbar-thumb {
      background: var(--border-bright);
      border-radius: 3px;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-family: var(--font-mono);
      font-size: 0.76rem;
    }

    thead {
      position: sticky;
      top: 0;
      background: var(--bg-raised);
      z-index: 1;
    }

    th {
      text-align: left;
      padding: 8px 10px;
      border-bottom: 1px solid var(--border);
      color: var(--text-dim);
      font-weight: 600;
      font-size: 0.68rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      white-space: nowrap;
    }

    td {
      text-align: left;
      padding: 6px 10px;
      border-bottom: 1px solid var(--border);
      color: var(--text-secondary);
      white-space: nowrap;
    }

    tr { transition: background 0.1s; }
    tr.active { background: var(--accent-dim); }
    tr:hover { background: rgba(255, 255, 255, 0.03); cursor: pointer; }
    tr.turn-invalid { background: var(--red-dim); }
    tr.turn-critical { background: var(--orange-dim); }
    tr.turn-invalid td:nth-child(3) { color: var(--red); font-weight: 700; }
    tr.active.turn-invalid { background: rgba(248, 113, 113, 0.2); }
    tr.active.turn-critical { background: rgba(251, 146, 60, 0.18); }

    /* ── FOOTER ── */
    .footer {
      color: var(--text-dim);
      font-family: var(--font-mono);
      font-size: 0.7rem;
      display: flex;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 6px;
      padding: 4px 0;
    }

    /* ── CHECKBOX ── */
    .toggle-label {
      font-family: var(--font-mono);
      font-size: 0.72rem;
      color: var(--text-dim);
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      user-select: none;
    }

    .toggle-label input[type="checkbox"] {
      accent-color: var(--accent);
    }

    /* ── RESPONSIVE ── */
    @media (max-width: 980px) {
      .outcome-header-row { flex-direction: column; align-items: flex-start; }
      .outcome-metrics { grid-template-columns: repeat(2, 1fr); }
      .layout { grid-template-columns: 1fr; }
      .state-grid { grid-template-columns: 1fr; }
      .control-bar { grid-template-columns: 1fr 1fr; }
      .protocol-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="outcome-hero" id="outcomeHero"></section>

    <section class="tech-accordion">
      <button class="tech-toggle" id="techToggle" type="button">
        // technical details <span id="techArrow">&#9654;</span>
      </button>
      <div class="tech-body" id="techBody">
        <div class="chip-row" id="metaChips"></div>
        <div class="protocol-panel" id="protocolPanel"></div>
      </div>
    </section>

    <section class="layout">
      <article class="panel">
        <h2>Map + Turn Player</h2>
        <div class="control-bar">
          <button class="btn" id="prevBtn">&#9664; Prev</button>
          <button class="btn" id="playBtn">&#9654; Play</button>
          <input type="range" id="turnSlider" min="1" max="1" step="1" value="1" />
          <div class="turn-meta" id="turnMeta"></div>
        </div>
        <div class="map" id="mapGrid"></div>
        <div class="footer">
          <span id="mapLegend"></span>
          <span id="coverageHint"></span>
        </div>
      </article>

      <article class="panel">
        <h2>Turn Details</h2>
        <div class="action-line" id="actionLine"></div>
        <div class="state-grid" id="stateMeters"></div>
        <div>
          <strong style="font-family:var(--font-mono);font-size:0.76rem;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.06em">Inventory</strong>
          <div class="inventory" id="inventoryGrid"></div>
        </div>
        <details>
          <summary>Raw model output</summary>
          <div class="mono raw-command" id="rawOutput"></div>
        </details>
        <details>
          <summary>Score events</summary>
          <div class="mono" id="scoreEvents"></div>
        </details>
      </article>
    </section>

    <section class="timeline">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:10px">
        <h2 style="margin:0">Turn Timeline</h2>
        <label class="toggle-label">
          <input type="checkbox" id="showImportantOnly" /> important only
        </label>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Action</th>
              <th>Valid</th>
              <th>&#916; Score</th>
              <th>Total</th>
              <th>Energy</th>
              <th>Hunger</th>
              <th>Thirst</th>
            </tr>
          </thead>
          <tbody id="timelineBody"></tbody>
        </table>
      </div>
    </section>

    <div class="footer">
      <span id="sourceLog"></span>
      <span>TinyWorld Survival Bench</span>
    </div>
  </div>
"""

    html_data = '<script id="viewerData" type="application/json">' + payload_json + "</script>"

    html_tail = """
  <script>
    const DATA = JSON.parse(document.getElementById('viewerData').textContent);

    const tileMeta = {
      unknown: { emoji: '\\u2588', label: '?' },
      empty: { emoji: '\\u25AB', label: '' },
      tree: { emoji: '\\u{1F332}', label: 'tree' },
      rock: { emoji: '\\u{1FAA8}', label: 'rock' },
      food: { emoji: '\\u{1F34E}', label: 'food' },
      water: { emoji: '\\u{1F4A7}', label: 'water' },
    };

    const inventoryMeta = {
      wood: '\\u{1FAB5} wood',
      stone: '\\u{1F9F1} stone',
      food: '\\u{1F34E} food',
      water: '\\u{1F4A7} water',
    };

    let currentTurnIndex = 0;
    let autoPlayTimer = null;

    const outcomeHero = document.getElementById('outcomeHero');
    const metaChips = document.getElementById('metaChips');
    const protocolPanel = document.getElementById('protocolPanel');
    const mapGrid = document.getElementById('mapGrid');
    const turnSlider = document.getElementById('turnSlider');
    const turnMeta = document.getElementById('turnMeta');
    const actionLine = document.getElementById('actionLine');
    const stateMeters = document.getElementById('stateMeters');
    const inventoryGrid = document.getElementById('inventoryGrid');
    const rawOutput = document.getElementById('rawOutput');
    const scoreEvents = document.getElementById('scoreEvents');
    const timelineBody = document.getElementById('timelineBody');
    const sourceLog = document.getElementById('sourceLog');
    const coverageHint = document.getElementById('coverageHint');

    const prevBtn = document.getElementById('prevBtn');
    const playBtn = document.getElementById('playBtn');

    const frames = DATA.frames || [];
    const worldWidth = DATA.world.width;
    const worldHeight = DATA.world.height;

    function clampTurnIndex(index) {
      if (!frames.length) return 0;
      return Math.max(0, Math.min(frames.length - 1, index));
    }

    function meterClass(value, maxValue = 100) {
      const max = numberOr(maxValue, 100);
      const current = numberOr(value, 0);
      const pct = max > 0 ? (current / max) * 100 : 0;
      if (pct >= 80) return 'meter bad';
      if (pct >= 60) return 'meter warn';
      return 'meter';
    }

    function energyMeterClass(value, maxValue = 100) {
      const max = numberOr(maxValue, 100);
      const current = numberOr(value, 0);
      const pct = max > 0 ? (current / max) * 100 : 0;
      if (pct <= 30) return 'meter bad';
      if (pct <= 50) return 'meter warn';
      return 'meter';
    }

    function formatCount(value, fallback = 'n/a') {
      if (value === null || value === undefined || value === '') return fallback;
      const num = Number(value);
      if (!Number.isFinite(num)) return fallback;
      return Math.round(num).toLocaleString('en-US');
    }

    function formatEstimatedCost(value) {
      if (value === null || value === undefined || value === '') return 'n/a';
      const num = Number(value);
      if (!Number.isFinite(num)) return 'n/a';
      return num.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 6 });
    }

    function formatDurationFromMs(valueMs) {
      if (valueMs === null || valueMs === undefined || valueMs === '') return 'n/a';
      const ms = Number(valueMs);
      if (!Number.isFinite(ms)) return 'n/a';

      if (ms < 10) return `${ms.toLocaleString('en-US', { minimumFractionDigits: 3, maximumFractionDigits: 3 })} ms`;
      if (ms < 1000) return `${ms.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} ms`;

      const seconds = ms / 1000;
      if (seconds < 60) return `${seconds.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} s`;

      const minutes = Math.floor(seconds / 60);
      const remSeconds = seconds % 60;
      if (minutes < 60) {
        return `${minutes}m ${remSeconds.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).padStart(4, '0')}s`;
      }

      const hours = Math.floor(minutes / 60);
      const remMinutes = minutes % 60;
      return `${hours}h ${String(remMinutes).padStart(2, '0')}m ${remSeconds.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).padStart(4, '0')}s`;
    }

    function formatScoreEvent(eventName) {
      const labels = {
        survive_turn: 'Survived turn (+1)',
        useful_gather: 'Useful gather (+3)',
        useful_consume: 'Useful eat/drink (+2)',
        invalid_action_penalty: 'Invalid action (-2)',
        death_penalty: 'Death penalty (-10)',
      };
      if (labels[eventName]) return labels[eventName];
      return String(eventName || '').replaceAll('_', ' ');
    }

    function formatSignedScore(value) {
      const num = Number(value ?? 0);
      if (!Number.isFinite(num)) return '0';
      return `${num > 0 ? '+' : ''}${num}`;
    }

    function formatEndReason(endReason, turnsPlayed, maxTurns) {
      const reason = String(endReason || '').trim();
      const turns = Number(turnsPlayed ?? 0);
      const max = Number(maxTurns ?? 0);
      if (reason === 'agent_dead') return `Agent died on turn ${turns}.`;
      if (reason === 'max_turns_reached') return `Reached turn limit (${max}).`;
      if (!reason) return 'Run ended.';
      return `Run ended: ${reason}.`;
    }

    function inferDeathCause(summary) {
      const explicit = String(summary?.death_cause_human || '').trim();
      if (explicit) return explicit;

      if (String(summary?.end_reason || '') !== 'agent_dead') return '';
      const lastFrame = frames.length ? frames[frames.length - 1] : null;
      const survival = lastFrame?.survival_delta || {};
      const starvation = Boolean(survival.starvation_triggered);
      const dehydration = Boolean(survival.dehydration_triggered);

      if (starvation && dehydration) return 'Starvation and dehydration reached critical threshold.';
      if (starvation) return 'Starvation reached critical threshold.';
      if (dehydration) return 'Dehydration reached critical threshold.';
      return 'Energy depleted to zero.';
    }

    function shortHash(value, length = 12) {
      const raw = String(value || '').trim();
      if (!raw) return '-';
      return raw.length <= length ? raw : raw.slice(0, length);
    }

    function numberOr(value, fallback) {
      const num = Number(value);
      return Number.isFinite(num) ? num : fallback;
    }

    function statLimit(ruleKey, fallback = 100) {
      const rules = DATA.protocol?.rules || {};
      const parsed = numberOr(rules[ruleKey], fallback);
      return parsed > 0 ? parsed : fallback;
    }

    function renderProtocolPanel() {
      if (!protocolPanel) return;
      const p = DATA.protocol || {};
      const rules = p.rules || {};
      const scoring = p.scoring || {};

      const energyMax = statLimit('energy_max', 100);
      const hungerMax = statLimit('hunger_max', 100);
      const thirstMax = statLimit('thirst_max', 100);

      const startEnergy = numberOr(rules.start_energy, '-');
      const startHunger = numberOr(rules.start_hunger, '-');
      const startThirst = numberOr(rules.start_thirst, '-');

      const passiveEnergyLoss = numberOr(rules.passive_energy_loss, '-');
      const passiveHungerGain = numberOr(rules.passive_hunger_gain, '-');
      const passiveThirstGain = numberOr(rules.passive_thirst_gain, '-');

      const starvationPenalty = numberOr(rules.starvation_energy_penalty, '-');
      const dehydrationPenalty = numberOr(rules.dehydration_energy_penalty, '-');

      const restGain = numberOr(rules.rest_energy_gain, '-');
      const eatReduction = numberOr(rules.eat_hunger_reduction, '-');
      const drinkReduction = numberOr(rules.drink_thirst_reduction, '-');

      protocolPanel.innerHTML = `
        <div class="protocol-head">Protocol ${p.protocol_version || '-'}</div>
        <div class="protocol-grid">
          <div class="protocol-block">
            <strong>State Scale</strong>
            <div>Energy: 0..${energyMax}</div>
            <div>Hunger: 0..${hungerMax}</div>
            <div>Thirst: 0..${thirstMax}</div>
          </div>
          <div class="protocol-block">
            <strong>Start State</strong>
            <div>Energy ${startEnergy}/${energyMax}</div>
            <div>Hunger ${startHunger}/${hungerMax}</div>
            <div>Thirst ${startThirst}/${thirstMax}</div>
          </div>
          <div class="protocol-block">
            <strong>Passive / Turn</strong>
            <div>Energy ${formatSignedScore(-passiveEnergyLoss)}</div>
            <div>Hunger +${passiveHungerGain}</div>
            <div>Thirst +${passiveThirstGain}</div>
          </div>
          <div class="protocol-block">
            <strong>Critical Thresholds</strong>
            <div>hunger=${hungerMax}: ${formatSignedScore(-starvationPenalty)} energy</div>
            <div>thirst=${thirstMax}: ${formatSignedScore(-dehydrationPenalty)} energy</div>
            <div>death: energy <= 0</div>
          </div>
          <div class="protocol-block">
            <strong>Action Effects</strong>
            <div>rest: +${restGain} energy</div>
            <div>eat: -${eatReduction} hunger</div>
            <div>drink: -${drinkReduction} thirst</div>
            <div>gather: collect from tile</div>
          </div>
          <div class="protocol-block">
            <strong>Scoring</strong>
            <div>survive: ${formatSignedScore(scoring.survive_turn)}</div>
            <div>gather: ${formatSignedScore(scoring.gather_useful)}</div>
            <div>consume: ${formatSignedScore(scoring.consume_useful)}</div>
            <div>invalid: ${formatSignedScore(scoring.invalid_action)}</div>
            <div>death: ${formatSignedScore(scoring.death)}</div>
          </div>
        </div>
        <div class="protocol-note">
          Parser: ${p.parser_case_mode || '-'} | Invalid policy: ${p.invalid_action_policy || '-'}
        </div>
      `;
    }

    function toggleProtocolPanel() {
      if (!protocolPanel) return;
      const isOpen = protocolPanel.classList.toggle('open');
      const chip = document.getElementById('protocolChip');
      if (chip) chip.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }

    function escapeHtml(value) {
      return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    function compactModelName() {
      const raw = String(DATA.meta.model || DATA.meta.model_profile || 'agent').trim();
      if (!raw) return 'agent';
      const parts = raw.split('/');
      const tail = parts[parts.length - 1] || raw;
      return tail;
    }

    function inferInvalidReason(frame) {
      const validationError = frame.validation_result?.error || '';
      const requestedRaw = frame.action_result?.requested || frame.raw_model_output || '';
      const requested = String(requestedRaw).trim().toLowerCase();
      const obs = frame.observation || {};
      const inv = obs.inventory || {};
      const pos = obs.position || { x: 0, y: 0 };
      const visibleTiles = Array.isArray(obs.visible_tiles) ? obs.visible_tiles : [];

      if (validationError === 'empty_output') {
        return 'empty output (model returned nothing)';
      }
      if (validationError === 'multiple_lines_not_allowed') {
        return 'multiple lines are not allowed';
      }
      if (validationError !== 'not_in_allowed_actions') {
        return 'action is invalid for this turn';
      }

      if (requested === 'drink') {
        if (Number(inv.water ?? 0) <= 0) {
          const onWater = visibleTiles.some(t => Number(t.x) === Number(pos.x) && Number(t.y) === Number(pos.y) && t.type === 'water');
          return onWater
            ? 'no water in inventory (on water tile: gather first)'
            : 'no water in inventory (gather water first)';
        }
        if (Number(obs.thirst ?? 0) <= 0) {
          return 'thirst is already zero';
        }
      }

      if (requested === 'eat') {
        if (Number(inv.food ?? 0) <= 0) {
          return 'no food in inventory (gather food first)';
        }
        if (Number(obs.hunger ?? 0) <= 0) {
          return 'hunger is already zero';
        }
      }

      if (requested === 'gather') {
        const tileHere = visibleTiles.find(t => Number(t.x) === Number(pos.x) && Number(t.y) === Number(pos.y));
        const tileType = String(tileHere?.type || 'unknown');
        if (!['tree', 'rock', 'food', 'water'].includes(tileType)) {
          return `nothing to gather on tile (${tileType})`;
        }
      }

      if (requested === 'move north' && Number(pos.y) <= 0) return 'blocked by north boundary';
      if (requested === 'move west' && Number(pos.x) <= 0) return 'blocked by west boundary';
      if (requested === 'move south' && Number(pos.y) >= (worldHeight - 1)) return 'blocked by south boundary';
      if (requested === 'move east' && Number(pos.x) >= (worldWidth - 1)) return 'blocked by east boundary';

      return `not allowed this turn (${requested || '?'})`;
    }

    function renderOutcomeHero() {
      const s = DATA.summary || {};
      const meta = DATA.meta || {};
      const turnsPlayed = Number(s.turns_played ?? 0);
      const maxTurns = Number(s.max_turns ?? 0);
      const turnsSurvived = Number(s.turns_survived ?? 0);
      const endReason = String(s.end_reason || '');
      const isDead = endReason === 'agent_dead';

      const gathered = Number(s.resources_gathered ?? 0);
      const gatherableTotal = Number(DATA.world?.gatherable_total);
      const resourcesText = Number.isFinite(gatherableTotal) && gatherableTotal >= 0
        ? `${gathered}/${gatherableTotal}` : `${gathered}`;

      const deathCause = inferDeathCause(s);
      let whyText = s.end_reason_human || formatEndReason(s.end_reason, s.turns_played, s.max_turns);
      if (isDead && deathCause) whyText += ` ${deathCause}`;

      const badgeClass = isDead ? 'died' : 'survived';
      const badgeText = isDead
        ? `DIED T${turnsSurvived}`
        : (endReason === 'max_turns_reached' ? `SURVIVED ${maxTurns}T` : `OK (${endReason || '?'})`);

      const modelName = meta.model || meta.model_profile || '?';
      const scenario = meta.scenario || '?';

      const finalScore = Number(s.final_score ?? 0);
      const scoreClass = finalScore < 0 ? 'score-value score-negative' : 'score-value';

      outcomeHero.innerHTML = `
        <div class="outcome-header-row">
          <div class="outcome-identity">
            <span class="outcome-model">${escapeHtml(compactModelName())}</span>
            <span class="outcome-separator">//</span>
            <span class="outcome-scenario">${escapeHtml(scenario)}</span>
          </div>
          <div class="outcome-badge ${badgeClass}">${escapeHtml(badgeText)}</div>
        </div>
        <div class="outcome-metrics">
          <div class="outcome-metric">
            <div class="metric-value ${scoreClass}">${s.final_score ?? '-'}</div>
            <div class="metric-label">Final Score</div>
          </div>
          <div class="outcome-metric">
            <div class="metric-value">${turnsSurvived}<span style="color:var(--text-dim);font-size:0.7em">/${maxTurns || '?'}</span></div>
            <div class="metric-label">Turns Survived</div>
          </div>
          <div class="outcome-metric">
            <div class="metric-value">${resourcesText}</div>
            <div class="metric-label">Resources</div>
          </div>
          <div class="outcome-metric">
            <div class="metric-value">${s.invalid_actions ?? 0}</div>
            <div class="metric-label">Invalid</div>
          </div>
          <div class="outcome-metric">
            <div class="metric-value">${turnsPlayed}</div>
            <div class="metric-label">Turns Played</div>
          </div>
        </div>
        <div class="outcome-why">${escapeHtml(whyText)}</div>
      `;

      // Technical details chips
      const latencyTotal = formatDurationFromMs(s.latency_ms);
      const latencyAvg = turnsPlayed > 0 ? formatDurationFromMs(Number(s.latency_ms ?? 0) / turnsPlayed) : 'n/a';

      metaChips.innerHTML = [
        `<span class="chip"><span class="chip-key">provider</span> <span class="chip-value">${escapeHtml(meta.provider_id || '-')}</span></span>`,
        `<span class="chip"><span class="chip-key">profile</span> <span class="chip-value">${escapeHtml(meta.model_profile || '-')}</span></span>`,
        `<span class="chip chip-model"><span class="chip-key">model</span> <span class="chip-value">${escapeHtml(meta.model || '-')}</span></span>`,
        `<span class="chip"><span class="chip-key">seed</span> <span class="chip-value">${escapeHtml(meta.seed ?? '-')}</span></span>`,
        `<span class="chip"><span class="chip-key">scenario</span> <span class="chip-value">${escapeHtml(meta.scenario || '-')}</span></span>`,
        `<button class="chip chip-btn" id="protocolChip" type="button" aria-expanded="false" title="Show protocol rules"><span class="chip-key">protocol</span> ${meta.protocol_version || '-'}</button>`,
        `<span class="chip"><span class="chip-key">bench</span> <span class="chip-value">${escapeHtml(meta.bench_version || '-')}</span></span>`,
        `<span class="chip"><span class="chip-key">engine</span> <span class="chip-value">${escapeHtml(meta.engine_version || '-')}</span></span>`,
        `<span class="chip"><span class="chip-key">prompt</span> <span class="chip-value">${escapeHtml(shortHash(meta.prompt_set_sha256, 16))}</span></span>`,
        `<span class="chip"><span class="chip-key">latency</span> <span class="chip-value">${latencyTotal}</span></span>`,
        `<span class="chip"><span class="chip-key">avg</span> <span class="chip-value">${latencyAvg}</span></span>`,
        `<span class="chip"><span class="chip-key">tokens</span> <span class="chip-value">${formatCount(s.tokens_used)}</span></span>`,
        `<span class="chip"><span class="chip-key">cost</span> <span class="chip-value">${formatEstimatedCost(s.estimated_cost)}</span></span>`,
      ].join('');

      const protocolChip = document.getElementById('protocolChip');
      if (protocolChip) {
        protocolChip.addEventListener('click', () => { toggleProtocolPanel(); });
      }

      sourceLog.textContent = meta.source_log_path || '-';
      coverageHint.textContent = meta.map_coverage === 'full'
        ? 'full map (engine snapshot)'
        : 'partial (fog of war)';

      const modelTag = compactModelName();
      document.getElementById('mapLegend').textContent =
        `agent: ${modelTag} | \\u{1F332} tree \\u{1FAA8} rock \\u{1F34E} food \\u{1F4A7} water`;
    }

    function renderTimeline() {
      const importantOnly = document.getElementById('showImportantOnly')?.checked;

      timelineBody.innerHTML = frames.map((frame, idx) => {
        const action = frame.action_result?.applied || frame.action_result?.requested || '-';
        const isValid = frame.validation_result?.is_valid;
        const valid = isValid ? '\\u2713' : '\\u2717';
        const delta = frame.score_delta?.total ?? 0;
        const obs = frame.observation || {};

        const isInvalid = !isValid;
        const isCritical = delta <= -5 || idx === frames.length - 1;
        const isImportant = isInvalid || isCritical || delta >= 3;

        if (importantOnly && !isImportant) return '';

        const classes = [
          idx === currentTurnIndex ? 'active' : '',
          isInvalid ? 'turn-invalid' : '',
          isCritical ? 'turn-critical' : '',
        ].filter(Boolean).join(' ');

        return `
          <tr data-idx="${idx}" class="${classes}">
            <td>${frame.turn}</td>
            <td>${action}</td>
            <td>${valid}</td>
            <td>${delta}</td>
            <td>${frame.cumulative_score ?? '-'}</td>
            <td>${obs.energy ?? '-'}</td>
            <td>${obs.hunger ?? '-'}</td>
            <td>${obs.thirst ?? '-'}</td>
          </tr>
        `;
      }).join('');

      for (const row of timelineBody.querySelectorAll('tr')) {
        row.addEventListener('click', () => {
          const idx = Number(row.getAttribute('data-idx') || '0');
          setTurn(idx);
        });
      }
    }

    function keepTimelineSelectionVisible() {
      const activeRow = timelineBody.querySelector('tr.active');
      if (!activeRow) return;
      const wrap = activeRow.closest('.table-wrap');
      if (!wrap) return;

      const rowTop = activeRow.offsetTop;
      const rowBottom = rowTop + activeRow.offsetHeight;
      const viewTop = wrap.scrollTop;
      const viewBottom = viewTop + wrap.clientHeight;

      if (rowTop < viewTop) {
        wrap.scrollTop = Math.max(0, rowTop - 6);
      } else if (rowBottom > viewBottom) {
        wrap.scrollTop = rowBottom - wrap.clientHeight + 6;
      }
    }

    function renderMap(frame) {
      const map = frame.map_snapshot || [];
      const afterPos = frame.agent_position_after || { x: 0, y: 0 };
      const pathSet = new Set((frame.path_prefix || []).map(p => `${p.x},${p.y}`));
      const modelTag = compactModelName();
      const modelTagEscaped = escapeHtml(modelTag);

      mapGrid.style.gridTemplateColumns = `repeat(${worldWidth}, minmax(42px, 1fr))`;
      mapGrid.innerHTML = '';

      for (let y = 0; y < worldHeight; y += 1) {
        for (let x = 0; x < worldWidth; x += 1) {
          const type = (map[y] && map[y][x]) || 'unknown';
          const meta = tileMeta[type] || tileMeta.unknown;
          const isAgent = afterPos.x === x && afterPos.y === y;
          const isPath = pathSet.has(`${x},${y}`);

          const tile = document.createElement('div');
          tile.className = `tile ${type} ${isAgent ? 'agent' : ''} ${isPath ? 'path' : ''}`;
          tile.innerHTML = `
            <span class="tile-type">${meta.label}</span>
            <span class="tile-emoji">${meta.emoji}</span>
            <span class="coord">${x},${y}</span>
            ${isAgent ? `<span class="agent-mark">\\u{1F916} <span class="name">${modelTagEscaped}</span></span>` : ''}
          `;
          tile.title = `${meta.label} @ (${x},${y})`;
          mapGrid.appendChild(tile);
        }
      }
    }

    function renderTurnDetails(frame) {
      const obs = frame.observation || {};
      const inv = obs.inventory || {};
      const actionApplied = frame.action_result?.applied || frame.action_result?.requested || '-';
      const valid = frame.validation_result?.is_valid;
      const validTag = valid ? '<span class="tag-ok">valid</span>' : '<span class="tag-bad">invalid</span>';
      const baseMessage = frame.action_result?.message || '-';
      const message = valid ? baseMessage : inferInvalidReason(frame);
      const actionDisplay = escapeHtml(actionApplied);
      const messageDisplay = escapeHtml(message);

      const deltaTotal = frame.score_delta?.total ?? 0;
      const deltaClass = deltaTotal < 0 ? 'delta-negative' : (deltaTotal > 0 ? 'delta-positive' : '');

      actionLine.innerHTML = `
        <div class="action-row">
          <strong style="font-family:var(--font-mono);font-size:0.85rem">T${frame.turn}</strong>
          ${validTag}
          <code class="cmd-action">${actionDisplay}</code>
        </div>
        <div style="color:var(--text-dim);font-size:0.78rem;font-family:var(--font-mono)">${messageDisplay}</div>
        <div class="action-row">
          <span class="score-delta ${deltaClass}">${frame.cumulative_score ?? '-'} (${formatSignedScore(deltaTotal)})</span>
        </div>
      `;

      const energy = Number(obs.energy ?? 0);
      const hunger = Number(obs.hunger ?? 0);
      const thirst = Number(obs.thirst ?? 0);
      const energyMax = statLimit('energy_max', 100);
      const hungerMax = statLimit('hunger_max', 100);
      const thirstMax = statLimit('thirst_max', 100);

      stateMeters.innerHTML = [
        { label: 'Energy', value: energy, max: energyMax, cls: energyMeterClass(energy, energyMax) },
        { label: 'Hunger', value: hunger, max: hungerMax, cls: meterClass(hunger, hungerMax) },
        { label: 'Thirst', value: thirst, max: thirstMax, cls: meterClass(thirst, thirstMax) },
      ].map(({ label, value, max, cls }) => {
        const pct = max > 0 ? Math.max(0, Math.min(100, (Number(value) / Number(max)) * 100)) : 0;
        return `
        <div class="${cls}">
          <div>${label} <strong>${value}/${max}</strong></div>
          <div class="bar"><div class="fill" style="width:${pct}%"></div></div>
        </div>
      `}).join('');

      inventoryGrid.innerHTML = Object.entries(inventoryMeta).map(([key, label]) => {
        return `<div class="pill"><span>${label}</span><strong>${inv[key] ?? 0}</strong></div>`;
      }).join('');

      rawOutput.textContent = frame.raw_model_output || '(empty)';
      const events = frame.score_delta?.events || [];
      const latency = frame.metrics?.latency_ms;
      const tokens = frame.metrics?.tokens_used;
      const cost = frame.metrics?.estimated_cost;

      scoreEvents.textContent = [
        `delta: ${formatSignedScore(deltaTotal)}`,
        `events: ${events.length ? events.map(formatScoreEvent).join(', ') : 'none'}`,
        `latency: ${formatDurationFromMs(latency)}`,
        `tokens: ${formatCount(tokens)}`,
        `cost: ${formatEstimatedCost(cost)}`,
      ].join('\\n');
    }

    function setTurn(index) {
      currentTurnIndex = clampTurnIndex(index);
      const frame = frames[currentTurnIndex];
      if (!frame) return;

      turnSlider.value = String(currentTurnIndex + 1);
      turnMeta.textContent = `${currentTurnIndex + 1}/${frames.length}`;

      renderMap(frame);
      renderTurnDetails(frame);
      renderTimeline();
      keepTimelineSelectionVisible();
    }

    function togglePlay() {
      if (autoPlayTimer) {
        clearInterval(autoPlayTimer);
        autoPlayTimer = null;
        playBtn.innerHTML = '&#9654; Play';
        return;
      }

      playBtn.innerHTML = '&#9646;&#9646; Pause';
      autoPlayTimer = setInterval(() => {
        if (currentTurnIndex >= frames.length - 1) {
          togglePlay();
          return;
        }
        setTurn(currentTurnIndex + 1);
      }, 650);
    }

    function init() {
      renderProtocolPanel();
      renderOutcomeHero();

      document.getElementById('techToggle').addEventListener('click', () => {
        const body = document.getElementById('techBody');
        const arrow = document.getElementById('techArrow');
        const isOpen = body.classList.toggle('open');
        arrow.innerHTML = isOpen ? '&#9660;' : '&#9654;';
      });

      turnSlider.min = '1';
      turnSlider.max = String(Math.max(1, frames.length));
      turnSlider.value = '1';

      turnSlider.addEventListener('input', () => {
        setTurn(Number(turnSlider.value) - 1);
      });

      prevBtn.addEventListener('click', () => {
        setTurn(currentTurnIndex - 1);
      });

      playBtn.addEventListener('click', () => {
        togglePlay();
      });

      const nextBtn = document.createElement('button');
      nextBtn.className = 'btn';
      nextBtn.id = 'nextBtn';
      nextBtn.innerHTML = 'Next &#9654;';
      prevBtn.parentElement.insertBefore(nextBtn, turnSlider);
      nextBtn.addEventListener('click', () => {
        setTurn(currentTurnIndex + 1);
      });

      const importantToggle = document.getElementById('showImportantOnly');
      if (importantToggle) {
        importantToggle.addEventListener('change', () => renderTimeline());
      }

      if (!frames.length) {
        turnMeta.textContent = 'no turns';
        actionLine.innerHTML = '<span class="tag-bad">empty run</span>';
        return;
      }

      setTurn(0);
    }

    init();
  </script>
</body>
</html>
"""

    return html_head + html_data + html_tail


def generate_viewer(log_path: Path, output_path: Path, title: str | None = None) -> Path:
    with log_path.open("r", encoding="utf-8") as handle:
        run_log = json.load(handle)

    payload = build_viewer_payload(run_log=run_log, source_log_path=log_path)
    page_title = title or f"TinyWorld Viewer - {log_path.name}"
    html_doc = render_html(payload=payload, page_title=page_title)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_doc, encoding="utf-8")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate HTML dashboard from a TinyWorld run log")
    parser.add_argument("--log", type=str, required=True, help="Path to run JSON log")
    parser.add_argument("--output", type=str, default=None, help="Output HTML path")
    parser.add_argument("--title", type=str, default=None, help="Optional page title")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    log_path = Path(args.log)
    if not log_path.exists():
        raise SystemExit(f"Log file not found: {log_path}")

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = log_path.with_suffix(".html")

    result = generate_viewer(log_path=log_path, output_path=output_path, title=args.title)
    print(f"Viewer generated: {result}")


if __name__ == "__main__":
    main()
