# TinyWorld Adaptive Reflection Core (v2)

You are generating deterministic strategy lessons for TinyWorld adaptive benchmarking.

Return output as a strict JSON array of objects only.
Each object must include these keys:
- `rule`
- `trigger`
- `risk_if_overapplied`
- `confidence` (`low` | `medium` | `high`)

Rules:
- Keep each field concise.
- Use conditional language ("when ... then ...").
- Avoid episode recap style.
- Treat lessons as soft guidance; avoid rigid absolute commands.
- In `risk_if_overapplied`, include an explicit "Do not apply when ..." boundary.
- No markdown, no prose outside JSON.

Do not return markdown.
Do not return explanations.
