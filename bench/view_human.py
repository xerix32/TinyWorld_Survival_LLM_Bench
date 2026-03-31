"""Human Play Web — interactive browser-based TinyWorld gameplay with benchmark-compatible log output."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from analysis.run_analyzer import build_run_analysis
from bench.common import DEFAULT_AGENT_ID, load_configs, resolve_artifact_dirs
from engine.actions import ActionOutcome, apply_action
from engine.observation import build_observation, get_visible_tiles
from engine.parser import parse_action
from engine.rules import apply_end_of_turn, compute_allowed_actions
from engine.scoring import apply_score, score_action, score_survival
from engine.version import __version__
from engine.world import create_world, serialize_npcs, serialize_tiles


# ---------------------------------------------------------------------------
# Game session
# ---------------------------------------------------------------------------

class HumanGameSession:
    """Manages a single human play-through using the official engine pipeline."""

    def __init__(
        self,
        *,
        seed: int,
        scenario_key: str,
        benchmark_cfg: dict[str, Any],
        scenarios_cfg: dict[str, Any],
    ) -> None:
        self.seed = seed
        self.scenario_key = scenario_key
        self.benchmark_cfg = benchmark_cfg
        self.scenario_cfg: dict[str, Any] = scenarios_cfg["scenarios"][scenario_key]
        self.rules_cfg: dict[str, Any] = benchmark_cfg["rules"]
        self.scoring_cfg: dict[str, Any] = benchmark_cfg["scoring"]
        self.parser_mode: str = benchmark_cfg.get("parser", {}).get("case_mode", "case_insensitive")
        self.protocol_version: str = str(benchmark_cfg.get("protocol_version", "AIB-0.3.0"))
        self.max_turns: int = int(benchmark_cfg.get("max_turns", 50))

        self.world = create_world(
            seed=seed,
            scenario_cfg=self.scenario_cfg,
            rules_cfg=self.rules_cfg,
            agent_id=DEFAULT_AGENT_ID,
        )
        self.initial_tiles = serialize_tiles(self.world)
        self.initial_npcs = serialize_npcs(self.world)
        self.discovered_tiles: dict[tuple[int, int], str] = {}

        self.turn_logs: list[dict[str, Any]] = []
        self.invalid_actions = 0
        self.resources_gathered = 0
        self.resources_gathered_breakdown: dict[str, int] = {"food": 0, "water": 0, "wood": 0, "stone": 0}
        self.turns_survived = 0
        self.attack_count = 0
        self.npc_kills = 0
        self.last_survival_update = None
        self.game_over = False
        self.started_at = datetime.now(timezone.utc)
        self._saved = False
        self._save_result: dict[str, Any] = {}

        # Compute initial observation
        self.world.turn = 1
        self._current_allowed = compute_allowed_actions(self.world, DEFAULT_AGENT_ID, self.rules_cfg)
        visible = get_visible_tiles(
            self.world,
            x=self.world.agents[DEFAULT_AGENT_ID].position.x,
            y=self.world.agents[DEFAULT_AGENT_ID].position.y,
        )
        for tile in visible:
            pos = (int(tile["x"]), int(tile["y"]))
            self.discovered_tiles[pos] = str(tile["type"])
        self._current_observation = build_observation(
            self.world, DEFAULT_AGENT_ID, self._current_allowed, self.protocol_version,
            visible_tiles=visible,
        )

    # -- public API --

    def get_state(self) -> dict[str, Any]:
        agent = self.world.agents[DEFAULT_AGENT_ID]
        return {
            "turn": self.world.turn,
            "max_turns": self.max_turns,
            "observation": self._current_observation,
            "allowed_actions": self._current_allowed,
            "alive": agent.alive,
            "score": agent.score,
            "energy": agent.energy,
            "hunger": agent.hunger,
            "thirst": agent.thirst,
            "inventory": dict(agent.inventory),
            "position": {"x": agent.position.x, "y": agent.position.y},
            "game_over": self.game_over,
            "seed": self.seed,
            "scenario": self.scenario_key,
            "protocol_version": self.protocol_version,
            "world_width": self.world.width,
            "world_height": self.world.height,
            "tiles": serialize_tiles(self.world),
            "npcs": serialize_npcs(self.world),
            "discovered_tiles": {f"{x},{y}": t for (x, y), t in self.discovered_tiles.items()},
        }

    def step(self, action_text: str) -> dict[str, Any]:
        if self.game_over:
            return {"ok": False, "error": "Game is already over."}

        agent = self.world.agents[DEFAULT_AGENT_ID]
        if not agent.alive:
            self.game_over = True
            return {"ok": False, "error": "Agent is dead."}

        turn = self.world.turn
        observation = self._current_observation
        allowed_actions = self._current_allowed

        parse_result = parse_action(
            raw_output=action_text.strip(),
            allowed_actions=allowed_actions,
            case_mode=self.parser_mode,
        )

        if parse_result.valid and parse_result.action is not None:
            action_outcome = apply_action(self.world, DEFAULT_AGENT_ID, parse_result.action, self.rules_cfg)
            action_score_delta, action_score_events = score_action(True, action_outcome, self.scoring_cfg)
            if action_outcome.useful_gather:
                self.resources_gathered += 1
                inv_delta = action_outcome.world_delta.get("inventory_delta", {})
                for item, delta in inv_delta.items():
                    if item in self.resources_gathered_breakdown and int(delta) > 0:
                        self.resources_gathered_breakdown[item] += int(delta)
            if parse_result.action == "attack":
                self.attack_count += 1
                if bool(action_outcome.world_delta.get("npc_killed", False)):
                    self.npc_kills += 1
        else:
            self.invalid_actions += 1
            action_outcome = ActionOutcome(
                action=parse_result.normalized_output,
                success=False,
                message="invalid action",
                invalid_reason=parse_result.error,
                world_delta={},
            )
            action_score_delta, action_score_events = score_action(False, None, self.scoring_cfg)

        survival_update = apply_end_of_turn(self.world, DEFAULT_AGENT_ID, self.rules_cfg)
        survival_score_delta, survival_score_events = score_survival(survival_update.alive_after, self.scoring_cfg)
        if survival_update.alive_after:
            self.turns_survived += 1
        self.last_survival_update = survival_update

        total_delta = action_score_delta + survival_score_delta
        apply_score(self.world.agents[DEFAULT_AGENT_ID], total_delta)

        # Build turn log (same format as run_match_once)
        turn_entry = {
            "seed": self.seed,
            "turn": turn,
            "observation": observation,
            "prompt_payload": {
                "system_prompt_sha256": "human_input",
                "user_prompt_sha256": "human_input",
                "combined_prompt_sha256": "human_input",
                "memory_hygiene": None,
            },
            "raw_model_output": action_text.strip(),
            "parsed_action": parse_result.action,
            "validation_result": {
                "is_valid": parse_result.valid,
                "error": parse_result.error,
                "allowed_actions": allowed_actions,
                "fix_thinking_enabled": False,
                "fix_thinking_applied": False,
            },
            "world_result_delta": {
                "action_delta": action_outcome.world_delta,
                "survival_delta": survival_update.as_delta(),
            },
            "opponent_steps": [],
            "action_result": {
                "requested": parse_result.normalized_output,
                "applied": parse_result.action,
                "success": action_outcome.success,
                "message": action_outcome.message,
                "invalid_reason": action_outcome.invalid_reason,
                "fix_thinking_applied": False,
            },
            "score_delta": {
                "action": action_score_delta,
                "survival": survival_score_delta,
                "total": total_delta,
                "events": action_score_events + survival_score_events,
            },
            "cumulative_score": self.world.agents[DEFAULT_AGENT_ID].score,
            "metrics": {
                "latency_ms": 0,
                "tokens_used": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cache_read_tokens": None,
                "cache_write_tokens": None,
                "estimated_cost": 0,
            },
        }
        self.turn_logs.append(turn_entry)

        # Check game over
        if not self.world.agents[DEFAULT_AGENT_ID].alive:
            self.game_over = True
        elif turn >= self.max_turns:
            self.game_over = True
        else:
            # Advance to next turn
            self.world.turn = turn + 1
            self._current_allowed = compute_allowed_actions(self.world, DEFAULT_AGENT_ID, self.rules_cfg)
            visible = get_visible_tiles(
                self.world,
                x=self.world.agents[DEFAULT_AGENT_ID].position.x,
                y=self.world.agents[DEFAULT_AGENT_ID].position.y,
            )
            for tile in visible:
                pos = (int(tile["x"]), int(tile["y"]))
                self.discovered_tiles[pos] = str(tile["type"])
            self._current_observation = build_observation(
                self.world, DEFAULT_AGENT_ID, self._current_allowed, self.protocol_version,
                visible_tiles=visible,
            )

        turn_result = {
            "ok": True,
            "turn": turn,
            "action": parse_result.action,
            "valid": parse_result.valid,
            "error": parse_result.error,
            "action_result": turn_entry["action_result"],
            "score_delta": turn_entry["score_delta"],
            "survival_delta": survival_update.as_delta(),
            "cumulative_score": turn_entry["cumulative_score"],
            "game_over": self.game_over,
        }
        return turn_result

    def build_run_log(self) -> dict[str, Any]:
        """Assemble a run log dict 100% compatible with run_match_once output."""
        final_agent = self.world.agents[DEFAULT_AGENT_ID]
        end_reason = "agent_dead" if not final_agent.alive else "max_turns_reached"
        death_cause, death_cause_human = None, None
        if not final_agent.alive and self.last_survival_update is not None:
            su = self.last_survival_update
            if su.starvation_triggered and su.dehydration_triggered:
                death_cause = "starvation_and_dehydration"
                death_cause_human = "Starvation and dehydration reached critical threshold."
            elif su.starvation_triggered:
                death_cause = "starvation"
                death_cause_human = "Starvation reached critical threshold."
            elif su.dehydration_triggered:
                death_cause = "dehydration"
                death_cause_human = "Dehydration reached critical threshold."
            else:
                death_cause = "energy_depletion"
                death_cause_human = "Energy was depleted to zero."

        turns_played = len(self.turn_logs)
        end_reason_human = (
            f"The agent died on turn {turns_played}." if end_reason == "agent_dead"
            else f"Reached the configured turn limit ({self.max_turns})."
        )

        run_summary: dict[str, Any] = {
            "version": __version__,
            "bench_version": __version__,
            "engine_version": __version__,
            "protocol_version": self.protocol_version,
            "seed": self.seed,
            "scenario": self.scenario_key,
            "provider_id": "human_local",
            "model_profile": "human_player",
            "model": "human/manual",
            "max_turns": self.max_turns,
            "prompt_set_sha256": "human_input",
            "prompt_variant": "human",
            "parser_case_mode": self.parser_mode,
            "fix_thinking": False,
            "moral_mode": False,
            "pvp_duel": False,
            "pvp_continue": False,
            "opponent_agent_count": 0,
            "opponents_alive_after": 0,
            "opponent_defeated_turn": None,
            "opponent_model_profile": None,
            "opponent_provider_id": None,
            "opponent_model": None,
            "opponent_agent_id": None,
            "opponent_final_score": None,
            "opponent_alive": None,
            "opponent_energy": None,
            "opponent_turns_survived": 0,
            "opponent_resources_gathered": 0,
            "opponent_resources_gathered_breakdown": {"food": 0, "water": 0, "wood": 0, "stone": 0},
            "opponent_invalid_actions": 0,
            "opponent_death_cause": None,
            "opponent_death_cause_human": None,
            "opponent_tokens_used": None,
            "opponent_token_breakdown": {
                "prompt_tokens": None, "completion_tokens": None,
                "cache_read_tokens": None, "cache_write_tokens": None,
            },
            "opponent_latency_ms": 0,
            "opponent_estimated_cost": None,
            "opponent_estimated_cost_source": None,
            "opponent_attack_count": 0,
            "opponent_attack_npc_count": 0,
            "opponent_attack_rival_count": 0,
            "opponent_npc_kills": 0,
            "opponent_rival_kills": 0,
            "opponent_meat_collected": 0,
            "memory_injected": False,
            "memory_lesson_count": 0,
            "memory_session_lesson_count": 0,
            "memory_current_seed_lesson_count": 0,
            "opponent_memory_injected": False,
            "opponent_memory_lesson_count": 0,
            "opponent_memory_session_lesson_count": 0,
            "opponent_memory_current_seed_lesson_count": 0,
            "history_window": 1,
            "attempt_kind": "standard",
            "adaptive_pair_key": None,
            "turns_played": turns_played,
            "turns_survived": self.turns_survived,
            "final_score": final_agent.score,
            "resources_gathered": self.resources_gathered,
            "resources_gathered_breakdown": self.resources_gathered_breakdown,
            "attack_count": self.attack_count,
            "attack_npc_count": 0,
            "attack_rival_count": 0,
            "npc_kills": self.npc_kills,
            "rival_kills": 0,
            "meat_collected": 0,
            "invalid_actions": self.invalid_actions,
            "alive": final_agent.alive,
            "end_reason": end_reason,
            "end_reason_human": end_reason_human,
            "death_cause": death_cause,
            "death_cause_human": death_cause_human,
            "tokens_used": 0,
            "token_breakdown": {
                "prompt_tokens": 0, "completion_tokens": 0,
                "cache_read_tokens": None, "cache_write_tokens": None,
            },
            "latency_ms": 0,
            "estimated_cost": 0,
            "estimated_cost_source": None,
            "pricing_ref": None,
        }

        # Run analysis
        try:
            analysis = build_run_analysis(
                turn_logs=self.turn_logs,
                run_summary=run_summary,
                rules_cfg=self.rules_cfg,
                initial_tiles=self.initial_tiles,
                protocol_version=self.protocol_version,
            )
            run_summary["analysis_version"] = analysis.get("analysis_version")
            run_summary["analysis_schema_version"] = analysis.get("analysis_schema_version")
            run_summary["kpi"] = analysis.get("kpi", {})
            run_summary["failure_archetypes"] = analysis.get("failure_archetypes", [])
            run_summary["failure_archetypes_human"] = analysis.get("failure_archetypes_human", [])
            run_summary["primary_failure_archetype"] = analysis.get("primary_failure_archetype")
            run_summary["primary_failure_archetype_human"] = analysis.get("primary_failure_archetype_human")
            run_summary["secondary_failure_archetypes"] = analysis.get("secondary_failure_archetypes", [])
            run_summary["secondary_failure_archetypes_human"] = analysis.get("secondary_failure_archetypes_human", [])
            run_summary["confidence_hint"] = analysis.get("confidence_hint")
            run_summary["short_summary"] = analysis.get("short_summary")
            run_summary["detailed_summary"] = analysis.get("detailed_summary")
            run_analysis = analysis.get("run_analysis", {})
        except Exception:
            run_analysis = {}

        run_log: dict[str, Any] = {
            "version": __version__,
            "protocol_version": self.protocol_version,
            "seed": self.seed,
            "scenario": self.scenario_key,
            "provider_id": "human_local",
            "model_profile": "human_player",
            "model": "human/manual",
            "engine_version": __version__,
            "prompt_versions": {
                "prompt_set_sha256": "human_input",
                "templates": {},
                "active_templates": [],
            },
            "benchmark_identity": {
                "bench_version": __version__,
                "engine_version": __version__,
                "protocol_version": self.protocol_version,
                "prompt_set_sha256": "human_input",
                "system_prompt_sha256": "human_input",
                "prompt_templates": {},
                "active_templates": [],
                "prompts_dir": "human",
                "prompt_variant": "human",
                "parser_case_mode": self.parser_mode,
                "fix_thinking": False,
                "moral_mode": False,
                "pvp_duel": False,
                "opponent_agent_count": 0,
                "memory_injected": False,
                "memory_lesson_count": 0,
                "memory_session_lesson_count": 0,
                "memory_current_seed_lesson_count": 0,
                "memory_hygiene": None,
                "opponent_memory_injected": False,
                "opponent_memory_lesson_count": 0,
                "opponent_memory_session_lesson_count": 0,
                "opponent_memory_current_seed_lesson_count": 0,
                "opponent_memory_hygiene": None,
                "history_window": 1,
                "discovery_window": 10,
                "path_window": 10,
                "attempt_kind": "standard",
                "adaptive_pair_key": None,
            },
            "config_snapshot": {
                "benchmark": self.benchmark_cfg,
                "scenario": self.scenario_cfg,
                "providers": {},
            },
            "run_summary": run_summary,
            "run_analysis": run_analysis,
            "duel": {
                "canonical": False,
                "turn_order": "primary_then_opponent",
                "primary_model_profile": "human_player",
                "opponent_model_profile": None,
                "attempt_kind": "standard",
            },
            "turn_logs": self.turn_logs,
            "world_snapshots": {
                "initial_tiles": self.initial_tiles,
                "final_tiles": serialize_tiles(self.world),
                "initial_npcs": self.initial_npcs,
                "final_npcs": serialize_npcs(self.world),
            },
            "discovered_tiles": {f"{x},{y}": t for (x, y), t in self.discovered_tiles.items()},
        }
        return run_log

    def save_log(self) -> dict[str, Any]:
        """Save log and auto-generate compare JSON + dashboard HTML.

        Returns dict with save result info.
        """
        if self._saved:
            return self._save_result

        import subprocess
        import tempfile

        run_log = self.build_run_log()

        # Write log to a temp file (not under artifacts/runs/)
        tmp_dir = Path(tempfile.mkdtemp(prefix="tinyworld_human_"))
        tmp_log = tmp_dir / f"run_seed{self.seed}_human_player.json"
        with tmp_log.open("w", encoding="utf-8") as f:
            json.dump(run_log, f, ensure_ascii=True, indent=2, sort_keys=True)

        # Run compare to generate the canonical run directory
        compare_run_dir = None
        dashboard_path = None
        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "bench.run_compare",
                    "--from-logs-glob", str(tmp_log),
                    "--no-open-viewer",
                ],
                capture_output=True, timeout=60, check=False,
                cwd=str(Path.cwd()),
            )
            output = result.stdout.decode("utf-8", errors="replace")
            # Find the compare run dir and dashboard from output
            for line in output.splitlines():
                if "Run root" in line:
                    tokens = line.strip().split()
                    if tokens:
                        p = Path(tokens[-1])
                        if not p.is_absolute():
                            p = Path.cwd() / p
                        if p.is_dir():
                            compare_run_dir = p
                if ".html" in line:
                    tokens = line.strip().split()
                    for token in reversed(tokens):
                        if token.endswith(".html"):
                            p = Path(token)
                            if not p.is_absolute():
                                p = Path.cwd() / p
                            if p.exists():
                                dashboard_path = p
        except Exception:
            pass

        # Copy the log into the compare run's logs/ dir
        log_path = tmp_log
        if compare_run_dir and compare_run_dir.exists():
            dest_logs = compare_run_dir / "logs"
            dest_logs.mkdir(parents=True, exist_ok=True)
            dest = dest_logs / tmp_log.name
            import shutil
            shutil.copy2(tmp_log, dest)
            log_path = dest

        # Clean up temp
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

        self._saved = True
        self._save_result = {
            "ok": True,
            "log_path": str(log_path),
            "dashboard_path": str(dashboard_path) if dashboard_path else None,
            "run_id": compare_run_dir.name if compare_run_dir else None,
            "final_score": run_log["run_summary"].get("final_score"),
            "turns_survived": run_log["run_summary"].get("turns_survived"),
            "alive": run_log["run_summary"].get("alive"),
            "end_reason": run_log["run_summary"].get("end_reason"),
        }
        return self._save_result


# ---------------------------------------------------------------------------
# HTML UI
# ---------------------------------------------------------------------------

def _render_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TinyWorld — Human Play</title>
<style>
:root {
  --bg: #1a1d23; --bg-raised: #23272e; --text: #e8e8e8; --text-dim: #666;
  --border: #333; --green: #4caf50; --red: #ef5350; --yellow: #ffc107; --blue: #42a5f5;
  --font: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: var(--font); background: var(--bg); color: var(--text); font-size: 13px; }
.wrap { max-width: 1200px; margin: 0 auto; padding: 16px; }
header { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid var(--border); margin-bottom: 12px; }
header h1 { font-size: 1.1rem; font-weight: 700; }
header h1 span { color: var(--green); }
.header-meta { font-size: 0.75rem; color: var(--text-dim); }
.layout { display: grid; grid-template-columns: 1fr 320px; gap: 16px; }
/* Map */
.map-panel { background: var(--bg-raised); border: 1px solid var(--border); border-radius: 6px; padding: 12px; }
.map-grid { display: grid; gap: 1px; margin: 0 auto; }
.map-cell { width: 100%; aspect-ratio: 1; border-radius: 3px; position: relative; font-size: 18px; display: flex; align-items: center; justify-content: center; flex-direction: column; }
.map-cell .tile-label { font-size: 8px; color: var(--text-dim); position: absolute; top: 1px; left: 3px; }
.map-cell .coord { font-size: 7px; color: #555; position: absolute; bottom: 1px; right: 2px; }
.tile-empty { background: #2a2d33; } .tile-food { background: #3a4a2a; } .tile-water { background: #1a3a5a; }
.tile-tree { background: #2a4a1a; } .tile-rock { background: #3a3a3a; } .tile-stone { background: #3a3a3a; }
.tile-wood { background: #4a3a1a; } .tile-unknown { background: #111; }
.tile-current { outline: 2px solid var(--yellow); outline-offset: -2px; z-index: 1; }
.tile-visited { background-blend-mode: overlay; }
.tile-visited::before { content: ''; position: absolute; inset: 0; background: rgba(255,255,255,0.06); border-radius: 3px; pointer-events: none; }
.npc-badge { position: absolute; top: 1px; right: 2px; font-size: 10px; }
/* Side panel */
.side { display: flex; flex-direction: column; gap: 10px; }
.card { background: var(--bg-raised); border: 1px solid var(--border); border-radius: 6px; padding: 10px; }
.card-title { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-dim); margin-bottom: 6px; }
/* Meters */
.meter { margin-bottom: 6px; }
.meter-label { display: flex; justify-content: space-between; font-size: 0.72rem; margin-bottom: 2px; }
.meter-bar { height: 8px; border-radius: 4px; background: #333; overflow: hidden; }
.meter-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
.energy-fill { background: var(--green); } .hunger-fill { background: var(--yellow); } .thirst-fill { background: var(--blue); }
.energy-fill.low { background: var(--red); } .hunger-fill.high { background: var(--red); } .thirst-fill.high { background: var(--red); }
/* Inventory */
.inv-row { display: flex; gap: 8px; flex-wrap: wrap; }
.inv-item { font-size: 0.75rem; padding: 2px 8px; border-radius: 4px; background: #333; }
/* Actions */
/* D-pad */
.dpad { display: grid; grid-template-columns: 40px 40px 40px; grid-template-rows: 40px 40px 40px; gap: 3px; justify-content: center; margin-bottom: 10px; }
.dpad-btn { font-size: 16px; background: #333; border: 1px solid var(--border); border-radius: 6px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.15s; padding: 0; }
.dpad-btn:hover { background: var(--green); border-color: var(--green); }
.dpad-up { grid-column: 2; grid-row: 1; }
.dpad-left { grid-column: 1; grid-row: 2; }
.dpad-center { grid-column: 2; grid-row: 2; font-size: 14px; }
.dpad-right { grid-column: 3; grid-row: 2; }
.dpad-down { grid-column: 2; grid-row: 3; }
.action-btns { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
.action-btn { padding: 4px 10px; font-size: 0.72rem; font-family: var(--font); background: #333; color: var(--text); border: 1px solid var(--border); border-radius: 4px; cursor: pointer; transition: all 0.15s; }
.action-btn:hover { background: var(--green); color: #000; border-color: var(--green); }
.action-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.action-input-row { display: flex; gap: 4px; }
.action-input { flex: 1; padding: 6px 8px; font-family: var(--font); font-size: 0.8rem; background: #333; color: var(--text); border: 1px solid var(--border); border-radius: 4px; outline: none; }
.action-input:focus { border-color: var(--green); }
.submit-btn { padding: 6px 14px; font-family: var(--font); font-size: 0.8rem; background: var(--green); color: #000; border: none; border-radius: 4px; cursor: pointer; font-weight: 700; }
.submit-btn:hover { opacity: 0.85; }
/* Feedback */
.feedback { font-size: 0.75rem; padding: 6px 8px; border-radius: 4px; margin-bottom: 4px; }
.feedback.valid { background: #1a3a1a; border: 1px solid #2a5a2a; }
.feedback.invalid { background: #3a1a1a; border: 1px solid #5a2a2a; }
/* Timeline */
.timeline { max-height: 200px; overflow-y: auto; font-size: 0.7rem; }
.timeline table { width: 100%; border-collapse: collapse; }
.timeline th, .timeline td { padding: 3px 6px; text-align: left; border-bottom: 1px solid #222; }
.timeline th { color: var(--text-dim); font-size: 0.6rem; text-transform: uppercase; position: sticky; top: 0; background: var(--bg-raised); }
/* Controls */
.ctrl-row { display: flex; gap: 6px; }
.ctrl-btn { padding: 6px 14px; font-family: var(--font); font-size: 0.72rem; border-radius: 4px; cursor: pointer; border: 1px solid var(--border); background: #333; color: var(--text); }
.ctrl-btn:hover { border-color: var(--text-dim); }
.ctrl-btn.save { background: var(--blue); color: #000; border-color: var(--blue); font-weight: 700; }
/* Game over overlay */
.game-over-banner { display: none; padding: 12px; text-align: center; background: #3a1a1a; border: 1px solid var(--red); border-radius: 6px; font-size: 1rem; font-weight: 700; }
.game-over-banner.show { display: block; }
/* Start screen */
.start-screen { text-align: center; padding: 60px 20px; }
.start-screen h2 { margin-bottom: 20px; }
.start-form { display: inline-flex; gap: 10px; align-items: center; }
.start-form label { font-size: 0.8rem; color: var(--text-dim); }
.start-form input, .start-form select { padding: 6px 10px; font-family: var(--font); font-size: 0.85rem; background: #333; color: var(--text); border: 1px solid var(--border); border-radius: 4px; }
.start-btn { padding: 8px 24px; font-family: var(--font); font-size: 0.9rem; background: var(--green); color: #000; border: none; border-radius: 4px; cursor: pointer; font-weight: 700; }
#gameArea { display: none; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1><span>TINYWORLD</span> HUMAN PLAY</h1>
    <div class="header-meta" id="headerMeta"></div>
  </header>

  <div id="startScreen" class="start-screen">
    <h2>New Game</h2>
    <div class="start-form">
      <label>Seed <input type="number" id="seedInput" value="1" min="1" max="9999" style="width:70px"></label>
      <label>Scenario <input type="text" id="scenarioInput" value="" style="width:140px" placeholder="(default)"></label>
      <button class="start-btn" id="startBtn">Start Game</button>
    </div>
  </div>

  <div id="gameArea">
    <div class="game-over-banner" id="gameOverBanner">GAME OVER</div>
    <div class="layout">
      <div class="map-panel">
        <div class="card-title">Map</div>
        <div class="map-grid" id="mapGrid"></div>
      </div>
      <div class="side">
        <div class="card">
          <div class="card-title">Status — Turn <span id="turnNum">1</span>/<span id="maxTurns">50</span> — Score <span id="scoreVal">0</span></div>
          <div class="meter"><div class="meter-label"><span>Energy</span><span id="energyVal"></span></div><div class="meter-bar"><div class="meter-fill energy-fill" id="energyBar"></div></div></div>
          <div class="meter"><div class="meter-label"><span>Hunger</span><span id="hungerVal"></span></div><div class="meter-bar"><div class="meter-fill hunger-fill" id="hungerBar"></div></div></div>
          <div class="meter"><div class="meter-label"><span>Thirst</span><span id="thirstVal"></span></div><div class="meter-bar"><div class="meter-fill thirst-fill" id="thirstBar"></div></div></div>
        </div>
        <div class="card">
          <div class="card-title">Inventory</div>
          <div class="inv-row" id="invRow"></div>
        </div>
        <div class="card">
          <div class="card-title">Actions</div>
          <div class="dpad">
            <button class="dpad-btn dpad-up" onclick="clickAction('move north')" title="move north">&#x2B06;&#xFE0F;</button>
            <button class="dpad-btn dpad-left" onclick="clickAction('move west')" title="move west">&#x2B05;&#xFE0F;</button>
            <button class="dpad-btn dpad-center" onclick="clickAction('rest')" title="rest">&#x1F6CC;</button>
            <button class="dpad-btn dpad-right" onclick="clickAction('move east')" title="move east">&#x27A1;&#xFE0F;</button>
            <button class="dpad-btn dpad-down" onclick="clickAction('move south')" title="move south">&#x2B07;&#xFE0F;</button>
          </div>
          <div class="action-btns" id="actionBtns"></div>
          <div class="action-input-row">
            <input class="action-input" id="actionInput" placeholder="type command..." autocomplete="off">
            <button class="submit-btn" id="submitBtn">Go</button>
          </div>
        </div>
        <div class="card" id="feedbackCard" style="display:none">
          <div class="card-title">Last Turn</div>
          <div id="feedbackContent"></div>
        </div>
        <div class="card">
          <div class="card-title">Timeline</div>
          <div class="timeline" id="timeline">
            <table><thead><tr><th>#</th><th>Action</th><th>OK</th><th>D</th><th>Score</th><th>E</th><th>H</th><th>T</th></tr></thead><tbody id="timelineBody"></tbody></table>
          </div>
        </div>
        <div class="ctrl-row">
          <button class="ctrl-btn save" id="saveBtn">Save &amp; End</button>
          <button class="ctrl-btn" id="newBtn">New Game</button>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
const API = '';
let gameActive = false;

// Parse URL params
const params = new URLSearchParams(location.search);
if (params.get('seed')) document.getElementById('seedInput').value = params.get('seed');
if (params.get('scenario')) document.getElementById('scenarioInput').value = params.get('scenario');
// Auto-start if seed provided via URL
if (params.get('seed') && params.get('autostart') !== '0') {
  window.addEventListener('DOMContentLoaded', () => document.getElementById('startBtn').click());
}

document.getElementById('startBtn').addEventListener('click', async () => {
  const seed = parseInt(document.getElementById('seedInput').value) || 1;
  const scenario = document.getElementById('scenarioInput').value.trim() || null;
  const body = { seed };
  if (scenario) body.scenario = scenario;
  const res = await fetch(API + '/api/human/start', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
  const data = await res.json();
  if (!data.ok) { alert(data.error || 'Failed to start'); return; }
  document.getElementById('startScreen').style.display = 'none';
  document.getElementById('gameArea').style.display = 'block';
  gameActive = true;
  updateUI(data.state);
});

document.getElementById('submitBtn').addEventListener('click', sendAction);
document.getElementById('actionInput').addEventListener('keydown', e => { if (e.key === 'Enter') sendAction(); });

// Arrow keys & WASD for movement
document.addEventListener('keydown', function(e) {
  if (!gameActive) return;
  if (document.activeElement === document.getElementById('actionInput')) return;
  const keyMap = {
    ArrowUp: 'move north', ArrowDown: 'move south', ArrowLeft: 'move west', ArrowRight: 'move east',
    w: 'move north', s: 'move south', a: 'move west', d: 'move east',
    W: 'move north', S: 'move south', A: 'move west', D: 'move east',
    r: 'rest', R: 'rest', g: 'gather', G: 'gather',
  };
  if (keyMap[e.key]) { e.preventDefault(); clickAction(keyMap[e.key]); }
});

async function sendAction() {
  if (!gameActive) return;
  const input = document.getElementById('actionInput');
  const action = input.value.trim();
  if (!action) return;
  input.value = '';
  const res = await fetch(API + '/api/human/action', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ action }) });
  const data = await res.json();
  if (!data.ok && data.error) { alert(data.error); return; }
  showFeedback(data.turn_result);
  updateUI(data.state);
  if (data.state.game_over) {
    gameActive = false;
    document.getElementById('gameOverBanner').classList.add('show');
    document.getElementById('gameOverBanner').textContent = data.state.alive ? 'MAX TURNS REACHED' : 'YOU DIED';
    disableActions();
    autoSave();
  }
}

function clickAction(action) {
  document.getElementById('actionInput').value = action;
  sendAction();
}

let saving = false;
async function autoSave() {
  if (saving) return;
  saving = true;
  const banner = document.getElementById('gameOverBanner');
  if (!banner.querySelector('.save-status')) {
    banner.innerHTML += '<div class="save-status" style="font-size:0.7rem;margin-top:6px;color:var(--text-dim)">Saving...</div>';
  }
  const statusEl = banner.querySelector('.save-status');
  document.getElementById('saveBtn').disabled = true;
  try {
    const res = await fetch(API + '/api/human/end', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      statusEl.textContent = 'Saved! Score: ' + (data.final_score ?? '?') + ' | Turns: ' + (data.turns_survived ?? '?') + (data.run_id ? ' | Run: ' + data.run_id : '');
      statusEl.style.color = 'var(--green)';
    } else {
      statusEl.textContent = 'Save failed: ' + (data.error || 'unknown');
      statusEl.style.color = 'var(--red)';
      saving = false;
      document.getElementById('saveBtn').disabled = false;
    }
  } catch (e) {
    statusEl.textContent = 'Save error: ' + e.message;
    statusEl.style.color = 'var(--red)';
    saving = false;
    document.getElementById('saveBtn').disabled = false;
  }
}

document.getElementById('saveBtn').addEventListener('click', autoSave);

document.getElementById('newBtn').addEventListener('click', () => {
  document.getElementById('startScreen').style.display = 'block';
  document.getElementById('gameArea').style.display = 'none';
  const banner = document.getElementById('gameOverBanner');
  banner.classList.remove('show');
  banner.textContent = 'GAME OVER';
  document.getElementById('feedbackCard').style.display = 'none';
  document.getElementById('timelineBody').innerHTML = '';
  document.getElementById('saveBtn').disabled = false;
  gameActive = false;
  saving = false;
});

function updateUI(state) {
  if (!state) return;
  const energyMax = 140; // read from rules
  document.getElementById('headerMeta').textContent = 'Seed ' + state.seed + ' | ' + state.scenario + ' | ' + state.protocol_version;
  document.getElementById('turnNum').textContent = state.turn;
  document.getElementById('maxTurns').textContent = state.max_turns;
  document.getElementById('scoreVal').textContent = state.score;

  // Meters
  const ePct = Math.max(0, Math.min(100, (state.energy / energyMax) * 100));
  document.getElementById('energyVal').textContent = state.energy + '/' + energyMax;
  const eBar = document.getElementById('energyBar');
  eBar.style.width = ePct + '%';
  eBar.className = 'meter-fill energy-fill' + (ePct < 25 ? ' low' : '');

  const hPct = Math.max(0, Math.min(100, state.hunger));
  document.getElementById('hungerVal').textContent = state.hunger + '/100';
  const hBar = document.getElementById('hungerBar');
  hBar.style.width = hPct + '%';
  hBar.className = 'meter-fill hunger-fill' + (hPct >= 80 ? ' high' : '');

  const tPct = Math.max(0, Math.min(100, state.thirst));
  document.getElementById('thirstVal').textContent = state.thirst + '/100';
  const tBar = document.getElementById('thirstBar');
  tBar.style.width = tPct + '%';
  tBar.className = 'meter-fill thirst-fill' + (tPct >= 80 ? ' high' : '');

  // Inventory
  const inv = state.inventory || {};
  const invEmoji = {wood: '\\u{1FAB5}', stone: '\\u{1F9F1}', food: '\\u{1F34E}', water: '\\u{1F4A7}'};
  document.getElementById('invRow').innerHTML = Object.entries(inv)
    .map(([k, v]) => '<span class="inv-item">' + (invEmoji[k] || '') + ' ' + k + ': ' + v + '</span>').join('');

  // Action buttons
  const btns = document.getElementById('actionBtns');
  btns.innerHTML = (state.allowed_actions || [])
    .map(a => '<button class="action-btn" onclick="clickAction(&quot;' + a + '&quot;)">' + a + '</button>').join('');

  // Map
  renderMap(state);
}

const tileMeta = {
  empty: { emoji: '\\u25AB', label: '' },
  tree: { emoji: '\\u{1F332}', label: 'tree' },
  rock: { emoji: '\\u{1FAA8}', label: 'rock' },
  food: { emoji: '\\u{1F34E}', label: 'food' },
  water: { emoji: '\\u{1F4A7}', label: 'water' },
  stone: { emoji: '\\u{1FAA8}', label: 'stone' },
  wood: { emoji: '\\u{1FAB5}', label: 'wood' },
  unknown: { emoji: '\\u2588', label: '?' },
};

function renderMap(state) {
  const grid = document.getElementById('mapGrid');
  const w = state.world_width || 8;
  const h = state.world_height || 8;
  grid.style.gridTemplateColumns = 'repeat(' + w + ', minmax(52px, 1fr))';
  const tiles = state.tiles || [];
  const npcs = state.npcs || [];
  const pos = state.position || {};
  const discovered = state.discovered_tiles || {};

  let html = '';
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const key = x + ',' + y;
      const isAgent = (pos.x === x && pos.y === y);
      const npc = npcs.find(n => (n.position ? n.position.x : n.x) === x && (n.position ? n.position.y : n.y) === y && n.alive);
      const isDiscovered = discovered.hasOwnProperty(key);
      let tileType = 'unknown';
      if (isDiscovered && tiles[y] && tiles[y][x]) tileType = tiles[y][x];
      if (!isDiscovered && !isAgent) tileType = 'unknown';

      const meta = tileMeta[tileType] || tileMeta.unknown;
      let cls = 'map-cell tile-' + tileType;
      if (isAgent) cls += ' tile-current';
      if (isDiscovered) cls += ' tile-visited';

      let content = '';
      if (meta.label) content += '<span class="tile-label">' + meta.label + '</span>';
      content += '<span class="coord">' + x + ',' + y + '</span>';
      if (isAgent) {
        content += '\\u{1F916}';
      } else if (!isDiscovered) {
        content += meta.emoji;
      } else {
        content += meta.emoji;
      }
      if (npc && isDiscovered) {
        var npcIcon = npc.npc_type === 'hostile' ? '\\u{1F47E}' : '\\u{1F43B}';
        content += '<span class="npc-badge">' + npcIcon + '</span>';
      }
      html += '<div class="' + cls + '" title="' + x + ',' + y + ' ' + tileType + '">' + content + '</div>';
    }
  }
  grid.innerHTML = html;
}

function showFeedback(result) {
  if (!result) return;
  const card = document.getElementById('feedbackCard');
  card.style.display = 'block';
  const cls = result.valid ? 'valid' : 'invalid';
  const action = result.action || result.action_result?.requested || '?';
  const msg = result.action_result?.message || '';
  const delta = result.score_delta?.total || 0;
  const events = (result.score_delta?.events || []).join(', ');
  document.getElementById('feedbackContent').innerHTML =
    '<div class="feedback ' + cls + '">' +
    '<strong>' + action + '</strong> — ' + msg +
    ' | delta: ' + (delta >= 0 ? '+' : '') + delta +
    (events ? ' (' + events + ')' : '') +
    '</div>';

  // Add to timeline
  const sd = result.survival_delta || {};
  const tbody = document.getElementById('timelineBody');
  const row = document.createElement('tr');
  row.innerHTML = '<td>' + result.turn + '</td><td>' + action + '</td><td>' + (result.valid ? 'Y' : 'N') +
    '</td><td>' + (delta >= 0 ? '+' : '') + delta + '</td><td>' + result.cumulative_score +
    '</td><td>' + (sd.energy_after ?? '') + '</td><td>' + (sd.hunger_after ?? '') + '</td><td>' + (sd.thirst_after ?? '') + '</td>';
  tbody.appendChild(row);
  row.scrollIntoView({ block: 'nearest' });
}

function disableActions() {
  document.querySelectorAll('.action-btn').forEach(b => b.disabled = true);
  document.getElementById('submitBtn').disabled = true;
  document.getElementById('actionInput').disabled = true;
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP Server
# ---------------------------------------------------------------------------

def _make_handler(benchmark_cfg: dict[str, Any], scenarios_cfg: dict[str, Any]):
    session_lock = threading.Lock()
    session: dict[str, HumanGameSession | None] = {"current": None}

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _send_json(self, payload: dict | list, code: int = 200) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(raw)

        def _send_html(self, html: str) -> None:
            raw = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
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

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                self._send_html(_render_html())
                return
            if parsed.path == "/api/human/state":
                with session_lock:
                    s = session["current"]
                    if s is None:
                        self._send_json({"ok": False, "error": "No active game session."}, 400)
                        return
                    self._send_json({"ok": True, "state": s.get_state()})
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)

            if parsed.path == "/api/human/start":
                body = self._read_json_body()
                seed = int(body.get("seed", 1))
                scenario = body.get("scenario") or benchmark_cfg.get("default_scenario", "v0_2_hunt")
                with session_lock:
                    try:
                        s = HumanGameSession(
                            seed=seed,
                            scenario_key=str(scenario),
                            benchmark_cfg=benchmark_cfg,
                            scenarios_cfg=scenarios_cfg,
                        )
                        session["current"] = s
                        self._send_json({"ok": True, "state": s.get_state()})
                    except Exception as e:
                        self._send_json({"ok": False, "error": str(e)}, 400)
                return

            if parsed.path == "/api/human/action":
                body = self._read_json_body()
                action_text = str(body.get("action", "")).strip()
                if not action_text:
                    self._send_json({"ok": False, "error": "Missing action."}, 400)
                    return
                with session_lock:
                    s = session["current"]
                    if s is None:
                        self._send_json({"ok": False, "error": "No active game session."}, 400)
                        return
                    turn_result = s.step(action_text)
                    self._send_json({"ok": True, "turn_result": turn_result, "state": s.get_state()})
                return

            if parsed.path == "/api/human/end":
                with session_lock:
                    s = session["current"]
                    if s is None:
                        self._send_json({"ok": False, "error": "No active game session."}, 400)
                        return
                    try:
                        save_result = s.save_log()
                        self._send_json(save_result)
                    except Exception as e:
                        self._send_json({"ok": False, "error": str(e)}, 500)
                return

            self._send_json({"ok": False, "error": "Not found."}, 404)

    return Handler


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TinyWorld Human Play — interactive web mode")
    parser.add_argument("--seed", type=int, default=None, help="Pre-select seed (optional; can pick in UI)")
    parser.add_argument("--scenario", type=str, default=None, help="Scenario key (default from config)")
    parser.add_argument("--port", type=int, default=8765, help="Server port (default 8765)")
    parser.add_argument("--benchmark-config", type=str, default="configs/benchmark.yaml")
    parser.add_argument("--scenarios-config", type=str, default="configs/scenarios.yaml")
    parser.add_argument("--open-browser", action="store_true", help="Open browser on start")
    parser.add_argument("--no-color", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    benchmark_cfg, scenarios_cfg = load_configs(args.benchmark_config, args.scenarios_config)

    handler_cls = _make_handler(benchmark_cfg, scenarios_cfg)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_cls)

    url = f"http://127.0.0.1:{args.port}/"
    if args.seed is not None:
        url += f"?seed={args.seed}"
        if args.scenario:
            url += f"&scenario={args.scenario}"

    print(f"TinyWorld Human Play v{__version__}")
    print(f"  Server: {url}")
    print(f"  Press Ctrl+C to stop.\n")

    if args.open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
