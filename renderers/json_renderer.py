"""Deterministic JSON rendering helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def to_canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2)


def prompt_pair_hash(system_prompt: str, user_prompt: str) -> str:
    digest = hashlib.sha256()
    digest.update(system_prompt.encode("utf-8"))
    digest.update(b"\n\n")
    digest.update(user_prompt.encode("utf-8"))
    return digest.hexdigest()
