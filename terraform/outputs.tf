# A targeted apply records only outputs whose resource dependencies are all targeted, so
# project_id and sessions_collection read from resources applied with the core infrastructure.

output "project_id" {
  description = "GCP project ID (gcp.project_id in config/base.toml)."
  value       = google_service_account.app.project
}

output "sessions_collection" {
  description = "Firestore collection holding chat sessions (sessions.collection in config/base.toml)."
  value       = google_firestore_field.sessions_ttl.collection
}

output "service_account_email" {
  description = "Email of the Cloud Run runtime service account."
  value       = google_service_account.app.email
}

output "cloud_run_url" {
  description = "Public URL of the Cloud Run service (available after the Phase 7 apply)."
  value       = google_cloud_run_v2_service.app.uri
}

output "custom_domain_mapping_records" {
  description = "DNS records to create at the registrar once the custom domain mapping is applied."
  value = var.custom_domain != "" ? [
    for r in try(google_cloud_run_domain_mapping.custom[0].status[0].resource_records, []) : {
      type   = r.type
      name   = r.name
      rrdata = r.rrdata
    }
  ] : []
}
