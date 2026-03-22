"""Jinja2-based prompt rendering."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from renderers.json_renderer import to_canonical_json


PROMPT_TEMPLATE_FILES = [
    "system/agent_core.md",
    "user/turn_observation.md",
    "user/turn_observation_with_memory.md",
    "partials/engine_contract.md",
    "partials/rules.md",
    "partials/action_reference.md",
    "partials/output_contract.md",
    "partials/memory_block.md",
]


class PromptLoader:
    def __init__(self, prompts_dir: str | Path) -> None:
        prompts_path = Path(prompts_dir)
        self._prompts_path = prompts_path.resolve()
        self._env = Environment(
            loader=FileSystemLoader(str(self._prompts_path)),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._template_hashes = self._compute_template_hashes()
        self._prompt_set_sha256 = self._compute_prompt_set_sha256()

    def render_template(self, template_name: str, context: dict[str, Any]) -> str:
        template = self._env.get_template(template_name)
        return template.render(**context).strip()

    def _compute_template_hashes(self) -> dict[str, str | None]:
        hashes: dict[str, str | None] = {}
        for template_name in PROMPT_TEMPLATE_FILES:
            template_path = self._prompts_path / template_name
            if not template_path.exists():
                hashes[template_name] = None
                continue
            content = template_path.read_text(encoding="utf-8")
            hashes[template_name] = sha256(content.encode("utf-8")).hexdigest()
        return hashes

    def _compute_prompt_set_sha256(self) -> str:
        lines: list[str] = []
        for template_name in sorted(self._template_hashes):
            template_hash = self._template_hashes[template_name] or "MISSING"
            lines.append(f"{template_name}:{template_hash}")
        payload = "\n".join(lines)
        return sha256(payload.encode("utf-8")).hexdigest()

    def get_prompt_metadata(self) -> dict[str, Any]:
        return {
            "prompts_dir": str(self._prompts_path),
            "prompt_set_sha256": self._prompt_set_sha256,
            "templates": dict(self._template_hashes),
            "active_templates": {
                "system": "system/agent_core.md",
                "turn": "user/turn_observation.md",
                "turn_with_memory": "user/turn_observation_with_memory.md",
            },
        }

    def render_system_prompt(self, context: dict[str, Any] | None = None) -> str:
        return self.render_template("system/agent_core.md", context or {})

    def render_turn_prompt(
        self,
        observation: dict[str, Any],
        include_memory: bool = False,
        memory_summary: str = "No memory available in v0.1.",
    ) -> str:
        template_name = "user/turn_observation_with_memory.md" if include_memory else "user/turn_observation.md"
        context = {
            "observation": observation,
            "observation_json": to_canonical_json(observation),
            "memory_summary": memory_summary,
        }
        return self.render_template(template_name, context)
