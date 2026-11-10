terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  app_name      = "playlist-generator" # Runtime SA, Artifact Registry repo and Cloud Run service name
  deployer_name = "playlist-deployer"  # CI/CD deploy SA impersonated by GitHub Actions

  # Secrets are created with gcloud, so their values never enter the Terraform state.
  secret_ids = {
    api_key                = "GOOGLE_API_KEY"         # Gemini API key
    spotify_client_secret  = "SPOTIFY_CLIENT_SECRET"  # Spotify app Client Secret
    session_encryption_key = "SESSION_ENCRYPTION_KEY" # Fernet key for Spotify tokens at rest
    anthropic_api_key      = "ANTHROPIC_API_KEY"      # Claude API key (llm.provider = "claude")
  }

  # App settings ship in the image (config/*.toml); this only selects config/production.toml.
  plain_env = {
    APP_ENV = "production" # Overlay applied on top of config/base.toml
  }
}

# ── APIs ───────────────────────────────────────────────────────────────────────
# The remaining APIs (firestore, iam, run, artifactregistry) are enabled once with gcloud.

resource "google_project_service" "firebaserules" {
  project            = var.project_id
  service            = "firebaserules.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "secretmanager" {
  project            = var.project_id
  service            = "secretmanager.googleapis.com"
  disable_on_destroy = false
}

# ── Firestore (session store) ─────────────────────────────────────────────────

resource "google_firestore_database" "main" {
  project                 = var.project_id
  name                    = "(default)"
  location_id             = var.region
  type                    = "FIRESTORE_NATIVE"
  delete_protection_state = "DELETE_PROTECTION_DISABLED"
}

# TTL is garbage collection only (deletes within ~24 h); the app enforces expiry on every read.
resource "google_firestore_field" "sessions_ttl" {
  project    = var.project_id
  database   = google_firestore_database.main.name
  collection = var.sessions_collection
  field      = "expires_at"

  ttl_config {}

  # Sessions are only read by document id, so the timestamp needs no single-field index.
  index_config {}

  depends_on = [google_firestore_database.main]
}

# ── Firestore Security Rules ───────────────────────────────────────────────────
# The app uses the server-side SDK, which bypasses rules, so all client access is denied.

resource "google_firebaserules_ruleset" "firestore" {
  project = var.project_id

  source {
    files {
      name    = "firestore.rules"
      content = <<-EOT
        rules_version = '2';
        service cloud.firestore {
          match /databases/{database}/documents {
            match /{document=**} {
              allow read, write: if false;
            }
          }
        }
      EOT
    }
  }

  depends_on = [
    google_firestore_database.main,
    google_project_service.firebaserules,
  ]
}

resource "google_firebaserules_release" "firestore" {
  project      = var.project_id
  name         = "cloud.firestore"
  ruleset_name = google_firebaserules_ruleset.firestore.name

  # A ruleset cannot be deleted while a release points to it, so the release is recreated with it.
  lifecycle {
    replace_triggered_by = [google_firebaserules_ruleset.firestore]
  }
}

# ── Runtime identity ───────────────────────────────────────────────────────────

resource "google_service_account" "app" {
  project      = var.project_id
  account_id   = local.app_name
  display_name = "Playlist Generator Service Account"
  description  = "Cloud Run runtime identity: Firestore sessions and the app secrets."
}

resource "google_project_iam_member" "datastore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.app.email}"
}

# ── Secret Manager access ──────────────────────────────────────────────────────
# Bindings reference the secrets by name, so the secrets must exist before these are applied.

resource "google_secret_manager_secret_iam_member" "app_api_key" {
  project   = var.project_id
  secret_id = local.secret_ids.api_key
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret_iam_member" "app_spotify_client_secret" {
  project   = var.project_id
  secret_id = local.secret_ids.spotify_client_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret_iam_member" "app_session_encryption_key" {
  project   = var.project_id
  secret_id = local.secret_ids.session_encryption_key
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret_iam_member" "app_anthropic_api_key" {
  project   = var.project_id
  secret_id = local.secret_ids.anthropic_api_key
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"

  depends_on = [google_project_service.secretmanager]
}

# ── Artifact Registry (applied in Phase 7) ─────────────────────────────────────
# Cleanup keeps the newest 2 versions to stay within the 0.5 GB free storage; KEEP wins over DELETE.

resource "google_artifact_registry_repository" "app" {
  project                = var.project_id
  location               = var.region
  repository_id          = local.app_name
  description            = "Container images for the Playlist Generator Cloud Run service."
  format                 = "DOCKER"
  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "keep-2-most-recent"
    action = "KEEP"

    most_recent_versions {
      keep_count = 2
    }
  }

  cleanup_policies {
    id     = "delete-the-rest"
    action = "DELETE"

    condition {
      tag_state = "ANY"
    }
  }
}

# ── Cloud Run (applied in Phase 7, once image_url exists) ──────────────────────

resource "google_cloud_run_v2_service" "app" {
  project  = var.project_id
  name     = local.app_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.app.email

    # Streamlit keeps one WebSocket per tab and Cloud Run caps every request at this timeout.
    timeout          = "3600s"
    session_affinity = true

    # max 1 instance bounds the bill (NFR-08); min 0 scales to zero when idle.
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.image_url

      ports {
        container_port = 8501
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        # Request-based billing: with explicit limits the provider defaults to always-on CPU.
        cpu_idle = true
      }

      dynamic "env" {
        for_each = local.plain_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.secret_ids
        content {
          name = env.value
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = var.image_url != ""
      error_message = "Cloud Run needs a non-empty image_url."
    }

    # CI deploys new images with gcloud, which must not show up as Terraform drift.
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [
    google_artifact_registry_repository.app,
    google_secret_manager_secret_iam_member.app_api_key,
    google_secret_manager_secret_iam_member.app_spotify_client_secret,
    google_secret_manager_secret_iam_member.app_session_encryption_key,
    google_secret_manager_secret_iam_member.app_anthropic_api_key,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── CI/CD deploy identity (applied in Phase 7) ─────────────────────────────────
# Separate from the runtime SA, so a compromised container cannot push images or deploy
# revisions. Every grant is scoped to the single resource the deploy touches.

resource "google_service_account" "deployer" {
  project      = var.project_id
  account_id   = local.deployer_name
  display_name = "Playlist Generator Deployer"
  description  = "GitHub Actions deploy identity: pushes images and deploys Cloud Run revisions."
}

resource "google_artifact_registry_repository_iam_member" "deployer_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.app.location
  repository = google_artifact_registry_repository.app.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_cloud_run_v2_service_iam_member" "deployer_developer" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

# Deploying a revision that runs as the runtime SA requires actAs on that SA.
resource "google_service_account_iam_member" "deployer_act_as_app" {
  service_account_id = google_service_account.app.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

# ── Workload Identity Federation (GitHub Actions → GCP, applied in Phase 7) ────
# Keyless CI: GitHub OIDC tokens from the allowed repository impersonate the deployer SA.

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"
  description               = "OIDC pool for GitHub Actions CI/CD."
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
  }

  # Without a condition any GitHub repository could exchange tokens in this pool.
  attribute_condition = "assertion.repository == '${var.github_repo}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_actions_impersonate" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}

# ── Custom domain (optional, Phase 7) ──────────────────────────────────────────
# The domain must be verified in Google Search Console first; the managed TLS cert is free.

resource "google_cloud_run_domain_mapping" "custom" {
  count    = var.custom_domain != "" ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = var.custom_domain

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.app.name
  }

  depends_on = [google_cloud_run_v2_service.app]
}
