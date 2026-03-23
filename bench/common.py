"""Shared helpers for benchmark runners."""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

import yaml

from analysis.run_analyzer import build_run_analysis
from engine.actions import ActionOutcome, apply_action
from engine.observation import build_observation
from engine.parser import parse_action
from engine.prompt_loader import PromptLoader
from engine.rules import apply_end_of_turn, compute_allowed_actions
from engine.scoring import apply_score, score_action, score_survival
from engine.version import __version__
from engine.world import create_world, serialize_tiles
from models.anthropic_wrapper import AnthropicWrapper
from models.base import BaseModelWrapper, RenderedPrompts
from models.dummy import DummyRandomWrapper
from models.local_wrapper import LocalWrapper
from models.openai_wrapper import OpenAIWrapper
from renderers.json_renderer import prompt_pair_hash
from bench.pricing import (
    estimate_cost_from_total_tokens,
    estimate_cost_usd,
    load_pricing_config,
    resolve_model_pricing,
)


DEFAULT_AGENT_ID = "agent_1"

_MOVE_ACTIONS = {"move north", "move south", "move east", "move west"}

_FAILURE_LABELS = {
    "wandering": "Wandering / low-yield movement",
    "starvation": "Starvation",
    "dehydration": "Dehydration",
    "gather_timing_failure": "Gather timing failure",
    "resource_tunnel_vision": "Resource tunnel vision",
    "local_loop": "Local loop",
    "invalid_output_collapse": "Invalid-output collapse",
    "late_recovery_failure": "Late recovery failure",
    "balanced_or_unclear": "Balanced or unclear",
}


@dataclass(frozen=True)
class ModelBinding:
    wrapper: BaseModelWrapper
    model_profile: str
    provider_id: str


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    resolved = Path(path)
    with resolved.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {resolved}")
    return data


