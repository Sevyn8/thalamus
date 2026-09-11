# Thalamus

Multi-tenant retail data platform: Customer Master (identity, tenants, RBAC),
DIS (data ingestion to a canonical retail schema), Synapse (analytics/actions
over canonical data), Axon (communications/delivery), and POS connectors
(Square, Clover). Runs on GCP (Cloud Run, Cloud SQL Postgres, Pub/Sub, GCS,
Secret Manager) with Auth0 for authentication.

See **ARCHITECTURE.md** (components, flows, invariants), **SECURITY.md**
(auth, RLS, tenancy), **OPERATIONS.md** (deploy, migrations, monitoring), and
**CLAUDE.md** (rules for coding agents).

## Repository map

| Path | What it is |
|---|---|
| `cm-backend/` | Customer Master API (Python 3.12, FastAPI, own uv project + Alembic chain) |
| `cm-frontend/` | Admin console (Next.js, pnpm) |
| `dis/` | Data Integration System — uv **workspace root** (libs + services + Alembic chain); `synapse/`, `axon/`, `connectors/` are workspace members |
| `synapse/` | Analytics/actions plane (own Alembic chain, own Makefile) |
| `axon/` | Delivery plane (own Alembic chain, own Makefile) |
| `connectors/` | Square/Clover connector jobs + shared SDK + OAuth libs |
| `contracts/` | Cross-language contract schemas + conformance harnesses |
| `infra/` | Terraform (single env: `envs/staging`) and hand-run DB grant SQL |
| `docs/design/` | Design assets |

## Toolchains

Python 3.12 with [uv](https://docs.astral.sh/uv/) (two projects: `dis/` is the
workspace root for everything DIS/Synapse/Axon/connectors; `cm-backend/` stands
alone). Node with pnpm for both frontends. Terraform for infra. Ruff, mypy
--strict, import-linter, and pytest gate the Python code; ESLint and tsc gate
the frontends.

## Local setup (minimum)

```bash
# DIS stack (Postgres + Pub/Sub emulator + topics + migrations)
cd dis
cp .env.example .env
make sync
make run-local
make check

# Customer Master
cd cm-backend && docker compose up -d && uv sync && uv run alembic upgrade head

# Frontends
cd cm-frontend && pnpm install && pnpm dev
cd dis/services/dis-ui-ver2 && pnpm install && pnpm dev
```

## Canonical commands

| Subsystem | Lint / types | Tests | Build |
|---|---|---|---|
| dis (+ connectors + synapse) | `make -C dis lint` (mypy per package, ruff, import-linter) | `make -C dis test` | — |
| synapse only | `make -C synapse lint` | `make -C synapse test`, `make -C synapse conformance` | — |
| axon only | `make -C axon lint` | `make -C axon test` | — |
| cm-backend | `uv run mypy --strict src/admin_backend` | `uv run pytest` (needs the local Postgres) | — |
| cm-frontend | `pnpm lint` | — | `pnpm build` (runs the four assert scripts) |
| dis-ui-ver2 | `pnpm lint`, `pnpm tsc` | `pnpm test` | `pnpm build` |
| contracts | — | `python3 contracts/conformance/validate.py` | — |

DIS integration tests need the docker-compose stack (`make -C dis run-local`);
synapse integration tests skip without a database DSN. `.github/workflows/ci.yml`
runs these same commands on every pull request against `main`.
