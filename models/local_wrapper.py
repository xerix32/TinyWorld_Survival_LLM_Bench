"""Placeholder local-model wrapper for future integration."""

from __future__ import annotations

from typing import Any, Mapping

from models.base import BaseModelWrapper, ModelResponse, RenderedPrompts


class LocalWrapper(BaseModelWrapper):
    def __init__(self, model_name: str = "local_placeholder") -> None:
        super().__init__(model_name=model_name)

    def generate(self, prompts: RenderedPrompts, metadata: Mapping[str, Any]) -> ModelResponse:
        del prompts, metadata
        raise NotImplementedError("Local provider integration is not implemented in v0.1")
