# 0001: Evaluate on BIRD Mini-Dev, July 2025 release

Date: 2026-10-16. Status: accepted.

## Context
The project needs a public benchmark with known answers, so accuracy claims can be checked by
anyone. Text-to-SQL has two common choices. Spider is older and many models have likely seen it.
BIRD uses real, messy databases (dirty values, codes that need the column notes to decode) and
gives an "evidence" hint per question. BIRD Mini-Dev is a 500-question subset over 11 SQLite
databases, small enough to run every configuration several times on a student budget.

There are two releases. The 2024 package has 498 questions. The July 2025 Hugging Face release has
500, and two of the shared questions have different gold SQL. A 2026 paper (Jin et al.) reports
annotation errors in the original set and publishes a further corrected version.

## Decision
Use the July 2025 release (`mini_dev_sqlite_2025.json`) by default. Keep the 2024 file so any run
can be repeated on it with `--questions-file mini_dev_sqlite_2024.json`.

## Consequences
- Numbers are not directly comparable with papers that used the 2024 release or the 2026 corrected
  release. The README states which release every number comes from.
- Running on the 2026 corrected set is listed as future work. It would show how much label noise
  moves the results.
