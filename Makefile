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

# ── Fetch ──────────────────────────────────────────────────────────────────────

BRANCH ?= main

.PHONY: fetch-plugin
fetch-plugin: ## Fetch specific files from a GitHub repo dir, e.g. make fetch-plugin REPO=Classic298/open-webui-plugins DIR=inline-visualizer-v2 FILES="SKILL.md tool.py" DEST=skills/inline-visualizer-v2 [BRANCH=main]
	@test -n "$(REPO)" || (echo "REPO is required, e.g. REPO=user/repo" && exit 1)
	@test -n "$(DIR)" || (echo "DIR is required, e.g. DIR=path/in/repo" && exit 1)
	@test -n "$(FILES)" || (echo "FILES is required, e.g. FILES=\"SKILL.md tool.py\"" && exit 1)
	@test -n "$(DEST)" || (echo "DEST is required, e.g. DEST=skills/my-plugin" && exit 1)
	@mkdir -p $(DEST)
	@for f in $(FILES); do \
		echo "Fetching $$f -> $(DEST)/$$f"; \
		curl -sLf "https://raw.githubusercontent.com/$(REPO)/$(BRANCH)/$(DIR)/$$f" -o "$(DEST)/$$f" \
			|| (echo "Failed to fetch $$f" && exit 1); \
	done

# ── Clean ──────────────────────────────────────────────────────────────────────

.PHONY: clean
clean: ## Remove local artifacts not tracked by git (.venv, caches, build outputs, test artefacts)
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.pyd' \) -exec rm -f {} +
	find . -type d -name '*.egg-info' -exec rm -rf {} +
	find . -type d -name '.mypy_cache' -exec rm -rf {} +
	find . -type d -name '.ruff_cache' -exec rm -rf {} +
	find . -type d -name '.pytest_cache' -exec rm -rf {} +
	find . -type d -name '.hypothesis' -exec rm -rf {} +
	rm -rf .venv dist build .eggs htmlcov .coverage coverage.xml

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
