# text_to_sql_agent

[![CI](https://github.com/JihanS07/text_to_sql_agent/actions/workflows/ci.yml/badge.svg)](https://github.com/JihanS07/text_to_sql_agent/actions/workflows/ci.yml)

An LLM agent that answers plain-English questions about a SQL database, plus the harness that
measures how well it does. The agent is written directly on the Claude Messages API with no agent
framework. It is tested on two benchmarks. BIRD Mini-Dev has 500 questions over 11 real databases.
EHRSQL 2024 asks questions about hospital records, and about a fifth of them have no answer in the
data, so the agent also has to know when to decline.

The agent itself is small. Most of the code measures it: every configuration is run on the same
questions, each one changes a single thing, and every accuracy comes with a confidence interval and
a paired significance test. Cost and latency are recorded for every question.

Status: the harness, agent, tests and CI are done. Model runs are next, so for now the results table
only has the harness check.

## How the agent works

```mermaid
flowchart LR
    Q[Question + hint] --> M[Claude]
    M -->|list_tables / describe_table / sample_rows| T[Read-only SQLite]
    M -->|run_sql: test a query| T
    T -->|rows or error text| M
    M -->|submit_answer| S[Scorer]
    S -->|compare with cached gold rows| R[results.jsonl]
```

One step is one model call. The model can look at the schema, read the dataset's column notes,
look at real rows, test queries, and see its own errors. It ends by calling `submit_answer`. The
loop also stops on a step cap (12), a token budget or an API failure, and every run records which
of these happened.

## Results

Execution accuracy (EX) on BIRD Mini-Dev, July 2025 release. Strategies are listed so that each one
changes one thing relative to the one above it.

| Strategy | What changes |
|---|---|
| `single_schema` | One call. The prompt holds the CREATE statements only. |
| `single_rows` | Adds 3 example rows per table. |
| `single_rows_desc` | Adds BIRD's column descriptions. |
| `agent_no_exec` | Agent that explores the schema but cannot run its own queries. |
| `agent` | Full agent: explore, run queries, fix errors, submit. |
| `oracle` | Submits the gold SQL. Checks the harness. |

<!-- results:start -->
| Strategy | Model | Hint | n | EX % (95% CI) | Simple | Moderate | Challenging | Tool calls/q | Exec errors | $/question | Median latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| oracle | none | yes | 500 | 99.8 (99.4-100.0) | 100.0 | 100.0 | 99.0 | 0.0 | 0.2% | 0.0000 | 0.0 |
<!-- results:end -->

Model runs pending. Paired comparisons (`sqlagent compare`) and the failure analysis will be added
below once they exist.

## What testing the harness turned up

The best possible score is 99.6 to 99.8%, not 100%, and it depends on the machine. Two gold queries
are slow on SQLite: question 701 took 325s and question 518 took 62s when run alone. Predicted
queries get 60 seconds, so 701 always times out and 518 passes or fails depending on machine load.
Two oracle runs on the same machine scored 99.6% and 99.8%, so scores from different machines are
not directly comparable.

The two releases of the dataset differ. The 2024 package has 498 questions and the July 2025 release
on Hugging Face has 500, with different gold SQL for two of the shared questions. This repo uses the
2025 release ([decision 0001](docs/decisions/0001-benchmark.md)).

Several of BIRD's column description files have a trailing comma in the header row. A normal CSV
reader then drops the value notes, which are the part the agent needs most, for example that
`POPLATEK MESICNE` means monthly issuance. `data.py` keeps them, and a test checks it.

## EHRSQL: hospital records and knowing when to decline

EHRSQL 2024 is a shared task on text-to-SQL over electronic health records
([paper](https://arxiv.org/abs/2405.06673), [data](https://github.com/glee4810/ehrsql-2024)). The
database is the MIMIC-IV demo: admissions, diagnoses, prescriptions, lab results, vitals and ICU
stays for 100 patients, open to anyone. About 20% of the validation and test questions cannot be
answered from it, for example "Whats the phone number of the dr who is taking care of patient 28447",
and the right response is to decline.

The score is the reliability score RS(c). A correct answer and a correct abstention each score 1,
abstaining on a question that has an answer scores 0, and any wrong answer scores -c. The task's
main metric is RS(10), so one wrong answer cancels ten right ones. Declining every question scores
the share of unanswerable questions, about 20%, and that is the floor.

The agent and tools are the ones used on BIRD. `agent_abstain` adds an `abstain` tool and tells the
model how it is scored. `agent` has no way to decline. Running both on the same questions measures
what the option to decline is worth
([decision 0007](docs/decisions/0007-ehrsql.md)).

<!-- ehrsql:start -->
| Strategy | Model | Split | n | RS(0) % | RS(5) % | RS(10) % (95% CI) | Accuracy on answerable % | Unanswerable caught % | Abstentions correct % | $/question | Median latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| abstain_all | none | test | 1167 | 20.0 | 20.0 | 20.0 (17.7 to 22.2) | 0.0 | 100.0 | 20.0 | 0.0000 | 0.0 |
| abstain_all | none | valid | 1163 | 19.9 | 19.9 | 19.9 (17.6 to 22.2) | 0.0 | 100.0 | 19.9 | 0.0000 | 0.0 |
| oracle | none | test | 1167 | 100.0 | 100.0 | 100.0 (100.0 to 100.0) | 100.0 | 100.0 | 100.0 | 0.0000 | 0.0 |
| oracle | none | valid | 1163 | 100.0 | 100.0 | 100.0 (100.0 to 100.0) | 100.0 | 100.0 | 100.0 | 0.0000 | 0.0 |
<!-- ehrsql:end -->

Model runs pending. The two baselines above need no API key.

The gold queries use `current_time`. In SQLite that is the time of day on the machine running the
query, for example `15:31:07`, not a date, so a gold query gives a different answer depending on when
it runs. The official scorer swaps in `2100-12-31 23:59:00`, the end of the dataset's shifted
timeline, before running anything. Skipping that step changes the answer to 174 of the 931
answerable validation questions and 177 of the 934 answerable test questions. This repo applies the
same rewrite to gold queries, graded predictions and the agent's own test queries, and the agent's
prompt says what "now" is.

`ehrsql.py` ports the official rewrite and scoring rules. On all 2,330 validation and test questions,
with a mix of correct, abstained, wrong and broken predictions, its per-question scores are
identical to the official scoring program's.

## Design choices

Each one has a short decision record in [docs/decisions](docs/decisions/README.md).

The database is read-only at the connection level (`mode=ro`), so SQLite refuses every write no
matter what SQL the model sends. sqlglot checks each query first only to give the agent a clearer
error message. A test runs `DELETE` with that check turned off to show the connection still refuses.

Scoring uses BIRD's official rule, `set(pred_rows) == set(gold_rows)`, so the numbers can be
compared with published results. Tests pin down where that rule is too lenient or too strict, and
[decision 0004](docs/decisions/0004-scoring.md) lists the cases. Gold results are computed once and
cached.

Every accuracy has a 95% bootstrap confidence interval. Question samples are seeded so every
strategy sees the same questions, and `sqlagent compare` runs an exact McNemar test on each pair.

Cost comes from the token counts the API returns, including prompt cache reads and writes. Prices
are kept in `pricing.py`, so old runs can be re-priced.

The `sqlagent` CLI is the main runner because it can resume a run and compare two runs. An
[Inspect AI](https://inspect.aisi.org.uk/) task runs the same agent and scorer and adds structured
logs and a transcript viewer.

## Quickstart

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
make install                 # dependencies, dev tools, git hooks
make data                    # BIRD Mini-Dev (800 MB download), checksum check, gold cache
cp .env.example .env         # then add ANTHROPIC_API_KEY

make oracle                  # harness check, no API key needed, expect 99.6 to 99.8%
make smoke                   # agent on 20 questions
uv run sqlagent run --strategy agent --limit 100 --model claude-haiku-5-5
uv run sqlagent compare runs/<run A> runs/<run B>
uv run sqlagent show runs/<run> <question_id>     # full trace of one question
uv run sqlagent failures runs/<run>               # CSV of wrong answers to label

make ehrsql-data             # EHRSQL 2024 and the MIMIC-IV demo database (37 MB)
make ehrsql-baselines        # oracle and always-abstain, no API key needed
make ehrsql-smoke            # agent with the abstain tool on 20 questions
make ehrsql                  # both agents on the same 200 validation questions

uv run inspect eval evals/bird_inspect.py --model mockllm/model -T strategy=agent -T limit=20
uv run inspect view
```

## Repository layout

```
src/sql_agent_eval/
  agent.py        the agent loop and prompts
  tools.py        tool definitions and their implementations
  db.py           read-only SQLite access, time limit, row cap
  strategies.py   the ablation configurations
  scoring.py      execution accuracy and the gold-result cache
  runner.py       concurrent, resumable evaluation runs
  report.py       tables, bootstrap intervals, McNemar test
  llm.py          Claude client with prompt caching, and a scripted fake for tests
  pricing.py      per-model token prices
  ehrsql.py       EHRSQL loading, the official query rewrite and reliability scoring
  ehr_runner.py   EHRSQL strategies, runs and summary table
  cli.py          `sqlagent` command
evals/            Inspect AI task
tests/            offline tests (no API key, no download)
docs/decisions/   decision records
docs/PLAN.md      the three-day plan
```

## Engineering setup

| Tool | Used for |
|---|---|
| uv | dependency management with a lock file |
| Ruff | linting and formatting |
| Pyright | static type checking |
| pytest | 47 offline tests, using a scripted model in place of the API |
| pre-commit | lint, format, tests and a secret-key check on every commit |
| GitHub Actions | the same checks on every push and pull request |
| sqlglot | SQL parsing for the read-only check |
| Inspect AI | second runner with structured logs and a viewer |

## Limitations

- Both benchmarks are SQLite only. Results may not carry over to other databases or SQL dialects.
- EHRSQL's test labels are public, so test scores here are not blind. Choices are made on the
  validation split.
- BIRD's scoring ignores row order and duplicates and can count a coincidental match as correct.
- Model outputs are not deterministic. The plan includes repeated runs to measure the spread.
- Some BIRD gold labels are known to contain errors. A corrected 2026 release exists and is future work.

## Data and license

Code: MIT. BIRD Mini-Dev is released under CC BY-SA 4.0 by its authors
([paper](https://arxiv.org/abs/2305.03111), [repository](https://github.com/bird-bench/mini_dev)).
EHRSQL 2024 is CC BY 4.0 ([repository](https://github.com/glee4810/ehrsql-2024)) and the MIMIC-IV
demo database is released under the Open Data Commons ODbL 1.0 by PhysioNet. All data is downloaded
by `make data` and `make ehrsql-data` and is not stored in this repo.
