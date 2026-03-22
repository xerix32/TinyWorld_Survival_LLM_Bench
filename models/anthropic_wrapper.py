"""Placeholder Anthropic wrapper for future integration."""

from __future__ import annotations

from typing import Any, Mapping

from models.base import BaseModelWrapper, ModelResponse, RenderedPrompts


class AnthropicWrapper(BaseModelWrapper):
    def __init__(self, model_name: str = "anthropic_placeholder") -> None:
        super().__init__(model_name=model_name)

    def generate(self, prompts: RenderedPrompts, metadata: Mapping[str, Any]) -> ModelResponse:
        del prompts, metadata
        raise NotImplementedError("Anthropic provider integration is not implemented in v0.1")
