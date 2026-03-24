from __future__ import annotations

from engine.prompt_loader import PromptLoader
from engine.prompt_loader import PROMPT_TEMPLATE_FILES


def _sample_observation() -> dict:
    return {
        "protocol_version": "AIB-0.1.1",
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
        "allowed_actions": ["move north", "wait"],
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
    assert "wait" in rendered


def test_prompt_loader_renders_memory_template() -> None:
    loader = PromptLoader("prompts")
    rendered = loader.render_turn_prompt(
        _sample_observation(),
        include_memory=True,
        session_lessons=[],
        current_seed_lessons=[],
    )

    assert "Session Memory (Adaptive Mode)" in rendered
    assert "No session lessons yet." in rendered
    assert "No current-seed lessons yet." in rendered


def test_prompt_loader_renders_memory_lessons_list() -> None:
    loader = PromptLoader("prompts")
    rendered = loader.render_turn_prompt(
        _sample_observation(),
        include_memory=True,
        session_lessons=[{"text": "Prioritize water when thirst rises."}],
        current_seed_lessons=[{"text": "Avoid repeated low-yield movement."}],
    )

    assert "Prioritize water when thirst rises." in rendered
    assert "Avoid repeated low-yield movement." in rendered
    assert "Session lessons (from earlier seeds in this adaptive session):" in rendered
    assert "Current-seed lessons (from the previous attempt on this same seed):" in rendered


def test_prompt_loader_renders_reflection_prompt() -> None:
    loader = PromptLoader("prompts")
    seed_rendered = loader.render_seed_reflection_prompt(
        run_summary={"final_score": 10, "seed": 7},
        run_analysis={"classification": {"primary_failure_archetype": "dehydration"}},
        existing_lessons=[{"text": "Collect adjacent critical resources before resting."}],
    )
    cross_rendered = loader.render_cross_seed_refinement_prompt(
        initial_run_summary={"final_score": 10, "seed": 7},
        initial_run_analysis={"classification": {"primary_failure_archetype": "dehydration"}},
        rerun_summary={"final_score": 15, "seed": 7},
        rerun_analysis={"classification": {"primary_failure_archetype": "late_recovery_failure"}},
        existing_lessons=[{"text": "Collect adjacent critical resources before resting."}],
        seed_lessons=[{"text": "Gather adjacent water before low-value movement."}],
    )

    assert "SAME seed" in seed_rendered
    assert "map-specific hints are allowed" in seed_rendered
    assert "strict JSON array of objects" in seed_rendered
    assert "risk_if_overapplied" in seed_rendered
    assert '"seed": 7' in seed_rendered
    assert "Collect adjacent critical resources before resting." in seed_rendered

    assert "transferable, seed-agnostic lessons" in cross_rendered
    assert "Tile (2,3) had food and should have been collected sooner." in cross_rendered
    assert "Outcome deltas (neutral numeric feedback):" in cross_rendered
    assert "strict JSON array of objects" in cross_rendered
    assert '"seed": 7' in cross_rendered
    assert "Gather adjacent water before low-value movement." in cross_rendered

    # Backward-compatible method remains available.
    rendered = loader.render_reflection_prompt(
        run_summary={"final_score": 10, "seed": 7},
        run_analysis={"classification": {"primary_failure_archetype": "dehydration"}},
        existing_lessons=[{"text": "Collect adjacent critical resources before resting."}],
    )

    assert "strict JSON array of strings" in rendered
    assert "Tile (2,3) had food and should have been collected sooner." in rendered
    assert '"seed": 7' in rendered
    assert "Collect adjacent critical resources before resting." in rendered


def test_prompt_loader_exposes_prompt_manifest_metadata() -> None:
    loader = PromptLoader("prompts")
    metadata = loader.get_prompt_metadata()

    assert isinstance(metadata["prompts_dir"], str)
    assert len(metadata["prompt_set_sha256"]) == 64
    for template_name in PROMPT_TEMPLATE_FILES:
        assert template_name in metadata["templates"]
        template_hash = metadata["templates"][template_name]
        assert template_hash is None or len(template_hash) == 64
