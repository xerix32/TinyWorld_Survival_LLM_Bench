# Turn Observation

Turn: {{ observation.turn }}
Agent ID: {{ observation.agent_id }}

Current structured observation:
```json
{{ observation_json }}
```

Allowed actions for this turn (exact strings):
{% for action in observation.allowed_actions %}
- {{ action }}
{% endfor %}
