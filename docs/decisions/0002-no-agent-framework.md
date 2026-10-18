# 0002: Write the agent loop on the raw Messages API

Date: 2026-10-16. Status: accepted.

## Context
Frameworks such as LangChain or LangGraph hide the loop behind abstractions. That speeds up a demo,
but this project's purpose is to show and measure what the loop does: which tools get called, why it
stops, what each step costs.

## Decision
`agent.py` implements the loop directly; `run_agent` itself is under 50 lines. It sends the conversation, run any tool
calls, send results back with matching `tool_use_id`s, stop on `submit_answer`. The model sits
behind a small `ChatModel` protocol so tests can swap in `ScriptedModel`.

The loop has hard limits: a step cap (12 by default), a token budget, and a per-query timeout.
Every run records how it stopped: `submitted`, `no_tool_call`, `max_steps`, `budget` or
`model_error`. If the agent never submits, the last query it ran successfully is graded instead,
and the stop reason marks this, so the policy can be analysed separately.

## Consequences
- Every line of agent behaviour is visible and testable offline.
- No automatic support for other providers. Adding one means writing one more `ChatModel` class.
