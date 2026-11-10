# Phase D — Secrets, Image and Cloud Run

**Goal:** the four secrets in Secret Manager, the production image in Artifact Registry and a public Cloud Run service running it.

**Estimated time:** ~25–35 min on a normal connection.

## D1 — Secrets in Secret Manager (~5 min)

The Gemini key, the Spotify Client Secret and the Claude key are read from `.env`; production gets a **new** Fernet key, generated inline. No value is printed. Use a Claude key from a workspace with a spend limit set in the Claude Console (the default workspace cannot have one).

```bash
grep '^GOOGLE_API_KEY=' .env | cut -d= -f2- | tr -d '"\r\n' | gcloud secrets create GOOGLE_API_KEY --data-file=- --project=YOUR_PROJECT_ID
grep '^SPOTIFY_CLIENT_SECRET=' .env | cut -d= -f2- | tr -d '"\r\n' | gcloud secrets create SPOTIFY_CLIENT_SECRET --data-file=- --project=YOUR_PROJECT_ID
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode(), end='')" | gcloud secrets create SESSION_ENCRYPTION_KEY --data-file=- --project=YOUR_PROJECT_ID
grep '^ANTHROPIC_API_KEY=' .env | cut -d= -f2- | tr -d '"\r\n' | gcloud secrets create ANTHROPIC_API_KEY --data-file=- --project=YOUR_PROJECT_ID
```

`tr` strips quotes and line endings, which would otherwise become part of the secret.

Grant the runtime service account access to exactly these four secrets:
```bash
terraform -chdir=terraform apply \
  -target=google_secret_manager_secret_iam_member.app_api_key \
  -target=google_secret_manager_secret_iam_member.app_spotify_client_secret \
  -target=google_secret_manager_secret_iam_member.app_session_encryption_key \
  -target=google_secret_manager_secret_iam_member.app_anthropic_api_key \
  -var="project_id=YOUR_PROJECT_ID"
```

✅ **Check (~1 min):** compare lengths, never values.

| Command | Expected |
| :--- | :--- |
| `gcloud secrets versions access latest --secret=GOOGLE_API_KEY --project=YOUR_PROJECT_ID \| wc -c` | Same as `grep '^GOOGLE_API_KEY=' .env \| cut -d= -f2- \| tr -d '"\r\n' \| wc -c` |
| `gcloud secrets versions access latest --secret=SPOTIFY_CLIENT_SECRET --project=YOUR_PROJECT_ID \| wc -c` | `32` |
| `gcloud secrets versions access latest --secret=SESSION_ENCRYPTION_KEY --project=YOUR_PROJECT_ID \| wc -c` | `44` |
| `gcloud secrets versions access latest --secret=ANTHROPIC_API_KEY --project=YOUR_PROJECT_ID \| wc -c` | Same as `grep '^ANTHROPIC_API_KEY=' .env \| cut -d= -f2- \| tr -d '"\r\n' \| wc -c` |

Gemini API keys do not all share one length: classic `AIza…` keys have 39 characters, newer AI Studio keys are longer. Comparing with `.env` is the reliable check.

## D2 — Artifact Registry (~2 min)

```bash
terraform -chdir=terraform apply -target=google_artifact_registry_repository.app -var="project_id=YOUR_PROJECT_ID"
```

✅ **Check:** the `playlist-generator` Docker repository is listed.
```bash
gcloud artifacts repositories list --location=us-central1 --project=YOUR_PROJECT_ID
```

The repository keeps only the 2 most recent images (cleanup policy), to stay within the 0.5 GB free storage.

## D3 — Production image (`linux/amd64`)

`config/base.toml` must already hold the project ID and the Spotify Client ID (Phase A8): settings are baked into the image.

