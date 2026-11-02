# Deployment Runbook — Overview

This runbook walks through the first production deployment of AI Playlist Generator on Google Cloud, phase by phase, with a verification step after each one. It expands the README's *Deployment on GCP* section (from [Step 1](../README.md#step-1--gcp-prerequisites-run-once)) with the checks, timings and pitfalls met in practice.

## Phases

| # | Phase | File | Estimated time |
| :--- | :--- | :--- | :--- |
| A | Prerequisites: GCP project, APIs, credentials, Spotify app, Gemini key, `.env` | [deployment-01-prerequisites.md](deployment-01-prerequisites.md) | ~45 min |
| B | Core infrastructure with Terraform: Firestore, TTL, rules, runtime identity | [deployment-02-core-infrastructure.md](deployment-02-core-infrastructure.md) | ~20 min |
| C | Local verification: integration tests, manual run, container | [deployment-03-local-verification.md](deployment-03-local-verification.md) | ~30 min |
| D | Secrets, Artifact Registry, production image and Cloud Run | [deployment-04-cloud-run.md](deployment-04-cloud-run.md) | ~25–35 min |
| E | Production redirect URI, releases and continuous deployment | [deployment-05-production-release.md](deployment-05-production-release.md) | ~15 min |
| F | Acceptance tests in production and cost guardrails | [deployment-06-acceptance-tests.md](deployment-06-acceptance-tests.md) | ~35 min + 20 min idle |
| — | Known issues and fixes | [deployment-07-troubleshooting.md](deployment-07-troubleshooting.md) | — |

Total: about 3–4 hours including waits, roughly 2 hours of hands-on work. The times assume a normal connection: building and pushing the image is the step most sensitive to bandwidth (see [Troubleshooting](deployment-07-troubleshooting.md#slow-docker-builds)).

## Conventions

Replace these placeholders with your own values:

| Placeholder | Meaning |
| :--- | :--- |
| `YOUR_PROJECT_ID` | GCP project ID (globally unique). Also goes in `gcp.project_id` of `config/base.toml`. |
| `YOUR_BILLING_ACCOUNT_ID` | An **open** billing account, from `gcloud billing accounts list`. |
| `YOUR_GCP_ACCOUNT_EMAIL` | The Google account that owns the project. |
| `YOUR_GCLOUD_CONFIG` | Name of a dedicated `gcloud` configuration, e.g. `ai-playlist-generator`. |
| `YOUR_SPOTIFY_CLIENT_ID` | Client ID of the Spotify app (public by design). |
| `YOUR_CLOUD_RUN_URL` | Canonical service URL from `terraform -chdir=terraform output -raw cloud_run_url`. |
| `YOUR_GITHUB_REPO` | GitHub repository allowed to deploy, as `owner/name`. |

Commands run from the project root, with the virtual environment created as in the README ([Installation](../README.md#installation)).

## Ground rules

- **Secrets never appear on screen or in chat.** They live in `.env` locally and in Secret Manager in production; the commands below read them from `.env` or generate them inline, and verifications only print lengths.
- **Settings ship inside the image.** `config/base.toml` and `config/production.toml` are copied into the container, so they must be complete **before** the image is built: a blank value raises a `ConfigError` at startup.
- **Terraform state is local** (`terraform/terraform.tfstate`, git-ignored). Back it up after every apply: without it Terraform can no longer manage the resources.
- **Targeted applies are intentional.** The infrastructure is applied in slices because Cloud Run needs an image, and the secret IAM bindings need the secrets, before they can be created.
