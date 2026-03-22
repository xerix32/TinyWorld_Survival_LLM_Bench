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
    :root {
      --bg-a: #f5f1e8;
      --bg-b: #dbe7e4;
      --panel: #fffdf8;
      --ink: #1f2928;
      --muted: #576563;
      --line: #ccd8d5;
      --accent: #0f766e;
      --accent-2: #c2410c;
      --ok: #1f8f5f;
      --bad: #b42318;
      --shadow: 0 10px 30px rgba(16, 42, 51, 0.10);
      --radius: 16px;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 15% 10%, rgba(15, 118, 110, 0.08), transparent 35%),
        radial-gradient(circle at 80% 20%, rgba(194, 65, 12, 0.08), transparent 32%),
        repeating-linear-gradient(
          90deg,
          rgba(35, 73, 70, 0.03),
          rgba(35, 73, 70, 0.03) 1px,
          transparent 1px,
          transparent 24px
        ),
        linear-gradient(180deg, var(--bg-a), var(--bg-b));
      font-family: "Avenir Next", "Trebuchet MS", "Gill Sans", sans-serif;
      line-height: 1.4;
      min-height: 100vh;
    }

    .wrap {
      max-width: 1280px;
      margin: 0 auto;
      padding: 20px;
      display: grid;
      gap: 16px;
    }

    .hero {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 16px 18px;
      box-shadow: var(--shadow);
      display: grid;
      gap: 6px;
    }

    .hero h1 {
      margin: 0;
      font-size: 1.35rem;
      font-weight: 700;
      letter-spacing: 0.2px;
    }

    .hero h1 .title-version {
      font-size: 0.92rem;
      color: #0f766e;
      font-weight: 800;
      margin-left: 8px;
      letter-spacing: 0.02em;
    }

    .hero p {
      margin: 0;
      color: var(--muted);
    }

    .chip-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 6px;
    }

    .chip {
      border: 1px solid var(--line);
      background: #f7faf8;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 0.84rem;
      color: var(--ink);
      white-space: nowrap;
    }

    .chip .chip-key {
      color: #596865;
      font-weight: 700;
      margin-right: 4px;
    }

    .chip .chip-value {
      color: #22302e;
      font-weight: 700;
    }

    .chip.chip-model .chip-value {
      color: #0f766e;
      font-weight: 800;
    }

    .chip-btn {
      cursor: pointer;
      font: inherit;
    }

    .chip-btn:hover {
      background: #edf7f4;
      border-color: #bdd6d1;
    }

    .protocol-panel {
      display: none;
      gap: 10px;
      margin-top: 8px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #f6fbf9;
      padding: 10px 12px;
    }

    .protocol-panel.open {
      display: grid;
    }

    .protocol-head {
      font-size: 0.9rem;
      font-weight: 700;
      color: #0e5f58;
    }

    .protocol-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(220px, 1fr));
      gap: 10px;
    }

    .protocol-block {
      border: 1px solid #d8e7e2;
      border-radius: 10px;
      background: #ffffff;
      padding: 8px 10px;
      font-size: 0.84rem;
      color: #31403e;
      display: grid;
      gap: 3px;
    }

    .protocol-block strong {
      color: #0f766e;
      font-size: 0.78rem;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }

    .protocol-note {
      color: #425957;
      font-size: 0.82rem;
    }

    .cards {
      display: grid;
      grid-template-columns: repeat(6, minmax(120px, 1fr));
      gap: 12px;
    }

    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 10px 12px;
      box-shadow: var(--shadow);
      animation: rise 0.24s ease both;
    }

    .card .label {
      font-size: 0.75rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }

    .card .value {
      margin-top: 4px;
      font-size: 1.18rem;
      font-weight: 700;
    }

    .card .value.value-compact {
      font-size: 1.00rem;
      line-height: 1.25;
    }

    .card .value.status-ok { color: var(--ok); }
    .card .value.status-bad { color: var(--bad); }
    .card .value.status-neutral { color: #a16207; }

    .layout {
      display: grid;
      grid-template-columns: 1.35fr 1fr;
      gap: 14px;
      align-items: start;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 14px;
      display: grid;
      gap: 12px;
    }

    .panel h2 {
      margin: 0;
      font-size: 1rem;
      letter-spacing: 0.02em;
      text-transform: uppercase;
      color: var(--accent);
    }

    .control-bar {
      display: grid;
      grid-template-columns: auto auto auto 1fr auto;
      gap: 8px;
      align-items: center;
    }

    .btn {
      border: 1px solid var(--line);
      background: #ffffff;
      color: var(--ink);
      border-radius: 10px;
      padding: 6px 10px;
      font-size: 0.86rem;
      cursor: pointer;
      transition: transform 0.12s ease, background 0.2s ease;
    }

    .btn:hover { transform: translateY(-1px); background: #f1f6f4; }

    input[type='range'] { width: 100%; accent-color: var(--accent); }

    .turn-meta {
      font-family: "JetBrains Mono", "Fira Code", "Cascadia Code", monospace;
      font-size: 0.86rem;
      color: var(--muted);
    }

    .map {
      display: grid;
      gap: 6px;
      background: #f2f7f5;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px;
    }

    .tile {
      position: relative;
      border: 1px solid #d7e3df;
      border-radius: 8px;
      min-height: 52px;
      display: grid;
      place-items: center;
      font-size: 1.12rem;
      background: #ffffff;
      transition: transform 0.15s ease;
      overflow: hidden;
    }

    .tile.path::after {
      content: "";
      position: absolute;
      inset: 3px;
      border: 1px dashed rgba(15, 118, 110, 0.45);
      border-radius: 6px;
      pointer-events: none;
    }

    .tile.agent {
      transform: scale(1.03);
      box-shadow: inset 0 0 0 2px rgba(194, 65, 12, 0.65);
    }

    .tile.unknown { background: #e6ecea; color: #7b8d89; }
    .tile.empty { background: #f8fbfa; }
    .tile.tree { background: #eef9ef; }
    .tile.rock { background: #eff3f6; }
    .tile.food { background: #fff5ec; }
    .tile.water { background: #eaf8ff; }

    .coord {
      position: absolute;
      top: 3px;
      right: 5px;
      font-size: 0.62rem;
      color: #6d7d7a;
      font-family: "JetBrains Mono", "Fira Code", monospace;
    }

    .agent-mark {
      position: absolute;
      left: 3px;
      right: 3px;
      bottom: 2px;
      display: flex;
      align-items: center;
      gap: 3px;
      font-size: 0.62rem;
      line-height: 1;
      padding: 1px 4px;
      border-radius: 6px;
      border: 1px solid rgba(15, 118, 110, 0.25);
      background: rgba(255, 255, 255, 0.82);
      color: #144a45;
      pointer-events: none;
    }

    .agent-mark .name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-family: "JetBrains Mono", "Fira Code", monospace;
      font-size: 0.54rem;
    }

    .state-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
    }

    .meter {
      display: grid;
      gap: 5px;
      font-size: 0.82rem;
      color: var(--muted);
    }

    .meter .bar {
      width: 100%;
      height: 8px;
      border-radius: 999px;
      background: #e4ecea;
      overflow: hidden;
    }

    .meter .fill {
      height: 100%;
      background: linear-gradient(90deg, var(--accent), #2da49a);
    }

    .meter.warn .fill {
      background: linear-gradient(90deg, #d97706, #f59e0b);
    }

    .meter.bad .fill {
      background: linear-gradient(90deg, #b42318, #ef4444);
    }

    .inventory {
      display: grid;
      grid-template-columns: repeat(2, minmax(100px, 1fr));
      gap: 8px;
    }

    .pill {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 6px 8px;
      font-size: 0.86rem;
      display: flex;
      justify-content: space-between;
      background: #f9fcfb;
    }

    .action-line {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    .tag-ok,
    .tag-bad {
      border-radius: 999px;
      font-size: 0.75rem;
      padding: 3px 8px;
      color: white;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    .tag-ok { background: var(--ok); }
    .tag-bad { background: var(--bad); }

    .cmd-action {
      color: #0f766e;
      font-weight: 800;
      background: #ecf8f5;
      border: 1px solid #c7e2db;
      border-radius: 6px;
      padding: 1px 6px;
    }

    .mono {
      font-family: "JetBrains Mono", "Fira Code", "Cascadia Code", monospace;
      font-size: 0.85rem;
      background: #f3f7f6;
      border: 1px solid #dde8e4;
      border-radius: 8px;
      padding: 8px;
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .mono.raw-command {
      color: #0f5f58;
      font-weight: 800;
      background: #ecf8f5;
      border-color: #c7e2db;
    }

    .timeline {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 12px;
      overflow: hidden;
    }

    .timeline h2 {
      margin: 0 0 10px 0;
      font-size: 1rem;
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.02em;
    }

    .table-wrap {
      max-height: 300px;
      overflow: auto;
      border: 1px solid #dfe8e5;
      border-radius: 10px;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
    }

    thead {
      position: sticky;
      top: 0;
      background: #eef4f2;
      z-index: 1;
    }

    th, td {
      text-align: left;
      padding: 7px 8px;
      border-bottom: 1px solid #e6eeeb;
      font-family: "JetBrains Mono", "Fira Code", monospace;
      white-space: nowrap;
    }

    tr.active { background: #e9f7f4; }
    tr:hover { background: #f5fbf9; cursor: pointer; }

    .footer {
      color: var(--muted);
      font-size: 0.82rem;
      display: flex;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 6px;
    }

    @keyframes rise {
      from { transform: translateY(6px); opacity: 0; }
      to { transform: translateY(0); opacity: 1; }
    }

    @media (max-width: 980px) {
      .cards { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
      .layout { grid-template-columns: 1fr; }
      .state-grid { grid-template-columns: 1fr; }
      .control-bar { grid-template-columns: 1fr 1fr; }
      .protocol-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1 id="dashboardTitle">🧭 TinyWorld Run Dashboard</h1>
      <p>Readable replay of one benchmark run: what the agent did, where it moved, and why the score changed.</p>
      <div class="chip-row" id="metaChips"></div>
      <div class="protocol-panel" id="protocolPanel"></div>
    </section>

    <section class="cards" id="summaryCards"></section>

    <section class="layout">
      <article class="panel">
        <h2>Map + Turn Player</h2>
        <div class="control-bar">
          <button class="btn" id="prevBtn">◀ Prev</button>
          <button class="btn" id="playBtn">▶ Play</button>
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
          <strong>Inventory</strong>
          <div class="inventory" id="inventoryGrid"></div>
        </div>
        <div>
          <strong>Raw model output</strong>
          <div class="mono raw-command" id="rawOutput"></div>
        </div>
        <div>
          <strong>Score events</strong>
          <div class="mono" id="scoreEvents"></div>
        </div>
      </article>
    </section>

    <section class="timeline">
      <h2>📜 Turn Timeline (click any row)</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Turn</th>
              <th>Action</th>
              <th>Valid</th>
              <th>Δ Score</th>
              <th>Total Score</th>
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
      <span>Made for humans first, benchmarks second.</span>
    </div>
  </div>
"""

    html_data = '<script id="viewerData" type="application/json">' + payload_json + "</script>"

    html_tail = """
  <script>
    const DATA = JSON.parse(document.getElementById('viewerData').textContent);

    const tileMeta = {
      unknown: { emoji: '◼️', label: 'unknown' },
      empty: { emoji: '▫️', label: 'empty' },
      tree: { emoji: '🌲', label: 'tree' },
      rock: { emoji: '🪨', label: 'rock' },
      food: { emoji: '🍎', label: 'food' },
      water: { emoji: '💧', label: 'water' },
    };

    const inventoryMeta = {
      wood: '🪵 wood',
      stone: '🧱 stone',
      food: '🍎 food',
      water: '💧 water',
    };

    let currentTurnIndex = 0;
    let autoPlayTimer = null;

    const summaryCards = document.getElementById('summaryCards');
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
    const dashboardTitle = document.getElementById('dashboardTitle');

    const prevBtn = document.getElementById('prevBtn');
    const playBtn = document.getElementById('playBtn');

    const frames = DATA.frames || [];
    const worldWidth = DATA.world.width;
    const worldHeight = DATA.world.height;

    function card(label, value, valueClass = '') {
      const cls = String(valueClass || '').trim();
      const clsAttr = cls ? ` ${cls}` : '';
      return `<div class="card"><div class="label">${label}</div><div class="value${clsAttr}">${value}</div></div>`;
    }

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

    function formatCount(value, fallback = 'not available') {
      if (value === null || value === undefined || value === '') return fallback;
      const num = Number(value);
      if (!Number.isFinite(num)) return fallback;
      return Math.round(num).toLocaleString('en-US');
    }

    function formatEstimatedCost(value) {
      if (value === null || value === undefined || value === '') return 'not available';
      const num = Number(value);
      if (!Number.isFinite(num)) return 'not available';
      return num.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 6 });
    }

    function formatDurationFromMs(valueMs) {
      if (valueMs === null || valueMs === undefined || valueMs === '') return 'not available';
      const ms = Number(valueMs);
      if (!Number.isFinite(ms)) return 'not available';

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
      if (reason === 'agent_dead') return `The agent died on turn ${turns}.`;
      if (reason === 'max_turns_reached') return `Reached the configured turn limit (${max}).`;
      if (!reason) return 'Run ended.';
      return `Run ended with status: ${reason}.`;
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
      return 'Energy was depleted to zero.';
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
        <div class="protocol-head">Protocol ${p.protocol_version || '-'} rules (v0.1 quick guide)</div>
        <div class="protocol-grid">
          <div class="protocol-block">
            <strong>State Scale</strong>
            <div>Energy: 0..${energyMax}</div>
            <div>Hunger: 0..${hungerMax}</div>
            <div>Thirst: 0..${thirstMax}</div>
            <div>Viewer meters are shown as current/max.</div>
          </div>
          <div class="protocol-block">
            <strong>Start State</strong>
            <div>Energy starts at ${startEnergy}/${energyMax}</div>
            <div>Hunger starts at ${startHunger}/${hungerMax}</div>
            <div>Thirst starts at ${startThirst}/${thirstMax}</div>
          </div>
          <div class="protocol-block">
            <strong>Passive Every Turn</strong>
            <div>Energy ${formatSignedScore(-passiveEnergyLoss)}</div>
            <div>Hunger +${passiveHungerGain}</div>
            <div>Thirst +${passiveThirstGain}</div>
            <div>This happens every turn, even with no enemies.</div>
          </div>
          <div class="protocol-block">
            <strong>Critical Thresholds</strong>
            <div>If hunger reaches ${hungerMax}: extra ${formatSignedScore(-starvationPenalty)} energy</div>
            <div>If thirst reaches ${thirstMax}: extra ${formatSignedScore(-dehydrationPenalty)} energy</div>
            <div>Death condition: energy ≤ 0.</div>
          </div>
          <div class="protocol-block">
            <strong>Action Effects</strong>
            <div>rest: +${restGain} energy (capped by max)</div>
            <div>eat: -${eatReduction} hunger (requires food in inventory)</div>
            <div>drink: -${drinkReduction} thirst (requires water in inventory)</div>
            <div>gather: collect resource from current tile into inventory</div>
          </div>
          <div class="protocol-block">
            <strong>Scoring + Validation</strong>
            <div>survive turn: ${formatSignedScore(scoring.survive_turn)}</div>
            <div>useful gather: ${formatSignedScore(scoring.gather_useful)}</div>
            <div>useful eat/drink: ${formatSignedScore(scoring.consume_useful)}</div>
            <div>invalid action: ${formatSignedScore(scoring.invalid_action)} (turn still consumed: ${p.invalid_action_policy || '-'})</div>
            <div>death: ${formatSignedScore(scoring.death)}</div>
          </div>
        </div>
        <div class="protocol-note">
          Parser mode: ${p.parser_case_mode || '-'}.
          Action validity is checked only against that turn's <code>allowed_actions</code>.
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
            ? 'no water in inventory (you are on water tile: use gather first)'
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
          return `nothing to gather on current tile (${tileType})`;
        }
      }

      if (requested === 'move north' && Number(pos.y) <= 0) return 'move blocked by north boundary';
      if (requested === 'move west' && Number(pos.x) <= 0) return 'move blocked by west boundary';
      if (requested === 'move south' && Number(pos.y) >= (worldHeight - 1)) return 'move blocked by south boundary';
      if (requested === 'move east' && Number(pos.x) >= (worldWidth - 1)) return 'move blocked by east boundary';

      return `action not allowed this turn (${requested || 'unknown action'})`;
    }

    function renderSummary() {
      const s = DATA.summary || {};
      const latencyTotal = formatDurationFromMs(s.latency_ms);
      const turnsPlayed = Number(s.turns_played ?? 0);
      const latencyAvg = turnsPlayed > 0 ? formatDurationFromMs(Number(s.latency_ms ?? 0) / turnsPlayed) : 'not available';
      const tokensUsed = formatCount(s.tokens_used);
      const estimatedCost = formatEstimatedCost(s.estimated_cost);
      const maxTurns = Number(s.max_turns ?? 0);
      const turnsSurvived = Number(s.turns_survived ?? 0);
      const turnsSurvivedText = maxTurns > 0
        ? `${turnsSurvived}/${maxTurns} (${((turnsSurvived / maxTurns) * 100).toFixed(1)}%)`
        : `${turnsSurvived}`;

      const gathered = Number(s.resources_gathered ?? 0);
      const gatherableTotal = Number(DATA.world?.gatherable_total);
      const resourcesText = Number.isFinite(gatherableTotal) && gatherableTotal >= 0
        ? `${gathered}/${gatherableTotal}`
        : `${gathered}`;

      const deathCause = inferDeathCause(s);
      let runStatus = s.end_reason_human || formatEndReason(s.end_reason, s.turns_played, s.max_turns);
      if (String(s.end_reason || '') === 'agent_dead' && deathCause) {
        runStatus = `${runStatus} Cause: ${deathCause}`;
      }
      const runStatusClass = String(s.end_reason || '') === 'agent_dead'
        ? 'status-bad value-compact'
        : (String(s.end_reason || '') === 'max_turns_reached' ? 'status-ok value-compact' : 'status-neutral value-compact');
      summaryCards.innerHTML = [
        card('Final Score', s.final_score ?? '-'),
        card('Turns Survived', turnsSurvivedText),
        card('Turns Played', s.turns_played ?? '-'),
        card('Invalid Actions', s.invalid_actions ?? '-'),
        card('Resources Gathered', resourcesText),
        card('Run Status', runStatus, runStatusClass),
        card('Model Latency Total', latencyTotal),
        card('Model Latency Avg', latencyAvg),
        card('Tokens Used', tokensUsed),
        card('Estimated Cost', estimatedCost),
      ].join('');

      const viewerVersion = String(DATA.meta.bench_version || DATA.meta.engine_version || '-').trim();
      if (dashboardTitle) {
        dashboardTitle.innerHTML = `🧭 TinyWorld Run Dashboard <span class="title-version">v${escapeHtml(viewerVersion)}</span>`;
      }

      metaChips.innerHTML = [
        `<span class="chip chip-model"><span class="chip-key">Model:</span><span class="chip-value">${escapeHtml(DATA.meta.model || '-')}</span></span>`,
        `<span class="chip"><span class="chip-key">Profile:</span><span class="chip-value">${escapeHtml(DATA.meta.model_profile || '-')}</span></span>`,
        `<span class="chip"><span class="chip-key">Provider:</span><span class="chip-value">${escapeHtml(DATA.meta.provider_id || '-')}</span></span>`,
        `<span class="chip"><span class="chip-key">Seed:</span><span class="chip-value">${escapeHtml(DATA.meta.seed ?? '-')}</span></span>`,
        `<span class="chip"><span class="chip-key">Scenario:</span><span class="chip-value">${escapeHtml(DATA.meta.scenario || '-')}</span></span>`,
        `<button class="chip chip-btn" id="protocolChip" type="button" aria-expanded="false" title="Show protocol rules">Protocol: ${DATA.meta.protocol_version || '-'} (click)</button>`,
        `<span class="chip"><span class="chip-key">Bench:</span><span class="chip-value">${escapeHtml(DATA.meta.bench_version || '-')}</span></span>`,
        `<span class="chip"><span class="chip-key">Engine:</span><span class="chip-value">${escapeHtml(DATA.meta.engine_version || '-')}</span></span>`,
        `<span class="chip"><span class="chip-key">Prompt set:</span><span class="chip-value">${escapeHtml(shortHash(DATA.meta.prompt_set_sha256, 16))}</span></span>`,
      ].join('');

      const protocolChip = document.getElementById('protocolChip');
      if (protocolChip) {
        protocolChip.addEventListener('click', () => {
          toggleProtocolPanel();
        });
      }

      sourceLog.textContent = `Source log: ${DATA.meta.source_log_path || '-'}`;
      coverageHint.textContent = DATA.meta.map_coverage === 'full'
        ? 'Map coverage: full (from engine snapshot)'
        : 'Map coverage: partial (unknown tiles = not yet observed)';

      const modelTag = compactModelName();
      document.getElementById('mapLegend').textContent =
        `Legend: 🤖 ${modelTag} (current agent), 👣 visited path, 🌲 tree, 🪨 rock, 🍎 food, 💧 water`;
    }

    function renderTimeline() {
      timelineBody.innerHTML = frames.map((frame, idx) => {
        const action = frame.action_result?.applied || frame.action_result?.requested || '-';
        const valid = frame.validation_result?.is_valid ? 'yes' : 'no';
        const delta = frame.score_delta?.total ?? 0;
        const obs = frame.observation || {};
        const rowClass = idx === currentTurnIndex ? 'active' : '';
        return `
          <tr data-idx="${idx}" class="${rowClass}">
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
            <span>${meta.emoji}</span>
            <span class="coord">${x},${y}</span>
            ${isAgent ? `<span class="agent-mark">🤖 <span class="name">${modelTagEscaped}</span></span>` : ''}
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

      actionLine.innerHTML = `
        ${validTag}
        <strong>Turn ${frame.turn}</strong>
        <span>Action: <code class="cmd-action">${actionDisplay}</code></span>
        <span>Result: ${messageDisplay}</span>
        <span>Score total: ${frame.cumulative_score ?? '-'}</span>
      `;

      const energy = Number(obs.energy ?? 0);
      const hunger = Number(obs.hunger ?? 0);
      const thirst = Number(obs.thirst ?? 0);
      const energyMax = statLimit('energy_max', 100);
      const hungerMax = statLimit('hunger_max', 100);
      const thirstMax = statLimit('thirst_max', 100);

      stateMeters.innerHTML = [
        { label: '⚡ Energy', value: energy, max: energyMax, cls: energyMeterClass(energy, energyMax) },
        { label: '🍽️ Hunger', value: hunger, max: hungerMax, cls: meterClass(hunger, hungerMax) },
        { label: '🥤 Thirst', value: thirst, max: thirstMax, cls: meterClass(thirst, thirstMax) },
      ].map(({ label, value, max, cls }) => {
        const pct = max > 0 ? Math.max(0, Math.min(100, (Number(value) / Number(max)) * 100)) : 0;
        return `
        <div class="${cls}">
          <div>${label}: <strong>${value}/${max}</strong></div>
          <div class="bar"><div class="fill" style="width:${pct}%"></div></div>
        </div>
      `}).join('');

      inventoryGrid.innerHTML = Object.entries(inventoryMeta).map(([key, label]) => {
        return `<div class="pill"><span>${label}</span><strong>${inv[key] ?? 0}</strong></div>`;
      }).join('');

      rawOutput.textContent = frame.raw_model_output || '(empty)';
      const events = frame.score_delta?.events || [];
      const deltaTotal = frame.score_delta?.total ?? 0;
      const latency = frame.metrics?.latency_ms;
      const tokens = frame.metrics?.tokens_used;
      const cost = frame.metrics?.estimated_cost;

      scoreEvents.textContent = [
        `Score delta total: ${formatSignedScore(deltaTotal)} points`,
        `Score events: ${events.length ? events.map(formatScoreEvent).join(', ') : 'none'}`,
        `Model latency: ${formatDurationFromMs(latency)}`,
        `Tokens used: ${formatCount(tokens)}`,
        `Estimated cost: ${formatEstimatedCost(cost)}`,
      ].join('\\n');
    }

    function setTurn(index) {
      currentTurnIndex = clampTurnIndex(index);
      const frame = frames[currentTurnIndex];
      if (!frame) return;

      turnSlider.value = String(currentTurnIndex + 1);
      turnMeta.textContent = `turn ${currentTurnIndex + 1}/${frames.length}`;

      renderMap(frame);
      renderTurnDetails(frame);
      renderTimeline();
      keepTimelineSelectionVisible();
    }

    function togglePlay() {
      if (autoPlayTimer) {
        clearInterval(autoPlayTimer);
        autoPlayTimer = null;
        playBtn.textContent = '▶ Play';
        return;
      }

      playBtn.textContent = '⏸ Pause';
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
      renderSummary();

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
      nextBtn.textContent = 'Next ▶';
      prevBtn.parentElement.insertBefore(nextBtn, turnSlider);
      nextBtn.addEventListener('click', () => {
        setTurn(currentTurnIndex + 1);
      });

      if (!frames.length) {
        turnMeta.textContent = 'no turns in this log';
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
        output_path = Path("artifacts/replays") / (log_path.stem + "_dashboard.html")

    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    if not log_path.is_absolute():
        log_path = Path.cwd() / log_path

    result_path = generate_viewer(log_path=log_path, output_path=output_path, title=args.title)
    print(f"Viewer generated: {result_path}")


if __name__ == "__main__":
    main()
