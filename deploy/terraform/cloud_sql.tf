###############################################################################
# Cloud SQL Postgres instance for the Nengok state store.
#
# Provisions one Cloud SQL Postgres instance (`nengok-state`), one logical
# database (`nengok`), IAM-based authentication, and the two role bindings the
# Cloud Run runtime service account needs to connect through the Auth Proxy.
# Automated backups are on with a 7-day retention window so durability is the
# operator's contract, not Nengok's.
###############################################################################

variable "project_id" {
  description = "GCP project id that owns the Cloud SQL instance and the Cloud Run service."
  type        = string
}

variable "region" {
  description = "Region for the Cloud SQL instance. Matches the existing Cloud Run service."
  type        = string
  default     = "asia-southeast1"
}

variable "runtime_service_account_email" {
  description = "Cloud Run runtime service account that authenticates to Cloud SQL via IAM."
  type        = string
  default     = "nengok-runtime@PROJECT_ID.iam.gserviceaccount.com"
}

variable "tier" {
  description = "Instance tier. db-f1-micro is the hackathon-demo footprint; upsize for production."
  type        = string
  default     = "db-f1-micro"
}

variable "backup_start_time" {
  description = "UTC start time for the daily automated backup window."
  type        = string
  default     = "17:00"
}

resource "google_sql_database_instance" "nengok_state" {
  name             = "nengok-state"
  project          = var.project_id
  region           = var.region
  database_version = "POSTGRES_16"

  deletion_protection = true

  settings {
    tier              = var.tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = 10
    disk_autoresize   = true

    backup_configuration {
      enabled                        = true
      start_time                     = var.backup_start_time
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }
    }

    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = null
      ssl_mode        = "ENCRYPTED_ONLY"
    }
  }
}

resource "google_sql_database" "nengok" {
  name     = "nengok"
  instance = google_sql_database_instance.nengok_state.name
  project  = var.project_id
  charset  = "UTF8"
}

resource "google_sql_user" "runtime_iam" {
  name     = trimsuffix(var.runtime_service_account_email, ".gserviceaccount.com")
  instance = google_sql_database_instance.nengok_state.name
  project  = var.project_id
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}

resource "google_project_iam_member" "cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${var.runtime_service_account_email}"
}

resource "google_project_iam_member" "cloudsql_instance_user" {
  project = var.project_id
  role    = "roles/cloudsql.instanceUser"
  member  = "serviceAccount:${var.runtime_service_account_email}"
}

output "instance_connection_name" {
  description = "Pass to cloud-sql-proxy as the positional instance argument."
  value       = google_sql_database_instance.nengok_state.connection_name
}

output "database_url_iam" {
  description = "DATABASE_URL for Nengok pods talking through the Auth Proxy sidecar."
  value       = "postgresql+psycopg://${replace(google_sql_user.runtime_iam.name, "@", "%40")}@127.0.0.1:5432/${google_sql_database.nengok.name}?sslmode=disable"
}
