# Thalamus staging bootstrap (Wave 0)

Local-state Terraform that creates the `thalamus-staging` GCP project, links
billing, and enables the baseline platform APIs. Run once, by hand, before any
`envs/staging` wave.

## Why local state

The bootstrap stands up the project foundation that later remote-state consumers
depend on, so it cannot itself depend on remote state. State stays in
`./terraform.tfstate` (gitignored). Do not add a gcs backend here.

## What it does NOT do

- Does NOT create the state bucket. `sevyn8-tfstate` already exists (org-shared,
  also used by DIS). `envs/staging/backend.tf` points at it with prefix
  `thalamus/staging`.
- Does NOT create any VPC, Postgres, secret, or service. Those are Waves 1-4.
- Does NOT touch `ithina-dis-cm` (the live shared DIS+CM project). Thalamus is a
  separate project.

## Prerequisites

`amit@sevyn8.com` gcloud ADC with, on org `395217984150`:
`resourcemanager.projects.create` and `billing.resourceAssociations.create`.

## Run

```
cd ~/projects/thalamus/infra/bootstrap
cp terraform.tfvars.example terraform.tfvars   # values are already correct
terraform init
terraform plan
terraform apply
```

Apply creates the project + billing link + APIs. If the project id is already
taken, apply fails cleanly (`alreadyExists`); pick an alternative id
(e.g. `sevyn8-thalamus-staging`) and re-run.
