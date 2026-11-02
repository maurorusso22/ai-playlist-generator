# Phase A — Prerequisites

**Goal:** a billed GCP project with the required APIs, local credentials for Terraform and Firestore, a Spotify app, a Gemini API key and a complete local `.env`.

**Estimated time:** ~45 min (about 20 min if the Spotify app and the Gemini key already exist).

## A1 — Docker running (~2 min)

```bash
open -a Docker
```

✅ **Check:** prints the server version without errors.
```bash
docker info --format '{{.ServerVersion}}'
```

## A2 — Dedicated gcloud configuration (~1 min)

A separate configuration keeps the default one, and any other project it points to, untouched.

```bash
gcloud config configurations create YOUR_GCLOUD_CONFIG
gcloud config set account YOUR_GCP_ACCOUNT_EMAIL
```

## A3 — Project and billing (~3 min)

```bash
gcloud projects create YOUR_PROJECT_ID --name="AI Playlist Generator"
gcloud config set project YOUR_PROJECT_ID
gcloud billing accounts list
gcloud billing projects link YOUR_PROJECT_ID --billing-account=YOUR_BILLING_ACCOUNT_ID
```

- Project IDs are **globally unique**: if `projects create` answers *"already in use"*, pick another ID (e.g. add a suffix) and use it everywhere below.
- Link an account whose `OPEN` column is `True`; closed accounts cannot be linked.

✅ **Check:** prints `True`.
```bash
gcloud billing projects describe YOUR_PROJECT_ID --format="value(billingEnabled)"
```

## A4 — Required APIs (~3–4 min)

```bash
gcloud services enable firestore.googleapis.com firebaserules.googleapis.com secretmanager.googleapis.com iam.googleapis.com run.googleapis.com artifactregistry.googleapis.com --project=YOUR_PROJECT_ID
```

✅ **Check:** the six APIs are listed.
```bash
gcloud services list --enabled --project=YOUR_PROJECT_ID --format="value(config.name)"
```

## A5 — Application Default Credentials (~2 min)

Terraform and the local Firestore client authenticate with ADC.

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

ADC is shared by every gcloud configuration: when switching back to another project, run `set-quota-project` again with that project's ID.

## A6 — Spotify app (~15 min)

The account that owns the app needs **Spotify Premium** (Development Mode requirement).

1. In the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) click **Create app**.
2. Fill in:
   - **App name:** `AI Playlist Generator`
   - **App description:** `Conversational playlist builder`
   - **Redirect URIs:** `http://127.0.0.1:8501/`, exactly, trailing slash included, then **Add**. Spotify rejects `localhost`; the production URI is added in Phase E.
   - **APIs used:** **Web API** only.
3. Accept the terms and save.
4. In **Settings** copy the **Client ID**; **View client secret** shows the Client Secret.
5. In **User Management** add every account allowed to log in (name + email, at most 5), yours included. Guest mode works for anyone.

## A7 — Gemini API key (~5 min)

Create the key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) **in a project without billing**, not in `YOUR_PROJECT_ID`: a key in a billed project is charged at paid-tier rates instead of using the free tier.

## A8 — Local configuration (~5 min)

Settings and secrets stay in separate files.

**Settings:** set `gcp.project_id = "YOUR_PROJECT_ID"` and `spotify.client_id = "YOUR_SPOTIFY_CLIENT_ID"` in `config/base.toml`. Both values are public by design and are committed; they must be in place before any image is built.

**Secrets:** create `.env` and write a fresh local Fernet key straight into it, so it never appears on screen:
```bash
cp .env.example .env
sed -i '' "s|^SESSION_ENCRYPTION_KEY=.*|SESSION_ENCRYPTION_KEY=$(.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')|" .env
```
Then open `.env` and paste `GOOGLE_API_KEY` (A7) and `SPOTIFY_CLIENT_SECRET` (A6), without quotes or trailing comments.

> `sed -i ''` is the macOS syntax; on Linux use `sed -i`.

✅ **Check:** prints `3`, i.e. every secret is filled, without printing any value.
```bash
grep -cE '^(GOOGLE_API_KEY|SPOTIFY_CLIENT_SECRET|SESSION_ENCRYPTION_KEY)=.+' .env
```

✅ **Check:** the settings load in both environments.
```bash
.venv/bin/python -c "from src.config.settings import get_settings; print(get_settings().gcp.project_id)"
APP_ENV=production .venv/bin/python -c "from src.config.settings import get_settings; print(get_settings().spotify.client_id)"
```

Next: [Phase B — Core infrastructure](deployment-02-core-infrastructure.md).
