# Deployment Troubleshooting

Problems met during the first deployment, with their cause and fix. Each entry starts from the symptom you would see.

## Intent gate always fails open

**Symptom:** every message logs
`Intent gate failed open (GoogleInvalidRequestError): … 400 INVALID_ARGUMENT … Manually set deadline 3s is too short. Minimum allowed deadline is 10s.`
The off-topic integration tests fail, while off-topic requests still get declined (by Gemini).

**Cause:** `google-genai` sends the client timeout as the `X-Server-Timeout` deadline header, and the Gemini API rejects deadlines under 10 seconds. With a 3-second timeout the gate never got an answer.

**Fix (in the code):** `src/guards/intent_gate.py` sets `X-Server-Timeout: 10` explicitly. The library only derives the header when it is absent, so the client-side timeout stays at 3 seconds while the server receives a valid deadline.

## A study-related music request is blocked

**Symptom:** with the gate working, *"I need to focus on my maths homework tonight"* is sometimes classified `OUT`.

**Cause:** the gate prompt listed "homework or maths" among the off-topic examples, so a message that only describes an activity looked off-topic.

**Fix (in the code):** the prompt in `src/guards/gate_prompt.py` now blocks requests to *solve* homework or maths problems and explicitly lets through messages that only describe what the user is doing or feeling.

## Off-topic tests fail after several runs

**Symptom:** `429 RESOURCE_EXHAUSTED … limit: 30, model: gemma-4-26b` in the test log, then off-topic tests fail.

**Cause:** Gemma's free tier allows 30 requests per minute per project; one run of the gate tests sends about a dozen.

**Fix:** wait a minute between runs. In production the gate fails open on `429`, by design.

## CPU always allocated

**Symptom:** `gcloud run services describe … | grep cpu-throttling` shows `'false'`.

**Cause:** in `google_cloud_run_v2_service`, `cpu_idle` defaults to `true` only when the `resources` block is absent. Setting `limits` without `cpu_idle` switches the service to always-on CPU and instance-based billing, so an instance is billed for its whole lifetime, idle time included.

**Fix (in Terraform):** `cpu_idle = true` next to the limits, then a targeted apply of the service:
```bash
terraform -chdir=terraform apply -target=google_cloud_run_v2_service.app -var="project_id=YOUR_PROJECT_ID" -var="image_url=us-central1-docker.pkg.dev/YOUR_PROJECT_ID/playlist-generator/playlist-generator:latest"
```
The plan shows `~ cpu_idle = false -> true` and **1 to change**.

## `maxScale: '20'` on the service

**Symptom:** the service metadata shows `run.googleapis.com/maxScale: '20'` while Terraform sets a maximum of 1 instance.

**Cause:** that is the service-level limit; Terraform sets the revision-level one (`autoscaling.knative.dev/maxScale: '1'`).

**Fix:** none needed: Cloud Run applies the lower of the two, so the effective limit is 1.

## Two different service URLs

**Symptom:** Terraform prints `…-<hash>-uc.a.run.app`, `gcloud` prints `…-<project-number>.us-central1.run.app`.

**Cause:** Cloud Run exposes both a legacy and a deterministic URL for the same service.

**Fix:** none on the infrastructure; use a single canonical URL everywhere ([Phase E1](deployment-05-production-release.md#e1--pick-the-canonical-url-1-min)).

## Docker build: invalid signature

**Symptom:** `apt-get update` fails with *"At least one invalid signature was encountered"* and *"The repository … is not signed"*.

**Cause:** with Docker Desktop this is almost always a full VM disk or a skewed VM clock, more rarely a VPN, proxy or antivirus altering plain-HTTP traffic to `deb.debian.org`.

**Fix:** check both:
```bash
docker system df
date -u && docker run --rm python:3.12.13-slim-bookworm sh -c 'date -u && df -h /'
```
A full disk: `docker builder prune -f` (removes only the build cache) or raise the disk limit in Docker Desktop → Settings → Resources. A skewed clock (dates minutes apart): restart Docker Desktop. Otherwise disable VPN or traffic filtering and retry.

## Slow Docker builds

**Symptom:** the build runs for tens of minutes; `pip install -r requirements.txt` downloads at a few tens of kB/s. A log quiet for minutes is normal in that state: pip prints a progress line only when a file completes.

**Diagnose:** rerun with full output saved to a git-ignored log:
```bash
docker build --progress=plain -t playlist-generator:local . 2>&1 | tee docker-build.log
```

**Fix:** the amd64 production build downloads every wheel again and pushes about 250 MB, so on a slow link use Cloud Build ([Phase D3, Option 2](deployment-04-cloud-run.md#d3--production-image-linuxamd64)) or retry on a faster connection. Later releases reuse the cached dependency layers and are fast.

## `gh secret set` fails with HTTP 404

**Symptom:** `failed to fetch public key: HTTP 404: Not Found (…/actions/secrets/public-key)`.

**Cause:** the GitHub repository does not exist yet, or `--repo` points to the wrong one.

**Fix:** create the repository first (with the name allowed by the `github_repo` Terraform variable), then rerun [Phase E4](deployment-05-production-release.md#continuous-deployment-github-actions). Until then, release manually.

## Gemini turns slower than NFR-01

**Symptom:** `LLM turn took 10–17s` in the logs, `UserWarning … above NFR-01` in the integration tests, occasionally `503 UNAVAILABLE … high demand` followed by an automatic retry.

**Cause:** model-side latency and load on the free tier; not a deployment problem.

**Fix:** none in the deployment. Track it as a product issue if it persists.
