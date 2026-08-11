# Axon - the communications and delivery plane. A PEER of dis/ and synapse/, with its own
# targets for the same reason it has its own alembic chain: a module whose checks live in
# another module's Makefile is a module whose checks get skipped when that one is refactored.
#
# There is no CI in this repository, so these targets are the only automation. They shell into
# dis/ because that is where the uv workspace root lives.
#
# NOTE WHERE THE MAIL-COPY GUARD IS NOT. test_no_em_dash_in_axon_copy.py lives in
# synapse-ui-server's suite, not here, because the copy it walks is composed there and because
# `make -C synapse test` is a command somebody already runs. It scans axon/src as well, so
# `make -C synapse test` covers this module's source for the rule that matters most.

.PHONY: help test lint format

help:
	@echo "test    - axon unit tests (offline; no database, no provider)"
	@echo "lint    - ruff check + ruff format --check + mypy --strict over axon"
	@echo "format  - ruff format over AXON ONLY"

test:
	cd ../dis && uv run pytest -c pyproject.toml ../axon

lint:
	cd ../dis && uv run ruff check --config pyproject.toml ../axon
	cd ../dis && uv run ruff format --check --config pyproject.toml ../axon
	cd ../dis && uv run mypy ../axon

format:
	cd ../dis && uv run ruff format --config pyproject.toml ../axon
