# Synapse — the analytics + actions plane. A PEER of dis/, not part of it.
#
# There is no CI in this repo (no .github/workflows, no root Makefile), so these
# targets are the only automation. They shell into dis/ because that is where the uv
# workspace root lives — Synapse is a member of it, so `uv run` there resolves
# synapse, dis-canonical and dis-rls together.

.PHONY: help test conformance lint

help:
	@echo "test         - synapse unit tests (offline; integration skips without a DSN)"
	@echo "conformance  - the capability + signal contract conformance harness"
	@echo "lint         - ruff + mypy --strict + import-linter over synapse"

test:
	cd ../dis && uv run pytest -c pyproject.toml ../synapse

# Also run by tests/unit/test_contracts_conformance.py so `make test` covers it —
# there is no CI to attach it to.
conformance:
	cd ../dis && uv run python ../contracts/synapse/validate.py

lint:
	cd ../dis && uv run ruff check --config pyproject.toml ../synapse
	cd ../dis && uv run mypy ../synapse
	cd ../dis && uv run lint-imports
