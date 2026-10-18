# 0004: Score with BIRD's set comparison and cache gold results

Date: 2026-10-16. Status: accepted.

## Context
Execution accuracy (EX) runs the predicted and gold queries and compares results. BIRD's official
script counts a prediction correct when `set(predicted_rows) == set(gold_rows)`.

That rule has known blind spots:
- Row order is ignored, even when the question asks for a ranking.
- Duplicate rows are ignored.
- Column order is not ignored, so the right values in a different column order count as wrong.
- Two different queries can return the same rows on this data by coincidence.

Separately, two gold queries are very slow on SQLite: question 518 took 62s and question 701 took
325s when run alone.

## Decision
- Use the official rule unchanged, so numbers are comparable with published BIRD results. Tests
  pin the behaviour (`test_row_order_does_not_matter`, `test_column_order_matters`).
- Run every gold query once with a 900s limit and store the rows in `gold_results.jsonl`
  (`sqlagent cache-gold`). Scoring reads the cache, so gold queries are never re-run.
- Predicted queries get a 60s limit.
- Gold and predicted rows go through the same JSON round trip before comparison, so cached and fresh
  results compare on equal terms.

## Consequences
- With a 60s limit on predictions, the oracle (which submits the gold SQL) scores 99.6 to 99.8%.
  Question 701 always times out. Question 518 runs in about 62s alone and passes or fails depending
  on machine load. That range is the ceiling under this rule, and the README says so.
- A full run is much faster, since half the SQL is no longer executed.
- Order-sensitive questions may be scored as correct when the order is wrong. Measuring how often
  this happens is listed as future work.
