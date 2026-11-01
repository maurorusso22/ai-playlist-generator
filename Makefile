.PHONY: run test-unit test-integration test-smoke test docker-build docker-run docker-push tf-apply

# ── Variables (override on the command line; defaults are read from .env) ────
PYTHON        := .venv/bin/python
PROJECT_ID    ?= $(shell grep -E '^GCP_PROJECT_ID=' .env 2>/dev/null | cut -d= -f2-)
REGION        ?= us-central1
IMAGE_NAME    ?= playlist-generator
IMAGE_URL     ?= $(REGION)-docker.pkg.dev/$(PROJECT_ID)/$(IMAGE_NAME)/$(IMAGE_NAME):latest
LLM_MODEL     ?= $(or $(shell grep -E '^LLM_MODEL=' .env 2>/dev/null | cut -d= -f2-),gemini-3.5-flash-lite)
INTENT_MODEL  ?= $(or $(shell grep -E '^INTENT_MODEL=' .env 2>/dev/null | cut -d= -f2-),gemma-4-26b-a4b-it)
SPOTIFY_CLIENT_ID ?= $(shell grep -E '^SPOTIFY_CLIENT_ID=' .env 2>/dev/null | cut -d= -f2-)
REDIRECT_URI  ?= $(shell grep -E '^SPOTIFY_REDIRECT_URI=' .env 2>/dev/null | cut -d= -f2-)
CUSTOM_DOMAIN ?=

## Start the Streamlit app locally (requires a populated .env file).
## The printed URL uses the loopback IP: Spotify rejects localhost redirect URIs and
## localStorage is per-origin, so always open http://127.0.0.1:8501.
run:
	$(PYTHON) -m streamlit run app.py --browser.serverAddress=127.0.0.1

## Run all unit tests (offline, no credentials required)
test-unit:
	$(PYTHON) -m pytest tests/unit/ -v

## Run all integration tests (requires a populated .env and ADC)
test-integration:
	$(PYTHON) -m pytest tests/integration/ -v

## Run smoke tests against the live Cloud Run URL (requires CLOUD_RUN_URL in .env)
test-smoke:
	$(PYTHON) -m pytest tests/integration/test_smoke.py -v

## Run the full test suite (unit + integration)
test:
	$(PYTHON) -m pytest tests/ -v

## Build the Docker image locally
docker-build:
	docker build -t $(IMAGE_NAME):local .

## Run the Docker image locally.
## Mounts Application Default Credentials (ADC) read-only, so the Firestore client inside
## the container authenticates without a service account key.
## Prerequisite: run `gcloud auth application-default login` once on your host.
docker-run:
	docker run --rm -p 127.0.0.1:8501:8501 \
	  --env-file .env \
	  -e GOOGLE_APPLICATION_CREDENTIALS=/tmp/adc.json \
	  -v "$(HOME)/.config/gcloud/application_default_credentials.json:/tmp/adc.json:ro" \
	  $(IMAGE_NAME):local

## Build for linux/amd64 (Cloud Run's platform, whatever the host) and push to Artifact Registry.
## Prerequisite: `gcloud auth configure-docker $(REGION)-docker.pkg.dev`
docker-push:
	docker build --platform linux/amd64 -t $(IMAGE_URL) .
	docker push $(IMAGE_URL)

## Full Terraform apply, for use after the first deployment (see README "Deployment on GCP").
## Override REDIRECT_URI with the canonical https:// URL once the service exists.
## With a custom domain always pass CUSTOM_DOMAIN, or the apply destroys the domain mapping.
tf-apply:
	cd terraform && terraform apply \
		-var="project_id=$(PROJECT_ID)" \
		-var="image_url=$(IMAGE_URL)" \
		-var="llm_model=$(LLM_MODEL)" \
		-var="intent_model=$(INTENT_MODEL)" \
		-var="spotify_client_id=$(SPOTIFY_CLIENT_ID)" \
		-var="spotify_redirect_uri=$(REDIRECT_URI)" \
		-var="custom_domain=$(CUSTOM_DOMAIN)"
