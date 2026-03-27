"""Deterministic run analyzer for TinyWorld single-agent traces."""

from __future__ import annotations

from typing import Any

from analysis.failure_archetypes import label_for, get_thresholds
from analysis.summary_builder import build_deterministic_summaries


RUN_ANALYSIS_SCHEMA_VERSION = "AIB-RA-AIB-0.2.1-v1"
RUN_ANALYSIS_VERSION = "AIB-AN-AIB-0.2.1-v1"


_MOVE_ACTIONS = {"move north", "move south", "move east", "move west"}
_WAIT_ACTIONS = {"rest", "wait"}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_position_tuple(value: Any) -> tuple[int, int] | None:
    if isinstance(value, dict):
        try:
            return int(value.get("x")), int(value.get("y"))
        except (TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None
    return None


def _tile_type_at_position(visible_tiles: Any, pos: tuple[int, int] | None) -> str | None:
    if pos is None or not isinstance(visible_tiles, list):
        return None
    for tile in visible_tiles:
        if not isinstance(tile, dict):
            continue
        if _as_int(tile.get("x"), -1) == pos[0] and _as_int(tile.get("y"), -1) == pos[1]:
            tile_type = str(tile.get("type", "")).strip().lower()
            return tile_type or None
    return None


def _resource_seen_updates(
    *,
    turn: int,
    visible_tiles: Any,
    seen_food_cells: set[tuple[int, int]],
    seen_water_cells: set[tuple[int, int]],
    first_food_seen_turn: int | None,
    first_water_seen_turn: int | None,
) -> tuple[int | None, int | None]:
    if not isinstance(visible_tiles, list):
        return first_food_seen_turn, first_water_seen_turn

    for tile in visible_tiles:
        if not isinstance(tile, dict):
            continue
        tx = _as_int(tile.get("x"), -1)
        ty = _as_int(tile.get("y"), -1)
        if tx < 0 or ty < 0:
            continue
        tile_type = str(tile.get("type", "")).strip().lower()
        pos = (tx, ty)
        if tile_type == "food":
            seen_food_cells.add(pos)
            if first_food_seen_turn is None:
                first_food_seen_turn = turn
        elif tile_type == "water":
            seen_water_cells.add(pos)
            if first_water_seen_turn is None:
                first_water_seen_turn = turn

    return first_food_seen_turn, first_water_seen_turn


def _build_final_facts(run_summary: dict[str, Any]) -> dict[str, Any]:
    turns = _as_int(run_summary.get("turns_played"), 0)
    invalid = _as_int(run_summary.get("invalid_actions"), 0)
    latency_ms = _as_float(run_summary.get("latency_ms"), 0.0)
    survived = bool(run_summary.get("alive", False))
    end_reason = str(run_summary.get("end_reason", ""))
    death_cause = run_summary.get("death_cause")
    if death_cause in {"", None}:
        death_cause = None

    return {
        "survived": survived,
        "death_turn": (turns if end_reason == "agent_dead" else None),
        "death_cause": death_cause,
        "final_score": _as_int(run_summary.get("final_score"), 0),
        "total_turns": turns,
        "total_invalid": invalid,
        "invalid_rate": (invalid / turns) if turns > 0 else 0.0,
        "total_latency": round(latency_ms, 6),
        "avg_latency": round((latency_ms / turns), 6) if turns > 0 else None,
        "total_tokens": run_summary.get("tokens_used"),
    }


def _classify_archetypes(
    *,
    final_facts: dict[str, Any],
    behavior_metrics: dict[str, Any],
    resource_metrics: dict[str, Any],
    state_pressure_metrics: dict[str, Any],
    outcome_helpers: dict[str, Any],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    total_turns = int(final_facts["total_turns"])
    invalid_rate = float(final_facts["invalid_rate"])
    final_score = float(final_facts["final_score"])

    first_water_seen = resource_metrics["first_water_seen_turn"]
    first_water_gather = resource_metrics["first_water_gather_turn"]
    first_food_seen = resource_metrics["first_food_seen_turn"]
    first_food_gather = resource_metrics["first_food_gather_turn"]

    delayed_turn = int(thresholds["delayed_priority_turn"])

    flags = {
        "dehydration": bool(outcome_helpers["died_from_dehydration"]),
        "starvation": bool(outcome_helpers["died_from_starvation"]),
        "energy_collapse": bool(outcome_helpers["died_from_energy_collapse"]),
        "delayed_water_priority": (
            first_water_seen is not None
            and (first_water_gather is None or int(first_water_gather) > delayed_turn)
            and (
                bool(outcome_helpers["died_from_dehydration"])
                or state_pressure_metrics["dehydration_pressure_turn"] is not None
            )
        ),
        "delayed_food_priority": (
            first_food_seen is not None
            and (first_food_gather is None or int(first_food_gather) > delayed_turn)
            and (
                bool(outcome_helpers["died_from_starvation"])
                or state_pressure_metrics["starvation_pressure_turn"] is not None
            )
        ),
        "wandering": (
            behavior_metrics["move_count"] >= max(6, int(total_turns * thresholds["wandering_move_ratio"]))
            and behavior_metrics["useful_action_ratio"] <= thresholds["wandering_useful_action_ratio"]
            and not behavior_metrics["loop_detected"]
        ),
        "local_loop": bool(behavior_metrics["loop_detected"]),
        "bad_gather_timing": (
            resource_metrics["missed_food_opportunities"] + resource_metrics["missed_water_opportunities"]
            >= int(thresholds["bad_gather_missed_opportunities"])
            and (
                not final_facts["survived"]
                or behavior_metrics["useful_action_ratio"] <= 0.25
            )
        ),
        "invalid_output_collapse": (
            invalid_rate >= thresholds["invalid_rate_collapse"]
            and (not final_facts["survived"] or final_score <= 0 or final_facts["total_invalid"] >= 3)
        ),
        "resource_tunnel_vision": (
            behavior_metrics["gather_count"] >= int(thresholds["resource_tunnel_gather_count"])
            and behavior_metrics["useful_action_ratio"] <= 0.25
            and (
                state_pressure_metrics["starvation_pressure_turn"] is not None
                or state_pressure_metrics["dehydration_pressure_turn"] is not None
                or state_pressure_metrics["first_hunger_warning_turn"] is not None
                or state_pressure_metrics["first_thirst_warning_turn"] is not None
            )
        ),
        "late_recovery_failure": bool(outcome_helpers["late_recovery_attempt"]) and not final_facts["survived"],
        "balanced_but_insufficient": False,
        "successful_stabilization": (
            bool(outcome_helpers["survived_full_run"])
            and invalid_rate <= thresholds["stabilization_invalid_rate_max"]
            and (
                first_food_gather is not None
                or first_water_gather is not None
            )
        ),
        "successful_optimization": (
            bool(outcome_helpers["survived_full_run"])
            and final_score >= thresholds["optimization_min_score"]
            and invalid_rate <= 0.05
            and behavior_metrics["revisit_ratio"] <= thresholds["optimization_max_revisit_ratio"]
            and behavior_metrics["useful_action_ratio"] >= 0.25
        ),
    }

    negative_detected = [code for code in flags if flags[code] and not code.startswith("successful_")]
    if (not final_facts["survived"]) and (not negative_detected):
        flags["balanced_but_insufficient"] = True

    if flags["successful_optimization"]:
        primary = "successful_optimization"
    elif flags["successful_stabilization"]:
        primary = "successful_stabilization"
    else:
        priority = [
            "invalid_output_collapse",
            "delayed_water_priority",
            "delayed_food_priority",
            "late_recovery_failure",
            "local_loop",
            "wandering",
            "bad_gather_timing",
            "resource_tunnel_vision",
            "dehydration",
            "starvation",
            "energy_collapse",
            "balanced_but_insufficient",
        ]
        primary = "balanced_but_insufficient"
        for code in priority:
            if flags.get(code):
                primary = code
                break

    secondary = [code for code, active in flags.items() if active and code != primary]
    secondary.sort()

    if primary in {"dehydration", "starvation", "energy_collapse", "delayed_water_priority", "delayed_food_priority"}:
        confidence = "high"
    elif primary in {"successful_optimization", "successful_stabilization"}:
        confidence = "high"
    elif len(secondary) >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "primary_failure_archetype": primary,
        "secondary_failure_archetypes": secondary,
        "confidence_hint": confidence,
        "primary_failure_archetype_human": label_for(primary),
        "secondary_failure_archetypes_human": [label_for(code) for code in secondary],
        "failure_archetypes": [primary, *secondary],
        "failure_archetypes_human": [label_for(primary), *[label_for(code) for code in secondary]],
        "rule_flags": flags,
    }


def build_run_analysis(
    *,
    run_identity: dict[str, Any],
    run_summary: dict[str, Any],
    turn_logs: list[dict[str, Any]],
    rules_cfg: dict[str, Any],
    initial_tiles: list[list[str]],
) -> dict[str, Any]:
    thresholds = get_thresholds()
    final_facts = _build_final_facts(run_summary)
    total_turns = int(final_facts["total_turns"])

    energy_max = max(1, _as_int(rules_cfg.get("energy_max"), 100))
    hunger_max = max(1, _as_int(rules_cfg.get("hunger_max"), 100))
    thirst_max = max(1, _as_int(rules_cfg.get("thirst_max"), 100))

    hunger_warning_threshold = max(1, int(hunger_max * thresholds["hunger_warning_ratio"]))
    thirst_warning_threshold = max(1, int(thirst_max * thresholds["thirst_warning_ratio"]))
    energy_warning_threshold = max(1, int(energy_max * thresholds["energy_warning_ratio"]))

    move_count = 0
    gather_count = 0
    wait_count = 0
    invalid_action_count = int(final_facts["total_invalid"])
    useful_action_count = 0
    distance_traveled = 0

    visited_cells: set[tuple[int, int]] = set()
    revisit_count = 0
    consecutive_revisit = 0
    consecutive_revisit_max = 0
    loop_detected = False
    move_count_early = 0
    useful_count_early = 0
    early_window_turns = min(total_turns, max(1, int(thresholds["early_window_turns"])))

    seen_food_cells: set[tuple[int, int]] = set()
    seen_water_cells: set[tuple[int, int]] = set()
    food_gathered_count = 0
    water_gathered_count = 0
    first_food_seen_turn: int | None = None
    first_water_seen_turn: int | None = None
    first_food_gather_turn: int | None = None
    first_water_gather_turn: int | None = None
    missed_food_opportunities = 0
    missed_water_opportunities = 0

    first_hunger_warning_turn: int | None = None
    first_thirst_warning_turn: int | None = None
    first_energy_warning_turn: int | None = None
    starvation_pressure_turn: int | None = None
    dehydration_pressure_turn: int | None = None
    low_energy_pressure_turn: int | None = None

    useful_consume_turns: list[int] = []

    if turn_logs:
        first_obs_pos = _as_position_tuple((turn_logs[0].get("observation") or {}).get("position"))
        if first_obs_pos is not None:
            visited_cells.add(first_obs_pos)

    for turn_obj in turn_logs:
        turn_number = _as_int(turn_obj.get("turn"), 0)
        observation = turn_obj.get("observation", {})
        validation = turn_obj.get("validation_result", {})
        action_result = turn_obj.get("action_result", {})
        action_delta = turn_obj.get("world_result_delta", {}).get("action_delta", {})

        before_pos = _as_position_tuple(observation.get("position"))
        after_pos = _as_position_tuple(action_delta.get("position_after")) or before_pos

        first_food_seen_turn, first_water_seen_turn = _resource_seen_updates(
            turn=turn_number,
            visible_tiles=observation.get("visible_tiles", []),
            seen_food_cells=seen_food_cells,
            seen_water_cells=seen_water_cells,
            first_food_seen_turn=first_food_seen_turn,
            first_water_seen_turn=first_water_seen_turn,
        )

        tile_here = _tile_type_at_position(observation.get("visible_tiles", []), before_pos)

        action_success = bool(action_result.get("success", False))
        action_applied = str(action_result.get("applied") or "").strip().lower()
        action_requested = str(action_result.get("requested") or "").strip().lower()
        valid = bool(validation.get("is_valid", False))

        moved = action_success and action_applied in _MOVE_ACTIONS
        if moved:
            move_count += 1
            distance_traveled += 1
            if turn_number <= early_window_turns:
                move_count_early += 1

        if action_success and action_applied == "gather":
            gather_count += 1

        if action_success and action_applied in _WAIT_ACTIONS:
            wait_count += 1

        score_events = [str(item) for item in (turn_obj.get("score_delta", {}).get("events") or [])]
        useful_now = ("useful_gather" in score_events) or ("useful_consume" in score_events)
        if useful_now:
            useful_action_count += 1
            if turn_number <= early_window_turns:
                useful_count_early += 1
        if "useful_consume" in score_events:
            useful_consume_turns.append(turn_number)

        if after_pos is not None and moved:
            if after_pos in visited_cells:
                revisit_count += 1
                consecutive_revisit += 1
                consecutive_revisit_max = max(consecutive_revisit_max, consecutive_revisit)
            else:
                visited_cells.add(after_pos)
                consecutive_revisit = 0
        else:
            consecutive_revisit = 0

        inventory_delta = action_delta.get("inventory_delta", {})
        if isinstance(inventory_delta, dict):
            food_inc = _as_int(inventory_delta.get("food"), 0)
            water_inc = _as_int(inventory_delta.get("water"), 0)
            if food_inc > 0:
                food_gathered_count += food_inc
                if first_food_gather_turn is None:
                    first_food_gather_turn = turn_number
            if water_inc > 0:
                water_gathered_count += water_inc
                if first_water_gather_turn is None:
                    first_water_gather_turn = turn_number

        if tile_here == "food" and not (action_success and action_applied == "gather"):
            missed_food_opportunities += 1
        if tile_here == "water" and not (action_success and action_applied == "gather"):
            missed_water_opportunities += 1

        hunger_now = _as_int(observation.get("hunger"), 0)
        thirst_now = _as_int(observation.get("thirst"), 0)
        energy_now = _as_int(observation.get("energy"), 0)

        if first_hunger_warning_turn is None and hunger_now >= hunger_warning_threshold:
            first_hunger_warning_turn = turn_number
        if first_thirst_warning_turn is None and thirst_now >= thirst_warning_threshold:
            first_thirst_warning_turn = turn_number
        if first_energy_warning_turn is None and energy_now <= energy_warning_threshold:
            first_energy_warning_turn = turn_number
        if starvation_pressure_turn is None and hunger_now >= hunger_max:
            starvation_pressure_turn = turn_number
        if dehydration_pressure_turn is None and thirst_now >= thirst_max:
            dehydration_pressure_turn = turn_number
        if low_energy_pressure_turn is None and energy_now <= energy_warning_threshold:
            low_energy_pressure_turn = turn_number

        if not valid:
            invalid_action_count += 0

    revisit_ratio = (revisit_count / move_count) if move_count > 0 else 0.0
    useful_action_ratio = (useful_action_count / total_turns) if total_turns > 0 else 0.0
    loop_detected = (
        revisit_ratio >= thresholds["loop_revisit_ratio"]
        and consecutive_revisit_max >= int(thresholds["loop_consecutive_revisit_max"])
    )

    behavior_metrics = {
        "move_count": move_count,
        "gather_count": gather_count,
        "wait_count": wait_count,
        "invalid_action_count": invalid_action_count,
        "useful_action_ratio": round(useful_action_ratio, 6),
        "distance_traveled": distance_traveled,
        "unique_cells_visited": len(visited_cells),
        "revisit_count": revisit_count,
        "revisit_ratio": round(revisit_ratio, 6),
        "consecutive_revisit_max": consecutive_revisit_max,
        "loop_detected": loop_detected,
    }

    resource_metrics = {
        "food_seen_count": len(seen_food_cells),
        "water_seen_count": len(seen_water_cells),
        "food_gathered_count": food_gathered_count,
        "water_gathered_count": water_gathered_count,
        "first_food_seen_turn": first_food_seen_turn,
        "first_water_seen_turn": first_water_seen_turn,
        "first_food_gather_turn": first_food_gather_turn,
        "first_water_gather_turn": first_water_gather_turn,
        "missed_food_opportunities": missed_food_opportunities,
        "missed_water_opportunities": missed_water_opportunities,
    }

    state_pressure_metrics = {
        "first_hunger_warning_turn": first_hunger_warning_turn,
        "first_thirst_warning_turn": first_thirst_warning_turn,
        "first_energy_warning_turn": first_energy_warning_turn,
        "starvation_pressure_turn": starvation_pressure_turn,
        "dehydration_pressure_turn": dehydration_pressure_turn,
        "low_energy_pressure_turn": low_energy_pressure_turn,
    }

    death_cause = final_facts.get("death_cause")
    died_from_starvation = death_cause in {"starvation", "starvation_and_dehydration"}
    died_from_dehydration = death_cause in {"dehydration", "starvation_and_dehydration"}
    died_from_energy_collapse = death_cause in {"energy_depletion", "energy_collapse"}

    pressure_turn_candidates = [turn for turn in [starvation_pressure_turn, dehydration_pressure_turn, low_energy_pressure_turn] if turn is not None]
    first_pressure_turn = min(pressure_turn_candidates) if pressure_turn_candidates else None
    late_recovery_tail_ratio = float(thresholds["late_recovery_tail_ratio"])
    late_recovery_attempt = False
    if useful_consume_turns:
        for consume_turn in useful_consume_turns:
            if total_turns > 0 and consume_turn >= int(total_turns * late_recovery_tail_ratio):
                late_recovery_attempt = True
                break
            if first_pressure_turn is not None and consume_turn >= (first_pressure_turn + 2):
                late_recovery_attempt = True
                break

    early_exploration_over_threshold = False
    if early_window_turns > 0:
        early_move_ratio = move_count_early / early_window_turns
        early_useful_ratio = useful_count_early / early_window_turns
        early_exploration_over_threshold = (
            early_move_ratio >= thresholds["wandering_move_ratio"]
            and early_useful_ratio <= thresholds["wandering_useful_action_ratio"]
        )

    outcome_helpers = {
        "died_from_starvation": died_from_starvation,
        "died_from_dehydration": died_from_dehydration,
        "died_from_energy_collapse": died_from_energy_collapse,
        "survived_full_run": bool(final_facts["survived"]) and str(run_summary.get("end_reason", "")) == "max_turns_reached",
        "early_exploration_over_threshold": early_exploration_over_threshold,
        "late_recovery_attempt": late_recovery_attempt,
    }

    classification = _classify_archetypes(
        final_facts=final_facts,
        behavior_metrics=behavior_metrics,
        resource_metrics=resource_metrics,
        state_pressure_metrics=state_pressure_metrics,
        outcome_helpers=outcome_helpers,
        thresholds=thresholds,
    )

    analysis_core = {
        "schema_version": RUN_ANALYSIS_SCHEMA_VERSION,
        "analysis_version": RUN_ANALYSIS_VERSION,
        "run_identity": run_identity,
        "final_facts": final_facts,
        "behavior_metrics": behavior_metrics,
        "resource_metrics": resource_metrics,
        "state_pressure_metrics": state_pressure_metrics,
        "outcome_helpers": outcome_helpers,
        "classification": {
            "primary_failure_archetype": classification["primary_failure_archetype"],
            "primary_failure_archetype_human": classification["primary_failure_archetype_human"],
            "secondary_failure_archetypes": classification["secondary_failure_archetypes"],
            "secondary_failure_archetypes_human": classification["secondary_failure_archetypes_human"],
            "confidence_hint": classification["confidence_hint"],
            "failure_archetypes": classification["failure_archetypes"],
            "failure_archetypes_human": classification["failure_archetypes_human"],
        },
    }

    summaries = build_deterministic_summaries(analysis_core)
    analysis_core["summaries"] = summaries
    return analysis_core
