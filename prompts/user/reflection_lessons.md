# Adaptive Reflection Task

You are writing lessons for a future run.

The next run may use a different seed and may produce a different map layout and resource placement.
Extract only general decision-making lessons that transfer across runs.
Do not include any seed-specific, map-specific, positional, or episode-specific facts.
A lesson is not a recap of what happened in this run.
A lesson is a general strategy or caution that may still be useful when the next run has a different seed.

Current memory lessons (already known):
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

Valid lesson examples:
- "Prioritize reachable water earlier when thirst is elevated."
- "Do not rest when a needed resource is immediately adjacent."
- "Reduce repeated movement without collecting nearby useful resources."

Invalid lesson examples:
- "Water was south in this run, so check south first."
- "Going east early was bad on this map."
- "Tile (2,3) had food and should have been collected sooner."

Output contract:
- Return ONLY a strict JSON array of strings.
- Return between 3 and 5 lessons.
- Each lesson must be seed-agnostic and transferable.

Output example:
["Prioritize reachable water when thirst pressure rises.","Avoid repeated low-yield movement loops.","Collect adjacent critical resources before resting."]