**Option 1 — Local build and push (the README path), ~10–15 min on a normal connection:**
```bash
gcloud auth configure-docker us-central1-docker.pkg.dev
make docker-push
```
`make docker-push` builds with `--platform linux/amd64` (Cloud Run runs on x86_64; an arm64 image from Apple Silicon fails to start) and pushes the `latest` tag. On Apple Silicon the amd64 build is emulated and downloads every wheel again for x86_64; the compressed image is about 250 MB.

**Option 2 — Cloud Build, for slow or metered connections:** only the source is uploaded and the image is built natively on Google's network. Not used for this project's first deployment, so treat it as an alternative. New projects without an organization run builds as the Compute Engine default service account, which only exists once the Compute Engine API is enabled:
```bash
gcloud services enable compute.googleapis.com cloudbuild.googleapis.com --project=YOUR_PROJECT_ID
```
Make sure `.env` is not uploaded (the upload honours `.gitignore`); this must print `OK`:
```bash
gcloud meta list-files-for-upload . | grep -qxE '\.env|\.venv/.*' && echo "STOP: .env would be uploaded" || echo OK
```
```bash
gcloud builds submit --tag=us-central1-docker.pkg.dev/YOUR_PROJECT_ID/playlist-generator/playlist-generator:latest --project=YOUR_PROJECT_ID .
```

✅ **Check:** the image with the `latest` tag is listed.
```bash
gcloud artifacts docker images list us-central1-docker.pkg.dev/YOUR_PROJECT_ID/playlist-generator --include-tags
```

## D4 — Cloud Run and CI identity (~5 min)

```bash
terraform -chdir=terraform apply \
  -target=google_cloud_run_v2_service.app \
  -target=google_cloud_run_v2_service_iam_member.public \
  -target=google_iam_workload_identity_pool.github \
  -target=google_iam_workload_identity_pool_provider.github \
  -target=google_service_account.deployer \
  -target=google_service_account_iam_member.github_actions_impersonate \
  -target=google_artifact_registry_repository_iam_member.deployer_writer \
  -target=google_cloud_run_v2_service_iam_member.deployer_developer \
  -target=google_service_account_iam_member.deployer_act_as_app \
  -var="project_id=YOUR_PROJECT_ID" \
  -var="image_url=us-central1-docker.pkg.dev/YOUR_PROJECT_ID/playlist-generator/playlist-generator:latest"
```

The first revision still uses the loopback redirect URI from `config/base.toml`: guest mode works, Spotify login does not until Phase E.

## Verification (~5 min)

✅ Health check prints `ok` (the first request may take a few seconds while the instance starts):
```bash
curl -s "$(terraform -chdir=terraform output -raw cloud_run_url)/_stcore/health"
```

✅ Service configuration:
```bash
gcloud run services describe playlist-generator --region=us-central1 --project=YOUR_PROJECT_ID --format=yaml | grep -E "maxScale|sessionAffinity|timeoutSeconds|cpu-throttling"
```

| Line | Expected | Notes |
| :--- | :--- | :--- |
| `autoscaling.knative.dev/maxScale` | `'1'` | Revision limit. A service-level `run.googleapis.com/maxScale` (e.g. `'20'`) may also appear: Cloud Run applies the lower of the two. |
| `run.googleapis.com/sessionAffinity` | `'true'` | One Streamlit WebSocket per tab. |
| `timeoutSeconds` | `3600` | The request timeout. A second `timeoutSeconds: 240` belongs to the default startup probe. |
| `run.googleapis.com/cpu-throttling` | `'true'` | Request-based billing. `'false'` means always-on CPU: see [Troubleshooting](deployment-07-troubleshooting.md#cpu-always-allocated). |

✅ Logs show the server start and no `ConfigError` or `Traceback`:
```bash
gcloud run services logs read playlist-generator --region=us-central1 --project=YOUR_PROJECT_ID --limit=50
```

✅ Open the URL from `terraform -chdir=terraform output -raw cloud_run_url` and generate a playlist **as a guest**.

Next: [Phase E — Production release](deployment-05-production-release.md).
