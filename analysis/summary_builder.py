"""Deterministic summary builder from structured run analysis."""

from __future__ import annotations

from analysis.failure_archetypes import label_for


def _format_cause(cause: str | None) -> str:
    mapping = {
        "dehydration": "dehydration",
        "starvation": "starvation",
        "energy_depletion": "energy collapse",
        "energy_collapse": "energy collapse",
        "starvation_and_dehydration": "starvation and dehydration",
    }
    if cause is None:
        return "unknown causes"
    return mapping.get(cause, cause.replace("_", " "))


def _short_summary_for_primary(primary: str, analysis: dict) -> str:
    final_facts = analysis.get("final_facts", {})
    outcome = analysis.get("outcome_helpers", {})
    resource_metrics = analysis.get("resource_metrics", {})
    behavior = analysis.get("behavior_metrics", {})

    if primary == "successful_optimization":
        return "Agent survived and optimized resource use with efficient exploration."
    if primary == "successful_stabilization":
        return "Agent survived by stabilizing food and water before critical pressure."
    if primary == "delayed_water_priority":
        return "Agent underperformed after delaying water collection despite early visibility."
    if primary == "delayed_food_priority":
        return "Agent underperformed after delaying food collection despite early visibility."
    if primary == "local_loop":
        return "Agent underperformed due to local looping and repeated revisits."
    if primary == "wandering":
        return "Agent underperformed due to wandering and low useful action conversion."
    if primary == "bad_gather_timing":
        return "Agent underperformed from missed gather timing opportunities."
    if primary == "invalid_output_collapse":
        return "Agent collapsed due to frequent invalid outputs."
    if primary == "resource_tunnel_vision":
        return "Agent tunneled on gathering without timely consumption."
    if primary == "late_recovery_failure":
        return "Agent attempted late recovery but failed to stabilize in time."
    if primary in {"dehydration", "starvation", "energy_collapse"}:
        if final_facts.get("survived"):
            return f"Agent survived but showed {label_for(primary).lower()} pressure."
        return f"Agent died from {label_for(primary).lower()}."
    if primary == "balanced_but_insufficient":
        if final_facts.get("survived"):
            return "Agent survived but showed limited optimization efficiency."
        return "Agent remained balanced but insufficient to avoid collapse."

    if outcome.get("survived_full_run"):
        return "Agent survived the full run with deterministic stability."

    if resource_metrics.get("missed_water_opportunities", 0) > resource_metrics.get("missed_food_opportunities", 0):
        return "Agent died after missing key water opportunities."

    if behavior.get("loop_detected"):
        return "Agent died after repeated movement loops."

    return "Agent underperformed due to mixed strategy inefficiencies."


def _detailed_summary_for_primary(primary: str, analysis: dict) -> str:
    final_facts = analysis.get("final_facts", {})
    resource_metrics = analysis.get("resource_metrics", {})
    behavior = analysis.get("behavior_metrics", {})
    state = analysis.get("state_pressure_metrics", {})
    classification = analysis.get("classification", {})

    turn_text = "unknown turn"
    death_turn = final_facts.get("death_turn")
    if isinstance(death_turn, int):
        turn_text = f"turn {death_turn}"

    if final_facts.get("survived"):
        intro = f"The agent survived the run ({final_facts.get('total_turns', 0)} turns)."
    else:
        cause_text = _format_cause(final_facts.get("death_cause"))
        intro = f"The agent died on {turn_text} from {cause_text}."

    details: list[str] = []

    water_seen = resource_metrics.get("first_water_seen_turn")
    water_gather = resource_metrics.get("first_water_gather_turn")
    food_seen = resource_metrics.get("first_food_seen_turn")
    food_gather = resource_metrics.get("first_food_gather_turn")

    if primary == "delayed_water_priority":
        details.append(
            f"Water was first seen on turn {water_seen}, but first water gather was {water_gather if water_gather is not None else 'never'}."
        )
    elif primary == "delayed_food_priority":
        details.append(
            f"Food was first seen on turn {food_seen}, but first food gather was {food_gather if food_gather is not None else 'never'}."
        )
    elif primary == "local_loop":
        details.append(
            f"Revisit ratio reached {behavior.get('revisit_ratio', 0):.2f} with max consecutive revisit streak {behavior.get('consecutive_revisit_max', 0)}."
        )
    elif primary == "wandering":
        details.append(
            f"Movement dominated the run ({behavior.get('move_count', 0)} moves) while useful-action ratio stayed low ({behavior.get('useful_action_ratio', 0):.2f})."
        )
    elif primary == "bad_gather_timing":
        details.append(
            f"Missed opportunities were high (food {resource_metrics.get('missed_food_opportunities', 0)}, water {resource_metrics.get('missed_water_opportunities', 0)})."
        )
    elif primary == "invalid_output_collapse":
        details.append(
            f"Invalid action rate reached {final_facts.get('invalid_rate', 0):.2f} ({final_facts.get('total_invalid', 0)} invalid actions)."
        )
    elif primary == "resource_tunnel_vision":
        details.append(
            f"Gather count was high ({behavior.get('gather_count', 0)}) but useful-action ratio remained {behavior.get('useful_action_ratio', 0):.2f}."
        )
    elif primary == "late_recovery_failure":
        details.append("Recovery actions happened late, after pressure had already escalated.")
    elif primary in {"dehydration", "starvation", "energy_collapse"}:
        pressure_turn = {
            "dehydration": state.get("dehydration_pressure_turn"),
            "starvation": state.get("starvation_pressure_turn"),
            "energy_collapse": state.get("low_energy_pressure_turn"),
        }.get(primary)
        if pressure_turn is not None:
            details.append(f"Critical pressure first appeared on turn {pressure_turn}.")
    elif primary in {"successful_stabilization", "successful_optimization"}:
        details.append(
            f"Resource stabilization happened early (food gather turn {food_gather if food_gather is not None else 'n/a'}, water gather turn {water_gather if water_gather is not None else 'n/a'})."
        )
        details.append(
            f"Revisit ratio was {behavior.get('revisit_ratio', 0):.2f} with useful-action ratio {behavior.get('useful_action_ratio', 0):.2f}."
        )
    else:
        details.append(
            f"The run mixed exploration and resource actions, but final score remained {final_facts.get('final_score', 0)}."
        )

    secondary = classification.get("secondary_failure_archetypes_human", [])
    if secondary:
        details.append(f"Secondary patterns: {', '.join(secondary[:3])}.")

    return " ".join([intro, *details]).strip()


def build_deterministic_summaries(analysis: dict) -> dict[str, str]:
    classification = analysis.get("classification", {})
    primary = str(classification.get("primary_failure_archetype", "balanced_but_insufficient"))

    short_summary = _short_summary_for_primary(primary, analysis)
    detailed_summary = _detailed_summary_for_primary(primary, analysis)
    return {
        "short_summary": short_summary,
        "detailed_summary": detailed_summary,
    }

