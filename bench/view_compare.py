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
      max-width: 1400px;
      margin: 0 auto;
      padding: 16px 20px;
      display: grid;
      gap: 12px;
    }

    /* ── HEADER ── */
    .page-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }

    .page-title {
      font-family: var(--font-mono);
      font-size: 0.88rem;
      font-weight: 700;
      color: var(--text-dim);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .page-title span {
      color: var(--accent);
    }

    /* ── PODIUM CARDS ── */
    .podium-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
    }

    .podium-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px 20px;
      display: grid;
      gap: 12px;
      transition: border-color 0.15s;
    }

    .podium-card.first {
      border-color: var(--accent);
      box-shadow: 0 0 20px var(--accent-glow);
    }

    .podium-card-header {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .podium-rank {
      font-family: var(--font-mono);
      font-size: 1.1rem;
      font-weight: 800;
      width: 32px;
      height: 32px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 8px;
      background: var(--bg-raised);
      border: 1px solid var(--border);
      color: var(--text-dim);
    }

    .podium-card.first .podium-rank {
      background: var(--accent-dim);
      color: var(--accent);
      border-color: rgba(34, 211, 238, 0.3);
    }

    .podium-model-name {
      font-family: var(--font-mono);
      font-size: 0.82rem;
      font-weight: 700;
      color: var(--text);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .podium-card.first .podium-model-name {
      color: var(--accent);
    }

    .podium-stats {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 1px;
      background: var(--border);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      overflow: hidden;
    }

    .podium-stat {
      background: var(--bg-raised);
      padding: 8px 10px;
      text-align: center;
    }

    .podium-stat .ps-value {
      font-family: var(--font-mono);
      font-size: 1rem;
      font-weight: 800;
      color: var(--text);
      line-height: 1.1;
    }

    .podium-card.first .podium-stat:first-child .ps-value {
      color: var(--accent);
    }

    .podium-stat .ps-label {
      font-size: 0.6rem;
      font-weight: 600;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-top: 2px;
    }

    /* ── SCORE BAR CHART ── */
    .score-chart {
      display: grid;
      gap: 10px;
    }

    .chart-row {
      display: grid;
      grid-template-columns: 160px 1fr;
      gap: 10px;
      align-items: center;
    }

    .chart-model {
      font-family: var(--font-mono);
      font-size: 0.72rem;
      font-weight: 600;
      color: var(--text-secondary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      text-align: right;
    }

    .chart-bar-bg {
      height: 28px;
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
      position: relative;
    }

    .chart-bar-fill {
      height: 100%;
      border-radius: 5px;
      display: flex;
      align-items: center;
      justify-content: flex-end;
      padding-right: 8px;
      min-width: 60px;
    }

    .chart-bar-fill.rank-1 { background: var(--accent); }
    .chart-bar-fill.rank-2 { background: var(--green); }
    .chart-bar-fill.rank-3 { background: var(--orange); }
    .chart-bar-fill.rank-other { background: var(--purple); }

    .chart-bar-label {
      font-family: var(--font-mono);
      font-size: 0.72rem;
      font-weight: 800;
      color: var(--bg);
      white-space: nowrap;
    }

    .chart-range {
      position: absolute;
      top: 0;
      right: 8px;
      height: 100%;
      display: flex;
      align-items: center;
      font-family: var(--font-mono);
      font-size: 0.62rem;
      color: var(--text-dim);
      gap: 4px;
      pointer-events: none;
    }

    /* ── TAB BAR ── */
    .tab-bar {
      display: flex;
      gap: 2px;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 4px;
    }

    .tab-btn {
      flex: 1;
      background: transparent;
      border: none;
      border-radius: var(--radius-sm);
      padding: 10px 20px;
      font-family: var(--font-mono);
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--text-dim);
      cursor: pointer;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      transition: all 0.15s;
    }

    .tab-btn:hover {
      color: var(--text-secondary);
      background: rgba(255,255,255,0.03);
    }

    .tab-btn.active {
      background: var(--accent-dim);
      color: var(--accent);
      box-shadow: inset 0 0 0 1px rgba(34, 211, 238, 0.2);
    }

    .tab-panel {
      display: none;
    }

    .tab-panel.active {
      display: grid;
      gap: 16px;
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
      font-size: 0.72rem;
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
      gap: 8px;
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
      font-size: 0.7rem;
      color: var(--text-secondary);
      white-space: nowrap;
    }

    /* ── PANEL CARD ── */
    .panel {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px;
      display: grid;
      gap: 16px;
    }

    .panel-title {
      font-family: var(--font-mono);
      font-size: 0.78rem;
      font-weight: 700;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }

    /* ── TABLES ── */
    .table-wrap {
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      max-height: 400px;
    }

    .table-wrap::-webkit-scrollbar { width: 6px; height: 6px; }
    .table-wrap::-webkit-scrollbar-track { background: var(--bg-raised); }
    .table-wrap::-webkit-scrollbar-thumb { background: var(--border-bright); border-radius: 3px; }

    table {
      width: 100%;
      border-collapse: collapse;
      font-family: var(--font-mono);
      font-size: 0.76rem;
    }

    th {
      text-align: left;
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      color: var(--text-dim);
      font-weight: 600;
      font-size: 0.68rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      white-space: nowrap;
      position: sticky;
      top: 0;
      background: var(--bg-raised);
      z-index: 2;
    }

    td {
      text-align: left;
      padding: 8px 12px;
      border-bottom: 1px solid var(--border);
      color: var(--text-secondary);
      white-space: nowrap;
    }

    tr { transition: background 0.1s; }
    tr:hover { background: rgba(255,255,255,0.03); cursor: pointer; }

    tbody tr.selected-row {
      background: var(--accent-dim);
    }

    /* ── EXPLORER LAYOUT ── */
    .explorer-layout {
      display: grid;
      grid-template-columns: 340px 1fr;
      gap: 12px;
      align-items: start;
    }

    .sidebar {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px;
      display: grid;
      gap: 12px;
      max-height: calc(100vh - 100px);
      overflow: hidden;
    }

    .sidebar-title {
      font-family: var(--font-mono);
      font-size: 0.72rem;
      font-weight: 700;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }

    /* ── FILTERS ── */
    .filter-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }

    .field {
      display: grid;
      gap: 3px;
    }

    .field-label {
      font-family: var(--font-mono);
      font-size: 0.65rem;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    select {
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 6px 8px;
      background: var(--bg-raised);
      font-family: var(--font-mono);
      font-size: 0.76rem;
      color: var(--text-secondary);
      cursor: pointer;
    }

    select:focus {
      outline: 1px solid var(--accent);
      border-color: var(--accent);
    }

    /* ── BUTTONS ── */
    button {
      border: 1px solid var(--border);
      background: var(--bg-raised);
      color: var(--text-secondary);
      border-radius: 6px;
      padding: 6px 10px;
      font-family: var(--font-mono);
      font-size: 0.74rem;
      font-weight: 600;
      cursor: pointer;
      transition: border-color 0.15s, color 0.15s;
    }

    button:hover {
      border-color: var(--accent);
      color: var(--accent);
    }

    /* ── RUN NAV ── */
    .run-nav {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }

    .run-count {
      font-family: var(--font-mono);
      color: var(--text-dim);
      font-size: 0.72rem;
      margin-left: auto;
    }

    /* ── RUN LIST ── */
    .run-list {
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--bg-raised);
      overflow: auto;
      padding: 6px;
      display: grid;
      gap: 4px;
      flex: 1;
      max-height: calc(100vh - 360px);
      min-height: 200px;
    }

    .run-list::-webkit-scrollbar { width: 5px; }
    .run-list::-webkit-scrollbar-track { background: transparent; }
    .run-list::-webkit-scrollbar-thumb { background: var(--border-bright); border-radius: 3px; }

    .seed-pair {
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 8px 10px;
      background: var(--bg-card);
      cursor: pointer;
      display: grid;
      gap: 5px;
      transition: border-color 0.15s;
    }

    .seed-pair:hover { border-color: var(--border-bright); }

    .seed-pair.active {
      border-color: rgba(34, 211, 238, 0.4);
      background: rgba(34, 211, 238, 0.05);
    }

    .seed-pair-header {
      font-family: var(--font-mono);
      font-weight: 700;
      font-size: 0.76rem;
      color: var(--text-secondary);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .seed-pair-row {
      display: grid;
      grid-template-columns: 1fr auto 50px;
      gap: 6px;
      align-items: center;
      font-family: var(--font-mono);
      font-size: 0.74rem;
      color: var(--text-dim);
    }

    .seed-pair-row span:last-child {
      text-align: right;
      color: var(--text-secondary);
      font-weight: 700;
    }

    .seed-delta {
      font-family: var(--font-mono);
      font-weight: 800;
      font-size: 0.72rem;
    }

    .seed-delta.positive { color: var(--green); }
    .seed-delta.negative { color: var(--red); }

    /* ── BADGES ── */
    .badge {
      font-family: var(--font-mono);
      font-size: 0.62rem;
      border-radius: 4px;
      padding: 1px 6px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      display: inline-flex;
      align-items: center;
    }

    .badge.ok {
      background: var(--green-dim);
      color: var(--green);
      border: 1px solid rgba(74, 222, 128, 0.3);
    }

    .badge.bad {
      background: var(--red-dim);
      color: var(--red);
      border: 1px solid rgba(248, 113, 113, 0.3);
    }

    .badge.warn {
      background: var(--orange-dim);
      color: var(--orange);
      border: 1px solid rgba(251, 146, 60, 0.25);
    }

    /* ── REPLAY PANEL ── */
    .replay-panel {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px;
      display: grid;
      gap: 16px;
    }

    .replay-header {
      display: grid;
      gap: 8px;
    }

    .replay-title {
      font-family: var(--font-mono);
      font-weight: 700;
      font-size: 0.92rem;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
      color: var(--text);
    }

    .replay-sub {
      font-family: var(--font-mono);
      font-size: 0.76rem;
      color: var(--text-dim);
    }

    .summary-cards {
      display: grid;
      grid-template-columns: repeat(7, 1fr);
      gap: 1px;
      background: var(--border);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      overflow: hidden;
    }

    .card {
      background: var(--bg-raised);
      padding: 8px 10px;
    }

    .card .label {
      font-size: 0.6rem;
      font-weight: 600;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-family: var(--font-mono);
      white-space: nowrap;
    }

    .card .value {
      font-family: var(--font-mono);
      font-weight: 800;
      font-size: 0.88rem;
      color: var(--text);
      margin-top: 2px;
      white-space: nowrap;
    }

    .model-switch {
      display: flex;
      gap: 6px;
      align-items: center;
      flex-wrap: wrap;
    }

    .model-switch .muted-label {
      font-family: var(--font-mono);
      font-size: 0.7rem;
      color: var(--text-dim);
    }

    /* ── TURN CONTROLS ── */
    .turn-controls {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
    }

    .turn-controls input[type=range] {
      flex: 1;
      min-width: 120px;
      accent-color: var(--accent);
      height: 4px;
    }

    .turn-meta {
      font-family: var(--font-mono);
      color: var(--text-dim);
      font-size: 0.76rem;
      white-space: nowrap;
    }

    /* ── MAP + DETAIL GRID ── */
    .replay-grid {
      display: grid;
      grid-template-columns: 1.5fr 1fr;
      gap: 12px;
      align-items: start;
    }

    .map-board {
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 8px;
      display: grid;
      gap: 6px;
    }

    .map-grid {
      display: grid;
      gap: 3px;
    }

    .tile {
      border: 1px solid var(--border);
      border-radius: 6px;
      min-height: 60px;
      padding: 4px;
      background: var(--bg-card);
      display: grid;
      align-content: center;
      justify-items: center;
      gap: 2px;
      position: relative;
      overflow: hidden;
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

    .tile.empty   { background: #1e1e22; border-color: #2a2a2e; }
    .tile.tree    { background: #132b18; border-color: #245a30; }
    .tile.rock    { background: #22222a; border-color: #3a3a44; }
    .tile.food    { background: #2a1c0a; border-color: #4a3018; }
    .tile.water   { background: #0c2030; border-color: #184060; }
    .tile.unknown { background: #1c1c20; }

    .tile.visited::after {
      content: '';
      position: absolute;
      inset: 2px;
      border: 1px dashed rgba(34, 211, 238, 0.35);
      border-radius: 4px;
      pointer-events: none;
    }

    .tile.current {
      box-shadow:
        inset 0 0 0 2px rgba(34, 211, 238, 0.7),
        0 0 16px rgba(34, 211, 238, 0.25),
        0 0 32px rgba(34, 211, 238, 0.08);
      z-index: 1;
    }

    .coord {
      position: absolute;
      top: 2px;
      right: 4px;
      color: #888;
      font-size: 0.56rem;
      font-family: var(--font-mono);
    }

    .tile-main {
      font-size: 1.35rem;
      text-align: center;
      line-height: 1;
      margin-top: 10px;
      filter: drop-shadow(0 1px 3px rgba(0,0,0,0.5));
    }

    .agent-mark {
      position: absolute;
      bottom: 2px;
      left: 2px;
      right: 2px;
      display: inline-flex;
      align-items: center;
      gap: 3px;
      border: 1px solid rgba(34, 211, 238, 0.45);
      border-radius: 4px;
      padding: 2px 4px;
      background: rgba(34, 211, 238, 0.2);
      color: var(--accent);
      font-family: var(--font-mono);
      font-size: 0.54rem;
      font-weight: 700;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      backdrop-filter: blur(4px);
    }

    .map-legend {
      font-family: var(--font-mono);
      color: var(--text-dim);
      font-size: 0.68rem;
    }

    /* ── DETAIL PANEL ── */
    .detail-panel {
      display: grid;
      gap: 12px;
    }

    .detail-section {
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 10px 12px;
      display: grid;
      gap: 6px;
    }

    .detail-label {
      font-family: var(--font-mono);
      font-size: 0.65rem;
      font-weight: 600;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }

    /* ── METERS ── */
    .meter-grid {
      display: grid;
      gap: 8px;
    }

    .meter {
      display: grid;
      gap: 3px;
    }

    .meter-head {
      display: flex;
      justify-content: space-between;
      font-family: var(--font-mono);
      font-size: 0.74rem;
      color: var(--text-secondary);
    }

    .meter-bar {
      width: 100%;
      height: 6px;
      border-radius: 999px;
      background: var(--border);
      overflow: hidden;
    }

    .meter-fill {
      height: 100%;
      border-radius: 999px;
      background: var(--accent);
      transition: width 0.3s ease;
    }

    .meter.warn .meter-fill { background: var(--orange); }
    .meter.bad .meter-fill { background: var(--red); }

    /* ── INVENTORY ── */
    .inv-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 4px;
    }

    .inv-item {
      border: 1px solid var(--border);
      border-radius: 4px;
      background: var(--bg-card);
      padding: 5px 8px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-family: var(--font-mono);
      font-size: 0.74rem;
      color: var(--text-secondary);
    }

    .inv-item strong { color: var(--text); }

    /* ── CODE BLOCK ── */
    .code-block {
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--bg-card);
      padding: 8px 10px;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: var(--font-mono);
      font-size: 0.74rem;
      color: var(--text-secondary);
    }

    .code-block.raw-cmd {
      color: var(--accent);
      background: rgba(34, 211, 238, 0.05);
      border-color: rgba(34, 211, 238, 0.15);
    }

    /* ── DETAILS/SUMMARY ── */
    details > summary {
      cursor: pointer;
      font-family: var(--font-mono);
      font-size: 0.72rem;
      font-weight: 600;
      color: var(--text-dim);
      padding: 4px 0;
      list-style: none;
      transition: color 0.15s;
    }

    details > summary::-webkit-details-marker { display: none; }
    details > summary::before { content: "\\25B8  "; font-size: 0.6rem; }
    details[open] > summary::before { content: "\\25BE  "; }
    details > summary:hover { color: var(--text-secondary); }

    /* ── TIMELINE ── */
    .timeline-section {
      display: grid;
      gap: 8px;
    }

    .timeline-wrap {
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      overflow: auto;
      max-height: 260px;
    }

    .timeline-wrap::-webkit-scrollbar { width: 5px; height: 5px; }
    .timeline-wrap::-webkit-scrollbar-track { background: var(--bg-raised); }
    .timeline-wrap::-webkit-scrollbar-thumb { background: var(--border-bright); border-radius: 3px; }

    /* ── EMPTY STATE ── */
    .empty-state {
      border: 1px dashed var(--border-bright);
      border-radius: var(--radius-sm);
      padding: 20px;
      color: var(--text-dim);
      font-family: var(--font-mono);
      font-size: 0.78rem;
      text-align: center;
    }

    /* ── FOOTER ── */
    .footer {
      color: var(--text-dim);
      font-family: var(--font-mono);
      font-size: 0.68rem;
      display: flex;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 6px;
      padding: 4px 0;
    }

    /* ── LIGHT THEME ── */
    [data-theme="light"] {
      --bg: #f5f5f5;
      --bg-raised: #ebebeb;
      --bg-card: #ffffff;
      --bg-card-hover: #f8f8f8;
      --border: #d4d4d8;
      --border-bright: #a1a1aa;
      --text: #18181b;
      --text-secondary: #3f3f46;
      --text-dim: #71717a;
      --accent: #0891b2;
      --accent-dim: rgba(8, 145, 178, 0.1);
      --accent-glow: rgba(8, 145, 178, 0.06);
      --green: #16a34a;
      --green-dim: rgba(22, 163, 74, 0.1);
      --red: #dc2626;
      --red-dim: rgba(220, 38, 38, 0.08);
      --orange: #ea580c;
      --orange-dim: rgba(234, 88, 12, 0.08);
    }

    [data-theme="light"] .tile.unknown { background: #e4e4e7; }
    [data-theme="light"] .tile.empty   { background: #f4f4f5; border-color: #d4d4d8; }
    [data-theme="light"] .tile.tree    { background: #dcfce7; border-color: #86efac; }
    [data-theme="light"] .tile.rock    { background: #f0f0f4; border-color: #c4c4cc; }
    [data-theme="light"] .tile.food    { background: #fff7ed; border-color: #fdba74; }
    [data-theme="light"] .tile.water   { background: #e0f2fe; border-color: #7dd3fc; }

    [data-theme="light"] .tile-main { filter: none; }
    [data-theme="light"] .tile .tile-type { font-weight: 700; }
    [data-theme="light"] .tile.tree .tile-type  { color: #15803d; }
    [data-theme="light"] .tile.rock .tile-type  { color: #6b7280; }
    [data-theme="light"] .tile.food .tile-type  { color: #c2410c; }
    [data-theme="light"] .tile.water .tile-type { color: #0369a1; }
    [data-theme="light"] .tile.empty .tile-type { color: #a1a1aa; }
    [data-theme="light"] .tile.unknown .tile-type { color: #a1a1aa; }
    [data-theme="light"] .coord { color: #a1a1aa; }

    [data-theme="light"] .tile.current {
      box-shadow: inset 0 0 0 2px rgba(8, 145, 178, 0.6), 0 0 12px rgba(8, 145, 178, 0.15);
    }

    [data-theme="light"] .agent-mark {
      background: rgba(8, 145, 178, 0.12);
      border-color: rgba(8, 145, 178, 0.35);
    }

    [data-theme="light"] .tile.visited::after {
      border-color: rgba(8, 145, 178, 0.35);
    }

    [data-theme="light"] .code-block.raw-cmd {
      background: rgba(8, 145, 178, 0.06);
      border-color: rgba(8, 145, 178, 0.2);
    }

    [data-theme="light"] .tab-btn.active {
      background: rgba(8, 145, 178, 0.1);
      box-shadow: inset 0 0 0 1px rgba(8, 145, 178, 0.2);
    }

    [data-theme="light"] .seed-pair.active {
      border-color: rgba(8, 145, 178, 0.4);
      background: rgba(8, 145, 178, 0.05);
    }

    /* ── THEME TOGGLE ── */
    .theme-toggle {
      position: fixed;
      top: 12px;
      right: 16px;
      z-index: 100;
      border: 1px solid var(--border);
      background: var(--bg-card);
      color: var(--text-dim);
      border-radius: 8px;
      padding: 6px 12px;
      font-family: var(--font-mono);
      font-size: 0.72rem;
      font-weight: 600;
      cursor: pointer;
      transition: border-color 0.15s, color 0.15s;
      letter-spacing: 0.04em;
    }

    .theme-toggle:hover {
      border-color: var(--accent);
      color: var(--accent);
    }

    /* ── RESPONSIVE ── */
    @media (max-width: 1100px) {
      .explorer-layout { grid-template-columns: 1fr; }
      .replay-grid { grid-template-columns: 1fr; }
      .summary-cards { grid-template-columns: repeat(4, 1fr); }
      .filter-row { grid-template-columns: 1fr; }
      .sidebar { max-height: none; }
    }
  </style>
</head>
<body>
  <button class=\"theme-toggle\" id=\"themeToggle\" type=\"button\"></button>
  <div class=\"wrap\">
    <div class=\"page-header\">
      <div class=\"page-title\"><span>TinyWorld</span> Compare Dashboard <span id=\"dashVersion\"></span></div>
    </div>

    <section id=\"compareSummary\"></section>

    <section class=\"tech-accordion\">
      <button class=\"tech-toggle\" id=\"techToggle\" type=\"button\">
        // technical details <span id=\"techArrow\">&#9654;</span>
      </button>
      <div class=\"tech-body\" id=\"techBody\">
        <div class=\"chip-row\" id=\"metaChips\"></div>
      </div>
    </section>

    <nav class=\"tab-bar\">
      <button class=\"tab-btn active\" data-tab=\"leaderboard\" type=\"button\">Leaderboard</button>
      <button class=\"tab-btn\" data-tab=\"explorer\" type=\"button\">Run Explorer</button>
    </nav>

    <!-- TAB 1: LEADERBOARD -->
    <div class=\"tab-panel active\" id=\"tab-leaderboard\">
      <div class=\"panel\">
        <div class=\"panel-title\">Score Comparison</div>
        <div id=\"scoreChart\" class=\"score-chart\"></div>
      </div>

      <div class=\"panel\">
        <div class=\"panel-title\">Model Ranking</div>
        <div class=\"table-wrap\">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Model</th>
                <th>Avg Score</th>
                <th>Best</th>
                <th>Worst</th>
                <th>Avg Survived</th>
                <th>Best Survived</th>
                <th>Death Rate</th>
                <th>Avg Invalid</th>
                <th>Avg Latency / call</th>
                <th>Total Tokens</th>
              </tr>
            </thead>
            <tbody id=\"rankingBody\"></tbody>
          </table>
        </div>
      </div>

      <div class=\"panel\">
        <div class=\"panel-title\">Head-to-Head</div>
        <div class=\"table-wrap\">
          <table>
            <thead>
              <tr>
                <th>Model A</th>
                <th>vs</th>
                <th>Runs</th>
                <th>A wins</th>
                <th>B wins</th>
                <th>Ties</th>
                <th>A Win Rate</th>
                <th>Avg Score Delta</th>
              </tr>
            </thead>
            <tbody id=\"h2hBody\"></tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- TAB 2: RUN EXPLORER -->
    <div class=\"tab-panel\" id=\"tab-explorer\">
      <div class=\"explorer-layout\">
        <aside class=\"sidebar\">
          <div class=\"sidebar-title\">Run Browser</div>

          <div class=\"filter-row\">
            <div class=\"field\">
              <span class=\"field-label\">Model</span>
              <select id=\"modelFilter\"></select>
            </div>
            <div class=\"field\">
              <span class=\"field-label\">Seed</span>
              <select id=\"seedFilter\"></select>
            </div>
          </div>
          <div class=\"field\">
            <span class=\"field-label\">Status</span>
            <select id=\"statusFilter\"></select>
          </div>

          <div class=\"run-nav\">
            <button type=\"button\" id=\"prevRunBtn\">&#9664; Prev</button>
            <button type=\"button\" id=\"nextRunBtn\">Next &#9654;</button>
            <div class=\"run-count\" id=\"runCount\"></div>
          </div>

          <div class=\"run-list\" id=\"runList\"></div>
        </aside>

        <main class=\"replay-panel\">
          <div class=\"replay-header\" id=\"replayHeader\"></div>

          <div class=\"turn-controls\">
            <button type=\"button\" id=\"prevTurnBtn\">&#9664;</button>
            <button type=\"button\" id=\"playTurnBtn\">&#9654; Play</button>
            <button type=\"button\" id=\"nextTurnBtn\">&#9654;</button>
            <input id=\"turnSlider\" type=\"range\" min=\"1\" max=\"1\" value=\"1\" />
            <div class=\"turn-meta\" id=\"turnMeta\"></div>
          </div>

          <div class=\"replay-grid\">
            <div class=\"map-board\">
              <div class=\"map-grid\" id=\"mapGrid\"></div>
              <div class=\"map-legend\" id=\"mapLegend\"></div>
            </div>

            <div class=\"detail-panel\">
              <div class=\"detail-section\">
                <div class=\"detail-label\">Turn Details</div>
                <div id=\"turnStatus\"></div>
              </div>

              <div class=\"detail-section\">
                <div class=\"detail-label\">State</div>
                <div class=\"meter-grid\" id=\"stateMeters\"></div>
              </div>

              <div class=\"detail-section\">
                <div class=\"detail-label\">Inventory</div>
                <div class=\"inv-grid\" id=\"inventoryGrid\"></div>
              </div>

              <details>
                <summary>Raw model output</summary>
                <div class=\"code-block raw-cmd\" id=\"rawOutput\"></div>
              </details>

              <details>
                <summary>Score events</summary>
                <div class=\"code-block\" id=\"scoreEvents\"></div>
              </details>
            </div>
          </div>

          <div class=\"timeline-section\">
            <div class=\"panel-title\">Turn Timeline</div>
            <div class=\"timeline-wrap\">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Action</th>
                    <th>Valid</th>
                    <th>&#916;</th>
                    <th>Total</th>
                    <th>Energy</th>
                    <th>Hunger</th>
                    <th>Thirst</th>
                  </tr>
                </thead>
                <tbody id=\"timelineBody\"></tbody>
              </table>
            </div>
          </div>
        </main>
      </div>
    </div>

    <div class=\"footer\">
      <span>TinyWorld Survival Bench</span>
    </div>
  </div>
"""

    html_data = '<script id="compareData" type="application/json">' + payload_json + "</script>"

    html_tail = """
  <script>
    const DATA = JSON.parse(document.getElementById('compareData').textContent || '{}');

    const tileMeta = {
      empty: { emoji: '\\u25AB', label: '' },
      tree: { emoji: '\\u{1F332}', label: 'tree' },
      rock: { emoji: '\\u{1FAA8}', label: 'rock' },
      food: { emoji: '\\u{1F34E}', label: 'food' },
      water: { emoji: '\\u{1F4A7}', label: 'water' },
      unknown: { emoji: '\\u2588', label: '?' },
    };

    const inventoryMeta = {
      wood: '\\u{1FAB5} wood',
      stone: '\\u{1F9F1} stone',
      food: '\\u{1F34E} food',
      water: '\\u{1F4A7} water',
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

    /* ── TABS ── */
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        const panel = document.getElementById('tab-' + btn.getAttribute('data-tab'));
        if (panel) panel.classList.add('active');
      });
    });

    function numberOr(value, fallback) {
      const num = Number(value);
      return Number.isFinite(num) ? num : fallback;
    }

    function formatCount(value, fallback = 'n/a') {
      if (value === null || value === undefined || value === '') return fallback;
      const num = Number(value);
      if (!Number.isFinite(num)) return fallback;
      return Math.round(num).toLocaleString('en-US');
    }

    function formatFloat(value, digits = 2, fallback = 'n/a') {
      if (value === null || value === undefined || value === '') return fallback;
      const num = Number(value);
      if (!Number.isFinite(num)) return fallback;
      return num.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
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

    function formatSignedScore(value) {
      const num = Number(value ?? 0);
      if (!Number.isFinite(num)) return '0';
      return `${num > 0 ? '+' : ''}${num}`;
    }

    function shortProfile(value) {
      const text = String(value || 'model');
      return text.length <= 18 ? text : `${text.slice(0, 18)}...`;
    }

    function getRunStatus(summary) {
      const endReason = String(summary?.end_reason || '');
      if (endReason === 'agent_dead') {
        return { key: 'dead', label: 'Died', className: 'bad' };
      }
      return { key: 'finished', label: 'Survived', className: 'ok' };
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
      const chips = [
        `protocol: ${meta.protocol_version || '-'}`,
        `bench: ${meta.bench_version || '-'}`,
        `engine: ${meta.engine_version || '-'}`,
        `scenario: ${meta.scenario || '-'}`,
        `models: ${formatCount(meta.models?.length || models.length)}`,
        `runs/model: ${formatCount(meta.runs_per_model)}`,
        `total runs: ${formatCount(meta.total_runs || runs.length)}`,
        `seeds: ${(meta.seed_list || []).join(', ') || '-'}`,
        `prompt: ${String(meta.prompt_set_sha256 || '-').slice(0, 12)}`,
        `fairness: paired seeds`,
      ];
      metaChips.innerHTML = chips.map(c => `<span class="chip">${c}</span>`).join('');
    }

    function enrichModelsFromRuns() {
      models.forEach(m => {
        const modelRuns = runs.filter(r => String(r.model_profile) === String(m.model_profile));
        if (!modelRuns.length) return;
        const scores = modelRuns.map(r => Number(r.summary?.final_score ?? 0));
        const survived = modelRuns.map(r => Number(r.summary?.turns_survived ?? 0));
        if (m.best_final_score == null) m.best_final_score = Math.max(...scores);
        if (m.worst_final_score == null) m.worst_final_score = Math.min(...scores);
        if (m.max_turns_survived == null) m.max_turns_survived = Math.max(...survived);
        if (m.tokens_used_total == null) {
          const tokens = modelRuns.map(r => Number(r.summary?.tokens_used ?? 0));
          m.tokens_used_total = tokens.reduce((a, b) => a + b, 0);
        }
      });
    }

    function modelLatencyPerTurn(m) {
      if (m.latency_ms_per_turn != null) return m.latency_ms_per_turn;
      const avgTurns = Number(m.avg_turns_survived ?? 0);
      if (avgTurns > 0 && m.latency_ms_avg != null) return Number(m.latency_ms_avg) / avgTurns;
      return null;
    }

    function renderCompareSummary() {
      const el = document.getElementById('compareSummary');
      if (!el || !models.length) { if (el) el.innerHTML = ''; return; }

      el.innerHTML = `<div class="podium-grid">
        ${models.map((m, i) => {
          const isFirst = i === 0;
          const survivalRate = formatFloat(100 - m.death_rate_pct, 1);
          const avgLatencyPerCall = formatDurationFromMs(modelLatencyPerTurn(m));
          return `<div class="podium-card ${isFirst ? 'first' : ''}">
            <div class="podium-card-header">
              <div class="podium-rank">${m.rank}</div>
              <div class="podium-model-name">${m.model_profile}</div>
            </div>
            <div class="podium-stats">
              <div class="podium-stat"><div class="ps-value">${formatFloat(m.avg_final_score, 2)}</div><div class="ps-label">Avg Score</div></div>
              <div class="podium-stat"><div class="ps-value">${survivalRate}%</div><div class="ps-label">Survival</div></div>
              <div class="podium-stat"><div class="ps-value">${avgLatencyPerCall}</div><div class="ps-label">Avg Latency</div></div>
            </div>
          </div>`;
        }).join('')}
      </div>`;
    }

    function renderScoreChart() {
      const el = document.getElementById('scoreChart');
      if (!el || !models.length) { if (el) el.innerHTML = ''; return; }

      const maxScore = Math.max(...models.map(m => Number(m.best_final_score ?? m.avg_final_score ?? 0)));
      const chartMax = Math.max(1, maxScore * 1.1);

      el.innerHTML = models.map((m, i) => {
        const avg = Number(m.avg_final_score ?? 0);
        const best = Number(m.best_final_score ?? avg);
        const worst = Number(m.worst_final_score ?? avg);
        const avgPct = Math.max(8, (avg / chartMax) * 100);
        const rankClass = i === 0 ? 'rank-1' : i === 1 ? 'rank-2' : i === 2 ? 'rank-3' : 'rank-other';
        const rangeText = best !== worst ? `${formatFloat(worst, 0)}–${formatFloat(best, 0)}` : '';

        return `<div class="chart-row">
          <div class="chart-model">${m.model_profile}</div>
          <div class="chart-bar-bg">
            <div class="chart-bar-fill ${rankClass}" style="width:${avgPct.toFixed(1)}%">
              <span class="chart-bar-label">${formatFloat(avg, 1)}</span>
            </div>
            ${rangeText ? `<div class="chart-range">${rangeText}</div>` : ''}
          </div>
        </div>`;
      }).join('');
    }

    function renderRanking() {
      if (!models.length) {
        rankingBody.innerHTML = '<tr><td colspan="11" style="color:var(--text-dim)">No model stats.</td></tr>';
        return;
      }

      rankingBody.innerHTML = models.map(row => {
        const avgLatencyPerCall = formatDurationFromMs(modelLatencyPerTurn(row));

        return `
        <tr>
          <td>${formatCount(row.rank)}</td>
          <td style="color:var(--accent);font-weight:700">${row.model_profile}</td>
          <td style="font-weight:700">${formatFloat(row.avg_final_score, 2)}</td>
          <td>${formatCount(row.best_final_score)}</td>
          <td>${formatCount(row.worst_final_score)}</td>
          <td>${formatFloat(row.avg_turns_survived, 2)} / ${formatCount(row.max_turns_avg || 0)}</td>
          <td>${formatCount(row.max_turns_survived)}</td>
          <td>${formatFloat(row.death_rate_pct, 1)}%</td>
          <td>${formatFloat(row.avg_invalid_actions, 2)}</td>
          <td>${avgLatencyPerCall}</td>
          <td>${formatCount(row.tokens_used_total)}</td>
        </tr>`;
      }).join('');
    }

    function renderPairwise() {
      if (!pairwise.length) {
        h2hBody.innerHTML = '<tr><td colspan="8" style="color:var(--text-dim)">Need 2+ models for H2H.</td></tr>';
        return;
      }

      h2hBody.innerHTML = pairwise.map(row => {
        const wr = row.win_rate_a_vs_b === null || row.win_rate_a_vs_b === undefined
          ? 'n/a' : `${formatFloat(row.win_rate_a_vs_b, 1)}%`;
        const delta = row.avg_delta_a_minus_b === null || row.avg_delta_a_minus_b === undefined
          ? 'n/a' : `${Number(row.avg_delta_a_minus_b) >= 0 ? '+' : ''}${formatFloat(row.avg_delta_a_minus_b, 2)}`;

        return `
          <tr>
            <td style="font-weight:600">${row.model_a_profile}</td>
            <td style="color:var(--text-dim);">${row.model_b_profile}</td>
            <td>${formatCount(row.paired_runs)}</td>
            <td style="color:var(--green);font-weight:600">${formatCount(row.wins_a)}</td>
            <td style="color:var(--red);font-weight:600">${formatCount(row.wins_b)}</td>
            <td style="color:var(--text-dim)">${formatCount(row.ties)}</td>
            <td style="font-weight:700">${wr}</td>
            <td>${delta}</td>
          </tr>
        `;
      }).join('');
    }

    function initFilters() {
      const modelOptions = ['all', ...new Set(runs.map(run => String(run.model_profile || ''))).values()];
      const seedOptions = ['all', ...new Set(runs.map(run => String(run.seed))).values()];

      modelFilter.innerHTML = modelOptions.map(v => `<option value="${v}">${v === 'all' ? 'All' : v}</option>`).join('');
      seedFilter.innerHTML = seedOptions.map(v => `<option value="${v}">${v === 'all' ? 'All' : `Seed ${v}`}</option>`).join('');
      statusFilter.innerHTML = [
        '<option value="all">All</option>',
        '<option value="dead">Died</option>',
        '<option value="finished">Survived</option>',
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

    function buildSeedPairs() {
      const bySeed = {};
      filteredRunIndexes.forEach(idx => {
        const run = runs[idx];
        const seedKey = String(run.seed);
        if (!bySeed[seedKey]) bySeed[seedKey] = [];
        bySeed[seedKey].push({ run, idx });
      });
      return Object.entries(bySeed).map(([seed, entries]) => {
        entries.sort((a, b) => {
          const sa = Number(a.run.summary?.final_score ?? 0);
          const sb = Number(b.run.summary?.final_score ?? 0);
          return sb - sa;
        });
        return { seed, entries };
      });
    }

    function renderRunList() {
      const seedPairs = buildSeedPairs();

      if (!seedPairs.length) {
        runList.innerHTML = '<div class="empty-state">No runs match filters.</div>';
        runCount.textContent = '0';
        renderReplayEmpty();
        return;
      }

      runCount.textContent = `${filteredRunIndexes.length} runs`;

      runList.innerHTML = seedPairs.map(pair => {
        const isActive = pair.entries.some(e => e.idx === selectedRunIndex);

        const rows = pair.entries.map(entry => {
          const s = entry.run.summary || {};
          const status = getRunStatus(s);
          const score = formatCount(s.final_score);
          const isSelected = entry.idx === selectedRunIndex;
          return `<div class="seed-pair-row" data-run-index="${entry.idx}" style="${isSelected ? 'color:var(--accent)' : ''}">
            <span>${shortProfile(entry.run.model_profile)}</span>
            <span class="badge ${status.className}">${status.label}</span>
            <span>${score}</span>
          </div>`;
        });

        let deltaHtml = '';
        if (pair.entries.length === 2) {
          const scoreA = Number(pair.entries[0].run.summary?.final_score ?? 0);
          const scoreB = Number(pair.entries[1].run.summary?.final_score ?? 0);
          const delta = scoreA - scoreB;
          const deltaClass = delta > 0 ? 'positive' : (delta < 0 ? 'negative' : '');
          deltaHtml = `<span class="seed-delta ${deltaClass}">${delta > 0 ? '+' : ''}${delta}</span>`;
        }

        return `<div class="seed-pair ${isActive ? 'active' : ''}" data-seed="${pair.seed}">
          <div class="seed-pair-header">
            <span>Seed ${pair.seed}</span>
            ${deltaHtml}
          </div>
          ${rows.join('')}
        </div>`;
      }).join('');

      runList.querySelectorAll('.seed-pair').forEach(node => {
        node.addEventListener('click', e => {
          const rowEl = e.target.closest('.seed-pair-row');
          if (rowEl) {
            const idx = Number(rowEl.getAttribute('data-run-index'));
            if (Number.isFinite(idx)) {
              selectedRunIndex = idx;
              currentTurnIndex = 0;
              stopAutoPlay();
              renderRunList();
              renderReplay();
              return;
            }
          }
          const seed = node.getAttribute('data-seed');
          const pair = seedPairs.find(p => p.seed === seed);
          if (pair && pair.entries.length) {
            selectedRunIndex = pair.entries[0].idx;
            currentTurnIndex = 0;
            stopAutoPlay();
            renderRunList();
            renderReplay();
          }
        });
      });

      const active = runList.querySelector('.seed-pair.active');
      if (active) active.scrollIntoView({ block: 'nearest' });
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
        { label: 'Score', value: formatCount(summary.final_score) },
        { label: 'Survival', value: `${formatCount(summary.turns_survived)}/${formatCount(summary.max_turns)}` },
        { label: 'Invalid', value: formatCount(summary.invalid_actions) },
        { label: 'Resources', value: gatheredLabel },
        { label: 'Latency (total)', value: formatDurationFromMs(summary.latency_ms) },
        { label: 'Latency (avg)', value: (() => {
          const turns = Number(summary.turns_survived ?? 0);
          const total = Number(summary.latency_ms ?? 0);
          return turns > 0 ? formatDurationFromMs(total / turns) : 'n/a';
        })() },
        { label: 'Tokens', value: formatCount(summary.tokens_used) },
      ];

      const sameSeedRuns = runs
        .map((r, i) => ({ r, i }))
        .filter(item => String(item.r.seed) === String(run.seed) && item.i !== selectedRunIndex);

      let switcherHtml = '';
      if (sameSeedRuns.length > 0) {
        switcherHtml = `<div class="model-switch">
          <span class="muted-label">Switch:</span>
          ${sameSeedRuns.map(item => `<button type="button" data-switch-run="${item.i}">${shortProfile(item.r.model_profile)}</button>`).join('')}
        </div>`;
      }

      replayHeader.innerHTML = `
        <div class="replay-title">
          <span>${run.model_profile}</span>
          <span style="color:var(--text-dim);font-size:0.78rem">seed ${run.seed}</span>
          <span class="badge ${status.className}">${status.label}</span>
        </div>
        ${summary.end_reason_human ? `<div class="replay-sub">${summary.end_reason_human}</div>` : ''}
        ${deathCause ? `<div class="replay-sub">${deathCause}</div>` : ''}
        <div class="summary-cards">
          ${cards.map(c => `<div class="card"><div class="label">${c.label}</div><div class="value">${c.value}</div></div>`).join('')}
        </div>
        ${switcherHtml}
      `;

      replayHeader.querySelectorAll('[data-switch-run]').forEach(btn => {
        btn.addEventListener('click', e => {
          e.stopPropagation();
          selectedRunIndex = Number(btn.getAttribute('data-switch-run'));
          currentTurnIndex = 0;
          stopAutoPlay();
          renderRunList();
          renderReplay();
        });
      });
    }

    function renderMap(run, frame) {
      const world = run.replay?.world || {};
      const width = Math.max(1, numberOr(world.width, 1));
      const height = Math.max(1, numberOr(world.height, 1));
      const map = frame.map_snapshot || [];
      const agent = frame.agent_position_after || frame.agent_position_before || { x: 0, y: 0 };

      const visited = new Set(
        (frame.path_prefix || []).map(pos => `${numberOr(pos.x, 0)},${numberOr(pos.y, 0)}`)
      );

      mapGrid.style.gridTemplateColumns = `repeat(${width}, minmax(52px, 1fr))`;

      const cells = [];
      for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
          const type = String(map?.[y]?.[x] || 'unknown');
          const metaEntry = tileMeta[type] || tileMeta.unknown;

          const isCurrent = numberOr(agent.x, -1) === x && numberOr(agent.y, -1) === y;
          const isVisited = visited.has(`${x},${y}`);

          const classes = ['tile', type];
          if (isVisited) classes.push('visited');
          if (isCurrent) classes.push('current');

          cells.push(`
            <div class="${classes.join(' ')}">
              <div class="tile-type">${metaEntry.label}</div>
              <div class="coord">${x},${y}</div>
              <div class="tile-main">${metaEntry.emoji}</div>
              ${isCurrent ? `<div class="agent-mark">\\u{1F916} ${shortProfile(run.model_profile)}</div>` : ''}
            </div>
          `);
        }
      }

      mapGrid.innerHTML = cells.join('');
      const coverage = String(run.replay?.meta?.map_coverage || 'partial');
      mapLegend.textContent = coverage === 'full'
        ? 'full map | dashed = visited'
        : 'partial map (fog) | dashed = visited';
    }

    function renderTurnDetails(run, frame) {
      const rules = replayRules(run);
      const observation = frame.observation || {};
      const validation = frame.validation_result || {};
      const actionResult = frame.action_result || {};
      const scoreDelta = frame.score_delta || {};
      const metrics = frame.metrics || {};
      const inventory = observation.inventory || {};

      const isValid = Boolean(validation.is_valid);
      const resultMessage = !isValid
        ? `Invalid: ${validation.error || 'not allowed'}`
        : (actionResult.message || (actionResult.success ? 'Applied.' : 'No effect.'));

      const badgeClass = isValid ? 'ok' : 'bad';
      const badgeLabel = isValid ? 'VALID' : 'INVALID';

      turnStatus.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-family:var(--font-mono);font-size:0.82rem">
          <span class="badge ${badgeClass}">${badgeLabel}</span>
          <span style="color:var(--accent);font-weight:700">${actionResult.requested || '-'}</span>
          <span style="color:var(--text-dim)">T${formatCount(frame.turn)}</span>
        </div>
        <div style="font-family:var(--font-mono);font-size:0.74rem;color:var(--text-dim);margin-top:4px">${resultMessage}</div>
        <div style="font-family:var(--font-mono);font-size:0.74rem;color:var(--text-secondary);margin-top:2px">score: ${formatCount(frame.cumulative_score)} (${formatSignedScore(scoreDelta.total || 0)})</div>
      `;

      const meters = [
        { key: 'energy', label: 'Energy', value: numberOr(observation.energy, 0), max: rules.energyMax },
        { key: 'hunger', label: 'Hunger', value: numberOr(observation.hunger, 0), max: rules.hungerMax },
        { key: 'thirst', label: 'Thirst', value: numberOr(observation.thirst, 0), max: rules.thirstMax },
      ];

      stateMeters.innerHTML = meters.map(item => {
        const pct = Math.max(0, Math.min(100, (item.value / item.max) * 100));
        return `
          <div class="${meterClass(item.key, item.value, item.max)}">
            <div class="meter-head"><span>${item.label}</span><span>${formatCount(item.value)}/${formatCount(item.max)}</span></div>
            <div class="meter-bar"><div class="meter-fill" style="width:${pct.toFixed(2)}%"></div></div>
          </div>
        `;
      }).join('');

      inventoryGrid.innerHTML = Object.entries(inventoryMeta).map(([key, label]) => {
        return `<div class="inv-item"><span>${label}</span><strong>${formatCount(inventory[key] || 0)}</strong></div>`;
      }).join('');

      rawOutput.textContent = String(frame.raw_model_output || '-').trim() || '-';

      const eventLines = [
        `delta: ${formatSignedScore(scoreDelta.total || 0)}`,
        `events: ${(scoreDelta.events || []).map(formatScoreEvent).join(', ') || '-'}`,
        `latency: ${formatDurationFromMs(metrics.latency_ms)}`,
        `tokens: ${formatCount(metrics.tokens_used)}`,
        `cost: ${formatFloat(metrics.estimated_cost, 6, 'n/a')}`,
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
            <td>${item.action_result?.requested || '-'}</td>
            <td>${valid ? '\\u2713' : '\\u2717'}</td>
            <td>${formatSignedScore(item.score_delta?.total || 0)}</td>
            <td>${formatCount(item.cumulative_score)}</td>
            <td>${formatCount(obs.energy)}</td>
            <td>${formatCount(obs.hunger)}</td>
            <td>${formatCount(obs.thirst)}</td>
          </tr>
        `;
      }).join('');

      timelineBody.querySelectorAll('tr').forEach(row => {
        row.addEventListener('click', () => {
          const index = Number(row.getAttribute('data-turn-index'));
          if (!Number.isFinite(index)) return;
          currentTurnIndex = index;
          renderReplay();
        });
      });

      const selected = timelineBody.querySelector('tr.selected-row');
      if (selected) selected.scrollIntoView({ block: 'nearest' });

      const frameCount = frames.length;
      turnMeta.textContent = frameCount ? `${currentTurnIndex + 1}/${frameCount}` : '0/0';
    }

    function renderReplayEmpty() {
      replayHeader.innerHTML = '<div class="empty-state">Select a run to view replay.</div>';
      mapGrid.innerHTML = '';
      mapLegend.textContent = '';
      turnStatus.innerHTML = '';
      stateMeters.innerHTML = '';
      inventoryGrid.innerHTML = '';
      rawOutput.textContent = '-';
      scoreEvents.textContent = '-';
      timelineBody.innerHTML = '';
      turnMeta.textContent = '0/0';
      turnSlider.min = '1';
      turnSlider.max = '1';
      turnSlider.value = '1';
    }

    function renderReplay() {
      const run = selectedRun();
      if (!run) { renderReplayEmpty(); return; }

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
      playTurnBtn.innerHTML = '&#9654; Play';
    }

    function toggleAutoPlay() {
      const run = selectedRun();
      const frames = run?.replay?.frames || [];
      if (frames.length <= 1) return;

      if (autoPlayTimer !== null) { stopAutoPlay(); return; }

      playTurnBtn.innerHTML = '&#9646;&#9646;';
      autoPlayTimer = window.setInterval(() => {
        if (currentTurnIndex >= frames.length - 1) { stopAutoPlay(); return; }
        currentTurnIndex += 1;
        renderReplay();
      }, 750);
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
      [modelFilter, seedFilter, statusFilter].forEach(node => {
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

      document.addEventListener('keydown', event => {
        const tag = String(event.target?.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

        if (event.key === 'ArrowLeft') { event.preventDefault(); moveRun(-1); return; }
        if (event.key === 'ArrowRight') { event.preventDefault(); moveRun(1); return; }
        if (event.key === 'ArrowUp') { event.preventDefault(); moveTurn(-1); return; }
        if (event.key === 'ArrowDown') { event.preventDefault(); moveTurn(1); }
      });
    }

    /* ── THEME ── */
    const THEME_KEY = 'tinyworld-theme';
    const themeToggle = document.getElementById('themeToggle');

    function applyTheme(theme) {
      document.documentElement.setAttribute('data-theme', theme);
      themeToggle.textContent = theme === 'dark' ? '// light' : '// dark';
      try { localStorage.setItem(THEME_KEY, theme); } catch(e) {}
    }

    function initTheme() {
      let saved = null;
      try { saved = localStorage.getItem(THEME_KEY); } catch(e) {}
      applyTheme(saved || 'dark');
    }

    themeToggle.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme') || 'dark';
      applyTheme(current === 'dark' ? 'light' : 'dark');
    });

    initTheme();

    function boot() {
      const vEl = document.getElementById('dashVersion');
      if (vEl) vEl.textContent = `v${meta.bench_version || meta.version || '?'}`;
      enrichModelsFromRuns();
      renderCompareSummary();
      renderMetaChips();
      renderScoreChart();
      renderRanking();
      renderPairwise();
      initFilters();
      rebuildFilteredRuns();
      renderRunList();
      renderReplay();
      bindEvents();

      document.getElementById('techToggle').addEventListener('click', () => {
        const body = document.getElementById('techBody');
        const arrow = document.getElementById('techArrow');
        const isOpen = body.classList.toggle('open');
        arrow.innerHTML = isOpen ? '&#9660;' : '&#9654;';
      });
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
