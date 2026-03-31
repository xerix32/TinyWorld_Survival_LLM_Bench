"""Generate a multi-run/multi-model interactive HTML dashboard from compare artifacts."""

from __future__ import annotations

import argparse
import html
import json
import socket
import subprocess
from pathlib import Path
import sys
import time
from typing import Any
from urllib.parse import quote
import webbrowser

from bench.cli_ui import colorize, use_color
from bench.pricing import estimate_cost_from_total_tokens, load_pricing_config, resolve_model_pricing
from engine.version import __version__


def render_html(payload: dict[str, Any], page_title: str) -> str:
    safe_title = html.escape(page_title)
    payload_json = json.dumps(payload, ensure_ascii=False)
    payload_json = payload_json.replace("</", "<\\/")
    arcade_template_path = Path(__file__).resolve().parent.parent / "showcase" / "tinyworld_arcade_engine_template.html"
    arcade_template_html = ""
    if arcade_template_path.exists():
        arcade_template_html = arcade_template_path.read_text(encoding="utf-8")
    arcade_template_json = json.dumps(arcade_template_html, ensure_ascii=False).replace("</", "<\\/")

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
      max-width: 1600px;
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
    .micro-badge.badge-premium { background: rgba(234,179,8,0.12); color: #eab308; }
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
    .winner-strip .ws-score-duo {
      display: grid;
      grid-template-columns: repeat(2, minmax(110px, 1fr));
      gap: 14px;
      align-items: center;
    }
    .winner-strip .ws-score {
      font-family: var(--font-mono);
      font-size: 1.5rem;
      font-weight: 800;
      color: var(--text);
      line-height: 1;
    }
    .winner-strip .ws-score-adaptive {
      color: var(--accent);
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
      overflow: hidden;
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

    /* ── BADGE RACE ── */
    .badge-race-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px 32px;
      padding: 8px 0;
    }
    @media (max-width: 800px) {
      .badge-race-grid { grid-template-columns: 1fr; }
    }
    .badge-race-cell {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .badge-race-title {
      font-family: var(--font-mono);
      font-size: 0.72rem;
      font-weight: 700;
      color: var(--text-secondary);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .badge-race-row {
      display: grid;
      grid-template-columns: 120px 1fr 45px;
      gap: 8px;
      align-items: center;
      height: 20px;
    }
    .badge-race-name {
      font-family: var(--font-mono);
      font-size: 0.65rem;
      font-weight: 600;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      text-align: right;
    }
    .badge-race-track {
      height: 14px;
      background: var(--bg-raised);
      border-radius: 4px;
      overflow: hidden;
    }
    .badge-race-fill {
      height: 100%;
      border-radius: 4px;
      min-width: 2px;
    }
    .badge-race-val {
      font-family: var(--font-mono);
      font-size: 0.65rem;
      font-weight: 700;
      color: var(--text);
      text-align: left;
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

    .protocol-summary {
      color: var(--text-secondary);
      font-size: 0.75rem;
      font-family: var(--font-mono);
      line-height: 1.45;
      border-top: 1px dashed var(--border);
      padding-top: 8px;
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
    .table-wrap.expanded { max-height: none; }
    .lb-expand-btn {
      display: block;
      margin: 6px auto 0;
      padding: 4px 16px;
      font-size: 0.7rem;
      font-family: var(--font-mono);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--text-secondary);
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      cursor: pointer;
      transition: all 0.15s;
    }
    .lb-expand-btn:hover { color: var(--text); border-color: var(--border-bright); }

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

    button:disabled,
    button:disabled:hover {
      border-color: #2b2c31;
      color: #5b5d66;
      background: #14151a;
      cursor: not-allowed;
      box-shadow: none;
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

    .npc-stack {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      align-items: center;
      gap: 2px;
      min-height: 14px;
      margin-top: 1px;
    }

    .npc-pill {
      border: 1px solid rgba(251, 146, 60, 0.45);
      background: rgba(251, 146, 60, 0.16);
      border-radius: 999px;
      padding: 0 4px;
      font-family: var(--font-mono);
      font-size: 0.52rem;
      font-weight: 700;
      color: #fdba74;
      line-height: 1.4;
      white-space: nowrap;
    }

    .npc-pill.hostile {
      border-color: rgba(248, 113, 113, 0.5);
      background: rgba(248, 113, 113, 0.16);
      color: #fca5a5;
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

    .agent-stack {
      position: absolute;
      left: 2px;
      right: 2px;
      bottom: 2px;
      display: grid;
      gap: 2px;
      pointer-events: none;
    }

    .agent-mark.opponent {
      border: 1px solid rgba(248, 113, 113, 0.45);
      background: rgba(248, 113, 113, 0.2);
      color: #fca5a5;
    }

    .map-legend {
      font-family: var(--font-mono);
      color: var(--text-dim);
      font-size: 0.68rem;
    }

    .map-summary-cards {
      margin-top: 4px;
      border-radius: 6px;
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

    .npc-grid {
      display: grid;
      gap: 4px;
    }

    .npc-item {
      border: 1px solid var(--border);
      border-radius: 4px;
      background: var(--bg-card);
      padding: 5px 8px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      font-family: var(--font-mono);
      font-size: 0.72rem;
      color: var(--text-secondary);
    }

    .npc-item.hostile {
      border-color: rgba(248, 113, 113, 0.45);
      background: rgba(248, 113, 113, 0.08);
      color: #fca5a5;
    }

    .npc-item .npc-hp {
      color: var(--text);
      font-weight: 700;
    }

    .npc-empty {
      border: 1px dashed var(--border);
      border-radius: 4px;
      padding: 6px 8px;
      font-family: var(--font-mono);
      font-size: 0.7rem;
      color: var(--text-dim);
      text-align: center;
    }

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

    [data-theme="light"] .npc-pill {
      border-color: rgba(194, 65, 12, 0.45);
      background: rgba(234, 88, 12, 0.1);
      color: #9a3412;
    }

    [data-theme="light"] .npc-pill.hostile {
      border-color: rgba(185, 28, 28, 0.45);
      background: rgba(220, 38, 38, 0.08);
      color: #991b1b;
    }

    [data-theme="light"] .npc-item.hostile {
      border-color: rgba(220, 38, 38, 0.45);
      background: rgba(220, 38, 38, 0.06);
      color: #991b1b;
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

    /* ── ARCADE TAB ── */
    .arcade-layout {
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
    }

    .arcade-sidebar {
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--bg-raised);
      padding: 10px;
      display: grid;
      gap: 10px;
      position: sticky;
      top: 12px;
    }

    .arcade-shell {
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      overflow: hidden;
      background: #05070f;
      min-height: 700px;
    }

    .arcade-frame {
      width: 100%;
      height: 82vh;
      min-height: 700px;
      border: 0;
      display: block;
      background: #05070f;
    }

    .arcade-meta {
      font-family: var(--font-mono);
      font-size: 0.74rem;
      color: var(--text-secondary);
      margin: 0;
      letter-spacing: 0.02em;
      display: none;
    }

    .arcade-controls {
      display: flex;
      flex-direction: column;
      align-items: stretch;
      gap: 8px;
      margin: 0;
    }

    .arcade-controls label {
      display: grid;
      grid-template-columns: 1fr;
      gap: 6px;
      font-family: var(--font-mono);
      font-size: 0.7rem;
      color: var(--text-dim);
      letter-spacing: 0.03em;
      min-width: 0;
    }

    .arcade-controls select {
      min-width: 0;
      width: 100%;
      font-size: 0.72rem;
      padding: 6px 8px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .arcade-nav-row {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 8px;
    }

    .arcade-note {
      margin-top: 0;
      font-family: var(--font-mono);
      font-size: 0.7rem;
      color: var(--text-dim);
      letter-spacing: 0.02em;
      border-top: 1px solid var(--border);
      padding-top: 8px;
      line-height: 1.35;
      overflow-wrap: anywhere;
      word-break: break-word;
    }

    .arcade-runid {
      font-family: var(--font-mono);
      font-size: 0.7rem;
      color: var(--text-secondary);
      letter-spacing: 0.02em;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--bg-card);
      padding: 6px 8px;
      line-height: 1.35;
      overflow-wrap: anywhere;
      word-break: break-word;
    }

    .arcade-attempt {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 20px;
    }

    .arcade-attempt-label {
      font-family: var(--font-mono);
      font-size: 0.68rem;
      color: var(--text-dim);
      letter-spacing: 0.03em;
    }

    .arcade-attempt-badge {
      display: inline;
      font-family: var(--font-mono);
      font-size: 0.76rem;
      font-weight: 800;
      letter-spacing: 0.02em;
      text-transform: uppercase;
      color: var(--text-secondary);
    }

    .arcade-attempt-badge.kind-initial {
      color: var(--green);
    }

    .arcade-attempt-badge.kind-rerun {
      color: var(--orange);
    }

    .arcade-attempt-badge.kind-rerun-mem {
      color: var(--accent);
    }

    /* ── RESPONSIVE ── */
    @media (max-width: 1100px) {
      .explorer-layout { grid-template-columns: 1fr; }
      .replay-grid { grid-template-columns: 1fr; }
      .summary-cards { grid-template-columns: repeat(4, 1fr); }
      .filter-row { grid-template-columns: 1fr; }
      .sidebar { max-height: none; }
      .arcade-layout { grid-template-columns: 1fr; }
      .arcade-sidebar { position: static; }
      .arcade-shell { min-height: 520px; }
      .arcade-frame { min-height: 520px; height: 72vh; }
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
      <button class=\"tab-btn\" data-tab=\"arcade\" type=\"button\">Arcade Render</button>
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
                <th data-tip=\"Average score with adaptive memory (higher = memory helps)\" class=\"tip-down adaptive-col\" data-sort-key=\"adaptive_avg_score\" data-sort-desc=\"1\" style=\"display:none\">Adaptive</th>
                <th data-tip=\"Score spread: worst to best run. Dot = average.\" class=\"tip-down\">Range</th>
                <th data-tip=\"Percentage of runs where the agent survived all turns (strict: reached max turns)\" class=\"tip-down\" data-sort-key=\"survival_pct\" data-sort-desc=\"1\">Survival</th>
                <th data-tip=\"PvP survival rate: percentage of runs where the agent did not die (won or outlasted)\" class=\"tip-down pvp-col\" data-sort-key=\"vs_survival_pct\" data-sort-desc=\"1\" style=\"display:none\">VS Survival</th>
                <th data-tip=\"Average API response time per turn\" class=\"tip-down\" data-sort-key=\"latency_per_turn\">Latency</th>
                <th data-tip=\"Estimated total cost across all runs\" class=\"tip-down\" data-sort-key=\"estimated_cost_grand_total\">Cost</th>
                <th data-tip=\"Average input / output tokens per run (high output ratio may indicate thinking)\" class=\"tip-down\" data-sort-key=\"completion_tokens_avg\" data-sort-desc=\"1\">I/O Tokens</th>
                <th data-tip=\"Average map coverage percentage\" class=\"tip-down\" data-sort-key=\"avg_coverage_pct\" data-sort-desc=\"1\">Coverage</th>
                <th data-tip=\"Average total attack actions per run (higher = more aggressive behavior)\" class=\"tip-down\" data-sort-key=\"avg_attack_count\" data-sort-desc=\"1\">Aggression</th>
                <th data-tip=\"Average total kills per run (NPC + rival agents)\" class=\"tip-down\" data-sort-key=\"avg_total_kills\" data-sort-desc=\"1\">Kills</th>
                <th data-tip=\"Among duel runs with at least one attack, percentage where this model attacked first\" class=\"tip-down\" data-sort-key=\"first_strike_pct\" data-sort-desc=\"1\">First Strike</th>
                <th data-tip=\"Share of attacks directed at rival agents (avg_attack_rival_count / avg_attack_count)\" class=\"tip-down\" data-sort-key=\"rival_attack_share_pct\" data-sort-desc=\"1\">Rival Focus</th>
                <th data-tip=\"Average moral aggression index (0-100, higher = less restrained)\" class=\"tip-down moral-col\" data-sort-key=\"avg_moral_aggression_index\" data-sort-desc=\"1\">Moral Aggr</th>
              </tr>
            </thead>
            <tbody id=\"lbBody\"></tbody>
          </table>
        </div>
        <button class=\"lb-expand-btn\" id=\"lbExpandBtn\" type=\"button\">Show all</button>
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
        <div class=\"panel-title\" data-tip=\"How each model scored in every badge category. Taller bar = stronger contender.\" class=\"tip-down\">Badge Race</div>
        <div id=\"badgeRaceGrid\" class=\"badge-race-grid\"></div>
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
                <th data-tip=\"Average total attack actions per run\" class=\"tip-down\" data-sort-key=\"avg_attack_count\" data-sort-desc=\"1\">Avg Attack</th>
                <th data-tip=\"Average NPC kills per run\" class=\"tip-down\" data-sort-key=\"avg_npc_kills\" data-sort-desc=\"1\">Avg NPC Kills</th>
                <th data-tip=\"Average rival-agent kills per run\" class=\"tip-down\" data-sort-key=\"avg_rival_kills\" data-sort-desc=\"1\">Avg Rival Kills</th>
                <th data-tip=\"Among duel runs with at least one attack, percentage where this model attacked first\" class=\"tip-down\" data-sort-key=\"first_strike_pct\" data-sort-desc=\"1\">First Strike</th>
                <th data-tip=\"Share of attacks directed at rival agents (avg_attack_rival_count / avg_attack_count)\" class=\"tip-down\" data-sort-key=\"rival_attack_share_pct\" data-sort-desc=\"1\">Rival Focus</th>
                <th data-tip=\"Average moral aggression index (0-100)\" class=\"tip-down moral-col\" data-sort-key=\"avg_moral_aggression_index\" data-sort-desc=\"1\">Avg Moral</th>
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

      <div class=\"panel\" id=\"adaptiveLearningPanel\" style=\"display:none\">
        <div class=\"panel-title\" data-tip=\"Adaptive Learning KPIs: how well each model iterates and improves its strategy across seeds. Higher composite score = better adaptive learner.\" class=\"tip-down\">Adaptive Learning Leaderboard</div>
        <div id=\"adaptiveLearningGrid\" class=\"badge-race-grid\"></div>
        <div class=\"table-wrap\" style=\"margin-top:16px\">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Model</th>
                <th data-kpi-sort=\"avg_memory_effect\" data-tip=\"Average memory effect across all seeds\" class=\"tip-down\" style=\"cursor:pointer\">Avg Mem</th>
                <th data-kpi-sort=\"composite_score\" data-tip=\"Composite score: weighted blend of PDI (60%), MPR (30%), SMER (10%) — empirically calibrated to predict memory benefit\" class=\"tip-down\" style=\"cursor:pointer\">Score ▼</th>
                <th data-kpi-sort=\"pdi\" data-tip=\"Policy Diversity Index: how much the policy text evolves across seeds (0=identical, 1=completely different)\" class=\"tip-down\" style=\"cursor:pointer\">PDI</th>
                <th data-kpi-sort=\"mpr\" data-tip=\"Memory Promotion Rate: fraction of seeds where reflections were promoted to memory\" class=\"tip-down\" style=\"cursor:pointer\">MPR</th>
                <th data-kpi-sort=\"smer\" data-tip=\"Session Memory Evolution Rate: average lesson changes per seed transition\" class=\"tip-down\" style=\"cursor:pointer\">SMER</th>
                <th data-kpi-sort=\"ccs\" data-tip=\"Confidence Calibration Score: correlation between stated confidence and actual memory effect (-1..+1)\" class=\"tip-down\" style=\"cursor:pointer\">CCS</th>
                <th data-tip=\"Memory effect per seed\" class=\"tip-down\">Per Seed</th>
              </tr>
            </thead>
            <tbody id=\"adaptiveLearningBody\"></tbody>
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
          <div class=\"field\">
            <span class=\"field-label\">Attempt</span>
            <select id=\"attemptFilter\"></select>
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
              <div class=\"summary-cards map-summary-cards\" id=\"mapSummaryCards\"></div>
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

              <div class=\"detail-section\">
                <div class=\"detail-label\">NPCs Nearby</div>
                <div class=\"npc-grid\" id=\"npcGrid\"></div>
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

    <!-- TAB 3: ARCADE RENDER -->
    <div class=\"tab-panel\" id=\"tab-arcade\">
      <section class=\"panel\">
        <div class=\"arcade-layout\">
          <aside class=\"arcade-sidebar\">
            <div class=\"arcade-meta\" id=\"arcadeMeta\"></div>
            <div class=\"arcade-controls\">
              <label>Seed
                <select id=\"arcadeSeedSelect\"></select>
              </label>
              <label>Run
                <select id=\"arcadeRunSelect\"></select>
              </label>
              <div class=\"arcade-nav-row\">
                <button type=\"button\" id=\"arcadePrevBtn\">&#9664; Prev</button>
                <button type=\"button\" id=\"arcadePlayBtn\">Play</button>
                <button type=\"button\" id=\"arcadeNextBtn\">Next &#9654;</button>
              </div>
              <div class=\"arcade-attempt\">
                <div class=\"arcade-attempt-label\">Run type:</div>
                <div class=\"arcade-attempt-badge\" id=\"arcadeAttemptBadge\">n/a</div>
              </div>
            </div>
            <div class=\"arcade-runid\" id=\"arcadeRunId\">run_id: n/a</div>
            <div class=\"arcade-note\" id=\"arcadeNote\">Source run: n/a.</div>
          </aside>
          <div class=\"arcade-shell\">
            <iframe id=\"arcadeFrame\" class=\"arcade-frame\" title=\"TinyWorld Arcade Renderer\" loading=\"lazy\"></iframe>
          </div>
        </div>
      </section>
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
    html_arcade_template = '<script id="arcadeEngineTemplate" type="application/json">' + arcade_template_json + "</script>"

    html_tail = """
  <script>
    const DATA = JSON.parse(document.getElementById('compareData').textContent || '{}');
    const ARCADE_ENGINE_TEMPLATE = JSON.parse(document.getElementById('arcadeEngineTemplate').textContent || '""');

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
    const attemptFilter = document.getElementById('attemptFilter');

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
    const mapSummaryCards = document.getElementById('mapSummaryCards');

    const turnStatus = document.getElementById('turnStatus');
    const stateMeters = document.getElementById('stateMeters');
    const inventoryGrid = document.getElementById('inventoryGrid');
    const npcGrid = document.getElementById('npcGrid');
    const rawOutput = document.getElementById('rawOutput');
    const scoreEvents = document.getElementById('scoreEvents');
    const timelineBody = document.getElementById('timelineBody');
    const arcadeFrame = document.getElementById('arcadeFrame');
    const arcadeMeta = document.getElementById('arcadeMeta');
    const arcadeNote = document.getElementById('arcadeNote');
    const arcadePrevBtn = document.getElementById('arcadePrevBtn');
    const arcadePlayBtn = document.getElementById('arcadePlayBtn');
    const arcadeNextBtn = document.getElementById('arcadeNextBtn');
    const arcadeSeedSelect = document.getElementById('arcadeSeedSelect');
    const arcadeRunSelect = document.getElementById('arcadeRunSelect');
    const arcadeAttemptBadge = document.getElementById('arcadeAttemptBadge');
    const arcadeRunId = document.getElementById('arcadeRunId');

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
    models.forEach((m, i) => {
      m._color = MODEL_COLORS[i % MODEL_COLORS.length];
      // Fallback for older JSON without grand_total fields
      if (m.estimated_cost_grand_total == null && m.estimated_cost_total != null) {
        m.estimated_cost_grand_total = m.estimated_cost_total;
      }
    });
    const pairwise = Array.isArray(DATA.pairwise) ? DATA.pairwise : [];
    const runs = Array.isArray(DATA.runs) ? DATA.runs : [];
    const runById = new Map(
      runs
        .filter(run => run && run.run_id !== undefined && run.run_id !== null)
        .map(run => [String(run.run_id), run])
    );
    const meta = DATA.meta || {};
    const dashboardRunId = String(meta.run_id || meta.compare_id || meta.session_id || 'n/a');
    const duelView = (DATA.duel_view && typeof DATA.duel_view === 'object') ? DATA.duel_view : null;
    const canonicalDuels = Array.isArray(DATA.duels) ? DATA.duels : [];
    const duelEntries = canonicalDuels.length > 0
      ? canonicalDuels
      : (Array.isArray(duelView?.duels) ? duelView.duels : []);
    const duelMode = duelEntries.length > 0;
    const legacyPvpMode = !duelMode && runs.some(run => Boolean(run?.summary?.pvp_duel));
    const adaptiveSection = (DATA.adaptive && typeof DATA.adaptive === 'object') ? DATA.adaptive : null;
    const adaptiveModelRows = Array.isArray(adaptiveSection?.models) ? adaptiveSection.models : [];
    // Compute adaptive-only average from pairs (excluding control runs)
    const adaptiveAvgByProfile = new Map();
    if (Array.isArray(adaptiveSection?.pairs)) {
      const byProfile = {};
      for (const p of adaptiveSection.pairs) {
        const mp = String(p.model_profile || '');
        if (!byProfile[mp]) byProfile[mp] = [];
        const score = Number(p.adaptive_score);
        if (Number.isFinite(score)) byProfile[mp].push(score);
      }
      for (const [mp, scores] of Object.entries(byProfile)) {
        if (scores.length) adaptiveAvgByProfile.set(mp, scores.reduce((a, b) => a + b, 0) / scores.length);
      }
    }
    const memoryEffectByProfile = new Map(
      (adaptiveSection?.learning_kpis || [])
        .map(k => [String(k?.model_profile || ''), Number(k?.avg_memory_effect ?? 0)])
        .filter((entry) => Number.isFinite(entry[1]))
    );
    // Compute no-memory average (avg of initial + control) from pairs
    const noMemAvgByProfile = new Map();
    if (Array.isArray(adaptiveSection?.pairs)) {
      const byProfile = {};
      for (const p of adaptiveSection.pairs) {
        const mp = String(p.model_profile || '');
        if (!byProfile[mp]) byProfile[mp] = [];
        const init = Number(p.initial_score);
        const ctrl = Number(p.control_score);
        if (Number.isFinite(init)) byProfile[mp].push(init);
        if (Number.isFinite(ctrl)) byProfile[mp].push(ctrl);
      }
      for (const [mp, scores] of Object.entries(byProfile)) {
        if (scores.length) noMemAvgByProfile.set(mp, scores.reduce((a, b) => a + b, 0) / scores.length);
      }
    }
    const normalizeMoralMode = (raw) => {
      if (typeof raw === 'boolean') return raw ? 'on' : 'off';
      const text = String(raw ?? '').trim().toLowerCase();
      if (!text) return null;
      if (text === 'true' || text === 'on') return 'on';
      if (text === 'false' || text === 'off') return 'off';
      return text;
    };
    const moralModesObserved = new Set(
      [normalizeMoralMode(meta?.moral_mode), ...runs.map(row => normalizeMoralMode(row?.summary?.moral_mode))].filter(Boolean)
    );
    const hasMoralFraming = moralModesObserved.has('on') || moralModesObserved.has('mixed');
    const hasAdaptive = adaptiveAvgByProfile.size > 0;
    const isPvpDataset = duelMode || legacyPvpMode;

    // Override avg_final_score with no-memory avg (initial+control) globally
    for (const m of models) {
      if (noMemAvgByProfile.has(m.model_profile)) {
        m.avg_final_score = noMemAvgByProfile.get(m.model_profile);
      }
    }
    // Re-sort and re-rank models after avg_final_score override
    models.sort((a, b) => (b.avg_final_score ?? 0) - (a.avg_final_score ?? 0));
    models.forEach((m, i) => { m.rank = i + 1; });

    let selectedRunIndex = 0;
    let filteredRunIndexes = [];
    let selectedDuelIndex = 0;
    let filteredDuelIndexes = [];
    const duelFocusByKey = {};
    let currentTurnIndex = 0;
    let autoPlayTimer = null;
    let arcadeCacheKey = '';
    const arcadeDataCache = new Map();
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
        if (btn.getAttribute('data-tab') === 'arcade') {
          renderArcade(true);
        }
      });
    });

    /* ── Leaderboard expand/collapse ── */
    const lbExpandBtn = document.getElementById('lbExpandBtn');
    if (lbExpandBtn) {
      const lbWrap = lbExpandBtn.previousElementSibling;
      lbExpandBtn.addEventListener('click', () => {
        const expanded = lbWrap.classList.toggle('expanded');
        lbExpandBtn.textContent = expanded ? 'Collapse' : 'Show all';
      });
    }

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

    function displayName(profile) {
      return String(profile || '')
        .replace(/^vercel_/, '')
        .replace(/_/g, ' ');
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
      const text = String(value || 'model')
        .trim()
        .replace(/^vercel_/, '')
        .replace(/^local_/, '')
        .replace(/^groq_/, '');
      return text.length <= 18 ? text : `${text.slice(0, 18)}...`;
    }

    function npcEmoji(npcType) {
      const t = String(npcType || '').toLowerCase();
      if (t.includes('animal') || t.includes('cow') || t.includes('boar') || t.includes('deer')) return '\\u{1F404}';
      if (t.includes('wolf') || t.includes('tiger') || t.includes('bear')) return '\\u{1F43A}';
      return '\\u{1F43E}';
    }

    function normalizeNpcState(raw) {
      if (!raw || typeof raw !== 'object') return null;
      const npcId = String(raw.npc_id || '').trim();
      if (!npcId) return null;
      const pos = (raw.position && typeof raw.position === 'object') ? raw.position : raw;
      const x = numberOr(pos.x, Number.NaN);
      const y = numberOr(pos.y, Number.NaN);
      return {
        npc_id: npcId,
        npc_type: String(raw.npc_type || 'npc'),
        x,
        y,
        hp: (raw.hp === null || raw.hp === undefined) ? null : numberOr(raw.hp, null),
        hostile: Boolean(raw.hostile),
        alive: raw.alive === undefined ? true : Boolean(raw.alive),
      };
    }

    function buildNpcStatesForFrame(run, frameIndex) {
      const states = new Map();
      const world = run?.replay?.world || {};
      const initial = Array.isArray(world.initial_npcs) ? world.initial_npcs : [];
      for (const raw of initial) {
        const npc = normalizeNpcState(raw);
        if (npc) states.set(npc.npc_id, npc);
      }

      const frames = Array.isArray(run?.replay?.frames) ? run.replay.frames : [];
      if (!frames.length) return Array.from(states.values());
      const last = Math.max(0, Math.min(frameIndex, frames.length - 1));

      for (let i = 0; i <= last; i++) {
        const frame = frames[i] || {};
        const visible = Array.isArray(frame.observation?.visible_npcs) ? frame.observation.visible_npcs : [];
        for (const raw of visible) {
          const npc = normalizeNpcState(raw);
          if (!npc) continue;
          const prev = states.get(npc.npc_id);
          states.set(npc.npc_id, { ...(prev || {}), ...npc });
        }

        const actionDelta = frame.world_result_delta?.action_delta || {};
        const npcId = String(actionDelta.npc_id || '').trim();
        if (!npcId) continue;

        const prev = states.get(npcId) || {
          npc_id: npcId,
          npc_type: String(actionDelta.npc_type || 'npc'),
          x: Number.NaN,
          y: Number.NaN,
          hp: null,
          hostile: false,
          alive: true,
        };
        const next = { ...prev };
        if (actionDelta.npc_type !== undefined) next.npc_type = String(actionDelta.npc_type || next.npc_type || 'npc');
        if (actionDelta.npc_hp_after !== undefined) next.hp = numberOr(actionDelta.npc_hp_after, next.hp);
        if (actionDelta.npc_hostile_after !== undefined) next.hostile = Boolean(actionDelta.npc_hostile_after);
        if (actionDelta.npc_alive_after !== undefined) next.alive = Boolean(actionDelta.npc_alive_after);
        states.set(npcId, next);
      }

      return Array.from(states.values()).sort((a, b) => {
        const ay = Number.isFinite(a.y) ? a.y : 9999;
        const by = Number.isFinite(b.y) ? b.y : 9999;
        if (ay !== by) return ay - by;
        const ax = Number.isFinite(a.x) ? a.x : 9999;
        const bx = Number.isFinite(b.x) ? b.x : 9999;
        if (ax !== bx) return ax - bx;
        return String(a.npc_id || '').localeCompare(String(b.npc_id || ''));
      });
    }

    function adaptiveAvgScoreForModel(modelProfile) {
      const raw = adaptiveAvgByProfile.get(String(modelProfile || ''));
      return Number.isFinite(raw) ? raw : null;
    }

    function syncConditionalColumns() {
      document.querySelectorAll('.adaptive-col').forEach(el => { el.style.display = hasAdaptive ? '' : 'none'; });
      document.querySelectorAll('.pvp-col').forEach(el => { el.style.display = isPvpDataset ? '' : 'none'; });
      document.querySelectorAll('.moral-col').forEach(el => { el.style.display = hasMoralFraming ? '' : 'none'; });
    }

    function getRunAttemptKind(run) {
      const raw = String(
        run?.attempt_kind
          ?? run?.summary?.attempt_kind
          ?? 'initial'
      ).trim();
      if (!raw) return 'initial';
      return raw;
    }

    function attemptSortIndex(kind) {
      if (kind === 'initial') return 1;
      if (kind === 'control_rerun') return 2;
      if (kind === 'adaptive_rerun') return 3;
      return 9;
    }

    function attemptLabel(kind) {
      if (kind === 'initial') return 'initial';
      if (kind === 'control_rerun') return 'rerun';
      if (kind === 'adaptive_rerun') return 'rerun+mem';
      return String(kind || 'run').replaceAll('_', ' ');
    }

    function attemptBadgeClass(kind) {
      if (kind === 'initial') return 'kind-initial';
      if (kind === 'control_rerun') return 'kind-rerun';
      if (kind === 'adaptive_rerun') return 'kind-rerun-mem';
      return '';
    }

    function setArcadeAttemptBadge(kind) {
      if (!arcadeAttemptBadge) return;
      const cls = attemptBadgeClass(kind);
      arcadeAttemptBadge.className = `arcade-attempt-badge${cls ? ` ${cls}` : ''}`;
      arcadeAttemptBadge.textContent = attemptLabel(kind || 'run');
    }

    function getRunStatus(summary) {
      const endReason = String(summary?.end_reason || '');
      if (endReason === 'agent_dead') {
        return { key: 'dead', label: 'Died', className: 'bad' };
      }
      return { key: 'finished', label: 'Survived', className: 'ok' };
    }

    function getDuelAttemptKind(duel) {
      const raw = String(duel?.attempt_kind || 'initial').trim();
      return raw || 'initial';
    }

    function getDuelStatus(duel, modelProfile) {
      const profile = String(modelProfile || '').trim();
      if (!profile) return { key: 'unknown', label: 'Unknown', className: '' };

      const summaryByModel = duel?.summary_by_model;
      const duelSummary = (summaryByModel && typeof summaryByModel === 'object')
        ? summaryByModel[profile]
        : null;
      if (duelSummary && typeof duelSummary === 'object') {
        const endReason = String(duelSummary.end_reason || '').trim();
        if (endReason === 'agent_dead') return { key: 'dead', label: 'Died', className: 'bad' };
        if (endReason === 'opponent_defeated' || endReason === 'max_turns_reached') {
          return { key: 'finished', label: 'Survived', className: 'ok' };
        }
        const key = String(duelSummary.status || '').trim().toLowerCase();
        if (key === 'dead') return { key: 'dead', label: 'Died', className: 'bad' };
        if (key === 'finished') return { key: 'finished', label: 'Survived', className: 'ok' };
      }

      const runIdByModel = (duel?.run_id_by_model && typeof duel.run_id_by_model === 'object')
        ? duel.run_id_by_model
        : {};
      const run = runById.get(String(runIdByModel[profile] || ''));
      if (run?.summary) return getRunStatus(run.summary);
      return { key: 'unknown', label: 'Unknown', className: '' };
    }

    function getDuelScore(duel, modelProfile) {
      const profile = String(modelProfile || '').trim();
      const summaryByModel = duel?.summary_by_model;
      const duelSummary = (summaryByModel && typeof summaryByModel === 'object')
        ? summaryByModel[profile]
        : null;
      if (duelSummary && typeof duelSummary === 'object' && duelSummary.final_score != null) {
        return Number(duelSummary.final_score);
      }
      const runIdByModel = (duel?.run_id_by_model && typeof duel.run_id_by_model === 'object')
        ? duel.run_id_by_model
        : {};
      const run = runById.get(String(runIdByModel[profile] || ''));
      const score = Number(run?.summary?.final_score);
      return Number.isFinite(score) ? score : null;
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
      const legacyPvpWarning = legacyPvpMode
        ? { message: 'legacy per-run perspective; switch may diverge' }
        : null;
      const effectiveCompatibilityWarnings = legacyPvpWarning
        ? [...compatibilityWarnings, legacyPvpWarning]
        : compatibilityWarnings;
      const modelCosts = models
        .map(modelRow => Number(modelRow?.estimated_cost_grand_total))
        .filter(value => Number.isFinite(value));
      const totalModelCost = modelCosts.length > 0
        ? modelCosts.reduce((sum, value) => sum + value, 0)
        : null;
      const baselineScoreTotal = (() => {
        const raw = Number(adaptiveSection?.baseline_totals?.score_total);
        if (Number.isFinite(raw)) return raw;
        const fallback = Number(meta.total_score);
        return Number.isFinite(fallback) ? fallback : null;
      })();
      const adaptiveScoreTotal = (() => {
        const raw = Number(adaptiveSection?.adaptive_totals?.score_total);
        if (Number.isFinite(raw)) return raw;
        const fallback = Number(meta.adaptive_aggregate_score);
        return Number.isFinite(fallback) ? fallback : null;
      })();
      const moralMode = (() => {
        const metaMode = normalizeMoralMode(meta?.moral_mode);
        if (metaMode) return metaMode;

        const modes = Array.from(new Set(
          (runs || [])
            .map(row => normalizeMoralMode(row?.summary?.moral_mode))
            .filter(Boolean)
        ));
        if (modes.length === 1) return modes[0];
        if (modes.length > 1) return 'mixed';
        return 'not available';
      })();

      const protocolBtn = `<button class="chip chip-btn" id="protocolChip" type="button" data-tip="Click to show the full game rules, stat mechanics, and scoring logic"><span class="chip-key">protocol</span> <span class="chip-val">${meta.protocol_version || '-'}</span></button>`;
      const chips = [
        protocolBtn,
        chip('bench', meta.bench_version || '-', 'Version of the benchmark harness that ran the tests'),
        chip('engine', meta.engine_version || '-', 'Version of the TinyWorld simulation engine'),
        chip('scenario', meta.scenario || '-', 'The map and rules configuration used for this benchmark'),
        chip('moral', moralMode, 'Optional moral framing in system prompt (on/off). Mixed means runs used different settings'),
        chip('models', formatCount(meta.models?.length || models.length), 'Number of distinct AI models tested'),
        chip('runs/model', formatCount(meta.runs_per_model), 'How many runs each model played (one per seed)'),
        chip('total runs', formatCount(meta.total_runs || runs.length), 'Total number of runs across all models and seeds'),
        chip('seeds', (meta.seed_list || []).join(', ') || '-', 'Random seeds used for map generation. Same seeds = same maps for all models'),
        chip('total compare time', formatDurationFromMs(compareDurationMs), 'Wall-clock compare duration (from compare start id timestamp to artifact generation)'),
        chip('total model time', formatDurationFromMs(totalModelTimeMs || null), 'Sum of all model API latency across all runs'),
        chip('estimated cost total', formatUsd(totalModelCost, 'not available'), 'Estimated total USD cost across all runs (provider-reported or deterministic fallback)'),
        chip('compatibility', effectiveCompatibilityWarnings.length ? 'warnings' : 'ok', 'Cross-run metadata consistency (protocol, prompt hash, bench version, engine version)'),
        chip('prompt', String(meta.prompt_set_sha256 || '-').slice(0, 12), 'SHA-256 hash of the prompt set. Same hash = identical prompts across runs'),
        chip('fairness', 'paired seeds', 'All models play the exact same maps (paired seeds) so score differences reflect model ability, not map luck'),
      ];
      if (baselineScoreTotal != null) {
        chips.push(
          chip(
            'total score',
            formatCount(baselineScoreTotal),
            'Aggregate baseline score total from initial (non-memory) attempts'
          )
        );
      }
      if (adaptiveScoreTotal != null) {
        chips.push(
          chip(
            'adaptive total score',
            formatCount(adaptiveScoreTotal),
            'Aggregate adaptive score total from memory-injected reruns'
          )
        );
      }
      metaChips.innerHTML = chips.join('');

      if (compatWarnings) {
        if (!effectiveCompatibilityWarnings.length) {
          compatWarnings.innerHTML = '';
        } else {
          compatWarnings.innerHTML = effectiveCompatibilityWarnings
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
      const matchTurnsRaw = Number(meta?.max_turns ?? runs[0]?.summary?.max_turns ?? 50);
      const matchTurns = Number.isFinite(matchTurnsRaw) && matchTurnsRaw > 0 ? Math.round(matchTurnsRaw) : 50;
      const startEnergy = numberOr(rules.start_energy, '-');
      const startHunger = numberOr(rules.start_hunger, '-');
      const startThirst = numberOr(rules.start_thirst, '-');
      const passiveEnergyLoss = numberOr(rules.passive_energy_loss, 0);
      const passiveHungerGain = numberOr(rules.passive_hunger_gain, '-');
      const passiveThirstGain = numberOr(rules.passive_thirst_gain, '-');
      const starvationPenalty = numberOr(rules.starvation_energy_penalty, 0);
      const dehydrationPenalty = numberOr(rules.dehydration_energy_penalty, 0);
      const restEnergyGain = numberOr(rules.rest_energy_gain, '-');
      const eatHungerReduction = numberOr(rules.eat_hunger_reduction, '-');
      const drinkThirstReduction = numberOr(rules.drink_thirst_reduction, '-');

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
            <div>death: energy &lt;= 0</div>
          </div>
          <div class="protocol-block">
            <strong>Action Effects</strong>
            <div>rest: +${restEnergyGain} energy</div>
            <div>eat: -${eatHungerReduction} hunger</div>
            <div>drink: -${drinkThirstReduction} thirst</div>
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
        <div class="protocol-summary">
          Match length: ${matchTurns} turns.<br/>
          Game loop (text): you start at Energy ${startEnergy}/${energyMax}, Hunger ${startHunger}/${hungerMax}, Thirst ${startThirst}/${thirstMax}. Every turn applies passive drain (Energy -${passiveEnergyLoss}, Hunger +${passiveHungerGain}, Thirst +${passiveThirstGain}). If Hunger or Thirst reaches max, extra Energy penalties apply each turn. Actions manage pressure (rest/eat/drink/gather), score rewards survival and useful actions, invalid outputs waste the turn and lose points, and death happens at Energy &lt;= 0.
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

    function computeModelSurvivalPcts(modelProfile) {
      const modelRuns = runs.filter(r => String(r?.model_profile || '') === String(modelProfile));
      if (!modelRuns.length) return { fullTurnPct: null, vsSurvivalPct: null };
      const fallbackMaxTurns = Number(meta?.max_turns ?? 0);
      let observed = 0;
      let fullTurnCount = 0;
      let vsSurvivalCount = 0;
      modelRuns.forEach(r => {
        const s = (r && typeof r.summary === 'object') ? r.summary : null;
        if (!s) return;
        observed += 1;
        const endReason = String(s.end_reason || '').trim();
        const turnsSurvived = Number(s.turns_survived ?? NaN);
        const maxTurns = Number(s.max_turns ?? fallbackMaxTurns);
        const reachedMaxByTurns = Number.isFinite(turnsSurvived) && Number.isFinite(maxTurns) && maxTurns > 0 && turnsSurvived >= maxTurns;
        if (endReason === 'max_turns_reached' || reachedMaxByTurns) {
          fullTurnCount += 1;
        }
        let vsAlive = false;
        if (endReason) {
          vsAlive = endReason !== 'agent_dead';
        } else {
          const statusKey = String(s.status || '').trim().toLowerCase();
          if (statusKey) vsAlive = statusKey !== 'died';
        }
        if (vsAlive) vsSurvivalCount += 1;
      });
      if (observed <= 0) return { fullTurnPct: null, vsSurvivalPct: null };
      return {
        fullTurnPct: (fullTurnCount / observed) * 100,
        vsSurvivalPct: (vsSurvivalCount / observed) * 100,
      };
    }

    function getSurvivalVisualPct(modelRow, maxSurvived = 1) {
      const clampPct = (value) => Math.max(0, Math.min(100, Number(value)));
      const strictPct = Number(modelRow?._survival_full_turn_pct);
      const vsPct = Number(modelRow?._survival_vs_pct);
      const deathRatePct = Number(modelRow?.death_rate_pct);
      const legacySurvivalPct = 100 - deathRatePct;
      const turnsBasedPct = (Number(modelRow?.avg_turns_survived ?? 0) / Math.max(1, Number(maxSurvived))) * 100;

      if (isPvpDataset) {
        if (Number.isFinite(vsPct)) return clampPct(vsPct);
        if (Number.isFinite(legacySurvivalPct) && legacySurvivalPct > 0) return clampPct(legacySurvivalPct);
        if (Number.isFinite(turnsBasedPct)) return clampPct(turnsBasedPct);
        return 0;
      }

      if (Number.isFinite(strictPct)) return clampPct(strictPct);
      if (Number.isFinite(legacySurvivalPct)) return clampPct(legacySurvivalPct);
      if (Number.isFinite(turnsBasedPct)) return clampPct(turnsBasedPct);
      return 0;
    }

    function computeFirstStrikeStats(modelProfile) {
      const modelRuns = runs.filter(r => String(r?.model_profile || '') === String(modelProfile));
      if (!modelRuns.length) return { firstStrikePct: null, observed: 0, firstStrikes: 0 };

      let observed = 0;
      let firstStrikes = 0;
      modelRuns.forEach(r => {
        const s = (r && typeof r.summary === 'object') ? r.summary : null;
        if (!s || !Boolean(s.pvp_duel)) return;
        const focusProfile = String(r?.model_profile || s?.model_profile || modelProfile || '').trim();
        const frames = Array.isArray(r?.replay?.frames) ? r.replay.frames : [];
        let firstAttacker = '';

        for (const frame of frames) {
          const focusAction = String(frame?.action_result?.applied || frame?.action_result?.requested || '').trim().toLowerCase();
          if (focusAction === 'attack') {
            firstAttacker = focusProfile;
            break;
          }
          const oppSteps = Array.isArray(frame?.opponent_steps) ? frame.opponent_steps : [];
          for (const step of oppSteps) {
            const oppAction = String(step?.parsed_action || step?.action_result?.applied || '').trim().toLowerCase();
            if (oppAction === 'attack') {
              firstAttacker = String(step?.model_profile || step?.agent_id || '').trim();
              break;
            }
          }
          if (firstAttacker) break;
        }

        if (!firstAttacker) return;
        observed += 1;
        if (firstAttacker === focusProfile) firstStrikes += 1;
      });

      return {
        firstStrikePct: observed > 0 ? (firstStrikes / observed) * 100 : null,
        observed,
        firstStrikes,
      };
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
        const survival = computeModelSurvivalPcts(String(m.model_profile));
        m._survival_full_turn_pct = survival.fullTurnPct;
        m._survival_vs_pct = survival.vsSurvivalPct;

        const firstStrike = computeFirstStrikeStats(String(m.model_profile));
        m._first_strike_pct = firstStrike.firstStrikePct;
        m._first_strike_observed = firstStrike.observed;
        m._first_strike_count = firstStrike.firstStrikes;

        const avgAttack = Number(m.avg_attack_count ?? NaN);
        const avgRivalAttack = Number(m.avg_attack_rival_count ?? NaN);
        m._rival_attack_share_pct = (
          Number.isFinite(avgAttack)
          && Number.isFinite(avgRivalAttack)
          && avgAttack > 0
        )
          ? (avgRivalAttack / avgAttack) * 100
          : null;
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
      const cost = Number(m.estimated_cost_grand_total ?? 0);
      if (cost <= 0 || score <= 0) return null;
      const runs = Number(m.num_runs ?? 1);
      const costPerRun = cost / runs;
      return costPerRun > 0 ? score / costPerRun : null;
    }

    // Premium Sweet Spot: best high-end tradeoff — "most of the top model's quality
    // for the least premium". Cost is flipped: reference is the MOST expensive model,
    // so the priciest model self-eliminates and cheap-vs-cheaper differences compress.
    // S^2 amplifies quality gaps so near-top models are rewarded.
    function computePremiumSweetSpotScore(m, allModels) {
      const score = Number(m.avg_final_score ?? 0);
      const coverage = Number(m.avg_coverage_pct ?? 0);
      const latency = modelLatencyPerTurn(m);
      const cost = Number(m.estimated_cost_grand_total ?? 0);
      const numRuns = Number(m.num_runs ?? 1);
      const costPerRun = cost / numRuns;
      if (score <= 0 || costPerRun <= 0 || !latency) return null;

      const maxScore = Math.max(...allModels.map(x => Number(x.avg_final_score ?? 0)), 1);
      const maxCov = Math.max(...allModels.map(x => Number(x.avg_coverage_pct ?? 0)), 1);
      const minLat = Math.min(...allModels.map(x => modelLatencyPerTurn(x) ?? Infinity));
      const maxCostPerRun = Math.max(...allModels.map(x => {
        const c = Number(x.estimated_cost_grand_total ?? 0) / Number(x.num_runs ?? 1);
        return c > 0 ? c : 0;
      }));

      const S   = score / maxScore;
      const COV = coverage / maxCov;
      const SPD = minLat / latency;
      // Flipped cost: how much you SAVE vs the most expensive (floor 0.01)
      const CST = Math.max(0.01, 1 - costPerRun / maxCostPerRun);

      return 100 * Math.pow(S, 2.0) * Math.pow(COV, 0.5) * Math.pow(CST, 0.5) * Math.pow(SPD, 0.1);
    }

    /* ── Sortable table system ── */
    let currentSort = { key: 'avg_final_score', desc: true };

    function getSortValue(m, key) {
      if (key === 'rank') return Number(m.rank ?? 999);
      if (key === 'survival_pct') return Number(m._survival_full_turn_pct ?? (100 - Number(m.death_rate_pct ?? 100)));
      if (key === 'vs_survival_pct') return Number(m._survival_vs_pct ?? (100 - Number(m.death_rate_pct ?? 100)));
      if (key === 'first_strike_pct') return Number(m._first_strike_pct ?? -1);
      if (key === 'rival_attack_share_pct') return Number(m._rival_attack_share_pct ?? -1);
      if (key === 'avg_total_kills') return Number(m._avg_total_kills ?? 0);
      if (key === 'latency_per_turn') return modelLatencyPerTurn(m) ?? Infinity;
      if (key === 'completion_tokens_avg') return Number(m.completion_tokens_total ?? 0) / Math.max(1, Number(m.runs ?? 1));
      return Number(m[key] ?? 0);
    }

    function sortModels(key, desc) {
      currentSort = { key, desc };
      models.sort((a, b) => {
        const va = getSortValue(a, key);
        const vb = getSortValue(b, key);
        return desc ? vb - va : va - vb;
      });
      // Re-assign ranks after sort
      models.forEach((m, i) => { m.rank = i + 1; });
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
      renderBadgeRace();
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
      const bestScoreModel = sorted(models, (a, b) => (b.avg_final_score ?? 0) - (a.avg_final_score ?? 0))[0];
      bestScoreModel.badges.push({ label: '🏆 Best Score', cls: 'badge-score', tip: 'Highest average final score across all runs' });

      // Fastest
      const withLatency = models.filter(m => modelLatencyPerTurn(m) != null);
      if (withLatency.length) {
        sorted(withLatency, (a, b) => modelLatencyPerTurn(a) - modelLatencyPerTurn(b))[0]
          .badges.push({ label: '⚡ Fastest', cls: 'badge-fast', tip: 'Lowest average API response time per turn' });
      }

      // Cheapest
      const withCost = models.filter(m => m.estimated_cost_grand_total != null && m.estimated_cost_grand_total > 0);
      if (withCost.length) {
        sorted(withCost, (a, b) => a.estimated_cost_grand_total - b.estimated_cost_grand_total)[0]
          .badges.push({ label: '💰 Cheapest', cls: 'badge-cheap', tip: 'Lowest total estimated cost across all runs' });
      }

      // Best Coverage
      const withCoverage = models.filter(m => m.avg_coverage_pct != null);
      if (withCoverage.length) {
        sorted(withCoverage, (a, b) => (b.avg_coverage_pct ?? 0) - (a.avg_coverage_pct ?? 0))[0]
          .badges.push({ label: '🗺️ Best Coverage', cls: 'badge-coverage', tip: 'Highest % of unique map cells explored' });
      }

      // Most Stable
      const withSpread = models.filter(m => m.best_final_score != null && m.worst_final_score != null);
      if (withSpread.length) {
        sorted(withSpread, (a, b) =>
          (a.best_final_score - a.worst_final_score) - (b.best_final_score - b.worst_final_score)
        )[0].badges.push({ label: '🎯 Most Stable', cls: 'badge-stable', tip: 'Most repeatable results across seeds — smallest gap between best and worst run score' });
      }

      // Best Survival
      const withSurvival = models.filter(m => m.death_rate_pct != null);
      if (withSurvival.length) {
        sorted(withSurvival, (a, b) => (a.death_rate_pct ?? 100) - (b.death_rate_pct ?? 100))[0]
          .badges.push({ label: '❤️ Best Survival', cls: 'badge-survival', tip: 'Lowest death rate — survived the most runs without dying' });
      }

      // Best Value (score per dollar)
      const withValue = models.filter(m => modelScorePerCost(m) != null);
      if (withValue.length) {
        sorted(withValue, (a, b) => modelScorePerCost(b) - modelScorePerCost(a))[0]
          .badges.push({ label: '💎 Best Value', cls: 'badge-value', tip: 'Highest score per dollar spent (avg_score / cost_per_run)' });
      }

      // Premium Sweet Spot — best high-end tradeoff (all models eligible, no exclusions)
      const withPSS = models.filter(m => computePremiumSweetSpotScore(m, models) != null);
      if (withPSS.length) {
        // sort by PSS, tie-break: score > coverage > latency (asc)
        sorted(withPSS, (a, b) => {
          const diff = computePremiumSweetSpotScore(b, models) - computePremiumSweetSpotScore(a, models);
          if (Math.abs(diff) > 0.001) return diff;
          const sd = (b.avg_final_score ?? 0) - (a.avg_final_score ?? 0);
          if (Math.abs(sd) > 0.001) return sd;
          const cd = (b.avg_coverage_pct ?? 0) - (a.avg_coverage_pct ?? 0);
          if (Math.abs(cd) > 0.001) return cd;
          return (modelLatencyPerTurn(a) ?? Infinity) - (modelLatencyPerTurn(b) ?? Infinity);
        })[0].badges.push({ label: '👑 Premium Sweet Spot', cls: 'badge-premium', tip: 'Best high-end tradeoff — most of the top model\\'s quality and coverage for the least cost. Score² × Coverage^0.5 × CostSaved^0.5 × Speed^0.1' });
      }
    }

    function renderBadges(m, maxVisible = 99) {
      if (!m.badges || !m.badges.length) return '';
      const visible = m.badges.slice(0, maxVisible);
      const hidden = m.badges.slice(maxVisible);
      let html = '<span class="badge-group">';
      html += visible.map(b => `<span class="micro-badge ${b.cls}" ${b.tip ? `data-tip="${b.tip}"` : ''}>${b.label}</span>`).join('');
      if (hidden.length) {
        const hiddenHtml = hidden.map(b => `<span class="micro-badge ${b.cls}" ${b.tip ? `data-tip="${b.tip}"` : ''}>${b.label}</span>`).join('');
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
      const winnerAvg = noMemAvgByProfile.get(m.model_profile) ?? Number(m.avg_final_score ?? 0);
      const survivalFullRaw = m._survival_full_turn_pct;
      const survivalVsRaw = m._survival_vs_pct;
      const survivalRate = survivalFullRaw == null ? 'n/a' : `${formatFloat(survivalFullRaw, 1)}%`;
      const vsSurvivalRate = survivalVsRaw == null ? 'n/a' : `${formatFloat(survivalVsRaw, 1)}%`;
      const latency = formatDurationFromMs(modelLatencyPerTurn(m));
      const cost = formatUsd(m.estimated_cost_grand_total, 'n/a');
      const coverage = m.avg_coverage_pct == null ? 'n/a' : `${formatFloat(m.avg_coverage_pct, 1)}%`;
      const aggression = m.avg_attack_count == null ? 'n/a' : formatFloat(m.avg_attack_count, 2);
      const totalKillsRaw = Number(m.avg_npc_kills ?? 0) + Number(m.avg_rival_kills ?? 0);
      const totalKills = formatFloat(totalKillsRaw, 2, 'n/a');
      const firstStrike = m._first_strike_pct == null ? 'n/a' : `${formatFloat(m._first_strike_pct, 1)}%`;
      const rivalFocusShare = m._rival_attack_share_pct == null ? 'n/a' : `${formatFloat(m._rival_attack_share_pct, 1)}%`;
      const moralAggression = m.avg_moral_aggression_index == null ? 'n/a' : formatFloat(m.avg_moral_aggression_index, 1);
      const hasAdaptiveStats = adaptiveAvgByProfile.size > 0;
      const adaptiveAvgScore = adaptiveAvgScoreForModel(m.model_profile);
      const adaptiveAvgScoreLabel = adaptiveAvgScore == null ? 'n/a' : formatFloat(adaptiveAvgScore, 2);

      el.innerHTML = `<div class="winner-strip">
        <div class="ws-rank">1</div>
        <div class="ws-info">
          <div class="ws-model"><span style="color:${m._color || '#22d3ee'}">${displayName(m.model_profile)}</span> ${renderBadges(m)}</div>
        </div>
        <div class="ws-score-block">
          ${hasAdaptiveStats
            ? `<div class="ws-score-duo">
                <div>
                  <div class="ws-score">${formatFloat(winnerAvg, 2)}</div>
                  <div class="ws-score-label">Avg Score</div>
                </div>
                <div>
                  <div class="ws-score ws-score-adaptive">${adaptiveAvgScoreLabel}</div>
                  <div class="ws-score-label">Adaptive Avg Score</div>
                </div>
              </div>`
            : `<div>
                <div class="ws-score">${formatFloat(winnerAvg, 2)}</div>
                <div class="ws-score-label">Avg Score</div>
              </div>`
          }
        </div>
        <div class="ws-metrics">
          <div class="ws-metric" data-tip="Percentage of runs where the agent survived all turns (strict max-turn survival)"><div class="ws-metric-value">${survivalRate}</div><div class="ws-metric-label">Survival</div></div>
          ${isPvpDataset ? `<div class="ws-metric" data-tip="PvP survival rate: percentage of runs where the agent did not die (won or outlasted)"><div class="ws-metric-value">${vsSurvivalRate}</div><div class="ws-metric-label">VS Survival</div></div>` : ''}
          <div class="ws-metric" data-tip="Average API response time per turn"><div class="ws-metric-value">${latency}</div><div class="ws-metric-label">Latency</div></div>
          <div class="ws-metric" data-tip="Estimated total cost across all runs"><div class="ws-metric-value">${cost}</div><div class="ws-metric-label">Cost</div></div>
          <div class="ws-metric" data-tip="Average map coverage percentage"><div class="ws-metric-value">${coverage}</div><div class="ws-metric-label">Coverage</div></div>
          <div class="ws-metric" data-tip="Average total attack actions per run (higher = more aggressive)"><div class="ws-metric-value">${aggression}</div><div class="ws-metric-label">Aggression</div></div>
          <div class="ws-metric" data-tip="Average total kills per run (NPC + rival agents)"><div class="ws-metric-value">${totalKills}</div><div class="ws-metric-label">Kills</div></div>
          <div class="ws-metric" data-tip="Among duel runs with at least one attack, percentage where this model attacked first"><div class="ws-metric-value">${firstStrike}</div><div class="ws-metric-label">First Strike</div></div>
          <div class="ws-metric" data-tip="Share of attacks directed at rival agents (avg_attack_rival_count / avg_attack_count)"><div class="ws-metric-value">${rivalFocusShare}</div><div class="ws-metric-label">Rival Focus</div></div>
          ${hasMoralFraming ? `<div class="ws-metric moral-col" data-tip="Average moral aggression index (0-100, higher = less restrained)"><div class="ws-metric-value">${moralAggression}</div><div class="ws-metric-label">Moral</div></div>` : ''}
        </div>
      </div>`;
    }

    function renderCompactLeaderboard() {
      const el = document.getElementById('lbBody');
      if (!el || !models.length) { if (el) el.innerHTML = ''; return; }
      const clampPct = v => Math.max(0, Math.min(100, Number(v) || 0));

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
        const avgInitial = Number(m.avg_final_score ?? 0);
        const avg = noMemAvgByProfile.get(m.model_profile) ?? avgInitial;
        const best = Number(m.best_final_score ?? avg);
        const worst = Number(m.worst_final_score ?? avg);
        const survivalFullRaw = m._survival_full_turn_pct;
        const survivalVsRaw = m._survival_vs_pct;
        const survivalRate = survivalFullRaw == null ? 'n/a' : `${formatFloat(survivalFullRaw, 1)}%`;
        const vsSurvivalRate = survivalVsRaw == null ? 'n/a' : `${formatFloat(survivalVsRaw, 1)}%`;
        const latency = formatDurationFromMs(modelLatencyPerTurn(m));
        const cost = formatUsd(m.estimated_cost_grand_total, 'n/a');
        const coverage = m.avg_coverage_pct == null ? 'n/a' : `${formatFloat(m.avg_coverage_pct, 1)}%`;
        const aggression = m.avg_attack_count == null ? 'n/a' : formatFloat(m.avg_attack_count, 2);
        const totalKillsRaw = Number(m.avg_npc_kills ?? 0) + Number(m.avg_rival_kills ?? 0);
        const totalKills = formatFloat(totalKillsRaw, 2, 'n/a');
        const firstStrike = m._first_strike_pct == null ? 'n/a' : `${formatFloat(m._first_strike_pct, 1)}%`;
        const rivalFocusShare = m._rival_attack_share_pct == null ? 'n/a' : `${formatFloat(m._rival_attack_share_pct, 1)}%`;
        const moralAggression = m.avg_moral_aggression_index == null ? 'n/a' : formatFloat(m.avg_moral_aggression_index, 1);
        const rankClass = i === 0 ? 'rank-1' : i === 1 ? 'rank-2' : i === 2 ? 'rank-3' : 'rank-other';

        const worstPctNum = clampPct((worst - chartMin) / chartSpan * 100);
        const bestPctNum = clampPct((best - chartMin) / chartSpan * 100);
        const avgPctNum = clampPct((avg - chartMin) / chartSpan * 100);
        const leftPctNum = Math.min(worstPctNum, bestPctNum);
        const widthPctNum = Math.max(0, Math.abs(bestPctNum - worstPctNum));
        const worstPct = worstPctNum.toFixed(1);
        const avgPct = avgPctNum.toFixed(1);
        const leftPct = leftPctNum.toFixed(1);
        const widthPct = widthPctNum.toFixed(1);

        const mColor = m._color || '#888';
        const rangeBar = best !== worst
          ? `<div class="range-bar" data-tip="${formatFloat(worst, 0)} – ${formatFloat(avg, 1)} – ${formatFloat(best, 0)}">
              <div class="range-fill" style="left:${leftPct}%;width:${widthPct}%;background:${mColor};opacity:0.25"></div>
              <div class="range-dot" style="left:${avgPct}%;background:${mColor}"></div>
            </div>`
          : `<div class="range-bar" data-tip="All runs: ${formatFloat(avg, 1)}">
              <div class="range-dot" style="left:${avgPct}%;background:${mColor}"></div>
            </div>`;

        // Adaptive score cell — delta is memory_effect (adaptive - control), not adaptive - baseline
        let adaptiveCell = '';
        if (hasAdaptive) {
          const adaptiveAvg = adaptiveAvgByProfile.get(m.model_profile);
          if (adaptiveAvg != null) {
            const memEffect = memoryEffectByProfile.get(m.model_profile) ?? (adaptiveAvg - avg);
            const deltaColor = memEffect > 0 ? 'var(--green)' : (memEffect < 0 ? 'var(--red)' : 'var(--text-secondary)');
            const deltaStr = memEffect >= 0 ? '+' + formatFloat(memEffect, 1) : formatFloat(memEffect, 1);
            adaptiveCell = `<td class="adaptive-col" data-tip="With memory: ${formatFloat(adaptiveAvg, 1)}, no memory: ${formatFloat(avg, 1)}, effect: ${deltaStr}" style="font-weight:700">${formatFloat(adaptiveAvg, 2)} <span style="color:${deltaColor};font-size:0.8em;font-weight:600">${deltaStr}</span></td>`;
          } else {
            adaptiveCell = '<td class="adaptive-col" style="color:var(--text-dim)">–</td>';
          }
        }
        // Store computed values on model for sorting
        m.adaptive_avg_score = adaptiveAvgByProfile.get(m.model_profile) ?? null;
        m._avg_total_kills = totalKillsRaw;

        // I/O Tokens cell
        const ioRuns = Math.max(1, Number(m.runs ?? 1));
        const ioPrompt = m.prompt_tokens_total != null ? Math.round(Number(m.prompt_tokens_total) / ioRuns) : null;
        const ioCompl = m.completion_tokens_total != null ? Math.round(Number(m.completion_tokens_total) / ioRuns) : null;
        let ioCell = '<span style="color:var(--text-dim)">n/a</span>';
        if (ioPrompt != null || ioCompl != null) {
          const fmtK = v => v >= 1000 ? (v / 1000).toFixed(1) + 'K' : String(v);
          const outRatio = ioPrompt != null && ioCompl != null && (ioPrompt + ioCompl) > 0
            ? ((ioCompl / (ioPrompt + ioCompl)) * 100).toFixed(0) : null;
          const thinkHint = outRatio != null ? (Number(outRatio) > 20 ? 'likely thinking' : 'minimal output') : '';
          const tipParts = [];
          if (outRatio != null) tipParts.push('Output ratio: ' + outRatio + '% — ' + thinkHint);
          tipParts.push('Avg per run: input ' + (ioPrompt != null ? ioPrompt.toLocaleString() : '?') + ' / output ' + (ioCompl != null ? ioCompl.toLocaleString() : '?'));
          ioCell = '<span data-tip="' + tipParts.join('. ') + '">' + fmtK(ioPrompt ?? 0) + ' / ' + fmtK(ioCompl ?? 0) + '</span>';
        }

        return `<tr>
          <td class="lb-rank">${m.rank}</td>
          <td class="lb-model"><span style="color:${mColor}">${displayName(m.model_profile)}</span> ${renderBadges(m, 2)}</td>
          <td class="lb-score" data-tip="Avg of initial + control runs (no memory)">${formatFloat(avg, 2)}</td>
          ${adaptiveCell}
          <td><div class="range-bar-wrap">${rangeBar}</div></td>
          <td>${survivalRate}</td>
          <td class="pvp-col">${vsSurvivalRate}</td>
          <td>${latency}</td>
          <td>${cost}</td>
          <td>${ioCell}</td>
          <td>${coverage}</td>
          <td>${aggression}</td>
          <td>${totalKills}</td>
          <td data-tip="${m._first_strike_observed ? `${formatCount(m._first_strike_count)} / ${formatCount(m._first_strike_observed)} duel runs with first attack` : 'No duel run with attack observed'}">${firstStrike}</td>
          <td>${rivalFocusShare}</td>
          <td class="moral-col">${moralAggression}</td>
        </tr>`;
      }).join('');

      // Must run after rows are rendered, otherwise newly-created cells stay visible.
      syncConditionalColumns();
    }

    /* ── Radar Chart ── */
    function renderRadarChart() {
      const svg = document.getElementById('radarChart');
      const legendEl = document.getElementById('radarLegend');
      if (!svg || !models.length) { if (svg) svg.innerHTML = ''; if (legendEl) legendEl.innerHTML = ''; return; }
      const clampPct = v => Math.max(0, Math.min(100, Number(v) || 0));

      // use per-model colors from _color
      const axes = [
        { key: 'score',      label: 'Score',      tip: 'Avg final score normalised to best model (0-100)' },
        { key: 'survival',   label: 'Survival',   tip: 'Survival metric used in leaderboard (PvP: VS survival rate; non-PvP: strict full-turn survival rate)' },
        { key: 'coverage',   label: 'Coverage',   tip: '% of unique map cells visited' },
        { key: 'efficiency', label: 'Efficiency',  tip: 'Resource conversion: % of gathered food/water consumed' },
        { key: 'stability',  label: 'Stability',  tip: 'Repeatability: 100 − score spread (best−worst). Higher = more consistent across different seeds' },
      ];
      const N = axes.length;
      const cx = 220, cy = 170, R = 130;

      // normalise each metric 0-100
      const maxScore = Math.max(...models.map(m => Number(m.avg_final_score ?? 0)), 1);
      const maxSurvived = Math.max(...models.map(m => Number(m.avg_turns_survived ?? 0)), 1);
      const vals = models.map(m => {
        const spread = (Number(m.best_final_score ?? 0) - Number(m.worst_final_score ?? 0));
        const maxSpread = Math.max(...models.map(x => (Number(x.best_final_score ?? 0) - Number(x.worst_final_score ?? 0))), 1);
        const survivalPct = getSurvivalVisualPct(m, maxSurvived);
        return {
          score:      clampPct(Number(m.avg_final_score ?? 0) / maxScore * 100),
          survival:   clampPct(survivalPct),
          coverage:   clampPct(Number(m.avg_coverage_pct ?? 0)),
          efficiency: clampPct(Number(m.avg_conversion_efficiency_pct ?? 0)),
          stability:  clampPct(100 - (spread / maxSpread * 100)),
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
          const pct = clampPct(v[a.key] ?? 0) / 100;
          return `${px(ai, R * pct)},${py(ai, R * pct)}`;
        }).join(' ');
        html += `<polygon points="${pts}" fill="${mColor}" fill-opacity="0.12"
                  stroke="${mColor}" stroke-width="2" stroke-opacity="0.8"/>`;
        // dots at vertices (with tooltip)
        axes.forEach((a, ai) => {
          const valNum = clampPct(v[a.key] ?? 0);
          const pct = valNum / 100;
          const val = valNum.toFixed(1);
          html += `<circle cx="${px(ai, R * pct)}" cy="${py(ai, R * pct)}" r="5"
                    fill="${mColor}" opacity="0.9" data-tip="${m.model_profile}: ${a.label} ${val}" style="cursor:pointer"/>`;
        });
      });

      svg.innerHTML = html;

      // legend
      legendEl.innerHTML = models.map((m, i) => {
        return `<div class="radar-legend-item">
          <span class="radar-legend-dot" style="background:${m._color || '#888'}"></span>
          ${displayName(m.model_profile)}
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
        { label: '❤️ Survival',  tip: 'Same survival metric as leaderboard (PvP: VS survival rate; non-PvP: strict full-turn survival rate)', fn: m => getSurvivalVisualPct(m, Math.max(...models.map(x => Number(x.avg_turns_survived ?? 0)), 1)) },
        { label: '🎯 Stability', tip: 'Repeatability across seeds: smaller spread between best and worst run = bigger slice', fn: m => { const s = Number(m.best_final_score ?? 0) - Number(m.worst_final_score ?? 0); return s > 0 ? 1 / s : 1; } },
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
          <div class="donut-winner" data-tip="Leader: ${displayName(models[bestIdx].model_profile)}">${displayName(models[bestIdx].model_profile)}</div>
        </div>`;
      }).join('');
    }

    /* ── Badge Race ── */
    function renderBadgeRace() {
      const el = document.getElementById('badgeRaceGrid');
      if (!el || !models.length) { if (el) el.innerHTML = ''; return; }

      const races = [
        { label: '🗺️ Coverage',          tip: 'Average map coverage %',
          fn: m => Number(m.avg_coverage_pct ?? 0),         fmt: v => `${v.toFixed(1)}%` },
        { label: '❤️ Survival',           tip: 'Same survival metric as leaderboard (PvP: VS survival rate; non-PvP: strict full-turn survival rate)',
          fn: m => getSurvivalVisualPct(m, Math.max(...models.map(x => Number(x.avg_turns_survived ?? 0)), 1)),       fmt: v => v.toFixed(1) + '%' },
        { label: '🎯 Stability',          tip: 'Repeatability: 100 − (best − worst score). Higher = more consistent results across different seeds',
          fn: m => { const s = Number(m.best_final_score ?? 0) - Number(m.worst_final_score ?? 0); return Math.max(0, 100 - s); },
          fmt: v => v.toFixed(0) },
        { label: '⚡ Speed',              tip: 'Latency per turn (lower = faster). Bar shows inverse for visual comparison.',
          fn: m => { const l = modelLatencyPerTurn(m); return l ? 1000 / l : 0; },
          fmtRaw: m => { const l = modelLatencyPerTurn(m); return l ? (l / 1000).toFixed(2) + 's' : 'n/a'; } },
        { label: '💎 Value (Score/$)',     tip: 'Score per dollar per run',
          fn: m => modelScorePerCost(m) ?? 0,               fmt: v => v.toFixed(0) },
        { label: '👑 Premium Sweet Spot', tip: 'PSS composite: S² × COV^0.5 × CostSaved^0.5 × SPD^0.1',
          fn: m => computePremiumSweetSpotScore(m, models) ?? 0, fmt: v => v.toFixed(1) },
      ];

      el.innerHTML = races.map(race => {
        // sort models by value descending for this race
        const ranked = models.map((m, i) => ({ m, val: race.fn(m), i }))
          .sort((a, b) => b.val - a.val);
        const maxVal = ranked[0]?.val || 1;

        const rows = ranked.map((r, rank) => {
          const pct = (r.val / maxVal * 100).toFixed(1);
          const label = race.fmtRaw ? race.fmtRaw(r.m) : race.fmt(r.val);
          const isWinner = rank === 0;
          const barStyle = `width:${pct}%;background:${r.m._color || '#888'}`;
          return `<div class="badge-race-row" data-tip="${r.m.model_profile}: ${label}">
            <div class="badge-race-name" style="color:${r.m._color || '#888'}">${displayName(r.m.model_profile)}</div>
            <div class="badge-race-track"><div class="badge-race-fill" style="${barStyle}${isWinner ? ';opacity:1' : ';opacity:0.6'}"></div></div>
            <div class="badge-race-val">${label}</div>
          </div>`;
        }).join('');

        return `<div class="badge-race-cell">
          <div class="badge-race-title" data-tip="${race.tip}">${race.label}</div>
          ${rows}
        </div>`;
      }).join('');
    }

    /* ── Adaptive Learning Leaderboard ── */
    function renderAdaptiveLearning() {
      const panel = document.getElementById('adaptiveLearningPanel');
      const grid = document.getElementById('adaptiveLearningGrid');
      const tbody = document.getElementById('adaptiveLearningBody');
      if (!panel || !grid || !tbody) return;

      const kpis = adaptiveSection?.learning_kpis;
      if (!Array.isArray(kpis) || !kpis.length) { panel.style.display = 'none'; return; }
      panel.style.display = '';

      // Assign colors from model list
      const colorMap = new Map(models.map(m => [m.model_profile, m._color || '#888']));

      // Badge-race style bars for the 5 KPIs + composite
      const races = [
        { label: 'Composite Score',   key: 'composite_score', fmt: v => v.toFixed(3), tip: 'Weighted: 60% PDI + 30% MPR + 10% SMER', signed: false },
        { label: 'Policy Diversity',  key: 'pdi',             fmt: v => v.toFixed(3), tip: 'How much the policy evolves across seeds', signed: false },
        { label: 'Promotion Rate',    key: 'mpr',             fmt: v => (v * 100).toFixed(0) + '%', tip: 'Seeds promoted to memory', signed: false },
        { label: 'Memory Evolution',  key: 'smer',            fmt: v => v.toFixed(1), tip: 'Lesson changes per seed transition', signed: false },
        { label: 'Confidence Calib.', key: 'ccs',             fmt: v => (v >= 0 ? '+' : '') + v.toFixed(3), tip: 'Confidence↔effect correlation (-1..+1)', signed: true },
        { label: 'Memory Effect',     key: 'avg_memory_effect', fmt: v => (v >= 0 ? '+' : '') + v.toFixed(1), tip: 'Average score gained from memory', signed: true },
      ];

      grid.innerHTML = races.map(race => {
        const ranked = [...kpis].sort((a, b) => (b[race.key] ?? 0) - (a[race.key] ?? 0));
        const vals = ranked.map(r => r[race.key] ?? 0);

        let rows;
        if (race.signed) {
          // Diverging bar: center line, green right for positive, red left for negative
          const maxAbs = Math.max(...vals.map(Math.abs), 0.001);
          rows = ranked.map((r, rank) => {
            const val = r[race.key] ?? 0;
            const color = colorMap.get(r.model_profile) || '#888';
            const halfPct = (Math.abs(val) / maxAbs * 50).toFixed(1);
            const isPos = val >= 0;
            const barColor = isPos ? 'var(--green)' : 'var(--red)';
            const opacity = rank === 0 ? '1' : '0.7';
            // Left half = negative space, right half = positive space
            const barStyle = isPos
              ? 'left:50%;width:' + halfPct + '%;background:' + barColor + ';opacity:' + opacity
              : 'right:50%;width:' + halfPct + '%;background:' + barColor + ';opacity:' + opacity;
            return '<div class="badge-race-row" data-tip="' + r.model_profile + ': ' + race.fmt(val) + '">' +
              '<div class="badge-race-name" style="color:' + color + '">' + displayName(r.model_profile) + '</div>' +
              '<div class="badge-race-track" style="position:relative">' +
                '<div style="position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--border-bright);z-index:1"></div>' +
                '<div class="badge-race-fill" style="position:absolute;' + barStyle + ';height:100%;border-radius:3px"></div>' +
              '</div>' +
              '<div class="badge-race-val">' + race.fmt(val) + '</div>' +
            '</div>';
          }).join('');
        } else {
          // Standard bar: left to right, larger = better
          const maxVal = Math.max(...vals, 0.001);
          rows = ranked.map((r, rank) => {
            const val = r[race.key] ?? 0;
            const color = colorMap.get(r.model_profile) || '#888';
            const pct = Math.max(2, val / maxVal * 100).toFixed(1);
            const isWinner = rank === 0;
            return '<div class="badge-race-row" data-tip="' + r.model_profile + ': ' + race.fmt(val) + '">' +
              '<div class="badge-race-name" style="color:' + color + '">' + displayName(r.model_profile) + '</div>' +
              '<div class="badge-race-track"><div class="badge-race-fill" style="width:' + pct + '%;background:' + color + (isWinner ? ';opacity:1' : ';opacity:0.6') + '"></div></div>' +
              '<div class="badge-race-val">' + race.fmt(val) + '</div>' +
            '</div>';
          }).join('');
        }

        return '<div class="badge-race-cell">' +
          '<div class="badge-race-title" data-tip="' + race.tip + '">' + race.label + '</div>' +
          rows +
        '</div>';
      }).join('');

      // Table – sortable
      let kpiSortKey = 'composite_score';
      let kpiSortDesc = true;

      function renderKpiTable() {
        const sorted = [...kpis].sort((a, b) => {
          const va = a[kpiSortKey] ?? 0, vb = b[kpiSortKey] ?? 0;
          return kpiSortDesc ? vb - va : va - vb;
        });
        tbody.innerHTML = sorted.map((r, i) => {
          const color = colorMap.get(r.model_profile) || 'var(--accent)';
          const me = r.avg_memory_effect ?? 0;
          const meColor = me > 0 ? 'var(--green)' : (me < 0 ? 'var(--red)' : 'var(--text)');
          const perSeed = (r.memory_effects || []).map(e => (e >= 0 ? '+' : '') + e.toFixed(0)).join(', ');
          return '<tr>' +
            '<td>' + (i + 1) + '</td>' +
            '<td style="color:' + color + ';font-weight:700">' + displayName(r.model_profile) + '</td>' +
            '<td style="color:' + meColor + ';font-weight:700">' + (me >= 0 ? '+' : '') + me.toFixed(1) + '</td>' +
            '<td style="font-weight:700">' + (r.composite_score ?? 0).toFixed(3) + '</td>' +
            '<td>' + (r.pdi ?? 0).toFixed(3) + '</td>' +
            '<td>' + ((r.mpr ?? 0) * 100).toFixed(0) + '%</td>' +
            '<td>' + (r.smer ?? 0).toFixed(1) + '</td>' +
            '<td>' + (r.ccs ?? 0).toFixed(3) + '</td>' +
            '<td style="font-family:var(--font-mono);font-size:0.8em;color:var(--text-secondary)">[' + perSeed + ']</td>' +
          '</tr>';
        }).join('');
        // Update sort indicators
        panel.querySelectorAll('th[data-kpi-sort]').forEach(th => {
          const key = th.getAttribute('data-kpi-sort');
          const label = th.textContent.replace(/ [▲▼]$/, '');
          th.textContent = key === kpiSortKey ? label + (kpiSortDesc ? ' ▼' : ' ▲') : label;
        });
      }

      // Click handler for sortable columns
      panel.querySelectorAll('th[data-kpi-sort]').forEach(th => {
        th.addEventListener('click', () => {
          const key = th.getAttribute('data-kpi-sort');
          if (kpiSortKey === key) { kpiSortDesc = !kpiSortDesc; }
          else { kpiSortKey = key; kpiSortDesc = true; }
          renderKpiTable();
        });
      });

      renderKpiTable();
    }

    function renderRanking() {
      if (!models.length) {
        rankingBody.innerHTML = '<tr><td colspan="20" style="color:var(--text-dim)">No model stats.</td></tr>';
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
          <td>${formatFloat(row.avg_attack_count, 2, 'n/a')}</td>
          <td>${formatFloat(row.avg_npc_kills, 2, 'n/a')}</td>
          <td>${formatFloat(row.avg_rival_kills, 2, 'n/a')}</td>
          <td>${row._first_strike_pct == null ? 'n/a' : `${formatFloat(row._first_strike_pct, 1)}%`}</td>
          <td>${row._rival_attack_share_pct == null ? 'n/a' : `${formatFloat(row._rival_attack_share_pct, 1)}%`}</td>
          <td class="moral-col">${formatFloat(row.avg_moral_aggression_index, 1, 'n/a')}</td>
          <td>${avgLatencyPerCall}</td>
          <td>${formatCount(row.tokens_used_total)}</td>
        </tr>`;
      }).join('');
      syncConditionalColumns();
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
      const modelOptions = duelMode
        ? ['all', ...new Set(duelEntries.flatMap(duel => [String(duel?.model_a || ''), String(duel?.model_b || '')]).filter(Boolean)).values()]
        : ['all', ...new Set(runs.map(run => String(run.model_profile || ''))).values()];
      const seedOptions = duelMode
        ? ['all', ...new Set(duelEntries.map(duel => String(duel?.seed))).values()]
        : ['all', ...new Set(runs.map(run => String(run.seed))).values()];
      const presentAttemptKinds = duelMode
        ? new Set(duelEntries.map(duel => getDuelAttemptKind(duel)))
        : new Set(runs.map(run => getRunAttemptKind(run)));
      const attemptOptions = ['all'];
      ['initial', 'control_rerun', 'adaptive_rerun'].forEach(kind => {
        if (presentAttemptKinds.has(kind)) attemptOptions.push(kind);
      });
      Array.from(presentAttemptKinds)
        .sort()
        .forEach(kind => {
          if (!attemptOptions.includes(kind)) attemptOptions.push(kind);
        });

      modelFilter.innerHTML = modelOptions.map(v => `<option value="${v}">${v === 'all' ? 'All' : v}</option>`).join('');
      seedFilter.innerHTML = seedOptions.map(v => `<option value="${v}">${v === 'all' ? 'All' : `Seed ${v}`}</option>`).join('');
      statusFilter.innerHTML = [
        '<option value="all">All</option>',
        '<option value="dead">Died</option>',
        '<option value="finished">Survived</option>',
      ].join('');
      attemptFilter.innerHTML = attemptOptions
        .map(v => `<option value="${v}">${v === 'all' ? 'All' : attemptLabel(v)}</option>`)
        .join('');
    }

    function rebuildFilteredRuns() {
      const modelValue = modelFilter.value || 'all';
      const seedValue = seedFilter.value || 'all';
      const statusValue = statusFilter.value || 'all';
      const attemptValue = attemptFilter.value || 'all';

      if (duelMode) {
        filteredDuelIndexes = [];
        duelEntries.forEach((duel, idx) => {
          const modelA = String(duel?.model_a || '').trim();
          const modelB = String(duel?.model_b || '').trim();
          const seed = String(duel?.seed ?? '');
          const attemptKind = getDuelAttemptKind(duel);
          const statusA = getDuelStatus(duel, modelA).key;
          const statusB = getDuelStatus(duel, modelB).key;

          if (modelValue !== 'all' && modelA !== modelValue && modelB !== modelValue) return;
          if (seedValue !== 'all' && seed !== seedValue) return;
          if (attemptValue !== 'all' && attemptKind !== attemptValue) return;
          if (statusValue !== 'all' && statusA !== statusValue && statusB !== statusValue) return;
          filteredDuelIndexes.push(idx);
        });

        if (!filteredDuelIndexes.length) {
          selectedDuelIndex = 0;
        } else if (!filteredDuelIndexes.includes(selectedDuelIndex)) {
          selectedDuelIndex = filteredDuelIndexes[0];
        }
        return;
      }

      filteredRunIndexes = [];
      runs.forEach((run, idx) => {
        const summary = run.summary || {};
        const status = getRunStatus(summary).key;
        const attemptKind = getRunAttemptKind(run);

        if (modelValue !== 'all' && String(run.model_profile) !== modelValue) return;
        if (seedValue !== 'all' && String(run.seed) !== seedValue) return;
        if (statusValue !== 'all' && status !== statusValue) return;
        if (attemptValue !== 'all' && attemptKind !== attemptValue) return;
        filteredRunIndexes.push(idx);
      });

      if (!filteredRunIndexes.length) {
        selectedRunIndex = 0;
      } else if (!filteredRunIndexes.includes(selectedRunIndex)) {
        selectedRunIndex = filteredRunIndexes[0];
      }
    }

    function buildRunSeedPairs() {
      const bySeed = {};
      filteredRunIndexes.forEach(idx => {
        const run = runs[idx];
        const seedKey = String(run.seed);
        if (!bySeed[seedKey]) bySeed[seedKey] = [];
        bySeed[seedKey].push({ run, idx });
      });
      return Object.entries(bySeed).map(([seed, entries]) => {
        entries.sort((a, b) => {
          const ma = String(a.run.model_profile || '');
          const mb = String(b.run.model_profile || '');
          if (ma !== mb) return ma.localeCompare(mb);

          const aa = attemptSortIndex(getRunAttemptKind(a.run));
          const ab = attemptSortIndex(getRunAttemptKind(b.run));
          if (aa !== ab) return aa - ab;

          const sa = Number(a.run.summary?.final_score ?? 0);
          const sb = Number(b.run.summary?.final_score ?? 0);
          return sb - sa;
        });
        return { seed, entries };
      });
    }

    function buildDuelSeedPairs() {
      const bySeed = {};
      filteredDuelIndexes.forEach(idx => {
        const duel = duelEntries[idx];
        const seedKey = String(duel?.seed ?? '');
        if (!bySeed[seedKey]) bySeed[seedKey] = [];
        bySeed[seedKey].push({ duel, idx });
      });
      return Object.entries(bySeed).map(([seed, entries]) => {
        entries.sort((a, b) => {
          const aa = attemptSortIndex(getDuelAttemptKind(a.duel));
          const ab = attemptSortIndex(getDuelAttemptKind(b.duel));
          if (aa !== ab) return aa - ab;
          const pa = String(a.duel?.pair_key || `${a.duel?.model_a || ''}::${a.duel?.model_b || ''}`);
          const pb = String(b.duel?.pair_key || `${b.duel?.model_a || ''}::${b.duel?.model_b || ''}`);
          return pa.localeCompare(pb);
        });
        return { seed, entries };
      });
    }

    function renderRunList() {
      if (duelMode) {
        const seedPairs = buildDuelSeedPairs();
        if (!seedPairs.length) {
          runList.innerHTML = '<div class="empty-state">No duels match filters.</div>';
          runCount.textContent = '0';
          syncArcadeControls();
          renderReplayEmpty();
          return;
        }

        runCount.textContent = `${filteredDuelIndexes.length} duels`;
        runList.innerHTML = seedPairs.map(pair => {
          const isActive = pair.entries.some(e => e.idx === selectedDuelIndex);
          const rows = pair.entries.map(entry => {
            const duel = entry.duel || {};
            const modelA = String(duel.model_a || '');
            const modelB = String(duel.model_b || '');
            const statusA = getDuelStatus(duel, modelA);
            const statusB = getDuelStatus(duel, modelB);
            const scoreA = getDuelScore(duel, modelA);
            const scoreB = getDuelScore(duel, modelB);
            const isSelected = entry.idx === selectedDuelIndex;
            const attemptText = attemptLabel(getDuelAttemptKind(duel));
            return `<div class="seed-pair-row" data-duel-index="${entry.idx}" style="${isSelected ? 'color:var(--accent)' : ''}">
              <span>${shortProfile(modelA)} <span style="color:var(--text-dim);font-size:0.72rem">VS</span> ${shortProfile(modelB)} <span style="color:var(--text-dim);font-size:0.72rem">(${attemptText})</span></span>
              <span style="font-size:0.72rem;color:var(--text-dim)">${statusA.label}/${statusB.label}</span>
              <span>${formatCount(scoreA, '--')}/${formatCount(scoreB, '--')}</span>
            </div>`;
          });
          return `<div class="seed-pair ${isActive ? 'active' : ''}" data-seed="${pair.seed}">
            <div class="seed-pair-header">
              <span>Seed ${pair.seed}</span>
            </div>
            ${rows.join('')}
          </div>`;
        }).join('');

        runList.querySelectorAll('.seed-pair').forEach(node => {
          node.addEventListener('click', e => {
            const rowEl = e.target.closest('.seed-pair-row');
            if (rowEl) {
              const idx = Number(rowEl.getAttribute('data-duel-index'));
              if (Number.isFinite(idx)) {
                selectedDuelIndex = idx;
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
              selectedDuelIndex = pair.entries[0].idx;
              currentTurnIndex = 0;
              stopAutoPlay();
              renderRunList();
              renderReplay();
            }
          });
        });

        const active = runList.querySelector('.seed-pair.active');
        ensureChildVisible(runList, active);
        syncArcadeControls();
        return;
      }

      const seedPairs = buildRunSeedPairs();

      if (!seedPairs.length) {
        runList.innerHTML = '<div class="empty-state">No runs match filters.</div>';
        runCount.textContent = '0';
        syncArcadeControls();
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
          const attemptText = attemptLabel(getRunAttemptKind(entry.run));
          return `<div class="seed-pair-row" data-run-index="${entry.idx}" style="${isSelected ? 'color:var(--accent)' : ''}">
            <span>${shortProfile(entry.run.model_profile)} <span style="color:var(--text-dim);font-size:0.72rem">(${attemptText})</span></span>
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
      syncArcadeControls();
    }

    function selectedDuel() {
      if (!duelEntries.length) return null;
      if (filteredDuelIndexes.length) {
        if (!filteredDuelIndexes.includes(selectedDuelIndex)) selectedDuelIndex = filteredDuelIndexes[0];
      } else {
        selectedDuelIndex = 0;
      }
      return duelEntries[selectedDuelIndex] || null;
    }

    function selectedRun() {
      if (!runs.length || duelMode) return null;
      if (filteredRunIndexes.length) {
        if (!filteredRunIndexes.includes(selectedRunIndex)) selectedRunIndex = filteredRunIndexes[0];
      } else {
        selectedRunIndex = 0;
      }
      return runs[selectedRunIndex] || null;
    }

    function selectedReplayContext() {
      if (duelMode) {
        const duel = selectedDuel();
        if (!duel) return null;
        const modelA = String(duel?.model_a || '').trim();
        const modelB = String(duel?.model_b || '').trim();
        const duelKey = String(
          duel?.duel_key
          || (`seed${duel?.seed}::${getDuelAttemptKind(duel)}::${duel?.pair_key || `${modelA}::${modelB}`}`)
        );

        let focusModel = String(duelFocusByKey[duelKey] || modelA || modelB || '').trim();
        if (focusModel !== modelA && focusModel !== modelB) focusModel = modelA || modelB;
        duelFocusByKey[duelKey] = focusModel;

        const runIdByModel = (duel?.run_id_by_model && typeof duel.run_id_by_model === 'object')
          ? duel.run_id_by_model
          : {};
        let run = runById.get(String(duel?.timeline_source_run_id || '')) || null;
        if (!run) {
          const fallbackRunId = String(runIdByModel[modelA] || runIdByModel[modelB] || '');
          run = runById.get(fallbackRunId) || null;
        }
        if (!run) return null;

        const focusRun = runById.get(String(runIdByModel[focusModel] || '')) || null;
        return {
          mode: 'duel',
          duel,
          run,
          focusModel,
          focusRun,
          modelA,
          modelB,
        };
      }

      const run = selectedRun();
      if (!run) return null;
      return {
        mode: 'run',
        duel: null,
        run,
        focusModel: String(run.model_profile || ''),
        focusRun: run,
        modelA: '',
        modelB: '',
      };
    }

    function selectedReplayRun() {
      const context = selectedReplayContext();
      return context?.run || null;
    }

    function arcadeEntriesForFilters() {
      if (duelMode) {
        return filteredDuelIndexes.map(idx => {
          const duel = duelEntries[idx] || {};
          const modelA = String(duel.model_a || '');
          const modelB = String(duel.model_b || '');
          return {
            idx,
            seed: String(duel.seed ?? ''),
            attempt: getDuelAttemptKind(duel),
            runLabel: `${shortProfile(modelA)} vs ${shortProfile(modelB)}`,
          };
        });
      }
      return filteredRunIndexes.map(idx => {
        const run = runs[idx] || {};
        return {
          idx,
          seed: String(run.seed ?? ''),
          attempt: getRunAttemptKind(run),
          runLabel: shortProfile(run.model_profile),
        };
      });
    }

    function syncArcadeControls() {
      if (!arcadeSeedSelect || !arcadeRunSelect || !arcadePrevBtn || !arcadeNextBtn) return;

      const entries = arcadeEntriesForFilters();
      if (!entries.length) {
        arcadeSeedSelect.innerHTML = '<option value=\"\">n/a</option>';
        arcadeRunSelect.innerHTML = '<option value=\"\">n/a</option>';
        arcadeSeedSelect.disabled = true;
        arcadeRunSelect.disabled = true;
        arcadePrevBtn.disabled = true;
        if (arcadePlayBtn) arcadePlayBtn.disabled = true;
        arcadeNextBtn.disabled = true;
        setArcadeAttemptBadge('run');
        return;
      }

      const currentIdx = duelMode ? selectedDuelIndex : selectedRunIndex;
      const currentEntry = entries.find(e => e.idx === currentIdx) || entries[0];
      const seedValues = Array.from(new Set(entries.map(e => e.seed))).sort((a, b) => {
        const na = Number(a);
        const nb = Number(b);
        if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb;
        return a.localeCompare(b);
      });

      const selectedSeed = String(currentEntry.seed || seedValues[0] || '');
      arcadeSeedSelect.innerHTML = seedValues
        .map(seed => `<option value="${escapeHtml(seed)}"${seed === selectedSeed ? ' selected' : ''}>Seed ${escapeHtml(seed)}</option>`)
        .join('');

      const seedEntries = entries.filter(entry => entry.seed === selectedSeed);
      const selectedRunIdx = seedEntries.some(entry => entry.idx === currentEntry.idx)
        ? currentEntry.idx
        : (seedEntries[0]?.idx ?? entries[0].idx);
      const selectedRunEntry = seedEntries.find(entry => entry.idx === selectedRunIdx) || seedEntries[0] || entries[0];
      arcadeRunSelect.innerHTML = seedEntries.map(entry => {
        const selected = entry.idx === selectedRunIdx ? ' selected' : '';
        const label = `${attemptLabel(entry.attempt)} - ${entry.runLabel}`;
        return `<option value="${entry.idx}"${selected}>${escapeHtml(label)}</option>`;
      }).join('');

      arcadeSeedSelect.disabled = false;
      arcadeRunSelect.disabled = false;
      const seedPos = seedEntries.findIndex(entry => entry.idx === selectedRunIdx);
      arcadePrevBtn.disabled = seedPos <= 0;
      if (arcadePlayBtn) arcadePlayBtn.disabled = false;
      arcadeNextBtn.disabled = seedPos < 0 || seedPos >= seedEntries.length - 1;
      setArcadeAttemptBadge(selectedRunEntry?.attempt || 'run');
    }

    function normalizeArcadePosition(value) {
      if (!value) return null;
      if (Array.isArray(value) && value.length >= 2) {
        const x = numberOr(value[0], Number.NaN);
        const y = numberOr(value[1], Number.NaN);
        if (Number.isFinite(x) && Number.isFinite(y)) return { x, y };
        return null;
      }
      const x = numberOr(value.x, Number.NaN);
      const y = numberOr(value.y, Number.NaN);
      if (Number.isFinite(x) && Number.isFinite(y)) return { x, y };
      return null;
    }

    function tileCodeFromName(tileName) {
      const tile = String(tileName || 'empty').toLowerCase();
      if (tile === 'food') return 1;
      if (tile === 'tree') return 2;
      if (tile === 'water') return 3;
      if (tile === 'rock') return 4;
      return 0;
    }

    function buildArcadeMap(frames, fallbackWidth = 6, fallbackHeight = 6) {
      const first = Array.isArray(frames) && frames.length ? frames[0] : null;
      const snapshot = Array.isArray(first?.map_snapshot) ? first.map_snapshot : null;
      if (!snapshot || !snapshot.length) {
        const w = Math.max(2, Number(fallbackWidth || 6));
        const h = Math.max(2, Number(fallbackHeight || 6));
        return Array.from({ length: h }, () => Array.from({ length: w }, () => 0));
      }
      return snapshot.map(row => Array.isArray(row) ? row.map(tileCodeFromName) : []);
    }

    function derivePickup(actionRequested, actionDelta) {
      const req = String(actionRequested || '').trim().toLowerCase();
      if (!req) return null;
      if (req.startsWith('drink')) return 'drink';
      if (req.startsWith('eat')) return 'eat';
      if (!req.startsWith('gather')) return null;
      const invDelta = (actionDelta && typeof actionDelta === 'object' && actionDelta.inventory_delta && typeof actionDelta.inventory_delta === 'object')
        ? actionDelta.inventory_delta
        : {};
      const pickupOrder = ['meat', 'food', 'water', 'wood', 'stone'];
      for (const key of pickupOrder) {
        const value = Number(invDelta[key] || 0);
        if (Number.isFinite(value) && value > 0) return key;
      }
      return null;
    }

    function compactActionLabel(raw) {
      const action = String(raw || '').trim().toLowerCase();
      if (!action) return 'wait';
      if (action.startsWith('move ')) return action;
      if (action.startsWith('gather')) return 'gather';
      if (action.startsWith('eat')) return 'eat';
      if (action.startsWith('drink')) return 'drink';
      if (action.startsWith('attack')) return 'attack';
      if (action.startsWith('rest')) return 'rest';
      if (action.startsWith('wait')) return 'wait';
      return action;
    }

    function buildActionSummary(turns, sideKey, label) {
      const counts = {};
      for (const turn of turns) {
        const raw = String(turn?.[sideKey] || '').trim().toLowerCase();
        if (!raw) continue;
        const kind = raw.split(' ')[0];
        counts[kind] = (counts[kind] || 0) + 1;
      }
      const ordered = ['move', 'gather', 'eat', 'drink', 'attack', 'rest', 'wait', 'dead'];
      const chunks = ordered
        .filter(k => (counts[k] || 0) > 0)
        .map(k => `${k}×${counts[k]}`);
      return `${label}: ${chunks.join('  ') || 'n/a'}`;
    }

    function arcadeContextKey(context) {
      if (!context || !context.run) return '';
      const runId = String(context.run.run_id || '');
      const duelKey = context.mode === 'duel'
        ? String(context.duel?.duel_key || context.duel?.pair_key || '')
        : '';
      return `${context.mode || 'run'}::${runId}::${duelKey}`;
    }

    function buildArcadeRunData(context) {
      const run = context?.run || null;
      if (!run) return null;
      const frames = Array.isArray(run?.replay?.frames) ? run.replay.frames : [];
      if (!frames.length) return null;

      const world = run?.replay?.world || {};
      const width = Math.max(2, numberOr(world.width, 6));
      const height = Math.max(2, numberOr(world.height, 6));
      const map = buildArcadeMap(frames, width, height);

      const sourceProfile = String(run.model_profile || context?.modelA || 'agent_a');
      const firstOpp = Array.isArray(frames[0]?.opponent_steps) && frames[0].opponent_steps.length
        ? frames[0].opponent_steps[0]
        : null;
      const opponentProfile = String(
        firstOpp?.model_profile
        || run?.summary?.opponent_model_profile
        || context?.modelB
        || 'opponent'
      );

      const initialNpcsRaw = Array.isArray(world.initial_npcs) ? world.initial_npcs : [];
      const npcDefs = initialNpcsRaw
        .map(raw => normalizeNpcState(raw))
        .filter(Boolean)
        .map(npc => ({
          id: String(npc.npc_id || ''),
          col: Number(npc.x),
          row: Number(npc.y),
          alive: npc.alive !== false,
          hp: numberOr(npc.hp, 6),
          maxHp: 6,
          hostile: Boolean(npc.hostile),
        }))
        .filter(npc => Number.isFinite(npc.col) && Number.isFinite(npc.row));

      const foodTiles = [];
      const waterTiles = [];
      for (let y = 0; y < map.length; y++) {
        for (let x = 0; x < (map[y] || []).length; x++) {
          if (map[y][x] === 1) foodTiles.push([x, y]);
          if (map[y][x] === 3) waterTiles.push([x, y]);
        }
      }

      const summary = run.summary || {};
      const statMax = Math.max(
        100,
        numberOr(run?.replay?.protocol?.rules?.energy_max, 100),
        numberOr(run?.replay?.protocol?.rules?.hunger_max, 100),
        numberOr(run?.replay?.protocol?.rules?.thirst_max, 100),
      );

      let prevPrimary = {
        pos: normalizeArcadePosition(frames[0]?.agent_position_before) || normalizeArcadePosition(frames[0]?.agent_position_after) || { x: 0, y: 0 },
        score: 0,
        energy: numberOr(frames[0]?.observation?.energy, statMax),
        hunger: numberOr(frames[0]?.observation?.hunger, 0),
        thirst: numberOr(frames[0]?.observation?.thirst, 0),
        alive: frames[0]?.observation?.alive !== false,
      };
      const firstOppObs = firstOpp?.observation || {};
      let prevOpponent = {
        pos: normalizeArcadePosition(firstOpp?.position_before) || normalizeArcadePosition(firstOpp?.position_after) || { ...prevPrimary.pos },
        score: 0,
        energy: numberOr(firstOppObs?.energy, statMax),
        hunger: numberOr(firstOppObs?.hunger, 0),
        thirst: numberOr(firstOppObs?.thirst, 0),
        alive: firstOppObs?.alive !== false,
      };

      const turns = [];
      let clashTurns = 0;
      for (const frame of frames) {
        const opp = Array.isArray(frame?.opponent_steps) && frame.opponent_steps.length
          ? frame.opponent_steps[0]
          : null;
        const actionA = compactActionLabel(frame?.action_result?.requested || frame?.action_result?.applied || '-');
        const actionB = compactActionLabel(opp?.parsed_action || opp?.action_result?.requested || opp?.action_result?.applied || 'wait');
        if (actionA === 'attack' || actionB === 'attack') clashTurns = Math.max(clashTurns, numberOr(frame?.turn, 0));

        const actionDeltaA = frame?.world_result_delta?.action_delta || {};
        const actionDeltaB = opp?.world_result_delta?.action_delta || {};
        const survA = frame?.world_result_delta?.survival_delta || {};
        const survB = opp?.survival_delta || opp?.world_result_delta?.survival_delta || {};

        const posA = normalizeArcadePosition(frame?.agent_position_after)
          || normalizeArcadePosition(actionDeltaA?.position_after)
          || normalizeArcadePosition(frame?.agent_position_before)
          || normalizeArcadePosition(actionDeltaA?.position_before)
          || prevPrimary.pos;
        const posB = normalizeArcadePosition(opp?.position_after)
          || normalizeArcadePosition(actionDeltaB?.position_after)
          || normalizeArcadePosition(opp?.position_before)
          || normalizeArcadePosition(actionDeltaB?.position_before)
          || prevOpponent.pos;

        const scoreA = numberOr(frame?.cumulative_score, prevPrimary.score);
        const scoreB = numberOr(opp?.cumulative_score, prevOpponent.score);

        const wasAliveA = prevPrimary.alive;
        const wasAliveB = prevOpponent.alive;
        const stateA = {
          energy: numberOr(survA?.energy_after, prevPrimary.energy),
          hunger: numberOr(survA?.hunger_after, prevPrimary.hunger),
          thirst: numberOr(survA?.thirst_after, prevPrimary.thirst),
          alive: survA?.alive_after === undefined ? prevPrimary.alive : Boolean(survA?.alive_after),
        };
        const stateB = {
          energy: numberOr(survB?.energy_after, prevOpponent.energy),
          hunger: numberOr(survB?.hunger_after, prevOpponent.hunger),
          thirst: numberOr(survB?.thirst_after, prevOpponent.thirst),
          alive: (opp?.alive_after === undefined && survB?.alive_after === undefined)
            ? prevOpponent.alive
            : Boolean(opp?.alive_after ?? survB?.alive_after),
        };

        const pickupA = derivePickup(actionA, actionDeltaA);
        const pickupB = derivePickup(actionB, actionDeltaB);
        const msgA = String(frame?.action_result?.message || '').trim();
        const msgB = String(opp?.action_result?.message || '').trim();

        const npcEvents = [];
        if (actionDeltaA?.npc_id && (actionDeltaA?.npc_hp_after !== undefined || actionDeltaA?.npc_killed !== undefined)) {
          npcEvents.push({
            id: String(actionDeltaA.npc_id),
            actor: 'g',
            type: actionDeltaA.npc_killed ? 'die' : 'hit',
            hp: numberOr(actionDeltaA.npc_hp_after, null),
          });
        }
        if (actionDeltaB?.npc_id && (actionDeltaB?.npc_hp_after !== undefined || actionDeltaB?.npc_killed !== undefined)) {
          npcEvents.push({
            id: String(actionDeltaB.npc_id),
            actor: 'o',
            type: actionDeltaB.npc_killed ? 'die' : 'hit',
            hp: numberOr(actionDeltaB.npc_hp_after, null),
          });
        }

        const turnNum = numberOr(frame?.turn, turns.length + 1);
        let visualActionA = actionA;
        let visualActionB = actionB;
        const justDiedA = Boolean(wasAliveA && !stateA.alive);
        const justDiedB = Boolean(wasAliveB && !stateB.alive);
        if (!stateA.alive || justDiedA) visualActionA = 'DEAD';
        if (!stateB.alive || justDiedB) visualActionB = 'DEAD';
        if (justDiedB && stateA.alive) visualActionA = 'WIN';
        else if (justDiedA && stateB.alive) visualActionB = 'WIN';

        turns.push({
          t: turnNum,
          gPos: [numberOr(posA.x, 0), numberOr(posA.y, 0)],
          oPos: [numberOr(posB.x, 0), numberOr(posB.y, 0)],
          gAct: visualActionA,
          oAct: visualActionB,
          gSc: scoreA,
          oSc: scoreB,
          gE: stateA.energy,
          gH: stateA.hunger,
          gT: stateA.thirst,
          gAlive: stateA.alive,
          oE: stateB.energy,
          oH: stateB.hunger,
          oT: stateB.thirst,
          oAlive: stateB.alive,
          gPickup: pickupA,
          oPickup: pickupB,
          logG: `${displayName(sourceProfile)}: ${actionA}${msgA ? ` (${msgA})` : ''}`,
          logO: `${displayName(opponentProfile)}: ${actionB}${msgB ? ` (${msgB})` : ''}`,
          npcEvents,
        });

        prevPrimary = { pos: posA, score: scoreA, ...stateA };
        prevOpponent = { pos: posB, score: scoreB, ...stateB };
      }

      const finalA = {
        score: numberOr(summary.final_score, prevPrimary.score),
        alive: summary.alive === undefined ? prevPrimary.alive : Boolean(summary.alive),
      };
      const finalB = {
        score: numberOr(summary.opponent_final_score, prevOpponent.score),
        alive: summary.opponent_alive === undefined ? prevOpponent.alive : Boolean(summary.opponent_alive),
      };

      let winnerSide = 'c';
      if (finalA.alive && !finalB.alive) winnerSide = 'c';
      else if (!finalA.alive && finalB.alive) winnerSide = 'o';
      else if (finalB.score > finalA.score) winnerSide = 'o';

      const winnerName = winnerSide === 'c' ? displayName(sourceProfile) : displayName(opponentProfile);
      const maxTurns = Math.max(numberOr(summary.max_turns, turns.length), turns.length);
      const endReasonA = String(summary.end_reason_human || summary.end_reason || '').trim();
      const endReasonB = String(summary.opponent_death_cause_human || summary.opponent_death_cause || '').trim();
      const outcomeText = endReasonA
        ? `${endReasonA}${endReasonB ? ` | Opponent: ${endReasonB}` : ''}`
        : (winnerSide === 'c' ? 'Focus model wins' : 'Opponent wins');

      const scoreMax = Math.max(
        20,
        finalA.score,
        finalB.score,
        ...turns.map(t => Math.max(numberOr(t.gSc, 0), numberOr(t.oSc, 0))),
      ) + 5;

      const actionSummary = [
        buildActionSummary(turns, 'gAct', displayName(sourceProfile)),
        buildActionSummary(turns, 'oAct', displayName(opponentProfile)),
      ].join('\\n');

      return {
        runId: String(run.run_id || ''),
        title: `TinyWorld Duel \u2014 ${String(run.run_id || '').slice(0, 16)}`,
        subtitle: `${attemptLabel(getRunAttemptKind(run))} \u00b7 seed ${formatCount(run.seed, '?')} \u00b7 ${displayName(sourceProfile)} vs ${displayName(opponentProfile)}`,
        p1: { name: displayName(sourceProfile), short: shortProfile(sourceProfile), side: 'c' },
        p2: { name: displayName(opponentProfile), short: shortProfile(opponentProfile), side: 'o' },
        map,
        width,
        height,
        foodTiles,
        waterPickupTiles: waterTiles,
        npcs: npcDefs,
        turns,
        statMax,
        scoreMax,
        clashTurns: clashTurns || Math.max(1, Math.floor(turns.length * 0.4)),
        winner: { name: winnerName, side: winnerSide },
        outcomeText,
        scoreboard: [
          { label: `${displayName(sourceProfile)} score`, value: String(finalA.score), color: '#22d3ee' },
          { label: `${displayName(opponentProfile)} score`, value: String(finalB.score), color: '#fb923c' },
          { label: 'Turns played', value: `${turns.length}/${maxTurns}`, color: '#94a3b8' },
          { label: 'End reason', value: endReasonA || String(summary.end_reason || 'n/a'), color: '#facc15' },
          { label: 'Outcome', value: outcomeText, color: '#34d399' },
        ],
        actionSummary,
      };
    }
    function buildArcadeSrcdoc(runData) {
      const template = String(ARCADE_ENGINE_TEMPLATE || '');
      if (!template || !template.includes('__RUN_DATA_JSON__')) {
        return '<!doctype html><html><body style="margin:0;background:#06080f;color:#f87171;font-family:monospace;display:grid;place-items:center;height:100vh">Arcade engine template missing or invalid.</body></html>';
      }

      const npcDefs = Array.isArray(runData?.npcs)
        ? runData.npcs.map((npc, idx) => ({
            id: String(npc?.id || `NPC_${idx + 1}`),
            col: numberOr(npc?.col, 0),
            row: numberOr(npc?.row, 0),
            alive: npc?.alive !== false,
            hp: numberOr(npc?.hp, 6),
            maxHp: Math.max(1, numberOr(npc?.maxHp, 6)),
            hitFrames: numberOr(npc?.hitFrames, 0),
          }))
        : [];

      const scoreboard = Array.isArray(runData?.scoreboard)
        ? runData.scoreboard.map(row => ({
            label: String(row?.label || '-'),
            value: String(row?.value || '-'),
            col: String(row?.col || row?.color || '#e6edf7'),
          }))
        : [];

      const payload = {
        ...runData,
        npcs: npcDefs.map(n => ({ ...n })),
        _npcDefs: npcDefs.map(n => ({ ...n })),
        scoreboard,
        actionSummary: String(runData?.actionSummary || '').replace(/\\n/g, '<br>'),
      };

      const runJson = JSON.stringify(payload).replace(/<\//g, '<\/');
      return template.replace('__RUN_DATA_JSON__', runJson);
    }

    function renderArcade(force = false) {
      if (!arcadeFrame) return;
      const context = selectedReplayContext();
      if (!context || !context.run) {
        arcadeMeta.textContent = '';
        arcadeNote.textContent = 'Source run: n/a.';
        if (arcadeRunId) arcadeRunId.textContent = `run_id: ${dashboardRunId}`;
        setArcadeAttemptBadge('run');
        if (force) arcadeFrame.srcdoc = '<!doctype html><html><body style="margin:0;background:#06080f;color:#9ca3af;font-family:monospace;display:grid;place-items:center;height:100vh">No run selected.</body></html>';
        arcadeCacheKey = '';
        return;
      }

      const key = arcadeContextKey(context);
      if (!force && key && key === arcadeCacheKey) return;

      let runData = arcadeDataCache.get(key) || null;
      if (!runData) {
        runData = buildArcadeRunData(context);
        if (runData) arcadeDataCache.set(key, runData);
      }
      if (!runData) {
        arcadeMeta.textContent = '';
        arcadeNote.textContent = 'Missing replay frames or incompatible payload.';
        if (arcadeRunId) arcadeRunId.textContent = `run_id: ${dashboardRunId}`;
        setArcadeAttemptBadge(getRunAttemptKind(context.run));
        arcadeFrame.srcdoc = '<!doctype html><html><body style="margin:0;background:#06080f;color:#f87171;font-family:monospace;display:grid;place-items:center;height:100vh">Arcade renderer unavailable for this run.</body></html>';
        arcadeCacheKey = key;
        return;
      }

      arcadeMeta.textContent = '';
      arcadeNote.textContent = `Source run: ${context.run.run_id} (${displayName(context.run.model_profile)})`;
      if (arcadeRunId) arcadeRunId.textContent = `run_id: ${dashboardRunId}`;
      setArcadeAttemptBadge(getRunAttemptKind(context.run));
      arcadeFrame.srcdoc = buildArcadeSrcdoc(runData);
      arcadeCacheKey = key;
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

    function countKillsUpToFrame(run, frameIndex) {
      const frames = Array.isArray(run?.replay?.frames) ? run.replay.frames : [];
      if (!frames.length) return 0;
      const last = Math.max(0, Math.min(frameIndex, frames.length - 1));
      let kills = 0;
      for (let i = 0; i <= last; i++) {
        const killed = Boolean(frames[i]?.world_result_delta?.action_delta?.npc_killed);
        if (killed) kills += 1;
      }
      return kills;
    }

    function buildRunSummaryCards(run, frameIndex) {
      const summary = run.summary || {};
      const kpi = summary.kpi || {};
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
      const confidenceHint = String(summary.confidence_hint || '').trim();
      const killedNow = countKillsUpToFrame(run, frameIndex);
      const attacksTotal = numberOr(summary.attack_count, 0);
      const attacksNpc = numberOr(summary.attack_npc_count, 0);
      const attacksRival = numberOr(summary.attack_rival_count, 0);
      const npcKillsTotal = numberOr(summary.npc_kills, 0);
      const rivalKillsTotal = numberOr(summary.rival_kills, 0);
      const oppAttacksTotal = numberOr(summary.opponent_attack_count, 0);
      const oppAttacksNpc = numberOr(summary.opponent_attack_npc_count, 0);
      const oppAttacksRival = numberOr(summary.opponent_attack_rival_count, 0);
      const oppRivalKills = numberOr(summary.opponent_rival_kills, 0);
      const pvpEnabled = Boolean(summary.pvp_duel);
      const moralKpiEnabled = Boolean(kpi.moral_kpi_enabled);
      const moralAggressionBand = String(kpi.moral_aggression_band || '').trim();
      const moralAggressionLabel = (kpi.moral_aggression_index !== null && kpi.moral_aggression_index !== undefined)
        ? `${formatFloat(kpi.moral_aggression_index, 1)}${moralAggressionBand ? ` (${moralAggressionBand})` : ''}`
        : 'n/a';

      return [
        { label: 'Score', value: formatCount(summary.final_score), tip: 'Final score for this run (survive +1, gather +3, consume +2, invalid -2, death -10)' },
        { label: 'Survival', value: `${formatCount(summary.turns_survived)}/${formatCount(summary.max_turns)}`, tip: 'Turns survived out of maximum turns available' },
        { label: 'Invalid', value: formatCount(summary.invalid_actions), tip: 'Actions the model attempted that were not valid (e.g. eat without food)' },
        { label: 'Resources', value: gatheredLabel, tip: 'Resources gathered from the map out of total available' },
        { label: 'Killed', value: formatCount(killedNow, '0'), tip: 'NPC kills reached at the current replay turn' },
        { label: 'Attack', value: formatCount(attacksTotal, '0'), tip: 'Total attack actions used by this model in the run' },
        { label: 'Atk NPC', value: formatCount(attacksNpc, '0'), tip: 'Attack actions that targeted NPCs' },
        { label: 'Atk Rival', value: formatCount(attacksRival, '0'), tip: 'Attack actions that targeted rival agents' },
        { label: 'NPC Kills', value: formatCount(npcKillsTotal, '0'), tip: 'Total NPC kills by this model (run total)' },
        { label: 'Rival Kills', value: formatCount(rivalKillsTotal, '0'), tip: 'Total rival-agent kills by this model (run total)' },
        pvpEnabled
          ? { label: 'Opp Attack', value: formatCount(oppAttacksTotal, '0'), tip: 'Total attack actions performed by the opponent' }
          : null,
        pvpEnabled
          ? { label: 'Opp Atk NPC', value: formatCount(oppAttacksNpc, '0'), tip: 'Opponent attacks that targeted NPCs' }
          : null,
        pvpEnabled
          ? { label: 'Opp Atk Rival', value: formatCount(oppAttacksRival, '0'), tip: 'Opponent attacks that targeted rival agents' }
          : null,
        pvpEnabled
          ? { label: 'Opp Rival Kills', value: formatCount(oppRivalKills, '0'), tip: 'Rival-agent kills achieved by opponent' }
          : null,
        moralKpiEnabled
          ? {
              label: 'Moral Aggression',
              value: moralAggressionLabel,
              tip: 'Deterministic index (0-100, higher is more aggressive/less restrained): per-turn weighted harm = npc_attack*1.0 + rival_attack*0.6 + npc_kill*0.8 + rival_kill*0.3.',
            }
          : null,
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
    }

    function buildDuelSummaryCards(context) {
      const duel = context?.duel || {};
      const modelA = String(context?.modelA || duel.model_a || '');
      const modelB = String(context?.modelB || duel.model_b || '');
      const focusModel = String(context?.focusModel || modelA || modelB);
      const runIdByModel = (duel?.run_id_by_model && typeof duel.run_id_by_model === 'object')
        ? duel.run_id_by_model
        : {};
      const runA = runById.get(String(runIdByModel[modelA] || '')) || null;
      const runB = runById.get(String(runIdByModel[modelB] || '')) || null;
      const summaryA = runA?.summary || {};
      const summaryB = runB?.summary || {};
      const focusRun = focusModel === modelB ? runB : runA;
      const focusSummary = focusRun?.summary || {};
      const focusKpi = (focusSummary.kpi && typeof focusSummary.kpi === 'object') ? focusSummary.kpi : {};
      const formatAB = (a, b, fallback = '--') => `${formatCount(a, fallback)}/${formatCount(b, fallback)}`;
      const formatABFloat = (a, b, digits = 1) => {
        const hasA = a !== null && a !== undefined && Number.isFinite(Number(a));
        const hasB = b !== null && b !== undefined && Number.isFinite(Number(b));
        if (!hasA && !hasB) return '--/--';
        return `${hasA ? formatFloat(Number(a), digits) : '--'}/${hasB ? formatFloat(Number(b), digits) : '--'}`;
      };
      const moralA = summaryA?.kpi?.moral_aggression_index;
      const moralB = summaryB?.kpi?.moral_aggression_index;
      const focusRivalKillsRaw = Number(focusSummary?.rival_kills);
      const focusRivalKills = Number.isFinite(focusRivalKillsRaw) ? Math.max(0, Math.round(focusRivalKillsRaw)) : null;
      const focusRivalKillsText = focusRivalKills == null ? '--/1' : `${formatCount(focusRivalKills, '0')}/1`;

      return [
        { label: 'Score', value: formatAB(summaryA.final_score, summaryB.final_score), tip: `${shortProfile(modelA)}/${shortProfile(modelB)} final score` },
        {
          label: 'Survival',
          value: `${formatCount(summaryA.turns_survived, '--')}/${formatCount(summaryA.max_turns, '--')} | ${formatCount(summaryB.turns_survived, '--')}/${formatCount(summaryB.max_turns, '--')}`,
          tip: `${shortProfile(modelA)} and ${shortProfile(modelB)} turns survived`,
        },
        { label: 'Attack', value: formatAB(summaryA.attack_count, summaryB.attack_count), tip: `${shortProfile(modelA)}/${shortProfile(modelB)} total attacks` },
        { label: 'Rival Kills', value: focusRivalKillsText, tip: `Focus model rival kills / rivals in duel (${shortProfile(focusModel)})` },
        { label: 'NPC Kills', value: formatAB(summaryA.npc_kills, summaryB.npc_kills), tip: `${shortProfile(modelA)}/${shortProfile(modelB)} NPC kills` },
        { label: 'Moral Aggression', value: formatABFloat(moralA, moralB, 1), tip: `${shortProfile(modelA)}/${shortProfile(modelB)} moral aggression index` },
        { label: 'Focus model', value: shortProfile(focusModel), tip: 'Current focus for details and state panels' },
        { label: 'Coverage', value: (focusKpi.coverage_pct != null) ? `${formatFloat(focusKpi.coverage_pct, 1)}%` : 'n/a', tip: `Coverage for focus model ${shortProfile(focusModel)}` },
        { label: 'Revisit ratio', value: formatFloat(focusKpi.revisit_ratio, 2), tip: `Revisit ratio for focus model ${shortProfile(focusModel)}` },
        { label: 'Conversion', value: (focusKpi.resource_conversion_efficiency_pct != null) ? `${formatFloat(focusKpi.resource_conversion_efficiency_pct, 1)}%` : 'n/a', tip: `Resource conversion for focus model ${shortProfile(focusModel)}` },
      ];
    }

    function renderReplayHeader(run, context = null) {
      if (context?.mode === 'duel' && context?.duel) {
        const duel = context.duel;
        const modelA = String(context.modelA || duel.model_a || '');
        const modelB = String(context.modelB || duel.model_b || '');
        const focusModel = String(context.focusModel || modelA || modelB);
        const focusRun = context.focusRun || run;
        const focusSummary = focusRun?.summary || {};
        const attemptKind = getDuelAttemptKind(duel);
        const attemptText = attemptLabel(attemptKind);
        const statusA = getDuelStatus(duel, modelA);
        const statusB = getDuelStatus(duel, modelB);
        const focusStatus = focusModel === modelB ? statusB : statusA;
        const summaryLine = String(focusSummary.short_summary || '').trim();
        const detailedSummary = String(focusSummary.detailed_summary || '').trim();
        const duelWarnings = Array.isArray(duel?.warnings) ? duel.warnings : [];
        const stripHtml = summaryLine
          ? `<div class="replay-sub-strip"><span class="replay-sub">${escapeHtml(summaryLine)}</span></div>`
          : '';
        const pairKey = String(duel?.pair_key || `${modelA}::${modelB}`);
        const samePairAttempts = duelEntries
          .map((entry, idx) => ({ entry, idx }))
          .filter(item =>
            String(item.entry?.seed) === String(duel?.seed)
            && String(item.entry?.pair_key || `${item.entry?.model_a || ''}::${item.entry?.model_b || ''}`) === pairKey
          )
          .sort((a, b) => attemptSortIndex(getDuelAttemptKind(a.entry)) - attemptSortIndex(getDuelAttemptKind(b.entry)));
        const currentDuelKey = String(duel?.duel_key || `seed${duel?.seed}::${attemptKind}::${pairKey}`);
        const attemptSwitcherHtml = samePairAttempts.length > 1
          ? `<div class="model-switch">
              <span class="muted-label">Attempt:</span>
              ${samePairAttempts.map(item => {
                const selectedStyle = item.idx === selectedDuelIndex ? ' style="color:var(--accent);border-color:var(--accent)"' : '';
                return `<button type="button" data-switch-duel="${item.idx}"${selectedStyle}>${attemptLabel(getDuelAttemptKind(item.entry))}</button>`;
              }).join('')}
            </div>`
          : '';
        const focusSwitcherHtml = `<div class="model-switch">
            <span class="muted-label">Focus:</span>
            <button type="button" data-focus-model="${escapeHtml(modelA)}"${focusModel === modelA ? ' style="color:var(--accent);border-color:var(--accent)"' : ''}>${shortProfile(modelA)}</button>
            <button type="button" data-focus-model="${escapeHtml(modelB)}"${focusModel === modelB ? ' style="color:var(--accent);border-color:var(--accent)"' : ''}>${shortProfile(modelB)}</button>
          </div>`;

        replayHeader.innerHTML = `
          <div class="replay-title">
            <span>${escapeHtml(modelA)} vs ${escapeHtml(modelB)}</span>
            <span style="color:var(--text-dim);font-size:0.78rem">seed ${formatCount(duel.seed)}</span>
            <span class="badge">${attemptText}</span>
            <span class="badge ${focusStatus.className}">${focusStatus.label} (${escapeHtml(shortProfile(focusModel))})</span>
          </div>
          ${stripHtml}
          ${attemptSwitcherHtml}
          ${focusSwitcherHtml}
          ${duelWarnings.length
            ? `<div class="compat-warning">warning: ${escapeHtml(String(duelWarnings[0]))}</div>`
            : ''}
          ${detailedSummary
            ? `<details class="analysis-detail"><summary>Deterministic Analysis</summary><div class="detail-body">${escapeHtml(detailedSummary)}</div></details>`
            : ''}
          <button type="button" class="play-seed-btn" title="Play this seed as human in the browser" style="margin-top:6px;padding:4px 12px;font-size:0.72rem;font-family:var(--font);background:#333;color:var(--text);border:1px solid var(--border);border-radius:4px;cursor:pointer"
            onclick="window.open('http://127.0.0.1:8765/?seed=${duel.seed}&scenario=${encodeURIComponent(DATA.meta?.scenario || 'v0_2_hunt')}&autostart=1', '_blank')">
            &#9654; Play This Seed
          </button>
        `;

        replayHeader.querySelectorAll('[data-switch-duel]').forEach(btn => {
          btn.addEventListener('click', e => {
            e.stopPropagation();
            selectedDuelIndex = Number(btn.getAttribute('data-switch-duel'));
            currentTurnIndex = 0;
            stopAutoPlay();
            renderRunList();
            renderReplay();
          });
        });

        replayHeader.querySelectorAll('[data-focus-model]').forEach(btn => {
          btn.addEventListener('click', e => {
            e.stopPropagation();
            duelFocusByKey[currentDuelKey] = String(btn.getAttribute('data-focus-model') || '');
            stopAutoPlay();
            renderReplay();
          });
        });
        return;
      }

      const summary = run.summary || {};
      const status = getRunStatus(summary);
      const currentAttemptKind = getRunAttemptKind(run);
      const currentAttemptLabel = attemptLabel(currentAttemptKind);
      const deathCause = String(summary.death_cause_human || '').trim();
      const shortSummary = String(summary.short_summary || '').trim();
      const detailedSummary = String(summary.detailed_summary || '').trim();
      const fallbackFacts = [summary.end_reason_human, deathCause]
        .map(value => String(value || '').trim())
        .filter(value => value.length > 0)
        .join(' | ');
      const summaryLine = shortSummary || fallbackFacts;
      const stripHtml = summaryLine
        ? `<div class="replay-sub-strip"><span class="replay-sub">${escapeHtml(summaryLine)}</span></div>`
        : '';

      const sameSeedRuns = runs
        .map((r, i) => ({ r, i }))
        .filter(item =>
          String(item.r.seed) === String(run.seed)
          && getRunAttemptKind(item.r) === currentAttemptKind
          && item.i !== selectedRunIndex
        );

      const sameModelSeedRuns = runs
        .map((r, i) => ({ r, i }))
        .filter(item =>
          String(item.r.seed) === String(run.seed)
          && String(item.r.model_profile || '') === String(run.model_profile || '')
        )
        .sort((a, b) => attemptSortIndex(getRunAttemptKind(a.r)) - attemptSortIndex(getRunAttemptKind(b.r)));

      let switcherHtml = '';
      if (sameSeedRuns.length > 0) {
        switcherHtml = `<div class="model-switch">
          <span class="muted-label">Switch:</span>
          ${sameSeedRuns.map(item => `<button type="button" data-switch-run="${item.i}">${shortProfile(item.r.model_profile)}</button>`).join('')}
        </div>`;
      }

      let attemptSwitcherHtml = '';
      if (sameModelSeedRuns.length > 1) {
        attemptSwitcherHtml = `<div class="model-switch">
          <span class="muted-label">Attempt:</span>
          ${sameModelSeedRuns.map(item => {
            const kind = getRunAttemptKind(item.r);
            const selectedStyle = item.i === selectedRunIndex ? ' style="color:var(--accent);border-color:var(--accent)"' : '';
            return `<button type="button" data-switch-run="${item.i}"${selectedStyle}>${attemptLabel(kind)}</button>`;
          }).join('')}
        </div>`;
      }

      replayHeader.innerHTML = `
        <div class="replay-title">
          <span>${run.model_profile}</span>
          <span style="color:var(--text-dim);font-size:0.78rem">seed ${run.seed}</span>
          <span class="badge">${currentAttemptLabel}</span>
          <span class="badge ${status.className}">${status.label}</span>
        </div>
        ${legacyPvpMode ? '<div class="compat-warning">warning: legacy per-run perspective; switch may diverge</div>' : ''}
        ${stripHtml}
        ${attemptSwitcherHtml}
        ${switcherHtml}
        ${detailedSummary
          ? `<details class="analysis-detail"><summary>Deterministic Analysis</summary><div class="detail-body">${escapeHtml(detailedSummary)}</div></details>`
          : ''}
        <button type="button" class="play-seed-btn" title="Play this seed as human in the browser" style="margin-top:6px;padding:4px 12px;font-size:0.72rem;font-family:var(--font);background:#333;color:var(--text);border:1px solid var(--border);border-radius:4px;cursor:pointer"
          onclick="window.open('http://127.0.0.1:8765/?seed=${run.seed}&scenario=${encodeURIComponent(DATA.meta?.scenario || 'v0_2_hunt')}&autostart=1', '_blank')">
          &#9654; Play This Seed
        </button>
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

    function renderMapSummaryCards(run, frameIndex, context = null) {
      const cards = (context?.mode === 'duel')
        ? buildDuelSummaryCards(context)
        : buildRunSummaryCards(run, frameIndex);
      mapSummaryCards.innerHTML = cards
        .map(c => `<div class="card"${c.tip ? ` data-tip="${c.tip}"` : ''}><div class="label">${c.label}</div><div class="value">${c.value}</div></div>`)
        .join('');
    }

    function renderMap(run, frame, frameIndex, context = null) {
      const world = run.replay?.world || {};
      const width = Math.max(1, numberOr(world.width, 1));
      const height = Math.max(1, numberOr(world.height, 1));
      const map = frame.map_snapshot || [];
      const focusModel = String(context?.focusModel || run.model_profile || '');
      const npcStates = buildNpcStatesForFrame(run, frameIndex);
      const npcsByCoord = new Map();
      let hostileNpcCount = 0;
      const markers = [];

      function normalizePosition(pos) {
        if (!pos) return null;
        if (Array.isArray(pos) && pos.length >= 2) return { x: Number(pos[0] ?? 0), y: Number(pos[1] ?? 0) };
        if (typeof pos === 'object') return { x: Number(pos.x ?? 0), y: Number(pos.y ?? 0) };
        return null;
      }

      const primaryPos = normalizePosition(frame.agent_position_after) || normalizePosition(frame.agent_position_before);
      if (primaryPos) {
        const primaryRole = String(run.model_profile || '') === focusModel ? 'primary' : 'opponent';
        markers.push({
          role: primaryRole,
          x: Number(primaryPos.x),
          y: Number(primaryPos.y),
          label: shortProfile(run.model_profile),
        });
      }

      const opponentSteps = Array.isArray(frame.opponent_steps) ? frame.opponent_steps : [];
      for (const step of opponentSteps) {
        const actionDelta = step?.world_result_delta?.action_delta || {};
        const posAfter = normalizePosition(step?.position_after)
          || normalizePosition(actionDelta?.position_after)
          || normalizePosition(step?.position_before)
          || normalizePosition(actionDelta?.position_before);
        if (!posAfter) continue;
        const stepModel = String(step?.model_profile || step?.agent_id || 'opponent');
        const role = stepModel === focusModel ? 'primary' : 'opponent';
        markers.push({
          role,
          x: Number(posAfter.x),
          y: Number(posAfter.y),
          label: shortProfile(stepModel),
        });
      }

      for (const npc of npcStates) {
        if (!npc || !npc.alive) continue;
        if (!Number.isFinite(npc.x) || !Number.isFinite(npc.y)) continue;
        const key = `${npc.x},${npc.y}`;
        if (!npcsByCoord.has(key)) npcsByCoord.set(key, []);
        npcsByCoord.get(key).push(npc);
        if (npc.hostile) hostileNpcCount += 1;
      }

      const visited = new Set(
        (frame.path_prefix || []).map(pos => `${numberOr(pos.x, 0)},${numberOr(pos.y, 0)}`)
      );

      mapGrid.style.gridTemplateColumns = `repeat(${width}, minmax(52px, 1fr))`;

      const cells = [];
      for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
          const type = String(map?.[y]?.[x] || 'unknown');
          const metaEntry = tileMeta[type] || tileMeta.unknown;

          const markersHere = markers.filter(m => Number(m.x) === x && Number(m.y) === y);
          const isCurrent = markersHere.some(m => m.role === 'primary');
          const isVisited = visited.has(`${x},${y}`);
          const npcsHere = npcsByCoord.get(`${x},${y}`) || [];

          const classes = ['tile', type];
          if (isVisited) classes.push('visited');
          if (isCurrent) classes.push('current');

          cells.push(`
            <div class="${classes.join(' ')}">
              <div class="tile-type">${metaEntry.label}</div>
              <div class="coord">${x},${y}</div>
              <div class="tile-main">${metaEntry.emoji}</div>
              <div class="npc-stack">
                ${npcsHere.map(npc => `<span class="npc-pill ${npc.hostile ? 'hostile' : ''}">${npcEmoji(npc.npc_type)}${npc.hp !== null ? ` ${formatCount(npc.hp)}` : ''}</span>`).join('')}
              </div>
              ${markersHere.length > 0
                ? `<div class="agent-stack">${markersHere.map(m => {
                      const cls = m.role === 'opponent' ? 'agent-mark opponent' : 'agent-mark';
                      const icon = m.role === 'opponent' ? '\\u{1F916}\\u{2694}\\u{FE0F}' : '\\u{1F916}';
                      return `<div class="${cls}">${icon} ${escapeHtml(String(m.label || '-'))}</div>`;
                    }).join('')}</div>`
                : ''}
            </div>
          `);
        }
      }

      mapGrid.innerHTML = cells.join('');
      const coverage = String(run.replay?.meta?.map_coverage || 'partial');
      const hasNpcData = npcStates.length > 0;
      const opponentRaw = String(run.summary?.opponent_model_profile || run.summary?.opponent_model || '').trim();
      const opponentTag = opponentRaw ? shortProfile(opponentRaw) : '';
      const duelLegend = (context?.mode === 'duel')
        ? `| \\u{1F916} focus: ${shortProfile(focusModel)} (${shortProfile(context?.modelA)} vs ${shortProfile(context?.modelB)}) `
        : '';
      const agentLegend = duelLegend || (
        opponentTag
          ? `| \\u{1F916} ${shortProfile(run.model_profile)} vs ${opponentTag} `
          : `| \\u{1F916} ${shortProfile(run.model_profile)} `
      );
      mapLegend.textContent = coverage === 'full'
        ? `full map | dashed = visited ${agentLegend}${hasNpcData ? `| \\u{1F43E} npc${hostileNpcCount > 0 ? ' (red = hostile)' : ''}` : ''}`
        : `partial map (fog) | dashed = visited ${agentLegend}${hasNpcData ? `| \\u{1F43E} npc${hostileNpcCount > 0 ? ' (red = hostile)' : ''}` : ''}`;
    }

    function renderTurnDetails(run, frame, context = null) {
      const rules = replayRules(run);
      const opponentSteps = Array.isArray(frame.opponent_steps) ? frame.opponent_steps : [];
      const focusModel = String(context?.focusModel || run.model_profile || '');
      const sourceModel = String(run.model_profile || '');
      const focusIsOpponent = Boolean(context?.mode === 'duel' && focusModel && focusModel !== sourceModel);
      const focusedOpponentStep = focusIsOpponent
        ? (opponentSteps.find(step => String(step?.model_profile || step?.agent_id || '') === focusModel) || null)
        : null;

      const observation = focusIsOpponent
        ? {
            energy: focusedOpponentStep?.energy_after,
            hunger: null,
            thirst: null,
            inventory: focusedOpponentStep?.inventory_after || {},
            visible_npcs: [],
          }
        : (frame.observation || {});
      const validation = focusIsOpponent
        ? (focusedOpponentStep?.validation_result || {})
        : (frame.validation_result || {});
      const actionResultRaw = focusIsOpponent
        ? (focusedOpponentStep?.action_result || {})
        : (frame.action_result || {});
      const actionResult = {
        ...actionResultRaw,
        requested: String(
          actionResultRaw?.requested
          || focusedOpponentStep?.parsed_action
          || actionResultRaw?.applied
          || '-'
        ),
      };
      const scoreDelta = focusIsOpponent ? {} : (frame.score_delta || {});
      const metrics = focusIsOpponent ? {} : (frame.metrics || {});
      const inventory = (observation && typeof observation === 'object' && observation.inventory && typeof observation.inventory === 'object')
        ? observation.inventory
        : {};

      const isValid = Boolean(validation.is_valid);
      const resultMessage = !isValid
        ? `Invalid: ${validation.error || 'not allowed'}`
        : (actionResult.message || (actionResult.success ? 'Applied.' : 'No effect.'));
      const opponentActions = opponentSteps
        .map(step => {
          const model = shortProfile(step?.model_profile || step?.agent_id || 'opponent');
          const action = String(step?.parsed_action || step?.action_result?.requested || '-');
          return `${model}:${action}`;
        })
        .filter(Boolean);
      const actionOrderText = opponentActions.length
        ? `${String((frame.action_result || {}).requested || '-')} -> ${opponentActions.join(', ')}`
        : String((frame.action_result || {}).requested || '-');

      const badgeClass = isValid ? 'ok' : 'bad';
      const badgeLabel = isValid ? 'VALID' : 'INVALID';
      const focusTag = context?.mode === 'duel' ? ` | focus: ${shortProfile(focusModel)}` : '';
      const scoreText = focusIsOpponent
        ? 'score: n/a (opponent per-turn score not included in source timeline)'
        : `score: ${formatCount(frame.cumulative_score)} (${formatSignedScore(scoreDelta.total || 0)})`;

      turnStatus.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-family:var(--font-mono);font-size:0.82rem">
          <span class="badge ${badgeClass}">${badgeLabel}</span>
          <span style="color:var(--accent);font-weight:700">${actionResult.requested || '-'}</span>
          <span style="color:var(--text-dim)">T${formatCount(frame.turn)}${escapeHtml(focusTag)}</span>
        </div>
        <div style="font-family:var(--font-mono);font-size:0.74rem;color:var(--text-dim);margin-top:4px">${resultMessage}</div>
        <div style="font-family:var(--font-mono);font-size:0.72rem;color:var(--text-secondary);margin-top:2px">order: ${escapeHtml(actionOrderText)}</div>
        <div style="font-family:var(--font-mono);font-size:0.74rem;color:var(--text-secondary);margin-top:2px">${escapeHtml(scoreText)}</div>
      `;

      const meters = [
        { key: 'energy', label: 'Energy', value: observation.energy, max: rules.energyMax },
        { key: 'hunger', label: 'Hunger', value: observation.hunger, max: rules.hungerMax },
        { key: 'thirst', label: 'Thirst', value: observation.thirst, max: rules.thirstMax },
      ];

      stateMeters.innerHTML = meters.map(item => {
        const hasValue = item.value !== null && item.value !== undefined && Number.isFinite(Number(item.value));
        const value = hasValue ? numberOr(item.value, 0) : 0;
        const pct = hasValue ? Math.max(0, Math.min(100, (value / item.max) * 100)) : 0;
        const valueLabel = hasValue ? `${formatCount(value)}/${formatCount(item.max)}` : '--';
        const klass = hasValue ? meterClass(item.key, value, item.max) : 'meter';
        return `
          <div class="${klass}">
            <div class="meter-head"><span>${item.label}</span><span>${valueLabel}</span></div>
            <div class="meter-bar"><div class="meter-fill" style="width:${pct.toFixed(2)}%"></div></div>
          </div>
        `;
      }).join('');

      inventoryGrid.innerHTML = Object.entries(inventoryMeta).map(([key, label]) => {
        return `<div class="inv-item"><span>${label}</span><strong>${formatCount(inventory[key], '0')}</strong></div>`;
      }).join('');

      const visibleNpcs = Array.isArray(observation.visible_npcs) ? observation.visible_npcs : [];
      npcGrid.innerHTML = focusIsOpponent
        ? '<div class="npc-empty">not available in timeline source for focused opponent</div>'
        : (visibleNpcs.length
          ? visibleNpcs.map(rawNpc => {
              const npc = normalizeNpcState(rawNpc);
              if (!npc) return '';
              const status = npc.hostile ? 'hostile' : '';
              const hpLabel = npc.hp === null ? 'hp ?' : `hp ${formatCount(npc.hp)}`;
              return `<div class="npc-item ${status}">
                <span>${npcEmoji(npc.npc_type)} ${escapeHtml(npc.npc_type)} @ ${formatCount(npc.x, '?')},${formatCount(npc.y, '?')}</span>
                <span class="npc-hp">${hpLabel}</span>
              </div>`;
            }).join('')
          : '<div class="npc-empty">none in 3x3 view</div>');

      rawOutput.textContent = focusIsOpponent
        ? (String(focusedOpponentStep?.raw_model_output || '-').trim() || '-')
        : (String(frame.raw_model_output || '-').trim() || '-');

      const eventLines = [
        `delta: ${focusIsOpponent ? 'n/a' : formatSignedScore(scoreDelta.total || 0)}`,
        `events: ${focusIsOpponent ? 'n/a (source-only)' : ((scoreDelta.events || []).map(formatScoreEvent).join(', ') || '-')}`,
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
            <td>${escapeHtml(String(item.action_result?.requested || '-'))}${Array.isArray(item.opponent_steps) && item.opponent_steps.length ? ` -> ${escapeHtml(item.opponent_steps.map(step => `${shortProfile(step?.model_profile || step?.agent_id || 'opponent')}:${String(step?.parsed_action || step?.action_result?.requested || '-')}`).join(', '))}` : ''}</td>
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
      mapSummaryCards.innerHTML = '';
      turnStatus.innerHTML = '';
      stateMeters.innerHTML = '';
      inventoryGrid.innerHTML = '';
      npcGrid.innerHTML = '';
      rawOutput.textContent = '-';
      scoreEvents.textContent = '-';
      timelineBody.innerHTML = '';
      turnMeta.textContent = '0/0';
      turnSlider.min = '1';
      turnSlider.max = '1';
      turnSlider.value = '1';
      if (arcadeFrame) {
        arcadeMeta.textContent = '';
        arcadeNote.textContent = 'Source run: n/a.';
        if (arcadeRunId) arcadeRunId.textContent = `run_id: ${dashboardRunId}`;
        setArcadeAttemptBadge('run');
        arcadeFrame.srcdoc = '<!doctype html><html><body style="margin:0;background:#06080f;color:#9ca3af;font-family:monospace;display:grid;place-items:center;height:100vh">Select Seed/Run to render the arcade view.</body></html>';
        arcadeCacheKey = '';
      }
    }

    function renderReplay() {
      const context = selectedReplayContext();
      const run = context?.run || null;
      if (!run) { renderReplayEmpty(); return; }

      const frames = run.replay?.frames || [];
      if (!frames.length) {
        renderReplayHeader(run, context);
        renderReplayEmpty();
        return;
      }

      currentTurnIndex = clampTurnIndex(currentTurnIndex, frames.length);
      const frame = frames[currentTurnIndex];

      turnSlider.min = '1';
      turnSlider.max = String(frames.length);
      turnSlider.value = String(currentTurnIndex + 1);

      renderReplayHeader(run, context);
      renderMap(run, frame, currentTurnIndex, context);
      renderMapSummaryCards(run, currentTurnIndex, context);
      renderTurnDetails(run, frame, context);
      renderRunList();
      renderArcade();
    }

    function stopAutoPlay() {
      if (autoPlayTimer !== null) {
        window.clearInterval(autoPlayTimer);
        autoPlayTimer = null;
      }
      playTurnBtn.innerHTML = '&#9654; Play';
    }

    function toggleAutoPlay() {
      const run = selectedReplayRun();
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
      if (duelMode) {
        if (!filteredDuelIndexes.length) return;
        const currentPos = filteredDuelIndexes.indexOf(selectedDuelIndex);
        const base = currentPos >= 0 ? currentPos : 0;
        const nextPos = Math.max(0, Math.min(filteredDuelIndexes.length - 1, base + offset));
        selectedDuelIndex = filteredDuelIndexes[nextPos];
      } else {
        if (!filteredRunIndexes.length) return;
        const currentPos = filteredRunIndexes.indexOf(selectedRunIndex);
        const base = currentPos >= 0 ? currentPos : 0;
        const nextPos = Math.max(0, Math.min(filteredRunIndexes.length - 1, base + offset));
        selectedRunIndex = filteredRunIndexes[nextPos];
      }
      currentTurnIndex = 0;
      stopAutoPlay();
      renderRunList();
      renderReplay();
    }

    function moveArcadeRun(offset) {
      const entries = arcadeEntriesForFilters();
      if (!entries.length) return;

      const currentIdx = duelMode ? selectedDuelIndex : selectedRunIndex;
      const currentEntry = entries.find(e => e.idx === currentIdx) || entries[0];
      const requestedSeed = String(arcadeSeedSelect?.value || '').trim();
      const selectedSeed = requestedSeed || String(currentEntry.seed || '');
      const seedEntries = entries.filter(entry => entry.seed === selectedSeed);
      if (!seedEntries.length) return;

      const seedPos = seedEntries.findIndex(entry => entry.idx === currentEntry.idx);
      const base = seedPos >= 0 ? seedPos : 0;
      const nextPos = Math.max(0, Math.min(seedEntries.length - 1, base + offset));
      if (nextPos === base) {
        syncArcadeControls();
        return;
      }

      const targetIdx = seedEntries[nextPos]?.idx;
      if (!Number.isFinite(targetIdx)) return;

      if (duelMode) selectedDuelIndex = targetIdx;
      else selectedRunIndex = targetIdx;
      currentTurnIndex = 0;
      stopAutoPlay();
      renderRunList();
      renderReplay();
    }

    function toggleArcadePlay() {
      if (!arcadeFrame || !arcadeFrame.contentWindow) return;
      try {
        const win = arcadeFrame.contentWindow;
        if (typeof win.togglePause === 'function') {
          win.togglePause();
          return;
        }
        const playBtn = win.document?.getElementById('btn-play');
        if (playBtn) playBtn.click();
      } catch (_) {
        // no-op: iframe may not be ready yet
      }
    }

    function moveTurn(offset) {
      const run = selectedReplayRun();
      const frames = run?.replay?.frames || [];
      if (!frames.length) return;
      currentTurnIndex = clampTurnIndex(currentTurnIndex + offset, frames.length);
      stopAutoPlay();
      renderReplay();
    }

    function bindEvents() {
      [modelFilter, seedFilter, statusFilter, attemptFilter].forEach(node => {
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
      if (arcadePrevBtn) arcadePrevBtn.addEventListener('click', () => moveArcadeRun(-1));
      if (arcadePlayBtn) arcadePlayBtn.addEventListener('click', () => toggleArcadePlay());
      if (arcadeNextBtn) arcadeNextBtn.addEventListener('click', () => moveArcadeRun(1));

      if (arcadeSeedSelect) {
        arcadeSeedSelect.addEventListener('change', () => {
          const wantedSeed = String(arcadeSeedSelect.value || '');
          const entries = arcadeEntriesForFilters().filter(entry => entry.seed === wantedSeed);
          if (!entries.length) return;
          const targetIdx = entries[0].idx;
          if (duelMode) selectedDuelIndex = targetIdx;
          else selectedRunIndex = targetIdx;
          currentTurnIndex = 0;
          stopAutoPlay();
          renderRunList();
          renderReplay();
        });
      }

      if (arcadeRunSelect) {
        arcadeRunSelect.addEventListener('change', () => {
          const targetIdx = Number(arcadeRunSelect.value);
          if (!Number.isFinite(targetIdx)) return;
          if (duelMode) selectedDuelIndex = targetIdx;
          else selectedRunIndex = targetIdx;
          currentTurnIndex = 0;
          stopAutoPlay();
          renderRunList();
          renderReplay();
        });
      }

      prevTurnBtn.addEventListener('click', () => moveTurn(-1));
      nextTurnBtn.addEventListener('click', () => moveTurn(1));
      playTurnBtn.addEventListener('click', () => toggleAutoPlay());

      turnSlider.addEventListener('input', () => {
        const run = selectedReplayRun();
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
      renderBadgeRace();
      renderAdaptiveLearning();
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

    return html_head + html_data + html_arcade_template + html_tail


def generate_compare_viewer(compare_path: Path, output_path: Path, title: str | None = None) -> Path:
    with compare_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    _apply_estimated_cost_fallback(payload)

    page_title = title or "TinyWorld Compare Dashboard"
    html_doc = render_html(payload=payload, page_title=page_title)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_doc, encoding="utf-8")
    return output_path


def _apply_estimated_cost_fallback(payload: dict[str, Any]) -> None:
    """Best-effort cost fallback for stale compare JSON used only by viewer rendering."""
    try:
        pricing_path = (Path.cwd() / "configs/pricing.yaml").resolve()
        if not pricing_path.exists():
            return
        pricing_cfg = load_pricing_config(pricing_path)
    except Exception:
        return

    runs = payload.get("runs")
    if not isinstance(runs, list):
        return

    for run in runs:
        if not isinstance(run, dict):
            continue

        summary = run.get("summary")
        if not isinstance(summary, dict):
            continue

        if run.get("tokens_used") is None and summary.get("tokens_used") is not None:
            run["tokens_used"] = summary.get("tokens_used")

        if run.get("estimated_cost") is not None and summary.get("estimated_cost") is not None:
            continue

        provider_id = str(summary.get("provider_id", run.get("provider_id", ""))).strip()
        model_name = str(summary.get("model", run.get("model", ""))).strip()
        tokens = summary.get("tokens_used", run.get("tokens_used"))
        try:
            tokens_int = int(tokens) if tokens is not None else None
        except (TypeError, ValueError):
            tokens_int = None
        if tokens_int is None:
            continue

        pricing = resolve_model_pricing(
            pricing_cfg=pricing_cfg,
            provider_id=provider_id,
            model=model_name,
        )
        cost = estimate_cost_from_total_tokens(pricing=pricing, total_tokens=tokens_int)
        if cost is None:
            continue

        cost = round(float(cost), 6)
        run["estimated_cost"] = cost
        run["estimated_cost_source"] = run.get("estimated_cost_source") or "pricing_fallback_viewer"
        summary["estimated_cost"] = cost
        summary["estimated_cost_source"] = summary.get("estimated_cost_source") or "pricing_fallback_viewer"

    models = payload.get("models")
    if not isinstance(models, list):
        return

    for model_row in models:
        if not isinstance(model_row, dict):
            continue
        profile = str(model_row.get("model_profile", "")).strip()
        if not profile:
            continue

        model_runs = [r for r in runs if isinstance(r, dict) and str(r.get("model_profile", "")).strip() == profile]
        if not model_runs:
            continue

        baseline_cost = 0.0
        baseline_seen = False
        adaptive_cost = 0.0
        adaptive_seen = False

        for r in model_runs:
            s = r.get("summary")
            if not isinstance(s, dict):
                continue
            cost_val = s.get("estimated_cost", r.get("estimated_cost"))
            try:
                cost_f = float(cost_val) if cost_val is not None else None
            except (TypeError, ValueError):
                cost_f = None
            if cost_f is None:
                continue
            attempt_kind = str(r.get("attempt_kind", s.get("attempt_kind", "initial"))).strip()
            if attempt_kind == "initial":
                baseline_cost += cost_f
                baseline_seen = True
            else:
                adaptive_cost += cost_f
                adaptive_seen = True

        if model_row.get("estimated_cost_total") is None and baseline_seen:
            model_row["estimated_cost_total"] = round(baseline_cost, 6)
        if model_row.get("estimated_cost_adaptive") is None and adaptive_seen:
            model_row["estimated_cost_adaptive"] = round(adaptive_cost, 6)
        if model_row.get("estimated_cost_grand_total") is None:
            total = 0.0
            total_seen = False
            if baseline_seen:
                total += baseline_cost
                total_seen = True
            if adaptive_seen:
                total += adaptive_cost
                total_seen = True
            if total_seen:
                model_row["estimated_cost_grand_total"] = round(total, 6)


def _short_path(path: Path) -> str:
    resolved = path.resolve()
    cwd = Path.cwd().resolve()
    try:
        return str(resolved.relative_to(cwd))
    except ValueError:
        return str(resolved)


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
    parser.add_argument(
        "--serve",
        nargs="?",
        const=8765,
        type=int,
        default=None,
        metavar="PORT",
        help="Serve the generated dashboard via local HTTP (http://127.0.0.1:PORT). If PORT is omitted, 8765 is used.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.serve is not None and not (1 <= int(args.serve) <= 65535):
        parser.error("--serve port must be between 1 and 65535.")
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

    browser_target = generated.resolve().as_uri()
    if args.serve is not None:
        _, started = _ensure_http_server(int(args.serve), Path.cwd())
        browser_target = _build_http_viewer_url(generated, Path.cwd(), int(args.serve))
        server_state = "started" if started else "already running"
        print(f"  Server:       {browser_target} ({server_state})")

    if args.open_browser:
        opened = webbrowser.open(browser_target)
        if opened:
            print("  Browser:      opened in your default browser")
        else:
            print("  Browser:      generated, but failed to auto-open")
    else:
        print("  Browser:      not opened (use --open-browser)")


if __name__ == "__main__":
    main()
