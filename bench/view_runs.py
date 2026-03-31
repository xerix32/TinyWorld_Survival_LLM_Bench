from __future__ import annotations

import argparse
import json
import shlex
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bench.cli_ui import colorize, use_color
from bench.view_compare import generate_compare_viewer
from engine.version import __version__


def _short_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except Exception:
        return str(path.resolve())


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not (1 <= port <= 65535):
        raise argparse.ArgumentTypeError("port must be in range 1..65535")
    return port


def _run_id_to_local_started(run_id: str) -> str | None:
    # Run IDs use UTC format: YYYYMMDDTHHMMSSZ
    if len(run_id) != 16 or not run_id.endswith("Z") or run_id[8] != "T":
        return None
    try:
        dt_utc = datetime.strptime(run_id, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    dt_local = dt_utc.astimezone()
    return dt_local.strftime("%Y-%m-%d %H:%M:%S %Z")


def _find_compare_json(run_dir: Path, run_id: str) -> Path | None:
    expected = run_dir / "results" / f"compare_{run_id}.json"
    if expected.exists():
        return expected.resolve()
    candidates = sorted((run_dir / "results").glob("compare_*.json")) if (run_dir / "results").exists() else []
    if candidates:
        return candidates[-1].resolve()
    return None


def _find_compare_html(run_dir: Path, run_id: str) -> Path | None:
    expected = run_dir / "replays" / f"compare_{run_id}_dashboard.html"
    if expected.exists():
        return expected.resolve()
    candidates = sorted((run_dir / "replays").glob("compare_*_dashboard.html")) if (run_dir / "replays").exists() else []
    if candidates:
        return candidates[-1].resolve()
    return None


def _load_compare_meta(compare_json: Path) -> dict:
    try:
        payload = json.loads(compare_json.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    meta = payload.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    # Extract max score across all models
    model_summaries = payload.get("models") or payload.get("model_summaries") or []
    if isinstance(model_summaries, list) and model_summaries:
        scores = [s.get("avg_final_score") for s in model_summaries if isinstance(s, dict) and s.get("avg_final_score") is not None]
        if scores:
            meta["max_score"] = max(scores)
    return meta


def _build_bench_command(meta: dict) -> str:
    models = meta.get("requested_models") or meta.get("models") or []
    if not isinstance(models, list):
        models = []

    cmd: list[str] = ["python", "-m", "bench.run_compare"]
    if models:
        cmd.extend(["--models", ",".join(str(x) for x in models)])

    seeds = meta.get("seed_list")
    if isinstance(seeds, list) and seeds:
        cmd.extend(["--seeds", ",".join(str(s) for s in seeds)])
    else:
        runs_per_model = meta.get("runs_per_model")
        if isinstance(runs_per_model, int) and runs_per_model > 0:
            cmd.extend(["--num-runs", str(runs_per_model)])

    scenario = meta.get("scenario")
    if scenario:
        cmd.extend(["--scenario", str(scenario)])

    if bool(meta.get("adaptive_mode")):
        cmd.append("--adaptive-memory")

    cmd.append("--open-browser")
    return shlex.join(cmd)


def _build_regen_command(compare_json: Path, run_id: str) -> str:
    output = compare_json.parent.parent / "replays" / f"compare_{run_id}_dashboard.html"
    cmd = [
        "python",
        "-m",
        "bench.view_compare",
        "--compare",
        _short_path(compare_json),
        "--output",
        _short_path(output),
        "--open-browser",
    ]
    return shlex.join(cmd)


def _cache_file_for_runs_root(runs_root: Path) -> Path:
    return (runs_root.parent / ".cache" / "view_runs_index.json").resolve()


def _file_fingerprint(path: Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return {
        "path": str(path.resolve()),
        "mtime_ns": int(stat.st_mtime_ns),
        "size": int(stat.st_size),
    }


def _build_row(run_id: str, compare_json: Path | None, compare_html: Path | None, meta: dict[str, Any]) -> dict[str, Any]:
    models = meta.get("models")
    seed_list = meta.get("seed_list")
    models_list = models if isinstance(models, list) else []
    is_human = any("human" in str(m).lower() for m in models_list)
    return {
        "run_id": run_id,
        "started": _run_id_to_local_started(run_id) or "n/a",
        "scenario": str(meta.get("scenario", "n/a")),
        "protocol": str(meta.get("protocol_version", "n/a")),
        "bench": str(meta.get("bench_version", "n/a")),
        "engine": str(meta.get("engine_version", "n/a")),
        "models": len(models_list),
        "seeds": len(seed_list) if isinstance(seed_list, list) else 0,
        "adaptive": "yes" if bool(meta.get("adaptive_mode")) else "no",
        "is_human": is_human,
        "max_score": meta.get("max_score"),
        "compare_json": _short_path(compare_json) if compare_json else "",
        "compare_html": _short_path(compare_html) if compare_html else "",
        "can_regen": bool(compare_json),
        "can_open": bool(compare_html),
        "bench_cmd": _build_bench_command(meta),
        "regen_cmd": _build_regen_command(compare_json, run_id) if compare_json else "",
    }


def _load_runs_cache(cache_path: Path) -> dict[str, dict[str, Any]]:
    if not cache_path.exists():
        return {}
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for run_id, entry in entries.items():
        if not isinstance(run_id, str) or not isinstance(entry, dict):
            continue
        fp = entry.get("fingerprint")
        row = entry.get("row")
        if not isinstance(fp, dict) or not isinstance(row, dict):
            continue
        out[run_id] = {"fingerprint": fp, "row": row}
    return out


def _save_runs_cache(cache_path: Path, entries: dict[str, dict[str, Any]]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "view_runs_index_v1",
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cache_path)


def _refresh_runs_index(
    runs_root: Path,
    cache_entries: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    next_entries: dict[str, dict[str, Any]] = {}
    reused = 0
    rebuilt = 0

    if not runs_root.exists():
        return rows, next_entries, {"reused": reused, "rebuilt": rebuilt}

    run_dirs = sorted([p for p in runs_root.iterdir() if p.is_dir()], reverse=True)

    for run_dir in run_dirs:
        run_id = run_dir.name
        compare_json = _find_compare_json(run_dir, run_id)
        compare_html = _find_compare_html(run_dir, run_id)
        current_fp = {
            "compare_json": _file_fingerprint(compare_json),
            "compare_html": _file_fingerprint(compare_html),
        }

        cached_entry = cache_entries.get(run_id)
        if cached_entry and cached_entry.get("fingerprint") == current_fp:
            row = cached_entry.get("row")
            if isinstance(row, dict):
                rows.append(row)
                next_entries[run_id] = cached_entry
                reused += 1
                continue

        meta = _load_compare_meta(compare_json) if compare_json else {}
        row = _build_row(run_id, compare_json, compare_html, meta)
        rows.append(row)
        next_entries[run_id] = {"fingerprint": current_fp, "row": row}
        rebuilt += 1

    return rows, next_entries, {"reused": reused, "rebuilt": rebuilt}


class _RunsIndex:
    def __init__(self, runs_root: Path):
        self._runs_root = runs_root
        self._cache_path = _cache_file_for_runs_root(runs_root)
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] = _load_runs_cache(self._cache_path)
        self._rows: list[dict[str, Any]] = []
        self._refresh_locked(initial=True)

    def _refresh_locked(self, *, initial: bool = False) -> None:
        rows, next_entries, _stats = _refresh_runs_index(self._runs_root, self._entries)
        entries_changed = next_entries != self._entries
        rows_changed = rows != self._rows

        self._entries = next_entries
        self._rows = rows

        # Persist cache on first build and whenever entries change.
        if initial or entries_changed or rows_changed:
            try:
                _save_runs_cache(self._cache_path, self._entries)
            except Exception:
                # Cache write must never break catalog serving.
                pass

    @property
    def runs_root(self) -> Path:
        return self._runs_root

    def get_rows(self) -> list[dict[str, Any]]:
        with self._lock:
            self._refresh_locked()
            return list(self._rows)


def _render_index_html() -> str:
    return """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>TinyWorld Runs Catalog</title>
  <style>
    :root { color-scheme: dark; }
    body { margin: 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; background: #0d1017; color: #dbe5ff; }
    .wrap { max-width: 1700px; margin: 0 auto; padding: 16px; }
    h1 { margin: 0 0 10px; font-size: 20px; color: #7ee7ff; }
    .bar { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
    button, select {
      border: 1px solid #2b455f; background: #102032; color: #bfeeff; padding: 8px 10px; border-radius: 8px; cursor: pointer;
      font-family: inherit;
    }
    button:hover, select:hover { border-color: #47d2ff; }
    button:disabled { opacity: 0.45; cursor: not-allowed; }
    input[type='text'] {
      width: 360px; max-width: 100%;
      background: #0c1624; color: #dbe5ff; border: 1px solid #263647; border-radius: 8px; padding: 8px;
      font-family: inherit;
    }
    .chip { display: inline-block; padding: 2px 6px; border-radius: 999px; border: 1px solid #2f4157; color: #aad7ff; }
    .loading-chip { display: inline-flex; align-items: center; gap: 6px; color: #7ee7ff; border-color: #2f7aa0; }
    .hidden { display: none !important; }
    .spinner {
      width: 11px; height: 11px; border-radius: 50%;
      border: 2px solid rgba(126, 231, 255, 0.25);
      border-top-color: #7ee7ff;
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }
    .table-wrap { border: 1px solid #1a2432; border-radius: 10px; overflow: auto; background: #0b1119; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; min-width: 1340px; }
    th, td { border-bottom: 1px solid #1a2432; padding: 7px 8px; text-align: left; vertical-align: top; position: relative; }
    th {
      color: #9ec3df; cursor: pointer; user-select: none; position: sticky; top: 0; background: #0d1017; z-index: 2;
      white-space: nowrap;
    }
    tr:hover { background: #0f1621; }
    .mono { font-family: inherit; }
    .run-id { white-space: nowrap; color: #d6ebff; font-weight: 600; }
    .started { line-height: 1.2; }
    .started .date { color: #dbe5ff; white-space: nowrap; }
    .started .tz { color: #7ea1bf; font-size: 11px; margin-top: 1px; }
    .act { display: flex; gap: 4px; flex-wrap: nowrap; white-space: nowrap; }
    .icon-btn {
      min-width: 34px; padding: 6px 7px; text-align: center; line-height: 1; font-size: 13px;
      border-radius: 7px;
    }
    .msg { white-space: pre-wrap; color: #9ec3df; margin-top: 8px; }
    .ok { color: #6ef7b0; }
    .err { color: #ff7f9f; }
    td.path { white-space: normal; overflow-wrap: anywhere; word-break: break-word; line-height: 1.2; }
    .path-dir { color: #88a5c4; font-size: 11px; margin-bottom: 1px; }
    .path-file { color: #dbe5ff; font-size: 12px; }
    .th-wrap { display: flex; align-items: center; gap: 6px; }
    .sort-ind { color: #79c9f0; font-size: 12px; min-width: 10px; display: inline-block; text-align: center; }
    .resizer {
      position: absolute; right: 0; top: 0; width: 6px; height: 100%;
      cursor: col-resize; user-select: none; touch-action: none;
    }
    .resizer:hover, .resizer.active { background: rgba(71, 210, 255, 0.2); }
    th.edge-hot, td.edge-hot { box-shadow: inset -2px 0 0 rgba(71, 210, 255, 0.45); cursor: col-resize; }
    .pager {
      display: flex; gap: 8px; align-items: center; justify-content: flex-end;
      margin-top: 10px; flex-wrap: wrap;
    }
    .pager .info { color: #9ec3df; min-width: 210px; text-align: right; }
    .muted { color: #7ea1bf; }
    .main-row:hover { background: #1e2530; }
    .detail-row td { font-size: 12px; }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>TinyWorld Runs Catalog <span style="font-size:0.55em;color:#7ea1bf;font-weight:400">v""" + __version__ + """</span></h1>
    <div class=\"bar\">
      <button id=\"refreshBtn\">Refresh</button>
      <input id=\"filterInput\" type=\"text\" placeholder=\"Filter by run/scenario/protocol/model count...\" />
      <span id=\"stats\" class=\"chip\"></span>
      <span id=\"loadingChip\" class=\"chip loading-chip hidden\"><span class=\"spinner\"></span><span>Loading</span></span>
    </div>
    <div class=\"table-wrap\">
      <table id=\"runsTable\">
        <colgroup id=\"runsCols\">
          <col style=\"width: 170px\" />
          <col style=\"width: 150px\" />
          <col style=\"width: 118px\" />
          <col style=\"width: 90px\" />
          <col style=\"width: 70px\" />
          <col style=\"width: 70px\" />
          <col style=\"width: 62px\" />
          <col style=\"width: 60px\" />
          <col style=\"width: 78px\" />
          <col style=\"width: 80px\" />
          <col style=\"width: 196px\" />
        </colgroup>
        <thead>
          <tr>
            <th data-k=\"run_id\" data-col-idx=\"0\"><span class=\"th-wrap\">Run ID <span class=\"sort-ind\">↕</span></span><span class=\"resizer\"></span></th>
            <th data-k=\"started\" data-col-idx=\"1\"><span class=\"th-wrap\">Started <span class=\"sort-ind\">↕</span></span><span class=\"resizer\"></span></th>
            <th data-k=\"scenario\" data-col-idx=\"2\"><span class=\"th-wrap\">Scenario <span class=\"sort-ind\">↕</span></span><span class=\"resizer\"></span></th>
            <th data-k=\"protocol\" data-col-idx=\"3\"><span class=\"th-wrap\">Protocol <span class=\"sort-ind\">↕</span></span><span class=\"resizer\"></span></th>
            <th data-k=\"bench\" data-col-idx=\"4\"><span class=\"th-wrap\">Bench <span class=\"sort-ind\">↕</span></span><span class=\"resizer\"></span></th>
            <th data-k=\"engine\" data-col-idx=\"5\"><span class=\"th-wrap\">Engine <span class=\"sort-ind\">↕</span></span><span class=\"resizer\"></span></th>
            <th data-k=\"models\" data-col-idx=\"6\"><span class=\"th-wrap\">Models <span class=\"sort-ind\">↕</span></span><span class=\"resizer\"></span></th>
            <th data-k=\"seeds\" data-col-idx=\"7\"><span class=\"th-wrap\">Seeds <span class=\"sort-ind\">↕</span></span><span class=\"resizer\"></span></th>
            <th data-k=\"adaptive\" data-col-idx=\"8\"><span class=\"th-wrap\">Adaptive <span class=\"sort-ind\">↕</span></span><span class=\"resizer\"></span></th>
            <th data-k=\"max_score\" data-col-idx=\"9\"><span class=\"th-wrap\">Max Score <span class=\"sort-ind\">↕</span></span><span class=\"resizer\"></span></th>
            <th data-col-idx=\"10\"><span class=\"th-wrap\">Actions</span><span class=\"resizer\"></span></th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
    <div class=\"pager\">
      <button id=\"pagePrevBtn\">◀ Prev</button>
      <button id=\"pageNextBtn\">Next ▶</button>
      <span class=\"muted\">Rows per page:</span>
      <select id=\"pageSizeSelect\">
        <option value=\"5\">5</option>
        <option value=\"10\" selected>10</option>
        <option value=\"25\">25</option>
        <option value=\"50\">50</option>
        <option value=\"100\">100</option>
      </select>
      <span id=\"pageInfo\" class=\"info\"></span>
    </div>
    <div id=\"msg\" class=\"msg\"></div>
  </div>
  <script>
    let rows = [];
    let sortKey = 'run_id';
    let sortDir = -1;
    let pageSize = 10;
    let pageIndex = 0;

    function esc(s) {
      return String(s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
    }

    function pathHtml(p) {
      const s = String(p ?? '');
      if (!s) return '';
      const i = s.lastIndexOf('/');
      if (i < 0) return `<div class="path-file" title="${esc(s)}">${esc(s)}</div>`;
      const dir = s.slice(0, i + 1);
      const file = s.slice(i + 1);
      return `<div class="path-dir" title="${esc(s)}">${esc(dir).replaceAll('/', '/<wbr>')}</div><div class="path-file" title="${esc(s)}">${esc(file)}</div>`;
    }

    function startedHtml(v) {
      const s = String(v ?? '');
      if (!s || s === 'n/a') return 'n/a';
      const parts = s.split(' ');
      if (parts.length < 3) return esc(s);
      return `<div class="started"><div class="date">${esc(parts[0])} ${esc(parts[1])}</div><div class="tz">${esc(parts.slice(2).join(' '))}</div></div>`;
    }

    async function fetchRuns() {
      const loadingChip = document.getElementById('loadingChip');
      const refreshBtn = document.getElementById('refreshBtn');
      if (loadingChip) loadingChip.classList.remove('hidden');
      if (refreshBtn) refreshBtn.disabled = true;
      try {
        const r = await fetch('/api/runs');
        if (!r.ok) throw new Error('failed to fetch /api/runs');
        rows = await r.json();
        pageIndex = 0;
        render();
      } finally {
        if (loadingChip) loadingChip.classList.add('hidden');
        if (refreshBtn) refreshBtn.disabled = false;
      }
    }

    function comparator(a, b) {
      const av = a[sortKey];
      const bv = b[sortKey];
      const aN = av == null; const bN = bv == null;
      if (aN && bN) return 0;
      if (aN) return 1;
      if (bN) return -1;
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sortDir;
      return String(av).localeCompare(String(bv)) * sortDir;
    }

    function filteredRows() {
      const q = document.getElementById('filterInput').value.trim().toLowerCase();
      let out = [...rows].sort(comparator);
      if (!q) return out;
      return out.filter((r) => {
        const s = `${r.run_id} ${r.started} ${r.scenario} ${r.protocol} ${r.bench} ${r.engine} ${r.models} ${r.seeds} ${r.adaptive} ${r.is_human ? 'human' : ''}`.toLowerCase();
        return s.includes(q);
      });
    }

    function updateSortIndicators() {
      for (const th of document.querySelectorAll('th[data-k]')) {
        const ind = th.querySelector('.sort-ind');
        if (!ind) continue;
        const k = th.dataset.k;
        if (k === sortKey) ind.textContent = (sortDir === 1 ? '↑' : '↓');
        else ind.textContent = '↕';
      }
    }

    function setMsg(text, cls='') {
      const el = document.getElementById('msg');
      el.className = `msg ${cls}`;
      el.textContent = text || '';
    }

    function copyText(text) {
      if (!text) return;
      navigator.clipboard?.writeText(text).then(() => setMsg('Copied command to clipboard.', 'ok')).catch(() => setMsg(text, ''));
    }

    async function regen(runId) {
      setMsg(`Regenerating viewer for ${runId}...`);
      const r = await fetch('/api/regenerate', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({run_id: runId})});
      const payload = await r.json().catch(() => ({}));
      if (!r.ok || payload.ok === false) {
        setMsg(payload.error || `Regenerate failed for ${runId}`, 'err');
        return;
      }
      setMsg(`Viewer regenerated: ${payload.html || ''}`, 'ok');
      await fetchRuns();
    }

    function render() {
      const body = document.querySelector('#runsTable tbody');
      const list = filteredRows();
      const total = list.length;
      const totalPages = Math.max(1, Math.ceil(total / pageSize));
      if (pageIndex >= totalPages) pageIndex = totalPages - 1;

      const start = pageIndex * pageSize;
      const pageRows = list.slice(start, start + pageSize);
      const end = Math.min(total, start + pageRows.length);

      document.getElementById('stats').textContent = `${total} run(s)`;
      document.getElementById('pageInfo').textContent = `Showing ${total === 0 ? 0 : start + 1}-${end} of ${total} · Page ${total === 0 ? 0 : pageIndex + 1}/${totalPages}`;
      document.getElementById('pagePrevBtn').disabled = (pageIndex <= 0);
      document.getElementById('pageNextBtn').disabled = (pageIndex >= totalPages - 1 || total === 0);

      body.innerHTML = pageRows.map((r, ri) => {
        const openDisabled = r.can_open ? '' : 'disabled';
        const regenDisabled = r.can_regen ? '' : 'disabled';
        const humanTag = r.is_human ? '<div style="font-size:10px;color:#ffc107;margin-top:2px">human</div>' : '';
        const rowIdx = start + ri;
        const detailRow = `<tr class="detail-row" id="detail-${rowIdx}" style="display:none">
          <td colspan="11" style="padding:8px 12px;background:#1a1d23;border-bottom:1px solid #333">
            <div style="display:flex;flex-wrap:wrap;gap:16px;font-size:0.78rem">
              <div><span style="color:#7ea1bf">Compare JSON:</span> <span class="mono">${esc(r.compare_json) || 'n/a'}</span></div>
              <div><span style="color:#7ea1bf">Dashboard HTML:</span> <span class="mono">${esc(r.compare_html) || 'n/a'}</span></div>
            </div>
          </td>
        </tr>`;
        return `<tr class="main-row" style="cursor:pointer" onclick="toggleDetail(${rowIdx})">
          <td class="mono run-id">${esc(r.run_id)}${humanTag}</td>
          <td class="mono">${startedHtml(r.started)}</td>
          <td>${esc(r.scenario)}</td>
          <td>${esc(r.protocol)}</td>
          <td>${esc(r.bench)}</td>
          <td>${esc(r.engine)}</td>
          <td>${esc(r.models)}</td>
          <td>${esc(r.seeds)}</td>
          <td>${esc(r.adaptive)}</td>
          <td style="text-align:right;font-weight:600;color:${r.max_score != null ? '#4caf50' : '#555'}">${r.max_score != null ? r.max_score : '-'}</td>
          <td>
            <div class="act">
              <button class="icon-btn" ${openDisabled} title="Open HTML" aria-label="Open HTML" onclick="event.stopPropagation();window.open('/${esc(r.compare_html)}','_blank')">🌐</button>
              <button class="icon-btn" ${regenDisabled} title="Regenerate viewer HTML" aria-label="Regenerate viewer HTML" onclick="event.stopPropagation();regen('${esc(r.run_id)}')">♻️</button>
              <button class="icon-btn" title="Copy view_compare command" aria-label="Copy view_compare command" onclick="event.stopPropagation();copyText(${JSON.stringify(r.regen_cmd)})">📋V</button>
              <button class="icon-btn" title="Copy run_compare command" aria-label="Copy run_compare command" onclick="event.stopPropagation();copyText(${JSON.stringify(r.bench_cmd)})">📋B</button>
            </div>
          </td>
        </tr>${detailRow}`;
      }).join('');
      updateSortIndicators();
    }

    function setupColumnResizers() {
      const cols = document.querySelectorAll('#runsCols col');
      const table = document.getElementById('runsTable');
      const tbody = table.querySelector('tbody');
      const headers = table.querySelectorAll('thead th');

      let activeHotCell = null;
      let activeHotHeader = null;

      function clearHot() {
        if (activeHotCell) activeHotCell.classList.remove('edge-hot');
        if (activeHotHeader) activeHotHeader.classList.remove('edge-hot');
        activeHotCell = null;
        activeHotHeader = null;
      }

      function startResize(idx, startX, startW) {
        const headerHandle = headers[idx]?.querySelector('.resizer');
        if (headerHandle) headerHandle.classList.add('active');
        const onMove = (mv) => {
          const next = Math.max(55, startW + (mv.clientX - startX));
          cols[idx].style.width = `${next}px`;
        };
        const onUp = () => {
          if (headerHandle) headerHandle.classList.remove('active');
          clearHot();
          window.removeEventListener('mousemove', onMove);
          window.removeEventListener('mouseup', onUp);
        };
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
      }

      for (const th of document.querySelectorAll('#runsTable thead th[data-col-idx]')) {
        const idx = Number(th.dataset.colIdx);
        const handle = th.querySelector('.resizer');
        if (!handle || Number.isNaN(idx) || !cols[idx]) continue;
        handle.addEventListener('mousedown', (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          startResize(idx, ev.clientX, cols[idx].offsetWidth);
        });
      }

      tbody.addEventListener('mousemove', (ev) => {
        const td = ev.target.closest('td');
        if (!td) {
          clearHot();
          return;
        }
        const rect = td.getBoundingClientRect();
        const nearRightEdge = ev.clientX >= (rect.right - 6);
        const idx = td.cellIndex;
        if (!nearRightEdge || Number.isNaN(idx) || !cols[idx]) {
          clearHot();
          return;
        }
        clearHot();
        activeHotCell = td;
        activeHotHeader = headers[idx] || null;
        if (activeHotCell) activeHotCell.classList.add('edge-hot');
        if (activeHotHeader) activeHotHeader.classList.add('edge-hot');
      });

      tbody.addEventListener('mouseleave', clearHot);

      tbody.addEventListener('mousedown', (ev) => {
        const td = ev.target.closest('td');
        if (!td) return;
        const rect = td.getBoundingClientRect();
        const nearRightEdge = ev.clientX >= (rect.right - 6);
        const idx = td.cellIndex;
        if (!nearRightEdge || Number.isNaN(idx) || !cols[idx]) return;
        ev.preventDefault();
        ev.stopPropagation();
        startResize(idx, ev.clientX, cols[idx].offsetWidth);
      });
    }

    document.getElementById('refreshBtn').addEventListener('click', fetchRuns);
    document.getElementById('filterInput').addEventListener('input', () => { pageIndex = 0; render(); });
    document.getElementById('pageSizeSelect').addEventListener('change', (ev) => {
      pageSize = Number(ev.target.value) || 10;
      pageIndex = 0;
      render();
    });
    document.getElementById('pagePrevBtn').addEventListener('click', () => {
      if (pageIndex > 0) pageIndex -= 1;
      render();
    });
    document.getElementById('pageNextBtn').addEventListener('click', () => {
      pageIndex += 1;
      render();
    });

    for (const th of document.querySelectorAll('th[data-k]')) {
      th.addEventListener('click', () => {
        const k = th.dataset.k;
        if (sortKey === k) sortDir *= -1;
        else {
          sortKey = k;
          sortDir = -1;
        }
        pageIndex = 0;
        render();
      });
    }

    function toggleDetail(idx) {
      const row = document.getElementById('detail-' + idx);
      if (row) row.style.display = row.style.display === 'none' ? '' : 'none';
    }

    setupColumnResizers();
    fetchRuns().catch((e) => setMsg(String(e), 'err'));
  </script>
</body>
</html>
"""


def _make_handler(runs_index: _RunsIndex, cwd: Path):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(cwd), **kwargs)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _send_json(self, payload: dict | list, code: int = 200) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0") or "0")
            data = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(data.decode("utf-8"))
            except Exception:
                payload = {}
            return payload if isinstance(payload, dict) else {}

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                html = _render_index_html().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                return
            if parsed.path == "/api/runs":
                rows = runs_index.get_rows()
                self._send_json(rows)
                return
            return super().do_GET()

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/regenerate":
                self._send_json({"ok": False, "error": "not found"}, code=404)
                return

            payload = self._read_json_body()
            run_id = str(payload.get("run_id", "")).strip()
            if not run_id:
                self._send_json({"ok": False, "error": "run_id is required"}, code=400)
                return

            run_dir = runs_index.runs_root / run_id
            compare_json = _find_compare_json(run_dir, run_id)
            if not compare_json:
                self._send_json({"ok": False, "error": f"compare json not found for run {run_id}"}, code=404)
                return

            output_path = run_dir / "replays" / f"compare_{run_id}_dashboard.html"
            try:
                generated = generate_compare_viewer(compare_path=compare_json, output_path=output_path, title=None)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"ok": False, "error": f"regeneration failed: {exc}"}, code=500)
                return

            self._send_json({"ok": True, "run_id": run_id, "html": _short_path(generated)})

    return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve TinyWorld runs catalog and regenerate compare viewers")
    parser.add_argument(
        "--runs-root",
        type=str,
        default="artifacts/runs",
        help="Runs root directory (default: artifacts/runs)",
    )
    parser.add_argument(
        "--serve",
        nargs="?",
        const=8080,
        type=_parse_port,
        default=8080,
        metavar="PORT",
        help="Serve the runs catalog via local HTTP (default: 8080)",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the runs catalog in your default browser.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    color_enabled = use_color()

    runs_root = Path(args.runs_root)
    if not runs_root.is_absolute():
        runs_root = (Path.cwd() / runs_root).resolve()

    if not runs_root.exists():
        print(
            colorize("TinyWorld Runs Catalog", "1;36", color_enabled)
            + " "
            + colorize(f"v{__version__}", "1;97", color_enabled)
        )
        print(colorize(f"Runs root not found: {_short_path(runs_root)}", "1;91", color_enabled))
        sys.exit(1)

    port = int(args.serve)
    runs_index = _RunsIndex(runs_root)
    handler = _make_handler(runs_index, Path.cwd())
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)

    url = f"http://127.0.0.1:{port}/"
    url_colored = (
        colorize("http://127.0.0.1", "1;96", color_enabled)
        + colorize(":", "1;97", color_enabled)
        + colorize(str(port), "1;93", color_enabled)
        + colorize("/", "1;96", color_enabled)
    )
    print(
        colorize("TinyWorld Runs Catalog", "1;36", color_enabled)
        + " "
        + colorize(f"v{__version__}", "1;97", color_enabled)
    )
    print("Runs catalog ready")
    print(f"  Runs root: {colorize(_short_path(runs_root), '1;97', color_enabled)}")
    print(f"  URL:       {url_colored}")

    if args.open_browser:
        opened = webbrowser.open(url)
        if opened:
            print("  Browser:   opened in your default browser")
        else:
            print("  Browser:   failed to auto-open")
    else:
        print("  Browser:   not opened (use --open-browser)")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
