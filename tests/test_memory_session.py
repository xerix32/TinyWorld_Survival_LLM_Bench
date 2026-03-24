from __future__ import annotations

from memory.session import build_prompt_memory_lessons


def test_build_prompt_memory_lessons_prioritizes_current_and_dedupes_exact() -> None:
    payload = build_prompt_memory_lessons(
        session_lessons=["Avoid loops.", "Prioritize water."],
        current_seed_lessons=["avoid loops.", "Collect food first."],
    )

    assert payload["current_seed_lessons"] == ["avoid loops.", "Collect food first."]
    assert payload["session_lessons"] == []
    assert payload["all_lessons"] == ["avoid loops.", "Collect food first."]
    assert payload["stats"]["session_removed_exact_count"] == 0
    assert payload["stats"]["session_skipped_due_to_current_seed_count"] == 2
    assert payload["stats"]["final_total_count"] == 2


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


def test_build_prompt_memory_lessons_applies_cap_to_current_only_when_present() -> None:
    payload = build_prompt_memory_lessons(
        session_lessons=["S1", "S2", "S3"],
        current_seed_lessons=["C1", "C2", "C3", "C4"],
        max_items=3,
    )

    assert payload["current_seed_lessons"] == ["C1", "C2", "C3"]
    assert payload["session_lessons"] == []
    assert payload["all_lessons"] == ["C1", "C2", "C3"]
    assert payload["stats"]["removed_by_cap_count"] == 1
    assert payload["stats"]["session_skipped_due_to_current_seed_count"] == 3
    assert payload["stats"]["final_total_count"] == 3


def test_build_prompt_memory_lessons_applies_topic_diversity_cap() -> None:
    payload = build_prompt_memory_lessons(
        session_lessons=[
            "Treat thirst warnings as urgent and seek water.",
            "Begin moving toward water as soon as thirst rises.",
            "If dehydration risk increases, gather water before extra exploration.",
            "When food appears, gather food promptly.",
        ],
        current_seed_lessons=[],
        max_items=6,
        max_lessons_per_topic=1,
    )

    assert payload["all_lessons"] == [
        "Treat thirst warnings as urgent and seek water.",
        "When food appears, gather food promptly.",
    ]
    assert payload["stats"]["session_removed_topic_count"] == 2
    assert payload["stats"]["max_lessons_per_topic"] == 1


def test_build_prompt_memory_lessons_topic_classifier_prefers_semantic_cluster() -> None:
    payload = build_prompt_memory_lessons(
        session_lessons=[
            "When dehydration pressure rises, choose a valid action and gather water promptly.",
        ],
        current_seed_lessons=[],
    )

    assert payload["all_lessons"] == [
        "When dehydration pressure rises, choose a valid action and gather water promptly.",
    ]
    assert payload["stats"]["selected_topic_counts"] == {"water_pressure": 1}


def test_build_prompt_memory_lessons_enforces_multi_topic_diversity_when_available() -> None:
    payload = build_prompt_memory_lessons(
        session_lessons=[
            "When thirst rises, gather water immediately.",
            "When dehydration pressure rises, drink as soon as possible.",
            "When hunger rises, gather food before extra movement.",
        ],
        current_seed_lessons=[],
        max_items=2,
        max_lessons_per_topic=3,
    )

    assert payload["all_lessons"] == [
        "When thirst rises, gather water immediately.",
        "When hunger rises, gather food before extra movement.",
    ]
    assert payload["stats"]["diversity_override_applied"] is True
    assert payload["stats"]["selected_topic_counts"] == {"food_pressure": 1, "water_pressure": 1}
