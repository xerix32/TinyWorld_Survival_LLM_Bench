# Cross-Seed Refinement (Transferable Memory)

You are refining memory that will be reused on future seeds in this adaptive session.

Extract only transferable, seed-agnostic lessons.
Do not include map-specific, positional, coordinate-based, or episode-specific facts.
A lesson is a general strategy or caution that remains useful when the next seed changes.

You are producing the next compact session memory set (not a raw append list).
Return a synthesized set that balances:
- priority selection,
- recovery/stabilization,
- anti-overfocus behavior.
- Keep lessons as soft guidance, not rigid commands.

Existing session lessons:
{% if existing_lessons %}
{% for lesson in existing_lessons %}
- {{ lesson.text }}
{% endfor %}
{% else %}
- none
{% endif %}

Current seed lessons used in the rerun:
{% if seed_lessons %}
{% for lesson in seed_lessons %}
- {{ lesson.text }}
{% endfor %}
{% else %}
- none
{% endif %}

Initial attempt summary:
```json
{{ initial_run_summary_json }}
```

Initial attempt analysis:
```json
{{ initial_run_analysis_json }}
```

Adaptive rerun summary:
```json
{{ rerun_summary_json }}
```

Adaptive rerun analysis:
```json
{{ rerun_analysis_json }}
```

Outcome deltas (neutral numeric feedback):
```json
{{ adaptive_feedback_json }}
```

Valid lesson examples:
- "Prioritize reachable water earlier when thirst is elevated."
- "Do not rest when a needed resource is immediately adjacent."
- "Reduce repeated movement without collecting nearby useful resources."

Invalid lesson examples:
- "Water was south in this run, so check south first."
- "Going east early was bad on this map."
- "Tile (2,3) had food and should have been collected sooner."

Output contract:
- Return ONLY a strict JSON array of objects.
- Return between 3 and 5 lessons.
- Each lesson must be transferable and seed-agnostic.
- Each lesson object must include:
  - `rule`
  - `trigger`
  - `risk_if_overapplied` (must include an explicit "Do not apply when ..." boundary)
  - `confidence` (`low` | `medium` | `high`)
- Avoid rigid or absolute wording such as: "always", "never", "sole priority", "forbidden action", "eliminate all".
- Include at least one lesson that prevents tunnel vision across pressures.
- Include at least one lesson that requires turn-by-turn re-evaluation when recent actions are not improving the targeted pressure.

Output example:
[
  {
    "rule": "Prioritize reachable critical resources before low-value movement.",
    "trigger": "pressure indicators rise and a useful resource is available",
    "risk_if_overapplied": "Do not apply when another pressure is worsening faster; this can reduce adaptability.",
    "confidence": "high"
  },
  {
    "rule": "Use early recovery actions instead of waiting for critical thresholds, then re-check every turn.",
    "trigger": "pressure remains elevated across consecutive turns and recent actions did not improve it",
    "risk_if_overapplied": "Do not apply when the targeted pressure is already improving; this can cause premature recovery.",
    "confidence": "medium"
  },
  {
    "rule": "Interrupt repetitive low-yield action patterns with a utility check.",
    "trigger": "several turns pass without useful gains",
    "risk_if_overapplied": "Do not apply when useful gains are still present; this may over-penalize productive revisits.",
    "confidence": "medium"
  }
]
