"""Generate a multi-run/multi-model interactive HTML dashboard from compare artifacts."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any
import webbrowser

from bench.cli_ui import colorize, use_color
from engine.version import __version__


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

    .page-title #dashVersion {
      color: var(--text-dim);
      font-size: 0.68rem;
      font-weight: 500;
    }

    /* ── MICRO BADGES ── */
    .micro-badge {
      display: inline-block;
      font-family: var(--font-mono);
      font-size: 0.54rem;
      font-weight: 700;
      padding: 1px 6px;
      border-radius: 9999px;
      line-height: 1.4;
      letter-spacing: 0.02em;
      white-space: nowrap;
      vertical-align: middle;
      margin-left: 4px;
    }
    .micro-badge.badge-score    { background: var(--accent-dim); color: var(--accent); }
    .micro-badge.badge-fast     { background: var(--green-dim);  color: var(--green); }
    .micro-badge.badge-cheap    { background: var(--green-dim);  color: var(--green); }
    .micro-badge.badge-coverage { background: var(--orange-dim); color: var(--orange); }
    .micro-badge.badge-stable   { background: rgba(167,139,250,0.12); color: var(--purple); }
    .micro-badge.badge-survival { background: var(--red-dim);    color: var(--red); }
    .micro-badge.badge-value   { background: rgba(6,182,212,0.12); color: #06b6d4; }
    .badge-group { display: inline; }
    .badge-hidden { display: none; }
    .badge-expand {
      display: inline-block;
      font-family: var(--font-mono);
      font-size: 0.62rem;
      font-weight: 700;
      padding: 2px 7px;
      border-radius: 6px;
      margin-left: 3px;
      background: var(--bg-raised);
      color: var(--text-dim);
      cursor: pointer;
      vertical-align: middle;
      border: 1px solid var(--border);
    }
    .badge-expand:hover { background: var(--border); color: var(--text); }

    /* ── WINNER STRIP ── */
    .winner-strip {
      background: var(--bg-card);
      border: 1px solid var(--accent);
      box-shadow: 0 0 20px var(--accent-glow);
      border-radius: var(--radius);
      padding: 14px 24px;
      display: flex;
      align-items: center;
      gap: 20px;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }
    .winner-strip .ws-rank {
      font-family: var(--font-mono);
      font-size: 1.3rem;
      font-weight: 800;
      color: var(--accent);
      width: 38px; height: 38px;
      display: flex; align-items: center; justify-content: center;
      background: var(--accent-dim);
      border: 1px solid rgba(34,211,238,0.3);
      border-radius: 10px;
      flex-shrink: 0;
    }
    .winner-strip .ws-info {
      min-width: 0;
    }
    .winner-strip .ws-model {
      font-family: var(--font-mono);
      font-size: 0.85rem;
      font-weight: 800;
      color: var(--accent);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .winner-strip .ws-score-block {
      text-align: center;
      padding: 0 16px;
      border-left: 1px solid var(--border);
      border-right: 1px solid var(--border);
    }
    .winner-strip .ws-score {
      font-family: var(--font-mono);
      font-size: 1.5rem;
      font-weight: 800;
      color: var(--text);
      line-height: 1;
    }
    .winner-strip .ws-score-label {
      font-size: 0.56rem;
      font-weight: 600;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-top: 2px;
    }
    .winner-strip .ws-metrics {
      display: flex;
      gap: 20px;
      flex-wrap: wrap;
      margin-left: auto;
    }
    .winner-strip .ws-metric {
      text-align: center;
    }
    .winner-strip .ws-metric-value {
      font-family: var(--font-mono);
      font-size: 0.82rem;
      font-weight: 800;
      color: var(--text);
    }
    .winner-strip .ws-metric-label {
      font-size: 0.54rem;
      font-weight: 600;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    /* ── COMPACT LEADERBOARD TABLE ── */
    .lb-table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      font-family: var(--font-mono);
      font-size: 0.74rem;
    }
    .lb-table th {
      font-size: 0.6rem;
      font-weight: 700;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      padding: 8px 10px;
      text-align: left;
      background: var(--bg-raised);
      border-bottom: 1px solid var(--border);
      position: sticky; top: 0; z-index: 2;
      white-space: nowrap;
    }
    .lb-table td {
      padding: 8px 10px;
      border-bottom: 1px solid var(--border);
      color: var(--text-secondary);
      white-space: nowrap;
    }
    .lb-table tbody tr:first-child td {
      color: var(--text);
      font-weight: 700;
    }
    .lb-table .lb-rank {
      font-weight: 800;
      color: var(--text-dim);
      width: 32px;
      text-align: center;
    }
    .lb-table .lb-model {
      font-weight: 700;
      color: var(--text);
      white-space: normal;
    }
    .lb-table .lb-score {
      font-weight: 800;
      color: var(--text);
    }

    /* Inline range bar */
    .range-bar-wrap {
      display: flex;
      align-items: center;
      gap: 0;
      min-width: 90px;
    }
    .range-bar {
      position: relative;
      height: 8px;
      flex: 1;
      background: var(--bg);
      border-radius: 4px;
      border: 1px solid var(--border);
    }
    .range-bar .range-fill {
      position: absolute;
      top: 1px; bottom: 1px;
      border-radius: 3px;
      opacity: 0.3;
    }
    .range-bar .range-fill.rank-1 { background: var(--accent); }
    .range-bar .range-fill.rank-2 { background: var(--green); }
    .range-bar .range-fill.rank-3 { background: var(--orange); }
    .range-bar .range-fill.rank-other { background: var(--purple); }
    .range-bar .range-dot {
      position: absolute;
      top: 50%;
      transform: translate(-50%, -50%);
      width: 10px; height: 10px;
      border-radius: 50%;
      border: 2px solid var(--bg-card);
      z-index: 1;
    }
    .range-bar .range-dot.rank-1 { background: var(--accent); }
    .range-bar .range-dot.rank-2 { background: var(--green); }
    .range-bar .range-dot.rank-3 { background: var(--orange); }
    .range-bar .range-dot.rank-other { background: var(--purple); }
    .range-bar .range-label {
      position: absolute;
      top: -14px;
      transform: translateX(-50%);
      font-family: var(--font-mono);
      font-size: 0.54rem;
      font-weight: 700;
      color: var(--text-dim);
      white-space: nowrap;
    }
    .range-bar .range-label-min { left: 0; transform: none; }
    .range-bar .range-label-max { right: 0; transform: none; text-align: right; }

    /* ── RADAR CHART ── */
    .radar-wrap {
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 10px 0;
    }
    .radar-legend {
      display: flex;
      flex-wrap: wrap;
      gap: 10px 18px;
      justify-content: center;
      margin-top: 8px;
    }
    .radar-legend-item {
      display: flex;
      align-items: center;
      gap: 6px;
      font-family: var(--font-mono);
      font-size: 0.68rem;
      color: var(--text-secondary);
    }
    .radar-legend-dot {
      width: 10px; height: 10px;
      border-radius: 50%;
      flex-shrink: 0;
    }

    /* ── DONUT CHARTS ── */
    .donut-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 18px 12px;
      padding: 8px 0;
    }
    @media (max-width: 600px) {
      .donut-grid { grid-template-columns: repeat(2, 1fr); }
    }
    .donut-cell {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
    }
    .donut-label {
      font-family: var(--font-mono);
      font-size: 0.66rem;
      font-weight: 700;
      color: var(--text-secondary);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .donut-winner {
      font-family: var(--font-mono);
      font-size: 0.60rem;
      color: var(--text-dim);
      max-width: 120px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      text-align: center;
    }

    /* ── TWO-CHART LAYOUT ── */
    .charts-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    @media (max-width: 900px) {
      .charts-row { grid-template-columns: 1fr; }
    }

    /* ── SORTABLE COLUMNS ── */
    th[data-sort-key] {
      cursor: pointer;
      user-select: none;
      position: relative;
    }
    th[data-sort-key]:hover { color: var(--accent); }
    th[data-sort-key]::after {
      content: '⇅';
      margin-left: 5px;
      font-size: 0.9em;
      opacity: 0.3;
    }
    th[data-sort-key].sort-asc::after {
      content: '▲';
      font-size: 0.9em;
      opacity: 1;
      color: var(--accent);
    }
    th[data-sort-key].sort-desc::after {
      content: '▼';
      font-size: 0.9em;
      opacity: 1;
      color: var(--accent);
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

    .compat-warnings {
      display: grid;
      gap: 6px;
    }

    .compat-warning {
      border: 1px solid rgba(251, 146, 60, 0.45);
      background: rgba(251, 146, 60, 0.10);
      border-radius: 6px;
      padding: 6px 10px;
      font-family: var(--font-mono);
      font-size: 0.72rem;
      color: #fdba74;
      font-weight: 600;
    }

    .chip-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    /* ── TOOLTIPS ── */
    [data-tip] {
      cursor: help;
    }

    .global-tooltip {
      position: fixed;
      z-index: 9999;
      pointer-events: none;
      background: var(--bg);
      color: var(--text);
      border: 1px solid var(--border-bright);
      border-radius: 6px;
      padding: 6px 10px;
      font-family: var(--font-sans);
      font-size: 0.72rem;
      font-weight: 400;
      line-height: 1.4;
      max-width: 320px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
      opacity: 0;
      transform: translateY(2px);
      transition: opacity 0.12s ease, transform 0.12s ease;
      white-space: normal;
      text-transform: none;
      letter-spacing: normal;
    }

    .global-tooltip.show {
      opacity: 1;
      transform: translateY(0);
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

    .chip .chip-key {
      color: var(--text-dim);
    }

    .chip .chip-val {
      color: var(--accent);
      font-weight: 600;
    }

    .chip-btn {
      cursor: pointer;
      border: 1px solid rgba(34, 211, 238, 0.3);
      background: var(--accent-dim);
      transition: border-color 0.15s;
    }

    .chip-btn:hover {
      border-color: var(--accent);
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
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
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
      gap: 6px;
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
      font-size: 0.72rem;
      color: var(--text-dim);
    }

    .replay-sub-strip {
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--bg-raised);
      padding: 6px 10px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }

    .analysis-detail {
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--bg-raised);
      padding: 6px 10px;
    }

    .analysis-detail summary {
      cursor: pointer;
      font-family: var(--font-mono);
      font-size: 0.72rem;
      color: var(--text-secondary);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      list-style: none;
    }

    .analysis-detail summary::-webkit-details-marker { display: none; }

    .analysis-detail .detail-body {
      margin-top: 8px;
      font-family: var(--font-mono);
      font-size: 0.76rem;
      color: var(--text-dim);
      line-height: 1.45;
    }

    .summary-cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
      gap: 1px;
      background: var(--border);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      overflow: hidden;
    }

    .card {
      background: var(--bg-raised);
      padding: 6px 9px;
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
      font-size: 0.82rem;
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
      padding: 8px 10px;
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
      --purple: #7c3aed;
    }
    [data-theme="light"] .micro-badge.badge-stable {
      background: rgba(124, 58, 237, 0.08);
      color: var(--purple);
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

    [data-theme="light"] .compat-warning {
      color: #9a3412;
      border-color: rgba(180, 83, 9, 0.35);
      background: rgba(255, 237, 213, 0.85);
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

    <nav class=\"tab-bar\">
      <button class=\"tab-btn active\" data-tab=\"leaderboard\" type=\"button\">Leaderboard</button>
      <button class=\"tab-btn\" data-tab=\"explorer\" type=\"button\">Run Explorer</button>
    </nav>

    <!-- TAB 1: LEADERBOARD -->
    <div class=\"tab-panel active\" id=\"tab-leaderboard\">
      <section id=\"winnerStrip\"></section>

      <div class=\"panel\">
        <div class=\"panel-title\" data-tip=\"All models ranked by average score. Badges highlight category leaders.\" class=\"tip-down\">Leaderboard</div>
        <div class=\"table-wrap\">
          <table class=\"lb-table\">
            <thead>
              <tr>
                <th data-sort-key=\"rank\">#</th>
                <th>Model</th>
                <th data-tip=\"Average score across all runs\" class=\"tip-down\" data-sort-key=\"avg_final_score\" data-sort-desc=\"1\">Avg Score</th>
                <th data-tip=\"Score spread: worst to best run. Dot = average.\" class=\"tip-down\">Range</th>
                <th data-tip=\"Percentage of runs where agent survived all turns\" class=\"tip-down\" data-sort-key=\"survival_pct\" data-sort-desc=\"1\">Survival</th>
                <th data-tip=\"Average API response time per turn\" class=\"tip-down\" data-sort-key=\"latency_per_turn\">Latency</th>
                <th data-tip=\"Estimated total cost across all runs\" class=\"tip-down\" data-sort-key=\"estimated_cost_total\">Cost</th>
                <th data-tip=\"Score points per dollar spent (higher = better value)\" class=\"tip-down\" data-sort-key=\"score_per_cost\" data-sort-desc=\"1\">Score/$</th>
                <th data-tip=\"Average map coverage percentage\" class=\"tip-down\" data-sort-key=\"avg_coverage_pct\" data-sort-desc=\"1\">Coverage</th>
              </tr>
            </thead>
            <tbody id=\"lbBody\"></tbody>
          </table>
        </div>
      </div>

      <div class=\"charts-row\">
        <div class=\"panel\">
          <div class=\"panel-title\" data-tip=\"Normalised profile across key dimensions. Larger area = more well-rounded model.\" class=\"tip-down\">Model Profile</div>
          <div class=\"radar-wrap\"><svg id=\"radarChart\" width=\"440\" height=\"360\"></svg></div>
          <div id=\"radarLegend\" class=\"radar-legend\"></div>
        </div>
        <div class=\"panel\">
          <div class=\"panel-title\" data-tip=\"Share of each model across six categories. Larger slice = stronger in that dimension.\" class=\"tip-down\">Category Breakdown</div>
          <div id=\"donutGrid\" class=\"donut-grid\"></div>
        </div>
      </div>

      <div class=\"panel\">
        <div class=\"panel-title\">Detailed Metrics</div>
        <div class=\"table-wrap\">
          <table>
            <thead>
              <tr>
                <th data-sort-key=\"rank\">#</th>
                <th>Model</th>
                <th data-tip=\"Average score across all runs for this model\" class=\"tip-down\" data-sort-key=\"avg_final_score\" data-sort-desc=\"1\">Avg Score</th>
                <th data-tip=\"Highest score in a single run\" class=\"tip-down\" data-sort-key=\"best_final_score\" data-sort-desc=\"1\">Best</th>
                <th data-tip=\"Lowest score in a single run\" class=\"tip-down\" data-sort-key=\"worst_final_score\" data-sort-desc=\"1\">Worst</th>
                <th data-tip=\"Average number of turns survived out of maximum turns\" class=\"tip-down\" data-sort-key=\"avg_turns_survived\" data-sort-desc=\"1\">Avg Survived</th>
                <th data-tip=\"Maximum turns survived in a single run\" class=\"tip-down\" data-sort-key=\"max_turns_survived\" data-sort-desc=\"1\">Best Survived</th>
                <th data-tip=\"Percentage of runs where the agent died before reaching max turns\" class=\"tip-down\" data-sort-key=\"death_rate_pct\">Death Rate</th>
                <th data-tip=\"Average number of invalid actions per run (penalised -2 each)\" class=\"tip-down\" data-sort-key=\"avg_invalid_actions\">Avg Invalid</th>
                <th data-tip=\"Average map coverage percentage (unique visited cells / total map cells)\" class=\"tip-down\" data-sort-key=\"avg_coverage_pct\" data-sort-desc=\"1\">Avg Coverage</th>
                <th data-tip=\"Average revisit ratio (revisited moves / total successful moves)\" class=\"tip-down\" data-sort-key=\"avg_revisit_ratio\">Avg Revisit</th>
                <th data-tip=\"Average resource conversion efficiency percentage\" class=\"tip-down\" data-sort-key=\"avg_conversion_efficiency_pct\" data-sort-desc=\"1\">Avg Conversion</th>
                <th data-tip=\"Average API response time per turn (total latency / total turns)\" class=\"tip-down\" data-sort-key=\"latency_per_turn\">Avg Latency / turn</th>
                <th data-tip=\"Total tokens consumed across all runs for this model\" class=\"tip-down\" data-sort-key=\"tokens_used_total\" data-sort-desc=\"1\">Total Tokens</th>
              </tr>
            </thead>
            <tbody id=\"rankingBody\"></tbody>
          </table>
        </div>
      </div>

      <div class=\"panel\">
        <div class=\"panel-title\" data-tip=\"Direct comparison on the same seeds: who wins when both models play the exact same map\" class=\"tip-down\">Head-to-Head</div>
        <div class=\"table-wrap\">
          <table>
            <thead>
              <tr>
                <th>Model A</th>
                <th>vs</th>
                <th data-tip=\"Number of paired runs (same seed) where both models competed\" class=\"tip-down\">Runs</th>
                <th data-tip=\"Times Model A scored higher than Model B on the same seed\" class=\"tip-down\">A wins</th>
                <th data-tip=\"Times Model B scored higher than Model A on the same seed\" class=\"tip-down\">B wins</th>
                <th data-tip=\"Times both models got the exact same score on the same seed\" class=\"tip-down\">Ties</th>
                <th data-tip=\"Percentage of paired runs won by Model A\" class=\"tip-down\">A Win Rate</th>
                <th data-tip=\"Average score difference (A minus B) across all paired seeds. Positive = A is better\" class=\"tip-down\">Avg Score Delta</th>
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

    <section class=\"tech-accordion\">
      <button class=\"tech-toggle\" id=\"techToggle\" type=\"button\">
        // technical details <span id=\"techArrow\">&#9654;</span>
      </button>
      <div class=\"tech-body\" id=\"techBody\">
        <div class=\"chip-row\" id=\"metaChips\"></div>
        <div class=\"compat-warnings\" id=\"compatWarnings\"></div>
        <div class=\"protocol-panel\" id=\"protocolPanel\"></div>
      </div>
    </section>

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
    const compatWarnings = document.getElementById('compatWarnings');
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

    // 16 maximally distinct hues – no two adjacent colours should be confusable
    const MODEL_COLORS = [
      '#22d3ee', // cyan
      '#f97316', // orange
      '#a78bfa', // violet
      '#22c55e', // green
      '#f43f5e', // rose
      '#eab308', // yellow
      '#3b82f6', // blue
      '#ec4899', // pink
      '#14b8a6', // teal
      '#f59e0b', // amber
      '#8b5cf6', // purple
      '#84cc16', // lime
      '#ef4444', // red
      '#06b6d4', // sky
      '#d946ef', // fuchsia
      '#10b981', // emerald
    ];
    const models = Array.isArray(DATA.models) ? DATA.models : [];
    models.forEach((m, i) => { m._color = MODEL_COLORS[i % MODEL_COLORS.length]; });
    const pairwise = Array.isArray(DATA.pairwise) ? DATA.pairwise : [];
    const runs = Array.isArray(DATA.runs) ? DATA.runs : [];
    const meta = DATA.meta || {};

    let selectedRunIndex = 0;
    let filteredRunIndexes = [];
    let currentTurnIndex = 0;
    let autoPlayTimer = null;
    let tooltipEl = null;
    let tooltipTarget = null;

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

    function initTooltips() {
      tooltipEl = document.createElement('div');
      tooltipEl.className = 'global-tooltip';
      tooltipEl.setAttribute('aria-hidden', 'true');
      document.body.appendChild(tooltipEl);

      function placeTooltip(clientX, clientY) {
        if (!tooltipEl || !tooltipEl.classList.contains('show')) return;
        const pad = 12;
        const vw = window.innerWidth || 1280;
        const vh = window.innerHeight || 720;
        const rect = tooltipEl.getBoundingClientRect();
        let left = clientX + 14;
        let top = clientY - rect.height - 12;
        if (left + rect.width + pad > vw) left = vw - rect.width - pad;
        if (left < pad) left = pad;
        if (top < pad) top = clientY + 14;
        if (top + rect.height + pad > vh) top = vh - rect.height - pad;
        tooltipEl.style.left = `${left}px`;
        tooltipEl.style.top = `${top}px`;
      }

      function showTooltip(target, clientX, clientY) {
        if (!tooltipEl) return;
        const tip = target?.getAttribute?.('data-tip');
        if (!tip) return;
        tooltipTarget = target;
        tooltipEl.textContent = tip;
        tooltipEl.classList.add('show');
        placeTooltip(clientX, clientY);
      }

      function hideTooltip() {
        if (!tooltipEl) return;
        tooltipTarget = null;
        tooltipEl.classList.remove('show');
      }

      document.addEventListener('mouseover', (event) => {
        const target = event.target?.closest?.('[data-tip]');
        if (!target) return;
        const rect = target.getBoundingClientRect();
        showTooltip(target, rect.left + (rect.width / 2), rect.top);
      });

      document.addEventListener('mousemove', (event) => {
        if (!tooltipTarget) return;
        placeTooltip(event.clientX, event.clientY);
      });

      document.addEventListener('mouseout', (event) => {
        if (!tooltipTarget) return;
        const from = event.target?.closest?.('[data-tip]');
        const to = event.relatedTarget?.closest?.('[data-tip]');
        if (from === tooltipTarget && to !== tooltipTarget) {
          hideTooltip();
        }
      });

      document.addEventListener('focusin', (event) => {
        const target = event.target?.closest?.('[data-tip]');
        if (!target) return;
        const rect = target.getBoundingClientRect();
        showTooltip(target, rect.left + (rect.width / 2), rect.top);
      });

      document.addEventListener('focusout', (event) => {
        const target = event.target?.closest?.('[data-tip]');
        if (target && target === tooltipTarget) hideTooltip();
      });

      document.addEventListener('scroll', () => {
        if (!tooltipTarget) return;
        const rect = tooltipTarget.getBoundingClientRect();
        placeTooltip(rect.left + (rect.width / 2), rect.top);
      }, true);

      document.addEventListener('click', () => {
        if (tooltipTarget) hideTooltip();
      });
    }

    function numberOr(value, fallback) {
      const num = Number(value);
      return Number.isFinite(num) ? num : fallback;
    }

    function escapeHtml(value) {
      return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
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

    function formatUsd(value, fallback = 'n/a') {
      if (value === null || value === undefined || value === '') return fallback;
      const num = Number(value);
      if (!Number.isFinite(num)) return fallback;
      if (Math.abs(num) >= 1) {
        return `$${num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
      }
      if (Math.abs(num) >= 0.01) {
        return `$${num.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`;
      }
      return `$${num.toLocaleString('en-US', { minimumFractionDigits: 6, maximumFractionDigits: 6 })}`;
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

    function ensureChildVisible(container, child) {
      if (!container || !child) return;
      const containerRect = container.getBoundingClientRect();
      const childRect = child.getBoundingClientRect();
      if (childRect.top < containerRect.top) {
        container.scrollTop -= (containerRect.top - childRect.top) + 6;
      } else if (childRect.bottom > containerRect.bottom) {
        container.scrollTop += (childRect.bottom - containerRect.bottom) + 6;
      }
    }

    function chip(label, value, tip) {
      const tipAttr = tip ? ` data-tip="${tip}"` : '';
      return `<span class="chip"${tipAttr}><span class="chip-key">${label}</span> <span class="chip-val">${value}</span></span>`;
    }

    function renderMetaChips() {
      const compareDurationMs = (() => {
        const generated = String(meta.generated_at_utc || '');
        const idRaw = String(meta.compare_id || '');
        const match = idRaw.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/);
        if (!generated || !match) return null;
        const started = Date.parse(`${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:${match[6]}Z`);
        const ended = Date.parse(generated);
        if (!Number.isFinite(started) || !Number.isFinite(ended)) return null;
        if (ended < started) return null;
        return ended - started;
      })();

      const totalModelTimeMs = models.reduce((sum, modelRow) => {
        const raw = Number(modelRow?.latency_ms_total ?? 0);
        if (!Number.isFinite(raw) || raw < 0) return sum;
        return sum + raw;
      }, 0);
      const compatibility = (meta.compatibility && typeof meta.compatibility === 'object') ? meta.compatibility : {};
      const compatibilityWarnings = Array.isArray(compatibility.warnings) ? compatibility.warnings : [];
      const modelCosts = models
        .map(modelRow => Number(modelRow?.estimated_cost_total))
        .filter(value => Number.isFinite(value));
      const totalModelCost = modelCosts.length > 0
        ? modelCosts.reduce((sum, value) => sum + value, 0)
        : null;

      const protocolBtn = `<button class="chip chip-btn" id="protocolChip" type="button" data-tip="Click to show the full game rules, stat mechanics, and scoring logic"><span class="chip-key">protocol</span> <span class="chip-val">${meta.protocol_version || '-'}</span></button>`;
      const chips = [
        protocolBtn,
        chip('bench', meta.bench_version || '-', 'Version of the benchmark harness that ran the tests'),
        chip('engine', meta.engine_version || '-', 'Version of the TinyWorld simulation engine'),
        chip('scenario', meta.scenario || '-', 'The map and rules configuration used for this benchmark'),
        chip('models', formatCount(meta.models?.length || models.length), 'Number of distinct AI models tested'),
        chip('runs/model', formatCount(meta.runs_per_model), 'How many runs each model played (one per seed)'),
        chip('total runs', formatCount(meta.total_runs || runs.length), 'Total number of runs across all models and seeds'),
        chip('seeds', (meta.seed_list || []).join(', ') || '-', 'Random seeds used for map generation. Same seeds = same maps for all models'),
        chip('total compare time', formatDurationFromMs(compareDurationMs), 'Wall-clock compare duration (from compare start id timestamp to artifact generation)'),
        chip('total model time', formatDurationFromMs(totalModelTimeMs || null), 'Sum of all model API latency across all runs'),
        chip('estimated cost total', formatUsd(totalModelCost, 'not available'), 'Estimated total USD cost across all runs (provider-reported or deterministic fallback)'),
        chip('compatibility', compatibilityWarnings.length ? 'warnings' : 'ok', 'Cross-run metadata consistency (protocol, prompt hash, bench version, engine version)'),
        chip('prompt', String(meta.prompt_set_sha256 || '-').slice(0, 12), 'SHA-256 hash of the prompt set. Same hash = identical prompts across runs'),
        chip('fairness', 'paired seeds', 'All models play the exact same maps (paired seeds) so score differences reflect model ability, not map luck'),
      ];
      metaChips.innerHTML = chips.join('');

      if (compatWarnings) {
        if (!compatibilityWarnings.length) {
          compatWarnings.innerHTML = '';
        } else {
          compatWarnings.innerHTML = compatibilityWarnings
            .map(item => `<div class="compat-warning">warning: ${escapeHtml(String(item?.message || 'compatibility mismatch detected'))}</div>`)
            .join('');
        }
      }

      const protocolChip = document.getElementById('protocolChip');
      if (protocolChip) {
        protocolChip.addEventListener('click', () => { toggleProtocolPanel(); });
      }
    }

    function renderProtocolPanel() {
      const panel = document.getElementById('protocolPanel');
      if (!panel) return;
      const p = runs[0]?.replay?.protocol || meta.protocol || {};
      const rules = p.rules || {};
      const scoring = p.scoring || {};

      const energyMax = Math.max(1, numberOr(rules.energy_max, 100));
      const hungerMax = Math.max(1, numberOr(rules.hunger_max, 100));
      const thirstMax = Math.max(1, numberOr(rules.thirst_max, 100));

      panel.innerHTML = `
        <div class="protocol-head">Protocol ${p.protocol_version || meta.protocol_version || '-'}</div>
        <div class="protocol-grid">
          <div class="protocol-block">
            <strong>State Scale</strong>
            <div>Energy: 0..${energyMax}</div>
            <div>Hunger: 0..${hungerMax}</div>
            <div>Thirst: 0..${thirstMax}</div>
          </div>
          <div class="protocol-block">
            <strong>Start State</strong>
            <div>Energy ${numberOr(rules.start_energy, '-')}/${energyMax}</div>
            <div>Hunger ${numberOr(rules.start_hunger, '-')}/${hungerMax}</div>
            <div>Thirst ${numberOr(rules.start_thirst, '-')}/${thirstMax}</div>
          </div>
          <div class="protocol-block">
            <strong>Passive / Turn</strong>
            <div>Energy ${formatSignedScore(-numberOr(rules.passive_energy_loss, 0))}</div>
            <div>Hunger +${numberOr(rules.passive_hunger_gain, '-')}</div>
            <div>Thirst +${numberOr(rules.passive_thirst_gain, '-')}</div>
          </div>
          <div class="protocol-block">
            <strong>Critical Thresholds</strong>
            <div>hunger=${hungerMax}: ${formatSignedScore(-numberOr(rules.starvation_energy_penalty, 0))} energy</div>
            <div>thirst=${thirstMax}: ${formatSignedScore(-numberOr(rules.dehydration_energy_penalty, 0))} energy</div>
            <div>death: energy &lt;= 0</div>
          </div>
          <div class="protocol-block">
            <strong>Action Effects</strong>
            <div>rest: +${numberOr(rules.rest_energy_gain, '-')} energy</div>
            <div>eat: -${numberOr(rules.eat_hunger_reduction, '-')} hunger</div>
            <div>drink: -${numberOr(rules.drink_thirst_reduction, '-')} thirst</div>
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
      const panel = document.getElementById('protocolPanel');
      if (!panel) return;
      panel.classList.toggle('open');
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

    function modelScorePerCost(m) {
      const score = Number(m.avg_final_score ?? 0);
      const cost = Number(m.estimated_cost_total ?? 0);
      if (cost <= 0 || score <= 0) return null;
      const runs = Number(m.num_runs ?? 1);
      const costPerRun = cost / runs;
      return costPerRun > 0 ? score / costPerRun : null;
    }

    /* ── Sortable table system ── */
    let currentSort = { key: 'avg_final_score', desc: true };

    function getSortValue(m, key) {
      if (key === 'rank') return Number(m.rank ?? 999);
      if (key === 'survival_pct') return 100 - Number(m.death_rate_pct ?? 100);
      if (key === 'latency_per_turn') return modelLatencyPerTurn(m) ?? Infinity;
      if (key === 'score_per_cost') return modelScorePerCost(m) ?? -Infinity;
      return Number(m[key] ?? 0);
    }

    function sortModels(key, desc) {
      currentSort = { key, desc };
      models.sort((a, b) => {
        const va = getSortValue(a, key);
        const vb = getSortValue(b, key);
        return desc ? vb - va : va - vb;
      });
      // update all sort indicators
      document.querySelectorAll('th[data-sort-key]').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.getAttribute('data-sort-key') === key) {
          th.classList.add(desc ? 'sort-desc' : 'sort-asc');
        }
      });
      renderCompactLeaderboard();
      renderRanking();
      renderRadarChart();
      renderDonutCharts();
    }

    document.addEventListener('click', (e) => {
      const th = e.target.closest('th[data-sort-key]');
      if (!th) return;
      const key = th.getAttribute('data-sort-key');
      const defaultDesc = th.hasAttribute('data-sort-desc');
      // toggle direction if same key, otherwise use default
      const desc = currentSort.key === key ? !currentSort.desc : defaultDesc;
      sortModels(key, desc);
    });

    function computeBadges() {
      if (!models.length) return;
      models.forEach(m => { m.badges = []; });

      const sorted = (arr, fn) => [...arr].sort(fn);

      // Best Score
      sorted(models, (a, b) => (b.avg_final_score ?? 0) - (a.avg_final_score ?? 0))[0]
        .badges.push({ label: '🏆 Best Score', cls: 'badge-score' });

      // Fastest
      const withLatency = models.filter(m => modelLatencyPerTurn(m) != null);
      if (withLatency.length) {
        sorted(withLatency, (a, b) => modelLatencyPerTurn(a) - modelLatencyPerTurn(b))[0]
          .badges.push({ label: '⚡ Fastest', cls: 'badge-fast' });
      }

      // Cheapest
      const withCost = models.filter(m => m.estimated_cost_total != null && m.estimated_cost_total > 0);
      if (withCost.length) {
        sorted(withCost, (a, b) => a.estimated_cost_total - b.estimated_cost_total)[0]
          .badges.push({ label: '💰 Cheapest', cls: 'badge-cheap' });
      }

      // Best Coverage
      const withCoverage = models.filter(m => m.avg_coverage_pct != null);
      if (withCoverage.length) {
        sorted(withCoverage, (a, b) => (b.avg_coverage_pct ?? 0) - (a.avg_coverage_pct ?? 0))[0]
          .badges.push({ label: '🗺️ Best Coverage', cls: 'badge-coverage' });
      }

      // Most Stable
      const withSpread = models.filter(m => m.best_final_score != null && m.worst_final_score != null);
      if (withSpread.length) {
        sorted(withSpread, (a, b) =>
          (a.best_final_score - a.worst_final_score) - (b.best_final_score - b.worst_final_score)
        )[0].badges.push({ label: '🎯 Most Stable', cls: 'badge-stable' });
      }

      // Best Survival
      const withSurvival = models.filter(m => m.death_rate_pct != null);
      if (withSurvival.length) {
        sorted(withSurvival, (a, b) => (a.death_rate_pct ?? 100) - (b.death_rate_pct ?? 100))[0]
          .badges.push({ label: '❤️ Best Survival', cls: 'badge-survival' });
      }

      // Best Value (score per dollar)
      const withValue = models.filter(m => modelScorePerCost(m) != null);
      if (withValue.length) {
        sorted(withValue, (a, b) => modelScorePerCost(b) - modelScorePerCost(a))[0]
          .badges.push({ label: '💎 Best Value', cls: 'badge-value' });
      }
    }

    function renderBadges(m, maxVisible = 99) {
      if (!m.badges || !m.badges.length) return '';
      const visible = m.badges.slice(0, maxVisible);
      const hidden = m.badges.slice(maxVisible);
      let html = '<span class="badge-group">';
      html += visible.map(b => `<span class="micro-badge ${b.cls}">${b.label}</span>`).join('');
      if (hidden.length) {
        const hiddenHtml = hidden.map(b => `<span class="micro-badge ${b.cls}">${b.label}</span>`).join('');
        html += `<span class="badge-expand" data-tip="${hidden.map(b=>b.label).join(', ')}"
                  onclick="event.stopPropagation();this.style.display='none';this.parentElement.querySelector('.badge-hidden').style.display='inline'">+${hidden.length}</span>`;
        html += `<span class="badge-hidden">${hiddenHtml}</span>`;
      }
      html += '</span>';
      return html;
    }

    function renderWinnerStrip() {
      const el = document.getElementById('winnerStrip');
      if (!el || !models.length) { if (el) el.innerHTML = ''; return; }

      const m = models[0];
      const survivalRate = formatFloat(100 - m.death_rate_pct, 1);
      const latency = formatDurationFromMs(modelLatencyPerTurn(m));
      const cost = formatUsd(m.estimated_cost_total, 'n/a');
      const coverage = m.avg_coverage_pct == null ? 'n/a' : `${formatFloat(m.avg_coverage_pct, 1)}%`;

      el.innerHTML = `<div class="winner-strip">
        <div class="ws-rank">1</div>
        <div class="ws-info">
          <div class="ws-model"><span style="color:${m._color || '#22d3ee'}">${m.model_profile}</span> ${renderBadges(m)}</div>
        </div>
        <div class="ws-score-block">
          <div class="ws-score">${formatFloat(m.avg_final_score, 2)}</div>
          <div class="ws-score-label">Avg Score</div>
        </div>
        <div class="ws-metrics">
          <div class="ws-metric" data-tip="Percentage of runs where the agent survived all turns"><div class="ws-metric-value">${survivalRate}%</div><div class="ws-metric-label">Survival</div></div>
          <div class="ws-metric" data-tip="Average API response time per turn"><div class="ws-metric-value">${latency}</div><div class="ws-metric-label">Latency</div></div>
          <div class="ws-metric" data-tip="Estimated total cost across all runs"><div class="ws-metric-value">${cost}</div><div class="ws-metric-label">Cost</div></div>
          <div class="ws-metric" data-tip="Average map coverage percentage"><div class="ws-metric-value">${coverage}</div><div class="ws-metric-label">Coverage</div></div>
        </div>
      </div>`;
    }

    function renderCompactLeaderboard() {
      const el = document.getElementById('lbBody');
      if (!el || !models.length) { if (el) el.innerHTML = ''; return; }

      const allScores = models.flatMap(m => [
        Number(m.best_final_score ?? m.avg_final_score ?? 0),
        Number(m.worst_final_score ?? m.avg_final_score ?? 0)
      ]);
      const globalMax = Math.max(...allScores);
      const globalMin = Math.min(...allScores);
      const chartMin = Math.max(0, globalMin - (globalMax - globalMin) * 0.15);
      const chartMax = globalMax + (globalMax - globalMin) * 0.15 || 1;
      const chartSpan = chartMax - chartMin || 1;

      el.innerHTML = models.map((m, i) => {
        const avg = Number(m.avg_final_score ?? 0);
        const best = Number(m.best_final_score ?? avg);
        const worst = Number(m.worst_final_score ?? avg);
        const survivalRate = formatFloat(100 - m.death_rate_pct, 1);
        const latency = formatDurationFromMs(modelLatencyPerTurn(m));
        const cost = formatUsd(m.estimated_cost_total, 'n/a');
        const coverage = m.avg_coverage_pct == null ? 'n/a' : `${formatFloat(m.avg_coverage_pct, 1)}%`;
        const rankClass = i === 0 ? 'rank-1' : i === 1 ? 'rank-2' : i === 2 ? 'rank-3' : 'rank-other';

        const worstPct = ((worst - chartMin) / chartSpan * 100).toFixed(1);
        const bestPct = ((best - chartMin) / chartSpan * 100).toFixed(1);
        const avgPct = ((avg - chartMin) / chartSpan * 100).toFixed(1);
        const widthPct = (bestPct - worstPct).toFixed(1);

        const mColor = m._color || '#888';
        const rangeBar = best !== worst
          ? `<div class="range-bar" data-tip="${formatFloat(worst, 0)} – ${formatFloat(avg, 1)} – ${formatFloat(best, 0)}">
              <div class="range-fill" style="left:${worstPct}%;width:${widthPct}%;background:${mColor};opacity:0.25"></div>
              <div class="range-dot" style="left:${avgPct}%;background:${mColor}"></div>
            </div>`
          : `<div class="range-bar" data-tip="All runs: ${formatFloat(avg, 1)}">
              <div class="range-dot" style="left:${avgPct}%;background:${mColor}"></div>
            </div>`;

        return `<tr>
          <td class="lb-rank">${m.rank}</td>
          <td class="lb-model"><span style="color:${mColor}">${m.model_profile}</span> ${renderBadges(m, 2)}</td>
          <td class="lb-score">${formatFloat(avg, 2)}</td>
          <td><div class="range-bar-wrap">${rangeBar}</div></td>
          <td>${survivalRate}%</td>
          <td>${latency}</td>
          <td>${cost}</td>
          <td>${(() => { const v = modelScorePerCost(m); return v != null ? formatFloat(v, 0) : 'n/a'; })()}</td>
          <td>${coverage}</td>
        </tr>`;
      }).join('');
    }

    /* ── Radar Chart ── */
    function renderRadarChart() {
      const svg = document.getElementById('radarChart');
      const legendEl = document.getElementById('radarLegend');
      if (!svg || !models.length) { if (svg) svg.innerHTML = ''; if (legendEl) legendEl.innerHTML = ''; return; }

      // use per-model colors from _color
      const axes = [
        { key: 'score',      label: 'Score',      tip: 'Avg final score normalised to best model (0-100)' },
        { key: 'survival',   label: 'Survival',   tip: 'Avg turns survived normalised to best model (0-100)' },
        { key: 'coverage',   label: 'Coverage',   tip: '% of unique map cells visited' },
        { key: 'efficiency', label: 'Efficiency',  tip: 'Resource conversion: % of gathered food/water consumed' },
        { key: 'stability',  label: 'Stability',  tip: 'Consistency: 100 − normalised score spread (smaller spread = higher)' },
      ];
      const N = axes.length;
      const cx = 220, cy = 170, R = 130;

      // normalise each metric 0-100
      const maxScore = Math.max(...models.map(m => Number(m.avg_final_score ?? 0)), 1);
      const maxSurvived = Math.max(...models.map(m => Number(m.avg_turns_survived ?? 0)), 1);
      const vals = models.map(m => {
        const spread = (Number(m.best_final_score ?? 0) - Number(m.worst_final_score ?? 0));
        const maxSpread = Math.max(...models.map(x => (Number(x.best_final_score ?? 0) - Number(x.worst_final_score ?? 0))), 1);
        const survPct = 100 - Number(m.death_rate_pct ?? 0);
        return {
          score:      Number(m.avg_final_score ?? 0) / maxScore * 100,
          survival:   survPct > 0 ? survPct : (Number(m.avg_turns_survived ?? 0) / maxSurvived * 100),
          coverage:   Number(m.avg_coverage_pct ?? 0),
          efficiency: Number(m.avg_conversion_efficiency_pct ?? 0),
          stability:  100 - (spread / maxSpread * 100),
        };
      });

      // helper: angle for axis i (start at top, go clockwise)
      const angle = i => (Math.PI * 2 * i / N) - Math.PI / 2;
      const px = (i, r) => cx + r * Math.cos(angle(i));
      const py = (i, r) => cy + r * Math.sin(angle(i));

      let html = '';

      // grid rings
      [0.25, 0.5, 0.75, 1].forEach(frac => {
        const pts = Array.from({length: N}, (_, i) => `${px(i, R*frac)},${py(i, R*frac)}`).join(' ');
        html += `<polygon points="${pts}" fill="none" stroke="var(--border)" stroke-width="1" opacity="0.5"/>`;
      });

      // axis lines + labels
      axes.forEach((a, i) => {
        html += `<line x1="${cx}" y1="${cy}" x2="${px(i, R)}" y2="${py(i, R)}" stroke="var(--border)" stroke-width="1" opacity="0.5"/>`;
        const lx = px(i, R + 18);
        const ly = py(i, R + 18);
        const anchor = Math.abs(lx - cx) < 5 ? 'middle' : lx > cx ? 'start' : 'end';
        html += `<text x="${lx}" y="${ly}" text-anchor="${anchor}" dominant-baseline="central"
                  fill="var(--text-dim)" font-family="var(--font-mono)" font-size="10" font-weight="600"
                  data-tip="${a.tip}" style="cursor:help">${a.label}</text>`;
      });

      // model polygons (reverse so rank-1 is on top)
      [...models].reverse().forEach((m, ri) => {
        const i = models.length - 1 - ri;
        const v = vals[i];
        const mColor = m._color || '#888';
        const pts = axes.map((a, ai) => {
          const pct = (v[a.key] ?? 0) / 100;
          return `${px(ai, R * pct)},${py(ai, R * pct)}`;
        }).join(' ');
        html += `<polygon points="${pts}" fill="${mColor}" fill-opacity="0.12"
                  stroke="${mColor}" stroke-width="2" stroke-opacity="0.8"/>`;
        // dots at vertices (with tooltip)
        axes.forEach((a, ai) => {
          const pct = (v[a.key] ?? 0) / 100;
          const val = (v[a.key] ?? 0).toFixed(1);
          html += `<circle cx="${px(ai, R * pct)}" cy="${py(ai, R * pct)}" r="5"
                    fill="${mColor}" opacity="0.9" data-tip="${m.model_profile}: ${a.label} ${val}" style="cursor:pointer"/>`;
        });
      });

      svg.innerHTML = html;

      // legend
      legendEl.innerHTML = models.map((m, i) => {
        return `<div class="radar-legend-item">
          <span class="radar-legend-dot" style="background:${m._color || '#888'}"></span>
          ${m.model_profile}
        </div>`;
      }).join('');
    }

    /* ── Donut Charts ── */
    function renderDonutCharts() {
      const el = document.getElementById('donutGrid');
      if (!el || !models.length) { if (el) el.innerHTML = ''; return; }

      const categories = [
        { label: '🏆 Score',      tip: 'Average final score across all runs (higher = better)', fn: m => Number(m.avg_final_score ?? 0) },
        { label: '⚡ Speed',      tip: 'Inverse of avg API latency per turn (lower latency = bigger slice)', fn: m => { const l = modelLatencyPerTurn(m); return l ? 1 / l : 0; } },
        { label: '⚙️ Efficiency', tip: 'Resource conversion: % of gathered food/water successfully consumed (eat+drink / total gathered)', fn: m => Number(m.avg_conversion_efficiency_pct ?? 0) },
        { label: '🗺️ Coverage',  tip: 'Map exploration: % of unique cells visited out of total map cells', fn: m => Number(m.avg_coverage_pct ?? 0) },
        { label: '❤️ Survival',  tip: 'Avg turns survived (when all die: raw turn count; otherwise: 100 − death rate %)', fn: m => { const s = 100 - Number(m.death_rate_pct ?? 100); return s > 0 ? s : Number(m.avg_turns_survived ?? 0); } },
        { label: '🎯 Stability', tip: 'Inverse of score spread (best − worst). Smaller spread = bigger slice = more consistent', fn: m => { const s = Number(m.best_final_score ?? 0) - Number(m.worst_final_score ?? 0); return s > 0 ? 1 / s : 1; } },
      ];

      el.innerHTML = categories.map(cat => {
        const raw = models.map(cat.fn);
        const total = raw.reduce((a, b) => a + b, 0) || 1;
        const size = 100, r = 36, ctr = 50;
        let cumAngle = -Math.PI / 2;
        let bestIdx = 0;
        raw.forEach((v, i) => { if (v > raw[bestIdx]) bestIdx = i; });

        let arcs = '';
        models.forEach((m, i) => {
          const frac = raw[i] / total;
          if (frac <= 0) return;
          const startAngle = cumAngle;
          const endAngle = cumAngle + frac * Math.PI * 2;
          cumAngle = endAngle;
          const large = frac > 0.5 ? 1 : 0;
          const x1 = ctr + r * Math.cos(startAngle);
          const y1 = ctr + r * Math.sin(startAngle);
          const x2 = ctr + r * Math.cos(endAngle - 0.001);
          const y2 = ctr + r * Math.sin(endAngle - 0.001);
          const mColor = m._color || '#888';
          const opacity = i === bestIdx ? 1 : 0.5;
          const pctLabel = (frac * 100).toFixed(1);
          const rawLabel = raw[i] < 1 ? raw[i].toFixed(3) : raw[i] < 100 ? raw[i].toFixed(1) : Math.round(raw[i]);
          arcs += `<path d="M${ctr},${ctr} L${x1},${y1} A${r},${r} 0 ${large} 1 ${x2},${y2} Z"
                    fill="${mColor}" opacity="${opacity}" data-tip="${m.model_profile}: ${rawLabel} (${pctLabel}%)" style="cursor:pointer"/>`;
        });

        // hollow centre
        arcs += `<circle cx="${ctr}" cy="${ctr}" r="${r * 0.55}" fill="var(--bg-card)"/>`;

        return `<div class="donut-cell">
          <div class="donut-label" data-tip="${cat.tip}">${cat.label}</div>
          <svg viewBox="0 0 ${size} ${size}" width="100" height="100">${arcs}</svg>
          <div class="donut-winner" data-tip="Leader: ${models[bestIdx].model_profile}">${models[bestIdx].model_profile}</div>
        </div>`;
      }).join('');
    }

    function renderRanking() {
      if (!models.length) {
        rankingBody.innerHTML = '<tr><td colspan="14" style="color:var(--text-dim)">No model stats.</td></tr>';
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
          <td>${row.avg_coverage_pct == null ? 'n/a' : `${formatFloat(row.avg_coverage_pct, 1)}%`}</td>
          <td>${formatFloat(row.avg_revisit_ratio, 2)}</td>
          <td>${row.avg_conversion_efficiency_pct == null ? 'n/a' : `${formatFloat(row.avg_conversion_efficiency_pct, 1)}%`}</td>
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
      ensureChildVisible(runList, active);
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
      const kpi = summary.kpi || {};
      const status = getRunStatus(summary);
      const deathCause = String(summary.death_cause_human || '').trim();
      const gatherableTotal = numberOr(run.replay?.world?.gatherable_total, null);
      const gathered = numberOr(summary.resources_gathered, 0);
      const gatheredLabel = gatherableTotal === null
        ? formatCount(gathered)
        : `${formatCount(gathered)}/${formatCount(gatherableTotal)}`;
      const coverageLabel = (kpi.coverage_pct !== null && kpi.coverage_pct !== undefined)
        ? `${formatFloat(kpi.coverage_pct, 1)}% (${formatCount(kpi.unique_cells_visited)}/${formatCount(kpi.map_cells_total)})`
        : formatCount(kpi.unique_cells_visited);
      const conversionLabel = (kpi.resource_conversion_efficiency_pct !== null && kpi.resource_conversion_efficiency_pct !== undefined)
        ? `${formatFloat(kpi.resource_conversion_efficiency_pct, 1)}%`
        : 'n/a';
      const failureMode = String(summary.primary_failure_archetype_human || summary.primary_failure_archetype || 'Balanced or unclear');
      const shortSummary = String(summary.short_summary || '').trim();
      const detailedSummary = String(summary.detailed_summary || '').trim();
      const confidenceHint = String(summary.confidence_hint || '').trim();
      const fallbackFacts = [summary.end_reason_human, deathCause]
        .map(value => String(value || '').trim())
        .filter(value => value.length > 0)
        .join(' | ');
      const summaryLine = shortSummary || fallbackFacts;
      const stripHtml = summaryLine
        ? `<div class="replay-sub-strip"><span class="replay-sub">${escapeHtml(summaryLine)}</span></div>`
        : '';

      const cards = [
        { label: 'Score', value: formatCount(summary.final_score), tip: 'Final score for this run (survive +1, gather +3, consume +2, invalid -2, death -10)' },
        { label: 'Survival', value: `${formatCount(summary.turns_survived)}/${formatCount(summary.max_turns)}`, tip: 'Turns survived out of maximum turns available' },
        { label: 'Invalid', value: formatCount(summary.invalid_actions), tip: 'Actions the model attempted that were not valid (e.g. eat without food)' },
        { label: 'Resources', value: gatheredLabel, tip: 'Resources gathered from the map out of total available' },
        { label: 'Failure mode', value: failureMode, tip: 'Primary deterministic failure archetype for this run' },
        confidenceHint ? { label: 'Confidence', value: confidenceHint, tip: 'Deterministic confidence hint from the rule engine' } : null,
        { label: 'Coverage', value: coverageLabel, tip: 'Unique visited cells over total map cells' },
        { label: 'Revisit ratio', value: formatFloat(kpi.revisit_ratio, 2), tip: 'Higher means more repeated movement over already visited cells' },
        { label: 'Conversion', value: conversionLabel, tip: 'Useful eat/drink conversions divided by gathered food+water' },
        { label: 'Dist / useful', value: formatFloat(kpi.distance_per_useful_gain, 2), tip: 'Successful move actions per useful event (lower is generally better)' },
        { label: 'Latency (total)', value: formatDurationFromMs(summary.latency_ms), tip: 'Total time spent waiting for API responses across all turns' },
        { label: 'Latency (avg)', value: (() => {
          const turns = Number(summary.turns_survived ?? 0);
          const total = Number(summary.latency_ms ?? 0);
          return turns > 0 ? formatDurationFromMs(total / turns) : 'n/a';
        })(), tip: 'Average API response time per turn' },
        { label: 'Tokens', value: formatCount(summary.tokens_used), tip: 'Total tokens consumed (input + output) across all turns' },
        { label: 'Cost', value: formatUsd(summary.estimated_cost), tip: 'Estimated run cost (provider-reported or deterministic fallback)' },
      ].filter(Boolean);

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
        ${stripHtml}
        <div class="summary-cards">
          ${cards.map(c => `<div class="card"${c.tip ? ` data-tip="${c.tip}"` : ''}><div class="label">${c.label}</div><div class="value">${c.value}</div></div>`).join('')}
        </div>
        ${switcherHtml}
        ${detailedSummary
          ? `<details class="analysis-detail"><summary>Deterministic Analysis</summary><div class="detail-body">${escapeHtml(detailedSummary)}</div></details>`
          : ''}
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
      ];
      let turnCost = metrics.estimated_cost;
      let turnCostApprox = false;
      if ((turnCost === null || turnCost === undefined || turnCost === '') && metrics.tokens_used != null) {
        const runCost = Number(run.summary?.estimated_cost);
        const runTokens = Number(run.summary?.tokens_used);
        const turnTokens = Number(metrics.tokens_used);
        if (
          Number.isFinite(runCost)
          && Number.isFinite(runTokens)
          && Number.isFinite(turnTokens)
          && runTokens > 0
          && turnTokens >= 0
        ) {
          turnCost = runCost * (turnTokens / runTokens);
          turnCostApprox = true;
        }
      }
      eventLines.push(`cost: ${formatUsd(turnCost)}${turnCostApprox ? ' (estimated)' : ''}`);
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
      const timelineWrap = timelineBody.closest('.timeline-wrap');
      ensureChildVisible(timelineWrap, selected);

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
      initTooltips();
      enrichModelsFromRuns();
      computeBadges();
      renderWinnerStrip();
      renderCompactLeaderboard();
      // mark default sort column
      document.querySelectorAll('th[data-sort-key="avg_final_score"]').forEach(th => th.classList.add('sort-desc'));
      renderMetaChips();
      renderProtocolPanel();
      renderRadarChart();
      renderDonutCharts();
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


def _short_path(path: Path) -> str:
    resolved = path.resolve()
    cwd = Path.cwd().resolve()
    try:
        return str(resolved.relative_to(cwd))
    except ValueError:
        return str(resolved)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate HTML compare dashboard from TinyWorld compare JSON")
    parser.add_argument("--compare", type=str, required=True, help="Path to compare JSON artifact")
    parser.add_argument("--output", type=str, default=None, help="Output HTML path")
    parser.add_argument("--title", type=str, default=None, help="Optional page title")
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the generated dashboard in your default browser.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    color_enabled = use_color()

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

    header = (
        colorize("TinyWorld Compare Viewer", "1;36", color_enabled)
        + " "
        + colorize(f"v{__version__}", "1;97", color_enabled)
    )
    print(header)
    print("Compare dashboard ready")
    print(f"  Compare JSON: {_short_path(compare_path)}")
    print(f"  HTML output:  {_short_path(generated)}")

    if args.open_browser:
        opened = webbrowser.open(generated.resolve().as_uri())
        if opened:
            print("  Browser:      opened in your default browser")
        else:
            print("  Browser:      generated, but failed to auto-open")
    else:
        print("  Browser:      not opened (use --open-browser)")


if __name__ == "__main__":
    main()
