# 0006: Bootstrap confidence intervals and paired tests

Date: 2026-10-16. Status: accepted.

## Context
On 100 questions, an accuracy near 50% has a 95% interval of about plus or minus 10 points
(standard error sqrt(0.5 * 0.5 / 100) = 0.05, times 1.96). Two strategies
that differ by four points may not differ at all. Comparing two unpaired accuracies also throws away
information, because both strategies answered the same questions.

## Decision
- Every accuracy in the summary table comes with a 95% percentile bootstrap interval
  (2,000 resamples, fixed seed).
- Question samples are seeded (`--limit 100 --seed 0` is always the same 100 questions), so
  strategies are compared on identical items.
- `sqlagent compare A B` reports the paired difference with a paired bootstrap interval and an exact
  McNemar test on the discordant questions (right under one strategy, wrong under the other).

## Consequences
- The README can say whether a difference is distinguishable from noise, not just which number is
  bigger.
- Model outputs are not deterministic, so the same strategy run twice will differ a little. Running
  the main strategy three times and reporting the spread is part of the plan.
