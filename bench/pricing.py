"""Deterministic token-pricing utilities for estimated-cost fallback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


TOKENS_PER_MILLION = 1_000_000.0


@dataclass(frozen=True)
class ModelPricing:
    provider_id: str
    model: str
    input_per_million_usd: float
    output_per_million_usd: float
    cache_read_per_million_usd: float | None = None
    cache_write_per_million_usd: float | None = None
    fallback_input_ratio_from_total_tokens: float | None = None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_pricing_config(path: str | Path) -> dict[str, Any]:
    resolved = Path(path)
    with resolved.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"pricing YAML root must be a mapping: {resolved}")
    return data


def resolve_model_pricing(
    *,
    pricing_cfg: dict[str, Any] | None,
    provider_id: str,
    model: str,
) -> ModelPricing | None:
    if not pricing_cfg:
        return None

    providers = pricing_cfg.get("providers")
    if not isinstance(providers, dict):
        return None

    provider_cfg = providers.get(provider_id)
    if not isinstance(provider_cfg, dict):
        return None

    model_table = provider_cfg.get("models")
    model_cfg: dict[str, Any] | None = None
    if isinstance(model_table, dict):
        candidate = model_table.get(model)
        if isinstance(candidate, dict):
            model_cfg = candidate

    if model_cfg is None:
        candidate_default = provider_cfg.get("default")
        if isinstance(candidate_default, dict):
            model_cfg = candidate_default

    if model_cfg is None:
        return None

    input_rate = _to_float(model_cfg.get("input_per_million_usd"))
    output_rate = _to_float(model_cfg.get("output_per_million_usd"))
    if input_rate is None or output_rate is None:
        return None

    fallback_ratio = _to_float(model_cfg.get("fallback_input_ratio_from_total_tokens"))
    if fallback_ratio is None:
        provider_default = provider_cfg.get("default")
        if isinstance(provider_default, dict):
            fallback_ratio = _to_float(provider_default.get("fallback_input_ratio_from_total_tokens"))

    if fallback_ratio is not None:
        fallback_ratio = max(0.0, min(1.0, fallback_ratio))

    return ModelPricing(
        provider_id=provider_id,
        model=model,
        input_per_million_usd=input_rate,
        output_per_million_usd=output_rate,
        cache_read_per_million_usd=_to_float(model_cfg.get("cache_read_per_million_usd")),
        cache_write_per_million_usd=_to_float(model_cfg.get("cache_write_per_million_usd")),
        fallback_input_ratio_from_total_tokens=fallback_ratio,
    )


def estimate_cost_usd(
    *,
    pricing: ModelPricing | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cache_read_tokens: int | None = None,
    cache_write_tokens: int | None = None,
) -> float | None:
    if pricing is None:
        return None
    if prompt_tokens is None or completion_tokens is None:
        return None

    total_tok = prompt_tokens + completion_tokens
    if total_tok <= 0:
        return None

    # If the provider-reported breakdown looks implausible (input ratio < 80%)
    # and we have a fallback ratio, prefer the fallback to avoid cost inflation
    # from providers that misreport prompt/completion splits.
    actual_input_ratio = float(prompt_tokens) / float(total_tok)
    if (
        actual_input_ratio < 0.80
        and pricing.fallback_input_ratio_from_total_tokens is not None
    ):
        return estimate_cost_from_total_tokens(pricing=pricing, total_tokens=total_tok)

    input_cost = (float(prompt_tokens) / TOKENS_PER_MILLION) * pricing.input_per_million_usd
    output_cost = (float(completion_tokens) / TOKENS_PER_MILLION) * pricing.output_per_million_usd
    total_cost = input_cost + output_cost

    if cache_read_tokens is not None and pricing.cache_read_per_million_usd is not None:
        total_cost += (float(cache_read_tokens) / TOKENS_PER_MILLION) * pricing.cache_read_per_million_usd
    if cache_write_tokens is not None and pricing.cache_write_per_million_usd is not None:
        total_cost += (float(cache_write_tokens) / TOKENS_PER_MILLION) * pricing.cache_write_per_million_usd

    return total_cost


def estimate_cost_from_total_tokens(
    *,
    pricing: ModelPricing | None,
    total_tokens: int | None,
) -> float | None:
    if pricing is None or total_tokens is None:
        return None
    ratio = pricing.fallback_input_ratio_from_total_tokens
    if ratio is None:
        return None

    total = max(0.0, float(total_tokens))
    prompt_tokens = int(round(total * ratio))
    completion_tokens = max(0, int(round(total)) - prompt_tokens)
    return estimate_cost_usd(
        pricing=pricing,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
