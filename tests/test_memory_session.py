from __future__ import annotations

from memory.session import build_prompt_memory_lessons


def test_build_prompt_memory_lessons_prioritizes_current_and_dedupes_exact() -> None:
    payload = build_prompt_memory_lessons(
        session_lessons=["Avoid loops.", "Prioritize water."],
        current_seed_lessons=["avoid loops.", "Collect food first."],
    )

    assert payload["current_seed_lessons"] == ["avoid loops.", "Collect food first."]
    assert payload["session_lessons"] == ["Prioritize water."]
    assert payload["all_lessons"] == [
        "avoid loops.",
        "Collect food first.",
        "Prioritize water.",
    ]
    assert payload["stats"]["session_removed_exact_count"] == 1
    assert payload["stats"]["final_total_count"] == 3


def test_build_prompt_memory_lessons_dedupes_near_duplicates() -> None:
    payload = build_prompt_memory_lessons(
        session_lessons=[
            "When thirst rises, gather water immediately.",
            "Gather water immediately when thirst rises.",
        ],
        current_seed_lessons=[],
    )

    assert payload["session_lessons"] == ["When thirst rises, gather water immediately."]
    assert payload["stats"]["session_removed_near_count"] == 1
    assert payload["stats"]["final_total_count"] == 1


def test_build_prompt_memory_lessons_applies_cap_after_priority() -> None:
    payload = build_prompt_memory_lessons(
        session_lessons=["S1", "S2", "S3"],
        current_seed_lessons=["C1", "C2", "C3", "C4"],
        max_items=5,
    )

    assert payload["current_seed_lessons"] == ["C1", "C2", "C3", "C4"]
    assert payload["session_lessons"] == ["S1"]
    assert payload["all_lessons"] == ["C1", "C2", "C3", "C4", "S1"]
    assert payload["stats"]["removed_by_cap_count"] == 2
    assert payload["stats"]["final_total_count"] == 5


def test_build_prompt_memory_lessons_applies_topic_diversity_cap() -> None:
    payload = build_prompt_memory_lessons(
        session_lessons=[
            "When water pressure rises, gather water quickly.",
            "When water is visible, gather water first.",
            "When water is low, seek water before movement.",
            "When food appears, gather food promptly.",
        ],
        current_seed_lessons=[],
        max_items=6,
        max_lessons_per_topic=2,
    )

    assert payload["all_lessons"] == [
        "When water pressure rises, gather water quickly.",
        "When water is visible, gather water first.",
        "When food appears, gather food promptly.",
    ]
    assert payload["stats"]["session_removed_topic_count"] == 1
