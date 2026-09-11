# dis

Data Integration System: multi-tenant retail data ingestion on GCP. This
directory is the uv workspace root for DIS, Synapse, Axon, and the connectors.

Repository-level documentation lives at the repo root: `README.md` (commands),
`ARCHITECTURE.md`, `SECURITY.md`, `OPERATIONS.md`.

Local: `make run-local` (docker stack + Pub/Sub topics + migrations), then
`make check`. Gates: `make test` (also runs connectors + synapse),
`make lint` (mypy --strict per package, ruff, import-linter).
