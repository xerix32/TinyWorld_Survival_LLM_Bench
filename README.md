# TinyWorld Survival Bench

Version: **0.1.11**

TinyWorld Survival Bench is a deterministic, benchmark-first grid-world runner for evaluating LLMs (and humans) as turn-based agents.

## What v0.1 includes
- Deterministic seeded 6x6 world generation.
- Single-agent benchmark loop with strict action validation.
- Prompt templates externalized under `prompts/`.
- Per-run JSON logs and suite CSV summaries.
- Dummy deterministic baseline model wrapper.
- OpenAI-compatible provider wrapper (usable for Vercel/Groq/LM Studio).
- Human CLI mode using the same engine and command protocol.

## Command Protocol (v0.1)
- `move north`
- `move south`
- `move east`
- `move west`
- `gather`
- `eat`
- `drink`
- `rest`
- `inspect`

## Determinism and fairness
- Engine is the source of truth for state, validation, scoring, and end conditions.
- With the same seed and same action sequence, outcomes are deterministic.
- Models receive only rendered prompts and must output one action string.

## Provider and model configuration
Providers and model profiles are configured in:
- `configs/providers.yaml` (default)
- `configs/providers.local.yaml` (local variant)

A model profile binds:
- `provider` (e.g. `vercel_gateway`, `groq_gateway`, `local_lmstudio`)
- `model` and runtime params (e.g. `temperature`, `max_tokens`)

This separates provider identity from model name, so the same model can be benchmarked across different backends.

## Official v0.1 baseline
- Official seed set: `1..20`
- Official scenario: `v0_1_basic`
- Official model profile: `dummy_v0_1`
- Official definition file: `configs/official_benchmark_v0_1.yaml`
- Official baseline CSV: `artifacts/results/baselines/baseline_v0_1_dummy_seed1-20.csv`

Re-generate baseline with:
```bash
python -m bench.run_suite \
  --seeds 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20 \
  --model dummy_v0_1 \
  --providers-config configs/providers.yaml \
  --output artifacts/results/baselines/baseline_v0_1_dummy_seed1-20.csv
```

## Run one benchmark match
```bash
python -m bench.run_match
```

`run_match` defaults:
- `--seed 7`
- `--model local_gpt_oss_20b`
- `--providers-config configs/providers.local.yaml`

The CLI shows live, in-place progress (percent, turn, action, protocol/effect, score), a human-readable summary with interpretation hints, and automatically generates an HTML report and opens it in your default browser.

Example with local provider file:
```bash
python -m bench.run_match --seed 7 --model vercel_gpt_oss_120b --providers-config configs/providers.local.yaml
```

Optional flags:
- `--scenario v0_1_basic`
- `--max-turns 50`
- `--output artifacts/logs/my_run.json`
- `--benchmark-config configs/benchmark.yaml`
- `--scenarios-config configs/scenarios.yaml`
- `--providers-config configs/providers.yaml`
- `--prompts-dir prompts`
- `--no-color`
- `--no-viewer`
- `--viewer-output artifacts/replays/my_report.html`
- `--viewer-title \"My TinyWorld Report\"`
- `--no-open-viewer`
- `--serve [PORT]` (serve report via `http://127.0.0.1:PORT`, default `8765`)

## Run a multi-seed suite
```bash
python -m bench.run_suite --seeds 1,2,3 --model dummy_v0_1
```

This writes one JSON log per run and a summary CSV under `artifacts/results/`.

## Aggregate existing logs into CSV
```bash
python -m bench.aggregate --logs-glob 'artifacts/logs/*.json'
```

## Generate graphical HTML viewer from a run log
```bash
python -m bench.view_log --log artifacts/logs/<run_log>.json
```

Optional flags:
- `--output artifacts/replays/<dashboard>.html`
- `--title \"My TinyWorld Run\"`

The viewer includes:
- score dashboard cards
- interactive turn slider/player
- map replay with emoji tiles, path overlay, and current agent marker
- clickable turn timeline
- per-turn action/state/metrics details

## Play manually (human CLI)
```bash
python -m bench.play_human --seed 7
```

Use only the command protocol actions listed above. Stop with `Ctrl+C`.

## Artifact locations
- Logs: `artifacts/logs/`
- Suite/Aggregate CSV: `artifacts/results/`
- Human replay logs: `artifacts/replays/`

## Reproducibility metadata in run JSON
Each run log includes benchmark identity metadata for fair comparisons:
- `benchmark_identity.bench_version`
- `benchmark_identity.engine_version`
- `benchmark_identity.protocol_version`
- `benchmark_identity.prompt_set_sha256`
- `benchmark_identity.system_prompt_sha256`
- `benchmark_identity.prompt_templates` (template-path -> sha256)
- `prompt_versions` (prompt-set/version alias block)
