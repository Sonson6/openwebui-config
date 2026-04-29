.DEFAULT_GOAL := help

# ── Setup ──────────────────────────────────────────────────────────────────────

.PHONY: install
install: ## Install dependencies and register pre-commit hooks (pre-commit + commit-msg)
	pip install -r requirements.txt
	pre-commit install --hook-type pre-commit --hook-type commit-msg

# ── Code quality ───────────────────────────────────────────────────────────────

.PHONY: fmt
fmt: ## Auto-format code with ruff
	ruff format .

.PHONY: lint
lint: ## Lint with ruff and type-check with mypy
	ruff check .
	mypy scripts/ tests/

.PHONY: check
check: ## Run all pre-commit hooks against every file
	pre-commit run --all-files

# ── Tests ──────────────────────────────────────────────────────────────────────

.PHONY: test
test: ## Run pytest against the dev instance (requires a running OpenWebUI)
	ENV=development pytest

.PHONY: test-prod
test-prod: ## Run pytest against the prod instance
	ENV=production pytest

# ── Apply / Export ─────────────────────────────────────────────────────────────

.PHONY: apply
apply: ## Push config and functions to the dev instance
	ENV=development python scripts/apply.py

.PHONY: apply-prod
apply-prod: ## Push config and functions to the prod instance
	@echo "Targeting PRODUCTION — are you sure? [y/N] " && read ans && [ $${ans:-N} = y ]
	ENV=production python scripts/apply.py

.PHONY: export
export: ## Pull current state from the dev instance into local files
	ENV=development python scripts/export.py

# ── Commit / Release ───────────────────────────────────────────────────────────

.PHONY: commit
commit: ## Interactive conventional commit prompt (commitizen)
	cz commit

.PHONY: bump
bump: ## Bump version + update CHANGELOG based on conventional commits
	cz bump

# ── Help ───────────────────────────────────────────────────────────────────────

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
