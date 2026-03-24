{% include "partials/memory_block.md" %}

{% include "user/turn_observation.md" %}

## Hard Action Gate (turn-critical)
- `allowed_actions` is the hard constraint for this turn.
- Return exactly one action string from `allowed_actions`.
- If a desired strategy/action is not present in `allowed_actions`, do not output it.
- If memory suggests something not present in `allowed_actions`, ignore that suggestion.
- Never repeat an action that is not present in `allowed_actions`.
- If a resource action is unavailable (for example `drink`), choose a valid action that helps progress toward that goal.
- Before replying, silently verify the exact output string appears verbatim in `allowed_actions`.
