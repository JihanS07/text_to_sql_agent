# Decision records

Each file records one design choice: the situation, what was decided, and what it costs. The format
is a lightweight version of Michael Nygard's Architecture Decision Records. A record is never edited
after the fact; a changed decision gets a new record that supersedes the old one.

| # | Decision |
|---|---|
| [0001](0001-benchmark.md) | Evaluate on BIRD Mini-Dev, using the July 2025 question release |
| [0002](0002-no-agent-framework.md) | Write the agent loop on the raw Messages API |
| [0003](0003-read-only-safety.md) | Enforce read-only access at the connection, use sqlglot only for messages |
| [0004](0004-scoring.md) | Score with BIRD's official set comparison and cache gold results |
| [0005](0005-inspect.md) | Add Inspect AI as a second runner, not a replacement |
| [0006](0006-statistics.md) | Report bootstrap confidence intervals and paired McNemar tests |
| [0007](0007-ehrsql.md) | Add EHRSQL 2024 as a second benchmark, scored for reliability |
