# Thalamus infra modules

Reusable Terraform modules for the consolidated Thalamus infra. Empty at Wave 0
(this file exists so git tracks the directory; git does not track empty dirs).

Waves 1-4 fold the DIS and CM modules in here (network, cloud-sql, secrets,
pubsub, buckets, service-accounts, artifact-registry, cloud-run-service,
cloud-run-job, and so on), per the target in ../README.md: one project, one VPC,
one Postgres with cm + dis as two schemas, pgvector, no peering.

Do not add modules this wave. Wave 0 is bootstrap-only (project + billing + APIs).
