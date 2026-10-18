# 0003: Enforce read-only access at the connection

Date: 2026-10-16. Status: accepted.

## Context
The agent writes and runs its own SQL. A model can emit `DROP TABLE` by mistake or because a
question or a database value contains instructions. The tool layer must make damage impossible, not
just unlikely.

## Decision
Two layers:
1. Real enforcement: the SQLite connection is opened with `?mode=ro` and `PRAGMA query_only = ON`.
   SQLite refuses every write regardless of the SQL text. `test_connection_refuses_writes_even_without_check`
   proves this with the parser check turned off.
2. Feedback: `check_read_only` parses the query with sqlglot and rejects writes, admin statements
   (`PRAGMA`, `ATTACH`) and multiple statements with a clear message the agent can act on. sqlglot's
   documentation says it is not a validator, so when it cannot classify a query (usually a typo),
   the query goes to SQLite, which returns the real syntax error.

Also: a progress handler interrupts any query past its time limit (15s inside the agent, 60s when
scoring), and tool output is capped at 20 rows and 6,000 characters.

## Consequences
- A parser bug cannot cause a write, because the parser is not the safety boundary.
- The time limit means a correct but slow query can be scored wrong. See 0004.
