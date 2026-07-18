# Thalamus infra

Consolidated, standalone. One GCP project, one VPC, one Postgres instance
with two schemas: cm and dis. pgvector enabled. No VPC peering.
tfstate prefix: thalamus/{env}

Fold infra/_import (cm-infra, dis-infra) into modules/, then remove _import.

Do not apply until:
- copied secrets rotated and repointed to the dev project
- _import folded in and removed
