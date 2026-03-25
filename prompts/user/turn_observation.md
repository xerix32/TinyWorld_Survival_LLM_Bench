# Turn Observation

Turn: {{ observation.turn }}
Agent ID: {{ observation.agent_id }}

Current structured observation:
```json
{{ observation_json }}
```

{% if observation.get("warnings") %}
WARNINGS:
{% for w in observation.warnings %}
- {{ w }}
{% endfor %}

{% endif %}
Allowed actions for this turn (exact strings):
{% for action in observation.allowed_actions %}
- {{ action }}
{% endfor %}
