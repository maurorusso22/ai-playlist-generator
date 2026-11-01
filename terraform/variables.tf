variable "project_id" {
  description = "GCP project ID where all resources are provisioned."
  type        = string
}

variable "region" {
  description = "GCP region for Firestore, Artifact Registry and Cloud Run (an Always Free region)."
  type        = string
  default     = "us-central1"
}

variable "sessions_collection" {
  description = "Firestore collection with the expires_at TTL field; must match sessions.collection in config/base.toml."
  type        = string
  default     = "sessions"
}

# image_url defaults to "" so the targeted core applies need only project_id;
# a precondition on google_cloud_run_v2_service.app rejects an empty value when it is applied.

variable "image_url" {
  description = "Container image URL for Cloud Run (Artifact Registry); Cloud Run only."
  type        = string
  default     = ""
}

variable "github_repo" {
  description = "GitHub repository (owner/repo) allowed to deploy through Workload Identity Federation."
  type        = string
  default     = "maurorusso22/ai-playlist-generator"
}

variable "custom_domain" {
  description = "Verified custom domain mapped to Cloud Run; leave empty to skip the domain mapping."
  type        = string
  default     = ""
}
