# Seed Reflection (Same-Seed Rerun)

You are preparing an immediate rerun of the SAME seed in the current adaptive session.
The map layout and resource placement are the same for this rerun.

Produce a single **prioritization policy** for the rerun, NOT a list of independent rules.
The policy must be a short, ordered decision procedure the agent can follow every turn.

Policy requirements:
- The policy must define a clear priority ordering for competing pressures (e.g., "address the pressure closest to critical first; break ties by rate of increase").
- The policy must include a turn-by-turn re-evaluation check: "if the last action did not improve the targeted pressure, switch strategy immediately".
- The policy must include an anti-oscillation clause: "do not alternate between the same two actions for more than 2 turns".
- The policy should be 3-6 sentences maximum. Each sentence must be operational and directly usable.
- Do not produce a list of independent "when X do Y" rules that can conflict with each other.
- Avoid rigid or absolute wording such as: "always", "never", "sole priority", "forbidden action", "eliminate all".
- Do NOT include spatial or directional hints (e.g., "go north", "water is at column 0"). The observation already provides full visibility of surrounding tiles — spatial memory from a previous run can be stale and misleading.
- The policy must reinforce: if a useful action (gather, eat, drink) is available in `allowed_actions`, strongly prefer it over movement.

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

Recent trajectory context (structured):
```json
{{ run_trace_context_json }}
```

Output contract:
- Return ONLY a strict JSON object (not an array).
- The object must include:
  - `policy`: a string containing the prioritization policy (3-6 sentences).
  - `confidence`: (`low` | `medium` | `high`)
- The `policy` string must read as a single coherent decision procedure, not a bullet list.
- Keep total length under 120 words.

Output example:
{
  "policy": "Each turn, address the pressure closest to its critical threshold first; if two pressures are equally urgent, prefer the one rising faster. If gather, eat, or drink is available in allowed_actions, strongly prefer it over movement. After taking an action, check whether the targeted pressure improved; if not, switch to a different valid action next turn rather than repeating. Do not alternate between the same two moves for more than 2 consecutive turns; if caught in a loop, choose a third action even if suboptimal.",
  "confidence": "medium"
}