def load_configs(
    benchmark_config_path: str | Path,
    scenarios_config_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return load_yaml_file(benchmark_config_path), load_yaml_file(scenarios_config_path)


def resolve_artifact_dirs(benchmark_cfg: dict[str, Any], project_root: Path) -> dict[str, Path]:
    logging_cfg = benchmark_cfg["logging"]

    logs_dir = Path(logging_cfg["logs_dir"])
    results_dir = Path(logging_cfg["results_dir"])
    replays_dir = Path(logging_cfg["replays_dir"])

    if not logs_dir.is_absolute():
        logs_dir = project_root / logs_dir
    if not results_dir.is_absolute():
        results_dir = project_root / results_dir
    if not replays_dir.is_absolute():
        replays_dir = project_root / replays_dir

    logs_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    replays_dir.mkdir(parents=True, exist_ok=True)

    return {
        "logs": logs_dir,
        "results": results_dir,
        "replays": replays_dir,
    }


def _resolve_api_key(provider_cfg: dict[str, Any]) -> str | None:
    api_key = provider_cfg.get("api_key")

    api_key_env = provider_cfg.get("api_key_env")
    if api_key_env:
        env_value = os.environ.get(str(api_key_env))
        if env_value:
            api_key = env_value

    if api_key is None:
        return None
    return str(api_key)


def _create_openai_compatible_wrapper(
    provider_id: str,
    provider_cfg: dict[str, Any],
    profile_name: str,
    profile_cfg: dict[str, Any],
) -> OpenAIWrapper:
    api_base = provider_cfg.get("api_base")
    if not api_base:
        raise ValueError(f"provider '{provider_id}' missing api_base")

    model_name = profile_cfg.get("model")
    if not model_name:
        raise ValueError(f"model profile '{profile_name}' missing model")

    api_key = _resolve_api_key(provider_cfg)
    if not api_key:
        raise ValueError(
            f"provider '{provider_id}' missing API key: set api_key or api_key_env"
        )

    def _resolve_numeric(key: str, default: Any) -> Any:
        if key in profile_cfg:
            return profile_cfg[key]
        if key in provider_cfg:
            return provider_cfg[key]
        return default

    return OpenAIWrapper(
        model_name=str(model_name),
        api_base=str(api_base),
        api_key=api_key,
        temperature=float(_resolve_numeric("temperature", 0.2)),
        max_tokens=int(_resolve_numeric("max_tokens", 1024)),
        requests_per_minute=int(_resolve_numeric("requests_per_minute", 30)),
        max_retries=int(_resolve_numeric("max_retries", 3)),
        retry_base_seconds=float(_resolve_numeric("retry_base_seconds", 2.0)),
        retry_max_seconds=float(_resolve_numeric("retry_max_seconds", 20.0)),
        request_timeout_seconds=float(_resolve_numeric("request_timeout_seconds", 60.0)),
        max_concurrent_requests=int(_resolve_numeric("max_concurrent_requests", 1)),
        provider_id=provider_id,
        profile_name=profile_name,
    )


def create_model_wrapper(
    model_name: str,
    seed: int,
    providers_cfg: dict[str, Any] | None = None,
) -> ModelBinding:
    selector = model_name.strip() if model_name else ""

    if providers_cfg:
        profiles = providers_cfg.get("model_profiles", {})
        providers = providers_cfg.get("providers", {})

        if not selector:
            selector = str(providers_cfg.get("default_model_profile", ""))

        if selector in profiles:
            profile_cfg = profiles[selector]
            provider_id = str(profile_cfg["provider"])
            provider_cfg = providers.get(provider_id)
            if provider_cfg is None:
                raise ValueError(f"provider '{provider_id}' not found for model profile '{selector}'")

            provider_type = str(provider_cfg.get("type", "")).strip()
            if provider_type == "dummy":
                wrapper = DummyRandomWrapper(
                    seed=seed,
                    model_name=str(profile_cfg.get("model_name", "dummy_random_v0_1")),
                )
                return ModelBinding(wrapper=wrapper, model_profile=selector, provider_id=provider_id)

            if provider_type == "openai_compatible":
                wrapper = _create_openai_compatible_wrapper(
                    provider_id=provider_id,
                    provider_cfg=provider_cfg,
                    profile_name=selector,
                    profile_cfg=profile_cfg,
                )
                return ModelBinding(wrapper=wrapper, model_profile=selector, provider_id=provider_id)

            if provider_type == "anthropic_placeholder":
                return ModelBinding(wrapper=AnthropicWrapper(), model_profile=selector, provider_id=provider_id)

            if provider_type == "local_placeholder":
                return ModelBinding(wrapper=LocalWrapper(), model_profile=selector, provider_id=provider_id)

            raise ValueError(f"unsupported provider type '{provider_type}' in provider '{provider_id}'")

    normalized = selector.lower()
    if normalized in {"", "dummy"}:
        return ModelBinding(
            wrapper=DummyRandomWrapper(seed=seed),
            model_profile="legacy_dummy",
            provider_id="dummy_provider",
        )
    if normalized == "anthropic":
        return ModelBinding(
            wrapper=AnthropicWrapper(),
            model_profile="legacy_anthropic",
            provider_id="anthropic",
        )
    if normalized == "local":
        return ModelBinding(
            wrapper=LocalWrapper(),
            model_profile="legacy_local",
            provider_id="local",
        )

    raise ValueError(
        "unknown model selector. Use --model with a profile from configs/providers.yaml "
        "(or legacy alias: dummy, anthropic, local)."
    )


def sanitize_providers_config(providers_cfg: dict[str, Any]) -> dict[str, Any]:
    sanitized = copy.deepcopy(providers_cfg)
    providers = sanitized.get("providers", {})
    if isinstance(providers, dict):
        for provider_cfg in providers.values():
            if isinstance(provider_cfg, dict) and "api_key" in provider_cfg:
                provider_cfg["api_key"] = "***REDACTED***"
    return sanitized


def _optional_sum_update(current_sum: float, has_value: bool, new_value: float | int | None) -> tuple[float, bool]:
    if new_value is None:
        return current_sum, has_value
    return current_sum + float(new_value), True


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _human_end_reason(end_reason: str, turns_played: int, max_turns: int) -> str:
    if end_reason == "agent_dead":
        return f"The agent died on turn {turns_played}."
    if end_reason == "max_turns_reached":
        return f"Reached the configured turn limit ({max_turns})."
    return f"Run ended with status: {end_reason}."


def _death_cause_from_survival(update: Any | None) -> tuple[str | None, str | None]:
    if update is None:
        return None, None

    starvation_triggered = bool(getattr(update, "starvation_triggered", False))
    dehydration_triggered = bool(getattr(update, "dehydration_triggered", False))

    if starvation_triggered and dehydration_triggered:
        return "starvation_and_dehydration", "Starvation and dehydration reached critical threshold."
    if starvation_triggered:
        return "starvation", "Starvation reached critical threshold."
    if dehydration_triggered:
        return "dehydration", "Dehydration reached critical threshold."
    return "energy_depletion", "Energy was depleted to zero."


def _emit_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    payload: dict[str, Any],
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(payload)
    except Exception:
        # CLI feedback should never break benchmark execution.
        return


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


def _failure_label(code: str | None) -> str:
    if code is None:
        return _FAILURE_LABELS["balanced_or_unclear"]
    return _FAILURE_LABELS.get(code, code.replace("_", " "))


def _build_run_analytics(
    *,
    turn_logs: list[dict[str, Any]],
    run_summary: dict[str, Any],
    rules_cfg: dict[str, Any],
    initial_tiles: list[list[str]],
    protocol_version: str | None = None,
) -> dict[str, Any]:
    turns_played = int(run_summary.get("turns_played", len(turn_logs)))
    invalid_actions = int(run_summary.get("invalid_actions", 0))
    end_reason = str(run_summary.get("end_reason", ""))
    death_cause = str(run_summary.get("death_cause", "") or "")

    hunger_max = int(rules_cfg.get("hunger_max", 100))
    thirst_max = int(rules_cfg.get("thirst_max", 100))
    hunger_alert = max(1, int(hunger_max * 0.70))
    thirst_alert = max(1, int(thirst_max * 0.70))

    map_cells_total = 0
    if initial_tiles and isinstance(initial_tiles, list):
        map_cells_total = sum(len(row) for row in initial_tiles if isinstance(row, list))

    visited_cells: set[tuple[int, int]] = set()
    revisits = 0
    move_success_count = 0
    gather_success_count = 0
    useful_gather_count = 0
    useful_consume_count = 0
    useful_eat_count = 0
    useful_drink_count = 0
    useful_events_total = 0
    max_invalid_streak = 0
    current_invalid_streak = 0
    critical_turns = 0
    critical_entries = 0
    critical_recovery_count = 0
    critical_streak = 0
    max_critical_streak = 0

    previous_critical = False
    positions_after: list[tuple[int, int]] = []
    move_flags: list[int] = []
    useful_flags: list[int] = []
    local_loop_hits = 0
    local_loop_active = False

    for turn in turn_logs:
        observation = turn.get("observation", {})
        validation = turn.get("validation_result", {})
        action_result = turn.get("action_result", {})
        action_delta = turn.get("world_result_delta", {}).get("action_delta", {})
        score_events = [str(item) for item in (turn.get("score_delta", {}).get("events") or [])]

        before_pos = _as_position_tuple(observation.get("position"))
        after_pos = _as_position_tuple(action_delta.get("position_after")) or before_pos
        if before_pos is not None and not visited_cells:
            visited_cells.add(before_pos)
        if after_pos is not None:
            if after_pos in visited_cells:
                revisits += 1
            else:
                visited_cells.add(after_pos)
            positions_after.append(after_pos)

        is_valid = bool(validation.get("is_valid", False))
        if not is_valid:
            current_invalid_streak += 1
            if current_invalid_streak > max_invalid_streak:
                max_invalid_streak = current_invalid_streak
        else:
            current_invalid_streak = 0

        action_applied = str(action_result.get("applied") or "").strip().lower()
        action_requested = str(action_result.get("requested") or "").strip().lower()
        action_success = bool(action_result.get("success", False))

        moved = action_applied in _MOVE_ACTIONS and action_success
        move_flags.append(1 if moved else 0)
        if moved:
            move_success_count += 1

        if action_requested == "gather" and action_success:
            gather_success_count += 1

        useful = False
        if "useful_gather" in score_events:
            useful = True
            useful_gather_count += 1
        if "useful_consume" in score_events:
            useful = True
            useful_consume_count += 1
            if action_applied == "eat":
                useful_eat_count += 1
            elif action_applied == "drink":
                useful_drink_count += 1
        useful_flags.append(1 if useful else 0)
        if useful:
            useful_events_total += 1

        hunger_now = int(observation.get("hunger", 0))
        thirst_now = int(observation.get("thirst", 0))
        critical_now = hunger_now >= hunger_alert or thirst_now >= thirst_alert
        if critical_now:
            critical_turns += 1
            critical_streak += 1
            if critical_streak > max_critical_streak:
                max_critical_streak = critical_streak
        else:
            critical_streak = 0

        if (not previous_critical) and critical_now:
            critical_entries += 1
        if previous_critical and (not critical_now):
            critical_recovery_count += 1
        previous_critical = critical_now

        if len(positions_after) >= 8:
            window_positions = positions_after[-8:]
            window_moves = sum(move_flags[-8:])
            window_useful = sum(useful_flags[-8:])
            unique_window_cells = len(set(window_positions))
            loop_now = unique_window_cells <= 3 and window_moves >= 6 and window_useful == 0
            if loop_now and not local_loop_active:
                local_loop_hits += 1
            local_loop_active = loop_now

    food_water_gathered = 0
    gathered_breakdown = run_summary.get("resources_gathered_breakdown", {})
    if isinstance(gathered_breakdown, dict):
        food_water_gathered = int(gathered_breakdown.get("food", 0)) + int(gathered_breakdown.get("water", 0))

    food_water_consumed_useful = useful_eat_count + useful_drink_count

    coverage_pct = None
    if map_cells_total > 0:
        coverage_pct = (len(visited_cells) / map_cells_total) * 100.0

    revisit_ratio = None
    if move_success_count > 0:
        revisit_ratio = revisits / move_success_count

    distance_per_useful_gain = None
    if useful_events_total > 0:
        distance_per_useful_gain = move_success_count / useful_events_total

    resource_conversion_efficiency = None
    resource_conversion_efficiency_pct = None
    if food_water_gathered > 0:
        resource_conversion_efficiency = food_water_consumed_useful / food_water_gathered
        resource_conversion_efficiency_pct = resource_conversion_efficiency * 100.0

    invalid_output_collapse = (turns_played > 0 and (invalid_actions / turns_played) >= 0.30) or max_invalid_streak >= 4
    wandering = (
        move_success_count >= max(8, int(turns_played * 0.55))
        and useful_events_total <= max(1, int(turns_played * 0.05))
    ) or (distance_per_useful_gain is not None and distance_per_useful_gain >= 8.0)
    gather_timing_failure = food_water_gathered > 0 and useful_consume_count == 0 and critical_turns >= 2
    resource_tunnel_vision = (
        gather_success_count >= max(4, int(turns_played * 0.25))
        and critical_turns >= 2
        and useful_consume_count <= 1
    )
    late_recovery_failure = (
        end_reason == "agent_dead"
        and critical_turns >= 3
        and useful_consume_count > 0
        and death_cause in {"starvation", "dehydration", "starvation_and_dehydration", "energy_depletion"}
    )
    starvation = death_cause in {"starvation", "starvation_and_dehydration"}
    dehydration = death_cause in {"dehydration", "starvation_and_dehydration"}
    local_loop = local_loop_hits > 0

    archetype_flags = {
        "invalid_output_collapse": invalid_output_collapse,
        "dehydration": dehydration,
        "starvation": starvation,
        "late_recovery_failure": late_recovery_failure,
        "local_loop": local_loop,
        "wandering": wandering,
        "gather_timing_failure": gather_timing_failure,
        "resource_tunnel_vision": resource_tunnel_vision,
    }
    archetype_order = [
        "invalid_output_collapse",
        "dehydration",
        "starvation",
        "late_recovery_failure",
        "local_loop",
        "wandering",
        "gather_timing_failure",
        "resource_tunnel_vision",
    ]
    detected = [code for code in archetype_order if archetype_flags.get(code)]
    if not detected:
        detected = ["balanced_or_unclear"]
    primary = detected[0]

    legacy_kpi = {
        "unique_cells_visited": len(visited_cells),
        "map_cells_total": map_cells_total if map_cells_total > 0 else None,
        "coverage_pct": round(coverage_pct, 4) if coverage_pct is not None else None,
        "moves_successful": move_success_count,
        "revisits": revisits,
        "revisit_ratio": round(revisit_ratio, 6) if revisit_ratio is not None else None,
        "useful_gather_count": useful_gather_count,
        "useful_consume_count": useful_consume_count,
        "useful_eat_count": useful_eat_count,
        "useful_drink_count": useful_drink_count,
        "useful_events_total": useful_events_total,
        "distance_per_useful_gain": round(distance_per_useful_gain, 6) if distance_per_useful_gain is not None else None,
        "food_water_gathered": food_water_gathered,
        "food_water_consumed_useful": food_water_consumed_useful,
        "resource_conversion_efficiency": round(resource_conversion_efficiency, 6)
        if resource_conversion_efficiency is not None
        else None,
        "resource_conversion_efficiency_pct": round(resource_conversion_efficiency_pct, 4)
        if resource_conversion_efficiency_pct is not None
        else None,
        "critical_turns": critical_turns,
        "critical_entries": critical_entries,
        "critical_recovery_count": critical_recovery_count,
        "max_critical_streak": max_critical_streak,
        "max_invalid_streak": max_invalid_streak,
        "local_loop_hits": local_loop_hits,
    }

    effective_protocol_version = str(
        protocol_version
        or run_summary.get("protocol_version")
        or "AIB-0.1"
    )
    run_identity = {
        "protocol_version": effective_protocol_version,
        "seed": run_summary.get("seed"),
        "scenario": run_summary.get("scenario"),
        "provider_id": run_summary.get("provider_id"),
        "model_profile": run_summary.get("model_profile"),
        "model": run_summary.get("model"),
        "prompt_variant": run_summary.get("prompt_variant"),
        "prompt_set_sha256": run_summary.get("prompt_set_sha256"),
    }
    structured = build_run_analysis(
        run_identity=run_identity,
        run_summary=run_summary,
        turn_logs=turn_logs,
        rules_cfg=rules_cfg,
        initial_tiles=initial_tiles,
    )
    classification = structured.get("classification", {})
    summaries = structured.get("summaries", {})

    failure_archetypes = classification.get("failure_archetypes")
    if not isinstance(failure_archetypes, list) or not failure_archetypes:
        failure_archetypes = detected

    failure_archetypes_human = classification.get("failure_archetypes_human")
    if not isinstance(failure_archetypes_human, list) or not failure_archetypes_human:
        failure_archetypes_human = [_failure_label(code) for code in failure_archetypes]

    primary_archetype = str(
        classification.get("primary_failure_archetype")
        or primary
    )
    primary_archetype_human = str(
        classification.get("primary_failure_archetype_human")
        or _failure_label(primary_archetype)
    )

    secondary_archetypes = classification.get("secondary_failure_archetypes")
    if not isinstance(secondary_archetypes, list):
        secondary_archetypes = [code for code in failure_archetypes if code != primary_archetype]

    secondary_archetypes_human = classification.get("secondary_failure_archetypes_human")
    if not isinstance(secondary_archetypes_human, list):
        secondary_archetypes_human = [_failure_label(code) for code in secondary_archetypes]

    return {
        "analysis_version": structured.get("analysis_version"),
        "analysis_schema_version": structured.get("schema_version"),
        "kpi": legacy_kpi,
        "failure_archetypes": failure_archetypes,
        "failure_archetypes_human": failure_archetypes_human,
        "primary_failure_archetype": primary_archetype,
        "primary_failure_archetype_human": primary_archetype_human,
        "secondary_failure_archetypes": secondary_archetypes,
        "secondary_failure_archetypes_human": secondary_archetypes_human,
        "confidence_hint": classification.get("confidence_hint"),
        "short_summary": summaries.get("short_summary"),
        "detailed_summary": summaries.get("detailed_summary"),
        "run_analysis": structured,
    }


def run_match_once(
    seed: int,
    model_name: str = "dummy",
    scenario_name: str | None = None,
    max_turns: int | None = None,
    benchmark_config_path: str | Path = "configs/benchmark.yaml",
    scenarios_config_path: str | Path = "configs/scenarios.yaml",
    providers_config_path: str | Path = "configs/providers.yaml",
    prompts_dir: str | Path = "prompts",
    output_path: str | Path | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    project_root = Path.cwd()
    benchmark_cfg, scenarios_cfg = load_configs(benchmark_config_path, scenarios_config_path)
    providers_cfg = load_yaml_file(providers_config_path)

    scenario_key = scenario_name or benchmark_cfg["default_scenario"]
    scenario = scenarios_cfg["scenarios"][scenario_key]

    parser_case_mode = benchmark_cfg["parser"]["case_mode"]
    invalid_action_policy = benchmark_cfg["invalid_action_policy"]
    if invalid_action_policy != "waste_turn":
        raise ValueError(f"unsupported invalid_action_policy in v0.1: {invalid_action_policy}")

    artifact_dirs = resolve_artifact_dirs(benchmark_cfg, project_root)
    rules_cfg = benchmark_cfg["rules"]
    scoring_cfg = benchmark_cfg["scoring"]
    protocol_version = benchmark_cfg["protocol_version"]
    pricing_config_path = benchmark_cfg.get("pricing_config_path", "configs/pricing.yaml")

    pricing_cfg: dict[str, Any] | None = None
    pricing_config_used: str | None = None
    if pricing_config_path:
        pricing_path = Path(str(pricing_config_path))
        if not pricing_path.is_absolute():
            pricing_path = (project_root / pricing_path).resolve()
        pricing_config_used = str(pricing_path)
        if pricing_path.exists():
            pricing_cfg = load_pricing_config(pricing_path)

    run_max_turns = int(max_turns if max_turns is not None else benchmark_cfg["max_turns"])

    world = create_world(seed=seed, scenario_cfg=scenario, rules_cfg=rules_cfg, agent_id=DEFAULT_AGENT_ID)
    initial_tiles = serialize_tiles(world)
    prompt_loader = PromptLoader(prompts_dir)
    system_prompt = prompt_loader.render_system_prompt({})
    prompt_metadata = prompt_loader.get_prompt_metadata()
    system_prompt_sha256 = prompt_pair_hash(system_prompt, "")

    model_binding = create_model_wrapper(model_name=model_name, seed=seed, providers_cfg=providers_cfg)
    wrapper = model_binding.wrapper
    model_pricing = resolve_model_pricing(
        pricing_cfg=pricing_cfg,
        provider_id=model_binding.provider_id,
        model=wrapper.model_name,
    )

    _emit_progress(
        progress_callback,
        {
            "event": "run_started",
            "seed": seed,
            "scenario": scenario_key,
            "scenario_is_default": scenario_name is None,
            "provider_id": model_binding.provider_id,
            "model_profile": model_binding.model_profile,
            "model": wrapper.model_name,
            "max_turns": run_max_turns,
            "protocol_version": protocol_version,
        },
    )

    log_full_prompts = bool(benchmark_cfg["logging"].get("log_full_prompts", False))

    turn_logs: list[dict[str, Any]] = []

    resources_gathered = 0
    resources_gathered_breakdown = {"wood": 0, "stone": 0, "food": 0, "water": 0}
    invalid_actions = 0
    survived_turns = 0

    tokens_sum = 0.0
    tokens_seen = False
    prompt_tokens_sum = 0.0
    prompt_tokens_seen = False
    completion_tokens_sum = 0.0
    completion_tokens_seen = False
    cache_read_tokens_sum = 0.0
    cache_read_tokens_seen = False
    cache_write_tokens_sum = 0.0
    cache_write_tokens_seen = False
    cost_sum = 0.0
    cost_seen = False
    estimated_cost_provider_used = False
    estimated_cost_fallback_used = False
    latency_sum_ms = 0.0
    last_survival_update: Any | None = None

    for turn in range(1, run_max_turns + 1):
        agent = world.agents[DEFAULT_AGENT_ID]
        if not agent.alive:
            break

        world.turn = turn
        _emit_progress(
            progress_callback,
            {
                "event": "turn_started",
                "turn": turn,
                "max_turns": run_max_turns,
            },
        )

        allowed_actions = compute_allowed_actions(world, DEFAULT_AGENT_ID, rules_cfg)
        observation = build_observation(world, DEFAULT_AGENT_ID, allowed_actions, protocol_version)
        user_prompt = prompt_loader.render_turn_prompt(observation=observation, include_memory=False)

        prompts = RenderedPrompts(system_prompt=system_prompt, user_prompt=user_prompt)
        model_metadata = {
            "seed": seed,
            "turn": turn,
            "agent_id": DEFAULT_AGENT_ID,
            "allowed_actions": allowed_actions,
            "observation": observation,
            "protocol_version": protocol_version,
            "provider_id": model_binding.provider_id,
            "model_profile": model_binding.model_profile,
        }

        call_started = perf_counter()
        model_response = wrapper.generate(prompts=prompts, metadata=model_metadata)
        measured_latency_ms = (perf_counter() - call_started) * 1000.0
        latency_ms = model_response.latency_ms if model_response.latency_ms is not None else measured_latency_ms
        latency_sum_ms += float(latency_ms)

        response_meta = model_response.metadata if isinstance(model_response.metadata, dict) else {}
        prompt_tokens = _optional_int(response_meta.get("prompt_tokens"))
        completion_tokens = _optional_int(response_meta.get("completion_tokens"))
        cache_read_tokens = _optional_int(response_meta.get("cache_read_tokens"))
        cache_write_tokens = _optional_int(response_meta.get("cache_write_tokens"))

        turn_total_tokens = model_response.tokens_used
        if turn_total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
            turn_total_tokens = prompt_tokens + completion_tokens

        tokens_sum, tokens_seen = _optional_sum_update(tokens_sum, tokens_seen, turn_total_tokens)
        prompt_tokens_sum, prompt_tokens_seen = _optional_sum_update(
            prompt_tokens_sum, prompt_tokens_seen, prompt_tokens
        )
        completion_tokens_sum, completion_tokens_seen = _optional_sum_update(
            completion_tokens_sum, completion_tokens_seen, completion_tokens
        )
        cache_read_tokens_sum, cache_read_tokens_seen = _optional_sum_update(
            cache_read_tokens_sum, cache_read_tokens_seen, cache_read_tokens
        )
        cache_write_tokens_sum, cache_write_tokens_seen = _optional_sum_update(
            cache_write_tokens_sum, cache_write_tokens_seen, cache_write_tokens
        )

        turn_estimated_cost = model_response.estimated_cost
        if turn_estimated_cost is not None:
            estimated_cost_provider_used = True
        if turn_estimated_cost is None:
            turn_estimated_cost = estimate_cost_usd(
                pricing=model_pricing,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
            )
            if turn_estimated_cost is not None:
                estimated_cost_fallback_used = True
        if turn_estimated_cost is None:
            turn_estimated_cost = estimate_cost_from_total_tokens(
                pricing=model_pricing,
                total_tokens=turn_total_tokens,
            )
            if turn_estimated_cost is not None:
                estimated_cost_fallback_used = True
        cost_sum, cost_seen = _optional_sum_update(cost_sum, cost_seen, turn_estimated_cost)

        parse_result = parse_action(
            raw_output=model_response.raw_text,
            allowed_actions=allowed_actions,
            case_mode=parser_case_mode,
        )

        if parse_result.valid and parse_result.action is not None:
            action_outcome = apply_action(
                world=world,
                agent_id=DEFAULT_AGENT_ID,
                action=parse_result.action,
                rules_cfg=rules_cfg,
            )
            action_score_delta, action_score_events = score_action(True, action_outcome, scoring_cfg)
            if action_outcome.useful_gather:
                resources_gathered += 1
                inventory_delta = action_outcome.world_delta.get("inventory_delta", {})
                for item, delta in inventory_delta.items():
                    if item in resources_gathered_breakdown and int(delta) > 0:
                        resources_gathered_breakdown[item] += int(delta)
        else:
            invalid_actions += 1
            action_outcome = ActionOutcome(
                action=parse_result.normalized_output,
                success=False,
                message="invalid action",
                invalid_reason=parse_result.error,
                world_delta={},
            )
            action_score_delta, action_score_events = score_action(False, None, scoring_cfg)

        survival_update = apply_end_of_turn(world=world, agent_id=DEFAULT_AGENT_ID, rules_cfg=rules_cfg)
        last_survival_update = survival_update
        survival_score_delta, survival_score_events = score_survival(survival_update.alive_after, scoring_cfg)

        if survival_update.alive_after:
            survived_turns += 1

        turn_score_delta = action_score_delta + survival_score_delta
        score_events = action_score_events + survival_score_events

        apply_score(world.agents[DEFAULT_AGENT_ID], turn_score_delta)

        prompt_payload: dict[str, Any] = {
            "system_prompt_sha256": prompt_pair_hash(system_prompt, ""),
            "user_prompt_sha256": prompt_pair_hash("", user_prompt),
            "combined_prompt_sha256": prompt_pair_hash(system_prompt, user_prompt),
        }
        if log_full_prompts:
            prompt_payload["system_prompt"] = system_prompt
            prompt_payload["user_prompt"] = user_prompt

        turn_logs.append(
            {
                "seed": seed,
                "turn": turn,
                "observation": observation,
                "prompt_payload": prompt_payload,
                "raw_model_output": model_response.raw_text,
                "parsed_action": parse_result.action,
                "validation_result": {
                    "is_valid": parse_result.valid,
                    "error": parse_result.error,
                    "allowed_actions": allowed_actions,
                },
                "world_result_delta": {
                    "action_delta": action_outcome.world_delta,
                    "survival_delta": survival_update.as_delta(),
                },
                "action_result": {
                    "requested": parse_result.normalized_output,
                    "applied": parse_result.action,
                    "success": action_outcome.success,
                    "message": action_outcome.message,
                    "invalid_reason": action_outcome.invalid_reason,
                },
                "score_delta": {
                    "action": action_score_delta,
                    "survival": survival_score_delta,
                    "total": turn_score_delta,
                    "events": score_events,
                },
                "cumulative_score": world.agents[DEFAULT_AGENT_ID].score,
                "metrics": {
                    "latency_ms": latency_ms,
                    "tokens_used": turn_total_tokens,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cache_read_tokens": cache_read_tokens,
                    "cache_write_tokens": cache_write_tokens,
                    "estimated_cost": turn_estimated_cost,
                },
            }
        )

        _emit_progress(
            progress_callback,
            {
                "event": "turn_completed",
                "turn": turn,
                "max_turns": run_max_turns,
                "alive": world.agents[DEFAULT_AGENT_ID].alive,
                "cumulative_score": world.agents[DEFAULT_AGENT_ID].score,
                "invalid_actions": invalid_actions,
                "action": parse_result.action or parse_result.normalized_output,
                "protocol_valid": parse_result.valid,
                "action_effect_applied": action_outcome.success,
            },
        )

        if not world.agents[DEFAULT_AGENT_ID].alive:
            break

    final_agent = world.agents[DEFAULT_AGENT_ID]
    end_reason = "agent_dead" if not final_agent.alive else "max_turns_reached"
    death_cause: str | None = None
    death_cause_human: str | None = None
    if not final_agent.alive:
        death_cause, death_cause_human = _death_cause_from_survival(last_survival_update)

    run_summary = {
        "version": __version__,
        "bench_version": __version__,
        "engine_version": __version__,
        "protocol_version": protocol_version,
        "prompt_set_sha256": prompt_metadata["prompt_set_sha256"],
        "seed": seed,
        "scenario": scenario_key,
        "provider_id": model_binding.provider_id,
        "model_profile": model_binding.model_profile,
        "model": wrapper.model_name,
        "max_turns": run_max_turns,
        "turns_played": len(turn_logs),
        "turns_survived": survived_turns,
        "final_score": final_agent.score,
        "resources_gathered": resources_gathered,
        "resources_gathered_breakdown": resources_gathered_breakdown,
        "invalid_actions": invalid_actions,
        "alive": final_agent.alive,
        "end_reason": end_reason,
        "end_reason_human": _human_end_reason(end_reason, len(turn_logs), run_max_turns),
        "death_cause": death_cause,
        "death_cause_human": death_cause_human,
        "tokens_used": int(tokens_sum) if tokens_seen else None,
        "token_breakdown": {
            "prompt_tokens": int(prompt_tokens_sum) if prompt_tokens_seen else None,
            "completion_tokens": int(completion_tokens_sum) if completion_tokens_seen else None,
            "cache_read_tokens": int(cache_read_tokens_sum) if cache_read_tokens_seen else None,
            "cache_write_tokens": int(cache_write_tokens_sum) if cache_write_tokens_seen else None,
        },
        "latency_ms": round(latency_sum_ms, 3),
        "estimated_cost": round(cost_sum, 6) if cost_seen else None,
        "estimated_cost_source": (
            "mixed"
            if estimated_cost_provider_used and estimated_cost_fallback_used
            else ("provider_reported" if estimated_cost_provider_used else ("pricing_fallback" if estimated_cost_fallback_used else None))
        ),
        "pricing_ref": (
            {
                "config_path": pricing_config_used,
                "provider_id": model_binding.provider_id,
                "model": wrapper.model_name,
                "input_per_million_usd": model_pricing.input_per_million_usd,
                "output_per_million_usd": model_pricing.output_per_million_usd,
                "cache_read_per_million_usd": model_pricing.cache_read_per_million_usd,
                "cache_write_per_million_usd": model_pricing.cache_write_per_million_usd,
                "fallback_input_ratio_from_total_tokens": model_pricing.fallback_input_ratio_from_total_tokens,
            }
            if model_pricing is not None
            else {
                "config_path": pricing_config_used,
                "provider_id": model_binding.provider_id,
                "model": wrapper.model_name,
                "input_per_million_usd": None,
                "output_per_million_usd": None,
                "cache_read_per_million_usd": None,
                "cache_write_per_million_usd": None,
                "fallback_input_ratio_from_total_tokens": None,
            }
        ),
    }

    analysis = _build_run_analytics(
        turn_logs=turn_logs,
        run_summary=run_summary,
        rules_cfg=rules_cfg,
        initial_tiles=initial_tiles,
        protocol_version=protocol_version,
    )
    run_summary["analysis_version"] = analysis["analysis_version"]
    run_summary["analysis_schema_version"] = analysis["analysis_schema_version"]
    run_summary["kpi"] = analysis["kpi"]
    run_summary["failure_archetypes"] = analysis["failure_archetypes"]
    run_summary["failure_archetypes_human"] = analysis["failure_archetypes_human"]
    run_summary["primary_failure_archetype"] = analysis["primary_failure_archetype"]
    run_summary["primary_failure_archetype_human"] = analysis["primary_failure_archetype_human"]
    run_summary["secondary_failure_archetypes"] = analysis["secondary_failure_archetypes"]
    run_summary["secondary_failure_archetypes_human"] = analysis["secondary_failure_archetypes_human"]
    run_summary["confidence_hint"] = analysis["confidence_hint"]
    run_summary["short_summary"] = analysis["short_summary"]
    run_summary["detailed_summary"] = analysis["detailed_summary"]

    run_log = {
        "version": __version__,
        "protocol_version": protocol_version,
        "seed": seed,
        "scenario": scenario_key,
        "provider_id": model_binding.provider_id,
        "model_profile": model_binding.model_profile,
        "model": wrapper.model_name,
        "engine_version": __version__,
        "prompt_versions": {
            "prompt_set_sha256": prompt_metadata["prompt_set_sha256"],
            "templates": prompt_metadata["templates"],
            "active_templates": prompt_metadata["active_templates"],
        },
        "benchmark_identity": {
            "bench_version": __version__,
            "engine_version": __version__,
            "protocol_version": protocol_version,
            "prompt_set_sha256": prompt_metadata["prompt_set_sha256"],
            "system_prompt_sha256": system_prompt_sha256,
            "prompt_templates": prompt_metadata["templates"],
            "active_templates": prompt_metadata["active_templates"],
            "prompts_dir": prompt_metadata["prompts_dir"],
        },
        "config_snapshot": {
            "benchmark": benchmark_cfg,
            "scenario": scenario,
            "providers": sanitize_providers_config(providers_cfg),
        },
        "run_summary": run_summary,
        "run_analysis": analysis["run_analysis"],
        "turn_logs": turn_logs,
        "world_snapshots": {
            "initial_tiles": initial_tiles,
            "final_tiles": serialize_tiles(world),
        },
    }

    if output_path is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_model_name = wrapper.model_name.replace("/", "_")
        safe_provider = model_binding.provider_id.replace("/", "_")
        output = artifact_dirs["logs"] / f"run_seed{seed}_{safe_provider}_{safe_model_name}_{timestamp}.json"
    else:
        output = Path(output_path)
        if not output.is_absolute():
            output = project_root / output

    output.parent.mkdir(parents=True, exist_ok=True)
    run_summary["log_path"] = str(output)
    analysis_output = output.with_name(f"{output.stem}_analysis.json")
    run_summary["analysis_path"] = str(analysis_output)

    analysis_payload = {
        "version": __version__,
        "protocol_version": protocol_version,
        "run_log_path": str(output),
        "run_analysis": analysis["run_analysis"],
    }

    with output.open("w", encoding="utf-8") as handle:
        json.dump(run_log, handle, ensure_ascii=True, indent=2, sort_keys=True)

    with analysis_output.open("w", encoding="utf-8") as handle:
        json.dump(analysis_payload, handle, ensure_ascii=True, indent=2, sort_keys=True)

    _emit_progress(
        progress_callback,
        {
            "event": "run_completed",
            "summary": run_summary,
        },
    )

    return run_log
