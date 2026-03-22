"""Base model wrapper interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class RenderedPrompts:
    system_prompt: str
    user_prompt: str


@dataclass
class ModelResponse:
    raw_text: str
    tokens_used: int | None = None
    estimated_cost: float | None = None
    latency_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseModelWrapper(ABC):
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    @abstractmethod
    def generate(self, prompts: RenderedPrompts, metadata: Mapping[str, Any]) -> ModelResponse:
        raise NotImplementedError
