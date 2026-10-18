# Project plan: Oct 16 to Oct 18, 2026

Goal: a public repo with real, reproducible results that I can link in the resume email going out
Sunday night, and explain line by line if an engineer asks.

## Day 1, Friday Oct 16: harness (done)
- [x] Choose benchmark and design (docs/decisions/0001 to 0006)
- [x] Project setup: uv, ruff, pyright, pytest, pre-commit, GitHub Actions CI
- [x] Download BIRD Mini-Dev, verify the archive checksum, cache all 500 gold results
- [x] Read-only database layer with time limit and row cap
- [x] Agent tools and the agent loop on the raw Messages API
- [x] Six strategies for the ablation, including an oracle for harness checks
- [x] Runner (resumable, concurrent), scorer, report with bootstrap CIs and McNemar test
- [x] Inspect AI task as a second runner
- [x] 32 offline tests; oracle scores 99.6 to 99.8% (the ceiling, see decision 0004)

## Day 2, Saturday Oct 17: run it and understand it
Morning (3 hours)
- [ ] Clone the repo, `make install`, `make data`, put the API key in `.env`
- [ ] Read every module. For each one, write two or three sentences in
      `docs/NOTES.md` in my own words: what it does, and one design choice I would defend
- [ ] `make smoke` (20 questions). Open three traces with `sqlagent show` and read every step

Afternoon (3 hours)
- [ ] `make ablation`: all six strategies on the same 100 questions, plus the agent without hints
- [ ] `sqlagent compare` for each neighbouring pair of strategies
- [ ] Full 500-question run of the best strategy, three times with different seeds, to measure
      run-to-run spread
- [ ] Haiku 5.5 vs Sonnet 5.5 on the same 100 questions, the agent strategy only

## Day 3, Sunday Oct 18: findings and write-up
- [ ] `sqlagent failures` on the main run. Hand-label 50 wrong answers with one cause each:
      wrong column, wrong join, wrong filter value, wrong aggregation, ignored hint,
      extra columns, gold looks wrong, other
- [ ] Count the labels and write the "What goes wrong" section of the README with real examples
- [ ] `make report`, paste the table into the README, write three or four findings in plain words
- [ ] Record a two-minute screen capture of one agent trace in `inspect view`
- [ ] Update the resume line with the real numbers
- [ ] Send the resume email with the repo link

## How I work on it
- Each change goes on a branch and through a pull request, so CI runs before anything reaches `main`.
- Commit messages follow Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`).
