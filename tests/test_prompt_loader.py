from __future__ import annotations

from engine.prompt_loader import PromptLoader
from engine.prompt_loader import PROMPT_TEMPLATE_FILES


def _sample_observation() -> dict:
    return {
        "protocol_version": "AIB-0.1",
        "turn": 1,
        "agent_id": "agent_1",
        "alive": True,
        "position": {"x": 2, "y": 3},
        "energy": 80,
        "hunger": 20,
        "thirst": 20,
        "inventory": {"wood": 0, "stone": 0, "food": 0, "water": 0},
        "visible_tiles": [
            {"x": 1, "y": 2, "type": "empty"},
            {"x": 2, "y": 2, "type": "tree"},
        ],
        "score": 0,
        "allowed_actions": ["move north", "inspect"],
    }


def test_prompt_loader_renders_system_prompt_with_required_sections() -> None:
    loader = PromptLoader("prompts")
    rendered = loader.render_system_prompt({})

    assert "Engine Contract" in rendered
    assert "Action Reference" in rendered
    assert "Output Contract" in rendered


def test_prompt_loader_renders_turn_prompt_with_turn_data() -> None:
    loader = PromptLoader("prompts")
    rendered = loader.render_turn_prompt(_sample_observation(), include_memory=False)

    assert "Turn: 1" in rendered
    assert "Agent ID: agent_1" in rendered
    assert "move north" in rendered
    assert "inspect" in rendered


def test_prompt_loader_renders_memory_template() -> None:
    loader = PromptLoader("prompts")
    rendered = loader.render_turn_prompt(
        _sample_observation(),
        include_memory=True,
        memory_summary="Memory is disabled in v0.1.",
    )

    assert "Memory" in rendered
    assert "Memory is disabled in v0.1." in rendered


def test_prompt_loader_exposes_prompt_manifest_metadata() -> None:
    loader = PromptLoader("prompts")
    metadata = loader.get_prompt_metadata()

    assert isinstance(metadata["prompts_dir"], str)
    assert len(metadata["prompt_set_sha256"]) == 64
    for template_name in PROMPT_TEMPLATE_FILES:
        assert template_name in metadata["templates"]
        template_hash = metadata["templates"][template_name]
        assert template_hash is None or len(template_hash) == 64
