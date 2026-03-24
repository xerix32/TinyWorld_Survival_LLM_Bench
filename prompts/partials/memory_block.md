## Session Memory (Adaptive Mode)

Session lessons (from earlier seeds in this adaptive session):
{% if session_lessons %}
{% for lesson in session_lessons %}
- {{ lesson.text }}
{% endfor %}
{% else %}
- No session lessons yet.
{% endif %}

Current-seed lessons (from the previous attempt on this same seed):
{% if current_seed_lessons %}
{% for lesson in current_seed_lessons %}
- {{ lesson.text }}
{% endfor %}
{% else %}
- No current-seed lessons yet.
{% endif %}

Decision policy for this turn:
- The current observation and `allowed_actions` are the source of truth.
- Session/current-seed lessons are soft guidance, not mandatory rules.
- If a lesson conflicts with the current observation or with `allowed_actions`, ignore that lesson.
- Avoid single-metric tunnel vision: do not keep optimizing one pressure while another pressure is worsening.
- Re-evaluate each turn: if the last two turns did not improve the targeted pressure, switch strategy.
