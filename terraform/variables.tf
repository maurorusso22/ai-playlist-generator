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
  description = "Firestore collection holding chat sessions and the expires_at TTL field."
  type        = string
  default     = "sessions"
}

variable "llm_model" {
  description = "Gemini model id passed to Cloud Run as LLM_MODEL."
  type        = string
  default     = "gemini-3.5-flash-lite"
}

variable "intent_model" {
  description = "Gemma model id of the intent gate, passed to Cloud Run as INTENT_MODEL."
  type        = string
  default     = "gemma-4-26b-a4b-it"
}

# Cloud Run-only inputs default to "" so the targeted core applies need only project_id;
# a precondition on google_cloud_run_v2_service.app rejects empty values when it is applied.

variable "image_url" {
  description = "Container image URL for Cloud Run (Artifact Registry); Cloud Run only."
  type        = string
  default     = ""
}

variable "spotify_client_id" {
  description = "Spotify app Client ID passed to Cloud Run as SPOTIFY_CLIENT_ID; Cloud Run only."
  type        = string
  default     = ""
}

variable "spotify_redirect_uri" {
  description = "OAuth redirect URI passed to Cloud Run as SPOTIFY_REDIRECT_URI; Cloud Run only."
  type        = string
  default     = ""

  # Same rule as src/config.py: Spotify rejects localhost and plain HTTP except loopback IPs.
  validation {
    condition = (
      var.spotify_redirect_uri == ""
      || can(regex("^(https://.+|http://127\\.0\\.0\\.1:[0-9]+/.*)$", var.spotify_redirect_uri))
    )
    error_message = "spotify_redirect_uri must be https://... or http://127.0.0.1:<port>/... (never localhost)."
  }
}

variable "spotify_market" {
  description = "ISO 3166-1 alpha-2 country code used for Spotify catalog search."
  type        = string
  default     = "IT"

  validation {
    condition     = can(regex("^[A-Z]{2}$", var.spotify_market))
    error_message = "spotify_market must be a two-letter uppercase country code (e.g. IT)."
  }
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
