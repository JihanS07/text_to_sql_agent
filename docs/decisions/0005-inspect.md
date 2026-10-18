# 0005: Add Inspect AI as a second runner

Date: 2026-10-16. Status: accepted.

## Context
Inspect is an open-source LLM evaluation framework from the UK AI Security Institute, published in
May 2024. Its structured logs and `inspect view` transcript viewer are a format other evaluation
engineers already read.

## Decision
`evals/bird_inspect.py` defines a `bird_minidev` Inspect task. Its solver calls this repo's own
`run_strategy`, and its scorer calls the same `execution_match`. Inspect is the runner and the log
viewer; the agent and the scoring rule stay ours. The `sqlagent` CLI remains the main runner because
it supports resuming and paired comparisons.

## Consequences
- Both runners produce numbers from the same code, so they should agree on the same questions.
- Inspect's CLI requires `--model`, which this task ignores (it calls Claude through `model_id`).
  We pass `--model mockllm/model` and say so in the task docstring.
- Inspect's own model layer, token accounting and built-in agents are not used.
