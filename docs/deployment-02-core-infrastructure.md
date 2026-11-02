# Phase B — Core Infrastructure (Terraform)

**Goal:** Firestore in Native mode with the session TTL policy, deny-all security rules and the runtime service account with Firestore access.

**Estimated time:** ~20 min, most of it waiting for the TTL policy.

## B1 — Initialize Terraform (~1–2 min)

```bash
terraform -chdir=terraform init
```

## B2 — Apply the core resources (~10–15 min)

```bash
terraform -chdir=terraform apply \
  -target=google_project_service.firebaserules \
  -target=google_project_service.secretmanager \
  -target=google_firestore_database.main \
  -target=google_firestore_field.sessions_ttl \
  -target=google_firebaserules_ruleset.firestore \
  -target=google_firebaserules_release.firestore \
  -target=google_service_account.app \
  -target=google_project_iam_member.datastore_user \
  -var="project_id=YOUR_PROJECT_ID"
```

- The plan shows **8 to add**. The *"Resource targeting is in effect"* warnings are expected.
- `google_firestore_field.sessions_ttl` is the slow one: about 6 minutes of *"Still creating…"* is normal.
- The Firestore location (`us-central1`, an Always Free region) cannot be changed after creation.

Back up `terraform/terraform.tfstate` once the apply completes.

## Verification (~2 min)

✅ The outputs show your project ID and `sessions_collection = "sessions"` (it must match `sessions.collection` in `config/base.toml`):
```bash
terraform -chdir=terraform output
```

✅ The configuration is valid:
```bash
terraform -chdir=terraform validate
```

✅ The TTL policy on `expires_at` is `ACTIVE` (`CREATING` is fine too: it becomes active on its own):
```bash
gcloud firestore fields ttls list --database="(default)" --project=YOUR_PROJECT_ID
```

Next: [Phase C — Local verification](deployment-03-local-verification.md).
