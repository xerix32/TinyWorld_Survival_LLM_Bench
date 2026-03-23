from __future__ import annotations

import pytest

from bench.common import create_model_wrapper, load_yaml_file


def test_dummy_profile_resolves_from_provider_config() -> None:
    providers_cfg = load_yaml_file("configs/providers.yaml")

    binding = create_model_wrapper("dummy_v0_1", seed=7, providers_cfg=providers_cfg)

    assert binding.provider_id == "dummy_provider"
    assert binding.model_profile == "dummy_v0_1"
    assert binding.wrapper.model_name == "dummy_random_v0_1"


def test_legacy_dummy_alias_still_supported() -> None:
    binding = create_model_wrapper("dummy", seed=7, providers_cfg=None)

    assert binding.provider_id == "dummy_provider"
    assert binding.model_profile == "legacy_dummy"


def test_openai_profile_requires_key_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    providers_cfg = load_yaml_file("configs/providers.yaml")
    monkeypatch.delenv("VERCEL_AI_GATEWAY_API_KEY", raising=False)
    providers_cfg["providers"]["vercel_gateway"].pop("api_key", None)

    with pytest.raises(ValueError, match="missing API key"):
        create_model_wrapper("vercel_gpt_oss_120b", seed=7, providers_cfg=providers_cfg)


def test_local_profile_resolves_without_env_key() -> None:
    providers_cfg = load_yaml_file("configs/providers.yaml")

    binding = create_model_wrapper("local_qwen35_9b_mlx", seed=7, providers_cfg=providers_cfg)

    assert binding.provider_id == "local_lmstudio"
    assert binding.model_profile == "local_qwen35_9b_mlx"
    assert binding.wrapper.model_name == "qwen3.5-9b-mlx"
