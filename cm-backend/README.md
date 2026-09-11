# cm-backend

Customer Master: the FastAPI service behind the Thalamus admin console. Owns
tenants, stores, users, org trees, RBAC, onboarding, tenant documents, and
channel-credential names; sole writer to the `core` schema.

Repository-level documentation lives at the repo root: `README.md` (commands),
`ARCHITECTURE.md`, `SECURITY.md`, `OPERATIONS.md`.

Local: `docker compose up -d && uv sync && uv run alembic upgrade head`, then
`scripts/check_setup.sh`. Gates: `uv run pytest`,
`uv run mypy --strict src/admin_backend`.
