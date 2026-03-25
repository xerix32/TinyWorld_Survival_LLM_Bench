from __future__ import annotations

import json

from memory.filter import filter_lessons
from memory.reflection import parse_reflection_lessons
from memory.session import merge_lessons


def test_parse_reflection_lessons_accepts_strict_json_array() -> None:
    raw = '["Prioritize water early.","Avoid repeated low-yield movement.","Collect adjacent critical resources before resting."]'
    lessons, error = parse_reflection_lessons(raw)
    assert error is None
    assert lessons == [
        "Prioritize water early.",
        "Avoid repeated low-yield movement.",
        "Collect adjacent critical resources before resting.",
    ]


def test_parse_reflection_lessons_accepts_structured_items() -> None:
    raw = """[
      {
        "rule": "Prioritize nearby critical resources before low-value movement.",
        "trigger": "pressure is rising and a useful resource is reachable",
        "risk_if_overapplied": "can overfocus and reduce adaptability",
        "confidence": "high"
      },
      {
        "rule": "Switch to recovery actions before critical thresholds.",
        "trigger": "risk indicators remain elevated across turns",
        "risk_if_overapplied": "can overreact and reduce long-term gains",
        "confidence": "medium"
      },
      {
        "rule": "Interrupt repeated low-yield loops with a utility check.",
        "trigger": "several turns pass without useful gains",
        "risk_if_overapplied": "can prematurely abandon productive exploration",
        "confidence": "medium"
      }
    ]"""
    lessons, error = parse_reflection_lessons(raw)
    assert error is None
    assert len(lessons) == 3
    assert lessons[0].startswith("When pressure is rising and a useful resource is reachable")
    assert "Overapply risk:" in lessons[0]
    assert "Confidence: high." in lessons[0]


def test_parse_reflection_lessons_avoids_double_when_prefix() -> None:
    raw = """[
      {
        "rule": "When water is visible early, prioritize gathering it before other actions.",
        "trigger": "when water is visible within the first few turns",
        "risk_if_overapplied": "may neglect other essential resources",
        "confidence": "high"
      },
      {
        "rule": "Switch to recovery actions before critical thresholds.",
        "trigger": "risk indicators remain elevated across turns",
        "risk_if_overapplied": "can overreact and reduce long-term gains",
        "confidence": "medium"
      },
      {
        "rule": "Interrupt repeated low-yield loops with a utility check.",
        "trigger": "several turns pass without useful gains",
        "risk_if_overapplied": "can prematurely abandon productive exploration",
        "confidence": "medium"
      }
    ]"""
    lessons, error = parse_reflection_lessons(raw)
    assert error is None
    assert len(lessons) == 3
    assert "When when" not in lessons[0]
    assert lessons[0].startswith(
        "When water is visible early, prioritize gathering it before other actions."
    )
    assert ", If " not in lessons[1]


def test_parse_reflection_lessons_accepts_json_fenced_block() -> None:
    raw = """```json
["Prioritize water early.","Avoid repeated low-yield movement.","Collect adjacent critical resources before resting."]
```"""
    lessons, error = parse_reflection_lessons(raw)
    assert error is None
    assert lessons == [
        "Prioritize water early.",
        "Avoid repeated low-yield movement.",
        "Collect adjacent critical resources before resting.",
    ]


def test_parse_reflection_lessons_rejects_non_json() -> None:
    lessons, error = parse_reflection_lessons("move north")
    assert lessons == []
    assert error == "invalid_json"


def test_parse_reflection_lessons_rejects_text_outside_fence() -> None:
    raw = """Here are lessons:
```json
["A","B","C"]
```"""
    lessons, error = parse_reflection_lessons(raw)
    assert lessons == []
    assert error == "invalid_json"


def test_parse_reflection_lessons_rejects_wrong_cardinality() -> None:
    raw = '["One lesson only"]'
    lessons, error = parse_reflection_lessons(raw)
    assert lessons == []
    assert error == "too_few_lessons"


def test_parse_seed_reflection_policy_accepts_object_format() -> None:
    from memory.reflection import parse_seed_reflection_policy

    raw = json.dumps({
        "policy": "Address the pressure closest to critical first. Re-evaluate each turn.",
        "hints": ["Water is west.", "Food is north."],
        "confidence": "high",
    })
    lessons, error = parse_seed_reflection_policy(raw)
    assert error is None
    assert len(lessons) == 3
    assert "closest to critical" in lessons[0]
    assert "Water is west." in lessons[1]


def test_parse_seed_reflection_policy_fallback_to_array() -> None:
    from memory.reflection import parse_seed_reflection_policy

    raw = json.dumps([
        {"rule": "Do X", "trigger": "when Y", "risk_if_overapplied": "Z", "confidence": "high"},
        {"rule": "Do A", "trigger": "when B", "risk_if_overapplied": "C", "confidence": "medium"},
        {"rule": "Do D", "trigger": "when E", "risk_if_overapplied": "F", "confidence": "low"},
    ])
    lessons, error = parse_seed_reflection_policy(raw)
    assert error is None
    assert len(lessons) == 3


def test_parse_seed_reflection_policy_rejects_missing_policy() -> None:
    from memory.reflection import parse_seed_reflection_policy

    raw = json.dumps({"hints": ["something"]})
    lessons, error = parse_seed_reflection_policy(raw)
    assert lessons == []
    assert error == "missing_policy"


def test_filter_lessons_is_pass_through_for_intra_seed_stage() -> None:
    lessons = ["A", "B", "C"]
    assert filter_lessons(lessons, context={"stage": "seed_reflection"}) == lessons


def test_filter_lessons_applies_hygiene_only_for_cross_seed_stage() -> None:
    lessons = [
        "General conditional strategy.",
        "Tile (2,3) had food and should have been collected sooner.",
        "On this map, going east first worked well.",
    ]
    assert filter_lessons(lessons, context={"stage": "cross_seed_refinement"}) == [
        "General conditional strategy.",
    ]


def test_merge_lessons_deduplicates_deterministically() -> None:
    merged = merge_lessons(
        ["Prioritize water early.", "Avoid loops."],
        ["avoid loops.", "Collect adjacent resources first."],
    )
    assert merged == [
        "Prioritize water early.",
        "Avoid loops.",
        "Collect adjacent resources first.",
    ]
