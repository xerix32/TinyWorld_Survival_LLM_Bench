# Seed Reflection (Same-Seed Rerun)

You are preparing an immediate rerun of the SAME seed in the current adaptive session.
The map layout and resource placement are the same for this rerun.

Extract 3-5 concise lessons that can improve the immediate same-seed rerun.
Prefer conditional decision rules, not long recaps.
Do not output coordinates.
Use lessons as soft guidance, not rigid commands.

Lens requirements (generic, not game-specific):
- At least 1 lesson about priority selection.
- At least 1 lesson about recovery/stabilization under pressure.
- At least 1 lesson about avoiding overfocus or repeated low-value actions.
- At least 1 lesson must explicitly prevent tunnel vision (one pressure improved while another worsens).
- At least 1 lesson must explicitly require turn-by-turn re-evaluation if recent actions are not improving the targeted pressure.

Current session lessons:
{% if existing_lessons %}
{% for lesson in existing_lessons %}
- {{ lesson.text }}
{% endfor %}
{% else %}
- none
{% endif %}

Run summary (structured):
```json
{{ run_summary_json }}
```

Run analysis (structured):
```json
{{ run_analysis_json }}
```

Output contract:
- Return ONLY a strict JSON array of objects.
- Return between 3 and 5 lessons.
- Each lesson object must include:
  - `rule`
  - `trigger`
  - `risk_if_overapplied` (must include an explicit "Do not apply when ..." boundary)
  - `confidence` (`low` | `medium` | `high`)
- Avoid rigid or absolute wording such as: "always", "never", "sole priority", "forbidden action", "eliminate all".

Output example:
[
  {
    "rule": "Prioritize a nearby critical resource before exploratory movement.",
    "trigger": "a survival pressure indicator is rising and a useful resource is reachable",
    "risk_if_overapplied": "Do not apply when another pressure is worsening faster than the targeted one; this can cause imbalance.",
    "confidence": "medium"
  },
  {
    "rule": "Switch to recovery actions before pressure reaches critical levels, then re-evaluate every turn.",
    "trigger": "the same pressure signal appears for consecutive turns and recent actions are not improving it",
    "risk_if_overapplied": "Do not apply when the targeted pressure is already improving; this may over-react and reduce efficiency.",
    "confidence": "high"
  },
  {
    "rule": "Break repeated low-yield loops by forcing a useful action check.",
    "trigger": "several turns pass with movement but no useful gain",
    "risk_if_overapplied": "Do not apply when exploration is still yielding useful resources; rigid use can miss opportunities.",
    "confidence": "medium"
  }
]
