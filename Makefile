.PHONY: install data check test oracle smoke ablation report ehrsql-data ehrsql-baselines ehrsql-smoke ehrsql

install:            ## install everything, including dev tools and git hooks
	uv sync --all-extras
	uv run pre-commit install

data:               ## download BIRD Mini-Dev and cache gold results
	bash scripts/download_data.sh

check:              ## what CI runs
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
	uv run pytest

oracle:             ## harness sanity check, no API key needed
	uv run sqlagent run --strategy oracle

smoke:              ## 20 questions with the agent; the output table reports the real cost
	uv run sqlagent run --strategy agent --limit 20

ablation:           ## every strategy on the same 100 questions
	for s in single_schema single_rows single_rows_desc agent_no_exec agent; do \
		uv run sqlagent run --strategy $$s --limit 100 || exit 1; \
	done
	uv run sqlagent run --strategy agent --limit 100 --no-hint

report:
	uv run sqlagent report --out results/summary.md --readme

ehrsql-data:        ## download EHRSQL 2024 and the MIMIC-IV demo database (37 MB)
	bash scripts/download_ehrsql.sh

ehrsql-baselines:   ## oracle and always-abstain on both splits, no API key needed
	for split in valid test; do \
		uv run sqlagent ehrsql-run --strategy oracle --split $$split || exit 1; \
		uv run sqlagent ehrsql-run --strategy abstain_all --split $$split || exit 1; \
	done

ehrsql-smoke:       ## agent with abstain on 20 validation questions
	uv run sqlagent ehrsql-run --strategy agent_abstain --limit 20

ehrsql:             ## both agents on the same 200 validation questions
	uv run sqlagent ehrsql-run --strategy agent --limit 200
	uv run sqlagent ehrsql-run --strategy agent_abstain --limit 200
	uv run sqlagent ehrsql-report --readme
