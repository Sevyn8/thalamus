# Synapse — the analytics + actions plane. A PEER of dis/, not part of it.
#
# There is no CI in this repo (no .github/workflows, no root Makefile), so these
# targets are the only automation. They shell into dis/ because that is where the uv
# workspace root lives — Synapse is a member of it, so `uv run` there resolves
# synapse, dis-canonical and dis-rls together.

.PHONY: help test conformance lint format

help:
	@echo "test         - synapse unit tests (offline; integration skips without a DSN)"
	@echo "conformance  - the capability + signal contract conformance harness"
	@echo "lint         - ruff check + ruff format --check + mypy --strict + import-linter"
	@echo "format       - ruff format over synapse ONLY (dis's target also spans dis + connectors)"

test:
	cd ../dis && uv run pytest -c pyproject.toml ../synapse

# Also run by tests/unit/test_contracts_conformance.py so `make test` covers it —
# there is no CI to attach it to.
conformance:
	cd ../dis && uv run python ../contracts/synapse/validate.py

# FORMATTING IS PART OF THE GATE. `ruff check` and mypy do not look at formatting,
# so without the `ruff format --check` line unformatted files accumulate silently.
# The cost is not aesthetic: the formatter is repo-wide, so the next contributor to
# run it reformats files they never edited, and their diff stops being reviewable.
#
# --check rather than --diff so it fails without printing the whole reflow; run
# `make format` to fix.
lint:
	cd ../dis && uv run ruff check --config pyproject.toml ../synapse
	cd ../dis && uv run ruff format --check --config pyproject.toml ../synapse
	cd ../dis && uv run mypy ../synapse
	cd ../dis && uv run lint-imports

# SYNAPSE ONLY, deliberately. dis/Makefile's `format` target spans `. ../connectors
# ../synapse`, so running it from there also reformats dis and connectors, which are
# not this package's to touch.
format:
	cd ../dis && uv run ruff format --config pyproject.toml ../synapse
