"""Central deterministic failure-archetype definitions and thresholds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_CONFIG_PATH = Path(__file__).resolve().parent / "failure_archetypes.json"
_CONFIG_CACHE: dict[str, Any] | None = None


def _load_config() -> dict[str, Any]:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        with _CONFIG_PATH.open("r", encoding="utf-8") as handle:
            _CONFIG_CACHE = json.load(handle)
    return _CONFIG_CACHE


def get_failure_config() -> dict[str, Any]:
    return _load_config()


def get_thresholds() -> dict[str, float]:
    raw = get_failure_config().get("thresholds", {})
    return {str(key): float(value) for key, value in raw.items()}


def get_archetype_labels() -> dict[str, str]:
    raw = get_failure_config().get("archetypes", [])
    labels: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip()
        label = str(item.get("label", "")).strip()
        if code and label:
            labels[code] = label
    return labels


def label_for(code: str) -> str:
    labels = get_archetype_labels()
    return labels.get(code, code.replace("_", " "))

