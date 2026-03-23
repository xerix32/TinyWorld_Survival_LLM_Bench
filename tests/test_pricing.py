from __future__ import annotations

from bench.pricing import estimate_cost_usd, load_pricing_config, resolve_model_pricing


def test_local_provider_pricing_is_explicit_zero() -> None:
    pricing_cfg = load_pricing_config("configs/pricing.yaml")
    pricing = resolve_model_pricing(
        pricing_cfg=pricing_cfg,
        provider_id="local_lmstudio",
        model="openai/gpt-oss-20b",
    )

    assert pricing is not None
    assert pricing.input_per_million_usd == 0.0
    assert pricing.output_per_million_usd == 0.0


def test_unknown_model_pricing_is_none() -> None:
    pricing_cfg = load_pricing_config("configs/pricing.yaml")
    pricing = resolve_model_pricing(
        pricing_cfg=pricing_cfg,
        provider_id="vercel_gateway",
        model="openai/gpt-9999-nonexistent",
    )
    assert pricing is None


def test_cost_estimation_from_prompt_completion_tokens() -> None:
    pricing_cfg = load_pricing_config("configs/pricing.yaml")
    pricing = resolve_model_pricing(
        pricing_cfg=pricing_cfg,
        provider_id="vercel_gateway",
        model="openai/gpt-4o",
    )
    assert pricing is not None

    estimated = estimate_cost_usd(
        pricing=pricing,
        prompt_tokens=10_000,
        completion_tokens=5_000,
        cache_read_tokens=2_000,
    )
    assert estimated is not None
    assert round(estimated, 6) == 0.0775
