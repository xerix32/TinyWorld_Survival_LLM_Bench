"""Generate a multi-run/multi-model interactive HTML dashboard from compare artifacts."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def render_html(payload: dict[str, Any], page_title: str) -> str:
    safe_title = html.escape(page_title)
    payload_json = json.dumps(payload, ensure_ascii=False)
    payload_json = payload_json.replace("</", "<\\/")

    html_head = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
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
      --warn: #b96b00;
      --shadow: 0 10px 30px rgba(16, 42, 51, 0.10);
      --radius: 14px;
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
      line-height: 1.35;
      min-height: 100vh;
    }

    .wrap {
      max-width: 1560px;
      margin: 0 auto;
      padding: 20px;
      display: grid;
      gap: 14px;
    }

    .hero {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 14px 16px;
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

    .hero p {
      margin: 0;
      color: var(--muted);
    }

    .chip-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 4px;
    }

    .chip {
      border: 1px solid var(--line);
      background: #f7faf8;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 0.82rem;
      color: var(--ink);
      white-space: nowrap;
    }

    .grid {
      display: grid;
      grid-template-columns: 1.2fr 1.45fr 2.35fr;
      gap: 14px;
      align-items: start;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 12px;
      display: grid;
      gap: 10px;
    }

    .panel h2 {
      margin: 0;
      font-size: 1.02rem;
      color: var(--accent);
      letter-spacing: 0.2px;
      text-transform: uppercase;
    }

    .table-wrap {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fcfffd;
      max-height: 320px;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.92rem;
    }

    th, td {
      padding: 8px 9px;
      border-bottom: 1px solid #e7efec;
      text-align: left;
      white-space: nowrap;
    }

    th {
      position: sticky;
      top: 0;
      background: #edf4f2;
      z-index: 2;
    }

    tbody tr.selected-row {
      background: rgba(15, 118, 110, 0.10);
      outline: 1px solid rgba(15, 118, 110, 0.28);
      outline-offset: -1px;
    }

    .run-browser-controls {
      display: grid;
      grid-template-columns: repeat(3, minmax(110px, 1fr));
      gap: 8px;
    }

    .field {
      display: grid;
      gap: 4px;
      font-size: 0.82rem;
      color: var(--muted);
    }

    select {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 7px 8px;
      background: #fcfffd;
      font: inherit;
      color: var(--ink);
    }

    .run-nav {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    button {
      border: 1px solid #b9ccc8;
      background: #f2f8f6;
      color: #1f2928;
      border-radius: 11px;
      padding: 8px 11px;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
    }

    button:hover {
      background: #e6f2ef;
    }

    .run-count {
      color: var(--muted);
      font-size: 0.86rem;
    }

    .run-list {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fcfffd;
      max-height: 500px;
      overflow: auto;
      padding: 6px;
      display: grid;
      gap: 6px;
    }

    .run-group {
      font-weight: 700;
      font-size: 0.82rem;
      color: #24524b;
      margin-top: 2px;
      padding-left: 3px;
    }

    .run-item {
      border: 1px solid #d7e4e0;
      border-radius: 9px;
      padding: 8px;
      background: #ffffff;
      cursor: pointer;
      display: grid;
      gap: 2px;
    }

    .run-item:hover {
      border-color: #8db5ad;
      background: #f7fcfa;
    }

    .run-item.active {
      border-color: var(--accent);
      background: #edf8f4;
      box-shadow: inset 0 0 0 1px rgba(15, 118, 110, 0.18);
    }

    .run-title {
      font-size: 0.89rem;
      font-weight: 700;
      display: flex;
      justify-content: space-between;
      gap: 8px;
    }

    .run-sub {
      color: var(--muted);
      font-size: 0.82rem;
    }

    .badge {
      font-size: 0.74rem;
      border-radius: 999px;
      padding: 2px 8px;
      border: 1px solid transparent;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-weight: 700;
    }

    .badge.ok {
      color: #0f5132;
      background: #dcfce7;
      border-color: #86efac;
    }

    .badge.bad {
      color: #7f1d1d;
      background: #fee2e2;
      border-color: #fca5a5;
    }

    .badge.warn {
      color: #7a4700;
      background: #fff3cf;
      border-color: #f4d07b;
    }

    .replay-header {
      display: grid;
      gap: 6px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #f8fcfb;
      padding: 10px;
    }

    .replay-title {
      font-weight: 700;
      font-size: 1rem;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }

    .summary-cards {
      display: grid;
      grid-template-columns: repeat(3, minmax(120px, 1fr));
      gap: 8px;
    }

    .card {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #ffffff;
      padding: 8px;
      display: grid;
      gap: 3px;
    }

    .card .label {
      color: var(--muted);
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.2px;
    }

    .card .value {
      font-weight: 800;
      font-size: 1rem;
    }

    .turn-controls {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #f8fcfb;
      padding: 8px;
    }

    .turn-controls input[type=range] {
      flex: 1;
      min-width: 180px;
    }

    .turn-meta {
      color: var(--muted);
      font-size: 0.9rem;
      white-space: nowrap;
    }

    .replay-grid {
      display: grid;
      grid-template-columns: 1.6fr 1.2fr;
      gap: 10px;
      align-items: start;
    }

    .map-board {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #f8fcfb;
      padding: 8px;
      display: grid;
      gap: 8px;
    }

    .map-grid {
      display: grid;
      gap: 6px;
    }

    .tile {
      border: 1px solid #d7e4e0;
      border-radius: 8px;
      min-height: 66px;
      padding: 4px;
      background: #ffffff;
      display: grid;
      align-content: space-between;
      gap: 3px;
      position: relative;
      overflow: hidden;
    }

    .tile.empty { background: #f9fbfc; }
    .tile.tree { background: #f2fbf4; }
    .tile.rock { background: #f2f4f5; }
    .tile.food { background: #fff6ed; }
    .tile.water { background: #eef7ff; }
    .tile.unknown { background: #f3f3f3; color: #7a7a7a; }

    .tile.visited::after {
      content: '';
      position: absolute;
      inset: 3px;
      border: 1px dashed rgba(15, 118, 110, 0.45);
      border-radius: 6px;
      pointer-events: none;
    }

    .tile.current {
      box-shadow: inset 0 0 0 2px rgba(194, 65, 12, 0.60);
    }

    .coord {
      position: absolute;
      top: 3px;
      right: 5px;
      color: #576563;
      font-size: 0.72rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      opacity: 0.9;
    }

    .tile-main {
      font-size: 1.36rem;
      text-align: center;
      line-height: 1;
      margin-top: 13px;
    }

    .agent-mark {
      position: absolute;
      bottom: 4px;
      left: 5px;
      display: inline-flex;
      align-items: center;
      gap: 3px;
      border: 1px solid rgba(15, 118, 110, 0.55);
      border-radius: 999px;
      padding: 1px 6px;
      background: rgba(237, 248, 244, 0.96);
      color: #0f5f58;
      font-size: 0.68rem;
      font-weight: 700;
      max-width: calc(100% - 12px);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .map-legend {
      color: var(--muted);
      font-size: 0.82rem;
    }

    .detail-panel {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #f8fcfb;
      padding: 8px;
      display: grid;
      gap: 8px;
    }

    .label {
      color: var(--muted);
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.2px;
    }

    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }

    .code-block {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 8px;
      min-height: 34px;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }

    .meter-grid {
      display: grid;
      gap: 7px;
    }

    .meter {
      display: grid;
      gap: 3px;
    }

    .meter-head {
      display: flex;
      justify-content: space-between;
      font-size: 0.82rem;
    }

    .meter-bar {
      width: 100%;
      height: 11px;
      border-radius: 999px;
      background: #dce9e5;
      overflow: hidden;
    }

    .meter-fill {
      height: 100%;
      background: #18956d;
    }

    .meter.warn .meter-fill { background: #b96b00; }
    .meter.bad .meter-fill { background: #b42318; }

    .inv-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(90px, 1fr));
      gap: 6px;
    }

    .inv-item {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 6px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
    }

    .timeline-wrap {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fcfffd;
      overflow: auto;
      max-height: 260px;
    }

    .muted { color: var(--muted); }

    .empty-state {
      border: 1px dashed #c9d7d3;
      border-radius: 10px;
      padding: 12px;
      background: #fafdfe;
      color: var(--muted);
    }

    @media (max-width: 1320px) {
      .grid {
        grid-template-columns: 1fr;
      }
      .replay-grid {
        grid-template-columns: 1fr;
      }
      .summary-cards {
        grid-template-columns: repeat(2, minmax(120px, 1fr));
      }
      .run-browser-controls {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <section class=\"hero\">
      <h1>🧭 TinyWorld Compare Dashboard</h1>
      <p>Paired-seed model comparison with drill-down replay for each run.</p>
      <div class=\"chip-row\" id=\"metaChips\"></div>
    </section>

    <div class=\"grid\">
      <section class=\"panel\">
        <h2>🏁 Model Ranking</h2>
        <div class=\"table-wrap\">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Model profile</th>
                <th>Avg score</th>
                <th>Avg survive</th>
                <th>Invalid avg</th>
                <th>Death rate</th>
              </tr>
            </thead>
            <tbody id=\"rankingBody\"></tbody>
          </table>
        </div>

        <h2>⚖️ Head-to-Head</h2>
        <div class=\"table-wrap\">
          <table>
            <thead>
              <tr>
                <th>Pair</th>
                <th>Paired runs</th>
                <th>Win rate A</th>
                <th>Avg Δ(A-B)</th>
                <th>W/L/T</th>
              </tr>
            </thead>
            <tbody id=\"h2hBody\"></tbody>
          </table>
        </div>
      </section>

      <section class=\"panel\">
        <h2>📚 Run Browser</h2>
        <div class=\"run-browser-controls\">
          <label class=\"field\">Model filter<select id=\"modelFilter\"></select></label>
          <label class=\"field\">Seed filter<select id=\"seedFilter\"></select></label>
          <label class=\"field\">Status filter<select id=\"statusFilter\"></select></label>
        </div>

        <div class=\"run-nav\">
          <button type=\"button\" id=\"prevRunBtn\">◀ Prev run</button>
          <button type=\"button\" id=\"nextRunBtn\">Next run ▶</button>
          <div class=\"run-count\" id=\"runCount\"></div>
        </div>

        <div class=\"run-list\" id=\"runList\"></div>
      </section>

      <section class=\"panel\">
        <h2>🎮 Selected Run Replay</h2>

        <div class=\"replay-header\" id=\"replayHeader\"></div>

        <div class=\"turn-controls\">
          <button type=\"button\" id=\"prevTurnBtn\">◀ Prev turn</button>
          <button type=\"button\" id=\"playTurnBtn\">▶ Play</button>
          <button type=\"button\" id=\"nextTurnBtn\">Next turn ▶</button>
          <input id=\"turnSlider\" type=\"range\" min=\"1\" max=\"1\" value=\"1\" />
          <div class=\"turn-meta\" id=\"turnMeta\"></div>
        </div>

        <div class=\"replay-grid\">
          <div class=\"map-board\">
            <div class=\"map-grid\" id=\"mapGrid\"></div>
            <div class=\"map-legend\" id=\"mapLegend\"></div>
          </div>

          <div class=\"detail-panel\">
            <div>
              <div class=\"label\">Turn Details</div>
              <div id=\"turnStatus\"></div>
            </div>

            <div>
              <div class=\"label\">State</div>
              <div class=\"meter-grid\" id=\"stateMeters\"></div>
            </div>

            <div>
              <div class=\"label\">Inventory</div>
              <div class=\"inv-grid\" id=\"inventoryGrid\"></div>
            </div>

            <div>
              <div class=\"label\">Raw model output</div>
              <div class=\"code-block\" id=\"rawOutput\"></div>
            </div>

            <div>
              <div class=\"label\">Score events</div>
              <div class=\"code-block\" id=\"scoreEvents\"></div>
            </div>
          </div>
        </div>

        <div>
          <h2>📜 Turn Timeline</h2>
          <div class=\"timeline-wrap\">
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
              <tbody id=\"timelineBody\"></tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  </div>
"""

    html_data = '<script id="compareData" type="application/json">' + payload_json + "</script>"

    html_tail = """
  <script>
    const DATA = JSON.parse(document.getElementById('compareData').textContent || '{}');

    const tileMeta = {
      empty: { emoji: '▫️', label: 'empty' },
      tree: { emoji: '🌲', label: 'tree' },
      rock: { emoji: '🪨', label: 'rock' },
      food: { emoji: '🍎', label: 'food' },
      water: { emoji: '💧', label: 'water' },
      unknown: { emoji: '◻️', label: 'unknown' },
    };

    const inventoryMeta = {
      wood: '🪵 wood',
      stone: '🧱 stone',
      food: '🍎 food',
      water: '💧 water',
    };

    const metaChips = document.getElementById('metaChips');
    const rankingBody = document.getElementById('rankingBody');
    const h2hBody = document.getElementById('h2hBody');

    const modelFilter = document.getElementById('modelFilter');
    const seedFilter = document.getElementById('seedFilter');
    const statusFilter = document.getElementById('statusFilter');

    const prevRunBtn = document.getElementById('prevRunBtn');
    const nextRunBtn = document.getElementById('nextRunBtn');
    const runCount = document.getElementById('runCount');
    const runList = document.getElementById('runList');

    const replayHeader = document.getElementById('replayHeader');
    const prevTurnBtn = document.getElementById('prevTurnBtn');
    const playTurnBtn = document.getElementById('playTurnBtn');
    const nextTurnBtn = document.getElementById('nextTurnBtn');
    const turnSlider = document.getElementById('turnSlider');
    const turnMeta = document.getElementById('turnMeta');

    const mapGrid = document.getElementById('mapGrid');
    const mapLegend = document.getElementById('mapLegend');

    const turnStatus = document.getElementById('turnStatus');
    const stateMeters = document.getElementById('stateMeters');
    const inventoryGrid = document.getElementById('inventoryGrid');
    const rawOutput = document.getElementById('rawOutput');
    const scoreEvents = document.getElementById('scoreEvents');
    const timelineBody = document.getElementById('timelineBody');

    const models = Array.isArray(DATA.models) ? DATA.models : [];
    const pairwise = Array.isArray(DATA.pairwise) ? DATA.pairwise : [];
    const runs = Array.isArray(DATA.runs) ? DATA.runs : [];
    const meta = DATA.meta || {};

    let selectedRunIndex = 0;
    let filteredRunIndexes = [];
    let currentTurnIndex = 0;
    let autoPlayTimer = null;

    function numberOr(value, fallback) {
      const num = Number(value);
      return Number.isFinite(num) ? num : fallback;
    }

    function formatCount(value, fallback = 'not available') {
      if (value === null || value === undefined || value === '') return fallback;
      const num = Number(value);
      if (!Number.isFinite(num)) return fallback;
      return Math.round(num).toLocaleString('en-US');
    }

    function formatFloat(value, digits = 2, fallback = 'not available') {
      if (value === null || value === undefined || value === '') return fallback;
      const num = Number(value);
      if (!Number.isFinite(num)) return fallback;
      return num.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
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

    function formatSignedScore(value) {
      const num = Number(value ?? 0);
      if (!Number.isFinite(num)) return '0';
      return `${num > 0 ? '+' : ''}${num}`;
    }

    function shortProfile(value) {
      const text = String(value || 'model');
      return text.length <= 16 ? text : `${text.slice(0, 16)}…`;
    }

    function getRunStatus(summary) {
      const endReason = String(summary?.end_reason || '');
      if (endReason === 'agent_dead') {
        return { key: 'dead', label: 'Agent died', className: 'bad' };
      }
      return { key: 'finished', label: 'Reached limit', className: 'ok' };
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

    function meterClass(metricName, value, maxValue) {
      const max = Math.max(1, numberOr(maxValue, 100));
      const current = Math.max(0, numberOr(value, 0));
      const pct = (current / max) * 100;

      if (metricName === 'energy') {
        if (pct <= 30) return 'meter bad';
        if (pct <= 50) return 'meter warn';
        return 'meter';
      }

      if (pct >= 80) return 'meter bad';
      if (pct >= 60) return 'meter warn';
      return 'meter';
    }

    function renderMetaChips() {
      const chips = [];
      chips.push(`Protocol: ${meta.protocol_version || '-'}`);
      chips.push(`Bench/Engine: ${meta.bench_version || '-'} / ${meta.engine_version || '-'}`);
      chips.push(`Scenario: ${meta.scenario || '-'}`);
      chips.push(`Models: ${formatCount(meta.models?.length || models.length)}`);
      chips.push(`Runs/model: ${formatCount(meta.runs_per_model)}`);
      chips.push(`Total runs: ${formatCount(meta.total_runs || runs.length)}`);
      chips.push(`Seeds: ${(meta.seed_list || []).join(', ') || '-'}`);
      chips.push(`Prompt hash: ${String(meta.prompt_set_sha256 || '-').slice(0, 12)}`);
      chips.push('Fairness: paired seeds (same seeds per model)');
      metaChips.innerHTML = chips.map((item) => `<span class=\"chip\">${item}</span>`).join('');
    }

    function renderRanking() {
      if (!models.length) {
        rankingBody.innerHTML = '<tr><td colspan="6" class="muted">No model stats available.</td></tr>';
        return;
      }

      rankingBody.innerHTML = models.map((row) => {
        return `
          <tr>
            <td>${formatCount(row.rank)}</td>
            <td>${row.model_profile}</td>
            <td>${formatFloat(row.avg_final_score, 2)}</td>
            <td>${formatFloat(row.avg_turns_survived, 2)} / ${formatCount(row.max_turns_avg || 0)}</td>
            <td>${formatFloat(row.avg_invalid_actions, 2)}</td>
            <td>${formatFloat(row.death_rate_pct, 1)}%</td>
          </tr>
        `;
      }).join('');
    }

    function renderPairwise() {
      if (!pairwise.length) {
        h2hBody.innerHTML = '<tr><td colspan="5" class="muted">Need at least two models for head-to-head.</td></tr>';
        return;
      }

      h2hBody.innerHTML = pairwise.map((row) => {
        const wr = row.win_rate_a_vs_b === null || row.win_rate_a_vs_b === undefined
          ? 'not available'
          : `${formatFloat(row.win_rate_a_vs_b, 1)}%`;
        const delta = row.avg_delta_a_minus_b === null || row.avg_delta_a_minus_b === undefined
          ? 'not available'
          : `${Number(row.avg_delta_a_minus_b) >= 0 ? '+' : ''}${formatFloat(row.avg_delta_a_minus_b, 2)}`;

        return `
          <tr>
            <td>${row.model_a_profile} vs ${row.model_b_profile}</td>
            <td>${formatCount(row.paired_runs)}</td>
            <td>${wr}</td>
            <td>${delta}</td>
            <td>${formatCount(row.wins_a)}/${formatCount(row.wins_b)}/${formatCount(row.ties)}</td>
          </tr>
        `;
      }).join('');
    }

    function initFilters() {
      const modelOptions = ['all', ...new Set(runs.map((run) => String(run.model_profile || ''))).values()];
      const seedOptions = ['all', ...new Set(runs.map((run) => String(run.seed))).values()];

      modelFilter.innerHTML = modelOptions.map((value) => `<option value=\"${value}\">${value === 'all' ? 'All models' : value}</option>`).join('');
      seedFilter.innerHTML = seedOptions.map((value) => `<option value=\"${value}\">${value === 'all' ? 'All seeds' : `Seed ${value}`}</option>`).join('');
      statusFilter.innerHTML = [
        '<option value="all">All statuses</option>',
        '<option value="dead">Agent died</option>',
        '<option value="finished">Reached turn limit</option>',
      ].join('');
    }

    function rebuildFilteredRuns() {
      const modelValue = modelFilter.value || 'all';
      const seedValue = seedFilter.value || 'all';
      const statusValue = statusFilter.value || 'all';

      filteredRunIndexes = [];
      runs.forEach((run, idx) => {
        const summary = run.summary || {};
        const status = getRunStatus(summary).key;

        if (modelValue !== 'all' && String(run.model_profile) !== modelValue) return;
        if (seedValue !== 'all' && String(run.seed) !== seedValue) return;
        if (statusValue !== 'all' && status !== statusValue) return;
        filteredRunIndexes.push(idx);
      });

      if (!filteredRunIndexes.length) {
        selectedRunIndex = 0;
      } else if (!filteredRunIndexes.includes(selectedRunIndex)) {
        selectedRunIndex = filteredRunIndexes[0];
      }
    }

    function renderRunList() {
      if (!filteredRunIndexes.length) {
        runList.innerHTML = '<div class="empty-state">No runs match the current filters.</div>';
        runCount.textContent = '0 runs';
        renderReplayEmpty();
        return;
      }

      runCount.textContent = `${filteredRunIndexes.length} run(s) shown`;

      let lastModel = null;
      const chunks = [];
      filteredRunIndexes.forEach((idx) => {
        const run = runs[idx];
        const summary = run.summary || {};
        const status = getRunStatus(summary);
        const survived = Number(summary.turns_survived || 0);
        const maxTurns = Number(summary.max_turns || 0);

        if (lastModel !== run.model_profile) {
          chunks.push(`<div class="run-group">${run.model_profile}</div>`);
          lastModel = run.model_profile;
        }

        chunks.push(`
          <div class="run-item ${idx === selectedRunIndex ? 'active' : ''}" data-run-index="${idx}">
            <div class="run-title">
              <span>Seed ${run.seed} · score ${formatCount(summary.final_score)}</span>
              <span class="badge ${status.className}">${status.label}</span>
            </div>
            <div class="run-sub">${survived}/${maxTurns} turns survived · invalid ${formatCount(summary.invalid_actions)}</div>
            <div class="run-sub mono">${run.model}</div>
          </div>
        `);
      });

      runList.innerHTML = chunks.join('');
      runList.querySelectorAll('.run-item').forEach((node) => {
        node.addEventListener('click', () => {
          const nextIndex = Number(node.getAttribute('data-run-index'));
          if (!Number.isFinite(nextIndex)) return;
          selectedRunIndex = nextIndex;
          currentTurnIndex = 0;
          stopAutoPlay();
          renderRunList();
          renderReplay();
        });
      });

      const active = runList.querySelector('.run-item.active');
      if (active) {
        active.scrollIntoView({ block: 'nearest' });
      }
    }

    function selectedRun() {
      if (!runs.length) return null;
      if (filteredRunIndexes.length) {
        if (!filteredRunIndexes.includes(selectedRunIndex)) selectedRunIndex = filteredRunIndexes[0];
      } else {
        selectedRunIndex = 0;
      }
      return runs[selectedRunIndex] || null;
    }

    function clampTurnIndex(index, frameCount) {
      if (frameCount <= 0) return 0;
      return Math.max(0, Math.min(frameCount - 1, index));
    }

    function replayRules(run) {
      const rules = run?.replay?.protocol?.rules || {};
      return {
        energyMax: Math.max(1, numberOr(rules.energy_max, 100)),
        hungerMax: Math.max(1, numberOr(rules.hunger_max, 100)),
        thirstMax: Math.max(1, numberOr(rules.thirst_max, 100)),
      };
    }

    function renderReplayHeader(run) {
      const summary = run.summary || {};
      const status = getRunStatus(summary);
      const deathCause = String(summary.death_cause_human || '').trim();
      const gatherableTotal = numberOr(run.replay?.world?.gatherable_total, null);
      const gathered = numberOr(summary.resources_gathered, 0);
      const gatheredLabel = gatherableTotal === null
        ? formatCount(gathered)
        : `${formatCount(gathered)}/${formatCount(gatherableTotal)}`;

      const cards = [
        { label: 'Final score', value: `${formatCount(summary.final_score)} points` },
        { label: 'Survival', value: `${formatCount(summary.turns_survived)}/${formatCount(summary.max_turns)} turns` },
        { label: 'Invalid actions', value: formatCount(summary.invalid_actions) },
        { label: 'Resources gathered', value: gatheredLabel },
        { label: 'Model latency', value: formatDurationFromMs(summary.latency_ms) },
        { label: 'Tokens used', value: formatCount(summary.tokens_used) },
      ];

      replayHeader.innerHTML = `
        <div class="replay-title">
          <span>${run.model_profile} · seed ${run.seed}</span>
          <span class="badge ${status.className}">${status.label}</span>
        </div>
        <div class="muted">${summary.end_reason_human || '-'}</div>
        ${deathCause ? `<div class="muted">Cause: ${deathCause}</div>` : ''}
        <div class="summary-cards">
          ${cards.map((card) => `<div class="card"><div class="label">${card.label}</div><div class="value">${card.value}</div></div>`).join('')}
        </div>
      `;
    }

    function renderMap(run, frame) {
      const world = run.replay?.world || {};
      const width = Math.max(1, numberOr(world.width, 1));
      const height = Math.max(1, numberOr(world.height, 1));
      const map = frame.map_snapshot || [];
      const agent = frame.agent_position_after || frame.agent_position_before || { x: 0, y: 0 };

      const visited = new Set(
        (frame.path_prefix || []).map((pos) => `${numberOr(pos.x, 0)},${numberOr(pos.y, 0)}`)
      );

      mapGrid.style.gridTemplateColumns = `repeat(${width}, minmax(64px, 1fr))`;

      const cells = [];
      for (let y = 0; y < height; y += 1) {
        for (let x = 0; x < width; x += 1) {
          const type = String(map?.[y]?.[x] || 'unknown');
          const metaEntry = tileMeta[type] || tileMeta.unknown;

          const isCurrent = numberOr(agent.x, -1) === x && numberOr(agent.y, -1) === y;
          const isVisited = visited.has(`${x},${y}`);

          const classes = ['tile', type];
          if (isVisited) classes.push('visited');
          if (isCurrent) classes.push('current');

          cells.push(`
            <div class="${classes.join(' ')}">
              <div class="coord">${x},${y}</div>
              <div class="tile-main">${metaEntry.emoji}</div>
              ${isCurrent ? `<div class="agent-mark">🤖 ${shortProfile(run.model_profile)}</div>` : ''}
            </div>
          `);
        }
      }

      mapGrid.innerHTML = cells.join('');
      const coverage = String(run.replay?.meta?.map_coverage || 'partial');
      mapLegend.textContent = coverage === 'full'
        ? 'Legend: 🤖 current agent, dashed = visited path, map coverage full from engine snapshot.'
        : 'Legend: 🤖 current agent, dashed = visited path, unknown tiles may still be hidden.';
    }

    function renderTurnDetails(run, frame) {
      const summary = run.summary || {};
      const rules = replayRules(run);

      const observation = frame.observation || {};
      const validation = frame.validation_result || {};
      const actionResult = frame.action_result || {};
      const scoreDelta = frame.score_delta || {};
      const metrics = frame.metrics || {};
      const inventory = observation.inventory || {};

      const isValid = Boolean(validation.is_valid);
      const resultMessage = !isValid
        ? `Invalid command: ${validation.error || 'not allowed this turn'}`
        : (actionResult.message || (actionResult.success ? 'Action applied.' : 'No effect.'));

      const badgeClass = isValid ? 'ok' : 'bad';
      const badgeLabel = isValid ? 'VALID' : 'INVALID';

      turnStatus.innerHTML = `
        <div class="replay-title">
          <span class="badge ${badgeClass}">${badgeLabel}</span>
          <span>Turn ${formatCount(frame.turn)} · Action: <span class="mono">${actionResult.requested || '-'}</span></span>
        </div>
        <div class="muted">Result: ${resultMessage}</div>
        <div class="muted">Score total: ${formatCount(frame.cumulative_score)} · Δ this turn: ${formatSignedScore(scoreDelta.total || 0)}</div>
      `;

      const meters = [
        { key: 'energy', icon: '⚡', value: numberOr(observation.energy, 0), max: rules.energyMax },
        { key: 'hunger', icon: '🍽️', value: numberOr(observation.hunger, 0), max: rules.hungerMax },
        { key: 'thirst', icon: '🥤', value: numberOr(observation.thirst, 0), max: rules.thirstMax },
      ];

      stateMeters.innerHTML = meters.map((item) => {
        const pct = Math.max(0, Math.min(100, (item.value / item.max) * 100));
        return `
          <div class="${meterClass(item.key, item.value, item.max)}">
            <div class="meter-head"><span>${item.icon} ${item.key}</span><span>${formatCount(item.value)}/${formatCount(item.max)}</span></div>
            <div class="meter-bar"><div class="meter-fill" style="width:${pct.toFixed(2)}%"></div></div>
          </div>
        `;
      }).join('');

      inventoryGrid.innerHTML = Object.entries(inventoryMeta).map(([key, label]) => {
        return `<div class="inv-item"><span>${label}</span><strong>${formatCount(inventory[key] || 0)}</strong></div>`;
      }).join('');

      rawOutput.textContent = String(frame.raw_model_output || '-').trim() || '-';

      const eventLines = [
        `score delta total: ${formatSignedScore(scoreDelta.total || 0)}`,
        `score events: ${(scoreDelta.events || []).map(formatScoreEvent).join(', ') || '-'}`,
        `model latency: ${formatDurationFromMs(metrics.latency_ms)}`,
        `tokens used: ${formatCount(metrics.tokens_used)}`,
        `estimated cost: ${formatFloat(metrics.estimated_cost, 6, 'not available')}`,
      ];
      scoreEvents.textContent = eventLines.join('\\n');

      const frames = run.replay?.frames || [];
      timelineBody.innerHTML = frames.map((item, idx) => {
        const obs = item.observation || {};
        const valid = Boolean(item.validation_result?.is_valid);
        const rowClass = idx === currentTurnIndex ? 'selected-row' : '';
        return `
          <tr class="${rowClass}" data-turn-index="${idx}">
            <td>${formatCount(item.turn)}</td>
            <td class="mono">${item.action_result?.requested || '-'}</td>
            <td>${valid ? 'yes' : 'no'}</td>
            <td>${formatSignedScore(item.score_delta?.total || 0)}</td>
            <td>${formatCount(item.cumulative_score)}</td>
            <td>${formatCount(obs.energy)}</td>
            <td>${formatCount(obs.hunger)}</td>
            <td>${formatCount(obs.thirst)}</td>
          </tr>
        `;
      }).join('');

      timelineBody.querySelectorAll('tr').forEach((row) => {
        row.addEventListener('click', () => {
          const index = Number(row.getAttribute('data-turn-index'));
          if (!Number.isFinite(index)) return;
          currentTurnIndex = index;
          renderReplay();
        });
      });

      const selected = timelineBody.querySelector('tr.selected-row');
      if (selected) {
        selected.scrollIntoView({ block: 'nearest' });
      }

      const frameCount = frames.length;
      const turnDisplay = frameCount ? `${currentTurnIndex + 1}/${frameCount}` : '0/0';
      turnMeta.textContent = `Turn ${turnDisplay}`;
    }

    function renderReplayEmpty() {
      replayHeader.innerHTML = '<div class="empty-state">Select a run to inspect replay details.</div>';
      mapGrid.innerHTML = '';
      mapLegend.textContent = '';
      turnStatus.innerHTML = '<div class="empty-state">No turn details available.</div>';
      stateMeters.innerHTML = '';
      inventoryGrid.innerHTML = '';
      rawOutput.textContent = '-';
      scoreEvents.textContent = '-';
      timelineBody.innerHTML = '';
      turnMeta.textContent = 'Turn 0/0';
      turnSlider.min = '1';
      turnSlider.max = '1';
      turnSlider.value = '1';
    }

    function renderReplay() {
      const run = selectedRun();
      if (!run) {
        renderReplayEmpty();
        return;
      }

      const frames = run.replay?.frames || [];
      if (!frames.length) {
        renderReplayHeader(run);
        renderReplayEmpty();
        return;
      }

      currentTurnIndex = clampTurnIndex(currentTurnIndex, frames.length);
      const frame = frames[currentTurnIndex];

      turnSlider.min = '1';
      turnSlider.max = String(frames.length);
      turnSlider.value = String(currentTurnIndex + 1);

      renderReplayHeader(run);
      renderMap(run, frame);
      renderTurnDetails(run, frame);
      renderRunList();
    }

    function stopAutoPlay() {
      if (autoPlayTimer !== null) {
        window.clearInterval(autoPlayTimer);
        autoPlayTimer = null;
      }
      playTurnBtn.textContent = '▶ Play';
    }

    function toggleAutoPlay() {
      const run = selectedRun();
      const frames = run?.replay?.frames || [];
      if (frames.length <= 1) return;

      if (autoPlayTimer !== null) {
        stopAutoPlay();
        return;
      }

      playTurnBtn.textContent = '⏸ Pause';
      autoPlayTimer = window.setInterval(() => {
        if (currentTurnIndex >= frames.length - 1) {
          stopAutoPlay();
          return;
        }
        currentTurnIndex += 1;
        renderReplay();
      }, 850);
    }

    function moveRun(offset) {
      if (!filteredRunIndexes.length) return;
      const currentPos = filteredRunIndexes.indexOf(selectedRunIndex);
      const base = currentPos >= 0 ? currentPos : 0;
      const nextPos = Math.max(0, Math.min(filteredRunIndexes.length - 1, base + offset));
      selectedRunIndex = filteredRunIndexes[nextPos];
      currentTurnIndex = 0;
      stopAutoPlay();
      renderRunList();
      renderReplay();
    }

    function moveTurn(offset) {
      const run = selectedRun();
      const frames = run?.replay?.frames || [];
      if (!frames.length) return;
      currentTurnIndex = clampTurnIndex(currentTurnIndex + offset, frames.length);
      stopAutoPlay();
      renderReplay();
    }

    function bindEvents() {
      [modelFilter, seedFilter, statusFilter].forEach((node) => {
        node.addEventListener('change', () => {
          stopAutoPlay();
          rebuildFilteredRuns();
          currentTurnIndex = 0;
          renderRunList();
          renderReplay();
        });
      });

      prevRunBtn.addEventListener('click', () => moveRun(-1));
      nextRunBtn.addEventListener('click', () => moveRun(1));

      prevTurnBtn.addEventListener('click', () => moveTurn(-1));
      nextTurnBtn.addEventListener('click', () => moveTurn(1));
      playTurnBtn.addEventListener('click', () => toggleAutoPlay());

      turnSlider.addEventListener('input', () => {
        const run = selectedRun();
        const frames = run?.replay?.frames || [];
        if (!frames.length) return;
        currentTurnIndex = clampTurnIndex(Number(turnSlider.value) - 1, frames.length);
        stopAutoPlay();
        renderReplay();
      });

      document.addEventListener('keydown', (event) => {
        const tag = String(event.target?.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

        if (event.key === 'ArrowLeft') {
          event.preventDefault();
          moveRun(-1);
          return;
        }

        if (event.key === 'ArrowRight') {
          event.preventDefault();
          moveRun(1);
          return;
        }

        if (event.key === 'ArrowUp') {
          event.preventDefault();
          moveTurn(-1);
          return;
        }

        if (event.key === 'ArrowDown') {
          event.preventDefault();
          moveTurn(1);
        }
      });
    }

    function boot() {
      renderMetaChips();
      renderRanking();
      renderPairwise();
      initFilters();
      rebuildFilteredRuns();
      renderRunList();
      renderReplay();
      bindEvents();
    }

    boot();
  </script>
</body>
</html>
"""

    return html_head + html_data + html_tail


def generate_compare_viewer(compare_path: Path, output_path: Path, title: str | None = None) -> Path:
    with compare_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    page_title = title or "TinyWorld Compare Dashboard"
    html_doc = render_html(payload=payload, page_title=page_title)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_doc, encoding="utf-8")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate HTML compare dashboard from TinyWorld compare JSON")
    parser.add_argument("--compare", type=str, required=True, help="Path to compare JSON artifact")
    parser.add_argument("--output", type=str, default=None, help="Output HTML path")
    parser.add_argument("--title", type=str, default=None, help="Optional page title")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    compare_path = Path(args.compare)
    if not compare_path.is_absolute():
        compare_path = (Path.cwd() / compare_path).resolve()

    if args.output is None:
        output_path = compare_path.with_name(compare_path.stem + "_dashboard.html")
    else:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = (Path.cwd() / output_path).resolve()

    generated = generate_compare_viewer(compare_path=compare_path, output_path=output_path, title=args.title)
    print(f"Compare dashboard generated: {generated}")


if __name__ == "__main__":
    main()
