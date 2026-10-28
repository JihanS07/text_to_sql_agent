# 0007: Add EHRSQL 2024 as a second benchmark, scored for reliability

Date: 2026-10-28. Status: accepted.

## Context
BIRD only asks questions that have an answer, so it never tests whether the agent knows when to
stop. In a hospital setting a confident wrong answer is worse than no answer. EHRSQL 2024 is a
text-to-SQL shared task on the MIMIC-IV demo database (100 patients, open access) where about 20% of
the validation and test questions cannot be answered from the data. Its main metric, RS(10), counts
a wrong answer as -10, a right answer or a correct abstention as 1, and abstaining on an answerable
question as 0.

The gold queries use `current_time`, `NOW()` and a few placeholders. The official scoring program
rewrites them before running anything, pinning "now" to 2100-12-31 23:59:00. Run as plain SQLite,
`current_time` is the time of day on the grading machine.

## Decision
- Port the official post-processing and scoring into `ehrsql.py` instead of writing new rules, and
  check the port against the official program on every validation and test question.
- Apply the same post-processing to gold queries, graded predictions and the agent's `run_sql`
  calls, and tell the agent in its prompt what "now" is. Otherwise the agent would test queries
  against a different clock from the one it is graded on.
- Keep BIRD's agent loop and tools. EHRSQL adds one tool, `abstain`, offered only to the
  `agent_abstain` strategy, so `agent` and `agent_abstain` differ by exactly that option and the
  scoring rule in the prompt.
- Tell the agent to answer yes or no questions with 1 or 0. The gold answers encode them that way,
  and a model returning the text "yes" would be scored wrong for formatting alone.
- Report RS(0), RS(5) and RS(10), accuracy on answerable questions, the share of unanswerable
  questions caught, and the share of abstentions that were correct. RS(10) gets a bootstrap interval.
- Pin the data to one commit of the EHRSQL repository and check SHA-256 hashes on download.

## Consequences
- The oracle scores 100% on both splits and always abstaining scores 19.9% (valid) and 20.0% (test),
  which is the share of unanswerable questions. Any model result has to clear that floor.
- Test labels are public in the repository, so test numbers here are not blind the way the original
  shared task leaderboard was. Prompt and strategy choices are made on the validation split only.
