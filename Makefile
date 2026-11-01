.PHONY: run test-unit test-integration test-smoke test docker-build docker-run docker-push tf-apply

# ── Variables (override on the command line; defaults are read from config/base.toml) ─
PYTHON        := .venv/bin/python
CONFIG_FILE   := config/base.toml
# Read one "section.key" value from CONFIG_FILE (empty when the file or the key is missing).
config_value   = $(shell $(PYTHON) -c "import sys, tomllib; s, k = sys.argv[1].split('.'); print(tomllib.load(open('$(CONFIG_FILE)', 'rb')).get(s, {}).get(k, ''))" $(1) 2>/dev/null)
PROJECT_ID    ?= $(call config_value,gcp.project_id)
SESSIONS_COLLECTION ?= $(call config_value,sessions.collection)
REGION        ?= us-central1
IMAGE_NAME    ?= playlist-generator
IMAGE_URL     ?= $(REGION)-docker.pkg.dev/$(PROJECT_ID)/$(IMAGE_NAME)/$(IMAGE_NAME):latest
CUSTOM_DOMAIN ?=

## Start the Streamlit app locally (requires the secrets in .env and a complete config/base.toml).
## The printed URL uses the loopback IP: Spotify rejects localhost redirect URIs and
## localStorage is per-origin, so always open http://127.0.0.1:8501.
run:
	$(PYTHON) -m streamlit run app.py --browser.serverAddress=127.0.0.1

## Run all unit tests (offline, no credentials required)
test-unit:
	$(PYTHON) -m pytest tests/unit/ -v

## Run all integration tests (requires .env, a complete config/base.toml and ADC)
test-integration:
	$(PYTHON) -m pytest tests/integration/ -v

## Run smoke tests against the live URL (the https:// spotify.redirect_uri in config/production.toml)
test-smoke:
	$(PYTHON) -m pytest tests/integration/test_smoke.py -v

## Run the full test suite (unit + integration)
test:
	$(PYTHON) -m pytest tests/ -v

## Build the Docker image locally
docker-build:
	docker build -t $(IMAGE_NAME):local .

## Run the Docker image locally: secrets from .env, settings from the config/ baked into the image.
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
## App settings ship inside the image (config/), so Terraform only needs the infrastructure inputs.
## With a custom domain always pass CUSTOM_DOMAIN, or the apply destroys the domain mapping.
tf-apply:
	cd terraform && terraform apply \
		-var="project_id=$(PROJECT_ID)" \
		-var="image_url=$(IMAGE_URL)" \
		-var="sessions_collection=$(SESSIONS_COLLECTION)" \
		-var="custom_domain=$(CUSTOM_DOMAIN)"
