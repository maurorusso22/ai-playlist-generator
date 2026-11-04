# Phase E — Production Redirect URI and Releases

**Goal:** Spotify login working in production on a single canonical URL, and a repeatable way to ship new images.

**Estimated time:** ~15 min.

## E1 — Pick the canonical URL (~1 min)

```bash
terraform -chdir=terraform output -raw cloud_run_url
```

Every Cloud Run service answers on **two equivalent URLs**:

| URL | Shape | Shown by |
| :--- | :--- | :--- |
| `https://playlist-generator-<hash>-uc.a.run.app` | Legacy, random hash | Terraform (`cloud_run_url`) |
| `https://playlist-generator-<project-number>.us-central1.run.app` | Deterministic | `gcloud run services update` / `deploy` |

Both serve the same revision, but sessions live in per-origin `localStorage` and the OAuth callback always lands on the registered redirect URI. Pick **one** (this runbook uses the Terraform output), register only that one, and share only that one: a user who starts on the other origin loses the chat after logging in.

## E2 — Register the redirect URI on Spotify (~3 min)

In the Spotify Developer Dashboard open the app → **Settings** → **Edit** → **Redirect URIs**, add `YOUR_CLOUD_RUN_URL/` (exact match, trailing slash included) and save. Keep `http://127.0.0.1:8501/` for local development.

## E3 — Point production at it (~1 min)

In `config/production.toml`, read on Cloud Run where Terraform sets `APP_ENV=production`:
```toml
[spotify]
redirect_uri = "YOUR_CLOUD_RUN_URL/"  # Canonical Cloud Run URL
```

✅ **Check:** the production overlay loads and shows the new URI.
```bash
APP_ENV=production .venv/bin/python -c "from src.config.settings import get_settings; print(get_settings().spotify.redirect_uri)"
```

## E4 — Release the new configuration

Settings are baked into the image, so a configuration change is a new image.

### Manual release (no CI yet) (~5 min)

```bash
make docker-push
gcloud run services update playlist-generator --image=us-central1-docker.pkg.dev/YOUR_PROJECT_ID/playlist-generator/playlist-generator:latest --region=us-central1 --project=YOUR_PROJECT_ID
```

Terraform ignores image changes on the service (`ignore_changes` on the container image), so `terraform apply` alone never ships a new image: releases go through `gcloud`, exactly as the CI job does. Use a targeted `terraform apply -target=google_cloud_run_v2_service.app` only for infrastructure changes to the service (resources, scaling, timeout, env).

### Continuous deployment (GitHub Actions)

1. Make sure the repository is the one allowed by Workload Identity Federation: the `github_repo` Terraform variable (`owner/name`). If it differs, re-apply the WIF resources with `-var="github_repo=YOUR_GITHUB_REPO"`.
2. Set `PROJECT_ID` and `SERVICE_ACCOUNT` (`playlist-deployer@YOUR_PROJECT_ID.iam.gserviceaccount.com`, the `deployer_service_account_email` output) in the `env` block of `.github/workflows/deploy.yml`.
3. Store the provider name as the `WIF_PROVIDER` repository secret. The repository must already exist on GitHub, otherwise `gh` fails with `HTTP 404` on the secrets public key:
   ```bash
   gcloud iam workload-identity-pools providers describe github-oidc --workload-identity-pool=github-actions --location=global --project=YOUR_PROJECT_ID --format="value(name)" | gh secret set WIF_PROVIDER --repo YOUR_GITHUB_REPO
   gh secret list --repo YOUR_GITHUB_REPO
   ```
4. Push to `main`: the `test` job (ruff + unit tests) gates the `deploy` job (amd64 build tagged with the commit SHA, push, `deploy-cloudrun`). Follow it with:
   ```bash
   gh run watch --repo YOUR_GITHUB_REPO
   ```

## Verification (~2 min)

✅ The new revision serves 100% of the traffic (printed by `gcloud run services update`), and request-based billing is still on:
```bash
gcloud run services describe playlist-generator --region=us-central1 --project=YOUR_PROJECT_ID --format=yaml | grep cpu-throttling
```

✅ Smoke tests now run (they read the URL from `config/production.toml`) and pass: HTTP 200 with HTML, and the Streamlit health check.
```bash
make test-smoke
```

Next: [Phase F — Acceptance tests](deployment-06-acceptance-tests.md).
