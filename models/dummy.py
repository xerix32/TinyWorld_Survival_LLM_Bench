"""Deterministic random baseline model wrapper."""

from __future__ import annotations

import random
from typing import Any, Mapping

from models.base import BaseModelWrapper, ModelResponse, RenderedPrompts


class DummyRandomWrapper(BaseModelWrapper):
    def __init__(self, seed: int, model_name: str = "dummy_random_v0_1") -> None:
        super().__init__(model_name=model_name)
        self._rng = random.Random(seed)

    def generate(self, prompts: RenderedPrompts, metadata: Mapping[str, Any]) -> ModelResponse:
        del prompts

        allowed_actions = list(metadata.get("allowed_actions", []))
        if not allowed_actions:
            return ModelResponse(raw_text="wait")

        return ModelResponse(raw_text=self._rng.choice(allowed_actions))
