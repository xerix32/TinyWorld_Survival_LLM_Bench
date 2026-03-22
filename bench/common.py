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


DEFAULT_AGENT_ID = "agent_1"


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

    return OpenAIWrapper(
        model_name=str(model_name),
        api_base=str(api_base),
        api_key=api_key,
        temperature=float(profile_cfg.get("temperature", provider_cfg.get("temperature", 0.2))),
        max_tokens=int(profile_cfg.get("max_tokens", provider_cfg.get("max_tokens", 1024))),
        requests_per_minute=int(provider_cfg.get("requests_per_minute", 30)),
        max_retries=int(provider_cfg.get("max_retries", 3)),
        retry_base_seconds=float(provider_cfg.get("retry_base_seconds", 2.0)),
        retry_max_seconds=float(provider_cfg.get("retry_max_seconds", 20.0)),
        request_timeout_seconds=float(provider_cfg.get("request_timeout_seconds", 60.0)),
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


def _human_end_reason(end_reason: str, turns_played: int, max_turns: int) -> str:
    if end_reason == "agent_dead":
        return f"The agent died on turn {turns_played}."
    if end_reason == "max_turns_reached":
        return f"Reached the configured turn limit ({max_turns})."
    return f"Run ended with status: {end_reason}."


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

    run_max_turns = int(max_turns if max_turns is not None else benchmark_cfg["max_turns"])

    world = create_world(seed=seed, scenario_cfg=scenario, rules_cfg=rules_cfg, agent_id=DEFAULT_AGENT_ID)
    initial_tiles = serialize_tiles(world)
    prompt_loader = PromptLoader(prompts_dir)
    system_prompt = prompt_loader.render_system_prompt({})
    prompt_metadata = prompt_loader.get_prompt_metadata()
    system_prompt_sha256 = prompt_pair_hash(system_prompt, "")

    model_binding = create_model_wrapper(model_name=model_name, seed=seed, providers_cfg=providers_cfg)
    wrapper = model_binding.wrapper

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
    cost_sum = 0.0
    cost_seen = False
    latency_sum_ms = 0.0

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

        tokens_sum, tokens_seen = _optional_sum_update(tokens_sum, tokens_seen, model_response.tokens_used)
        cost_sum, cost_seen = _optional_sum_update(cost_sum, cost_seen, model_response.estimated_cost)

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
                    "tokens_used": model_response.tokens_used,
                    "estimated_cost": model_response.estimated_cost,
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

    run_summary = {
        "version": __version__,
        "bench_version": __version__,
        "engine_version": __version__,
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
        "tokens_used": int(tokens_sum) if tokens_seen else None,
        "latency_ms": round(latency_sum_ms, 3),
        "estimated_cost": round(cost_sum, 6) if cost_seen else None,
    }

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

    with output.open("w", encoding="utf-8") as handle:
        json.dump(run_log, handle, ensure_ascii=True, indent=2, sort_keys=True)

    _emit_progress(
        progress_callback,
        {
            "event": "run_completed",
            "summary": run_summary,
        },
    )

    return run_log
