# `deploy/`: Cloud Run hosting + GCP integrations

Nengok's normal install path is `pip install nengok` plus a local dashboard
launched via `nengok dashboard`. This directory hosts that same dashboard on
**Cloud Run** and wires it into the GCP products Nengok has standardized on.

- **`Dockerfile`**: multi-stage build that bakes the Vite frontend into
  `nengok/server`'s static mount and runs `nengok dashboard` on `0.0.0.0:8765`.
- **`cloud-run.yaml`**: Cloud Run service manifest (Knative). Three containers:
  the dashboard (`app`), the Cloud SQL Auth Proxy (`cloudsql-proxy`), and the
  Managed Prometheus collector (`collector`) sidecars. CI substitutes the image
  reference and project id at deploy time.
- **`cloud-run-migrations.yaml`**: one-shot Cloud Run job that runs
  `nengok db migrate` against the Cloud SQL instance through the same Auth
  Proxy. The CI deploy step applies it before each service rollout so a failed
  migration aborts the rollout instead of shipping broken schema.
- **`runmonitoring.yaml`**: the scrape config the collector reads (stored in
  Secret Manager, mounted at `/etc/rungmp/config.yaml`).
- **`terraform/cloud_sql.tf`**: Cloud SQL Postgres instance (`nengok-state`),
  the `nengok` database, IAM authentication, and the two role bindings the
  Cloud Run runtime service account needs. Automated backups on with a 7-day
  retention window; durability is the operator's contract.
- **`local/`**: optional docker-compose files for local Postgres / MySQL
  validation, plus Cloud SQL Auth Proxy launcher scripts for connecting a
  laptop to a hosted Cloud SQL instance.

> If you are evaluating Nengok as a user, you can ignore this directory and run
> the dashboard locally.

---

## GCP products in use

| Product | Role | Where |
|---|---|---|
| **Cloud Run** | Hosts the dashboard | `cloud-run.yaml` |
| **Artifact Registry** | Stores the Docker image | CI build/push, `nengok` repo |
| **Vertex AI** | Serves Gemini via the runtime service account (ADC) | `GOOGLE_GENAI_USE_VERTEXAI=true` |
| **Secret Manager** | Supplies the Phoenix key + dashboard token as env vars | `secretKeyRef` bindings |
| **Cloud Logging** | Ingests structured JSON logs (automatic) | `K_SERVICE` → `gcp` log format |
| **Cloud Monitoring** | Scrapes `/metrics` via a Managed Prometheus sidecar | `collector` container |

These map to the 5 items agreed in
[issue #25](https://github.com/waizwafiq/Nengok/issues/25).

---

## One-time setup

Set the shared variables (region matches the CI workflow):

```bash
PROJECT_ID="$(gcloud config get-value project)"
REGION="asia-southeast1"
# Cloud Run's runtime identity. Defaults to the compute SA unless you set one.
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
```

### 1. Enable APIs

```bash
gcloud services enable \
  run.googleapis.com \
  aiplatform.googleapis.com \
  monitoring.googleapis.com \
  logging.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  --project "$PROJECT_ID"
```

### 2. Artifact Registry

The CI workflow pushes to
`${REGION}-docker.pkg.dev/${PROJECT_ID}/nengok/nengok-dashboard:<sha>`. Create
the repo once:

```bash
gcloud artifacts repositories create nengok \
  --repository-format=docker --location="$REGION" --project "$PROJECT_ID"
```

### 3. Secret Manager

Three secrets back the deployment. Gemini needs **no** API key secret because
Vertex authenticates with the runtime service account.

```bash
# Phoenix API key (use your real key, or a placeholder you update later)
printf %s "$PHOENIX_API_KEY_VALUE" | gcloud secrets create nengok-phoenix-api-key --data-file=-

# Dashboard bearer token. Generate a strong random value
openssl rand -hex 24 | gcloud secrets create nengok-dashboard-token --data-file=-

# Managed Prometheus scrape config
gcloud secrets create nengok-gmp-config --data-file=deploy/runmonitoring.yaml
```

### 4. IAM for the runtime service account

```bash
for ROLE in roles/aiplatform.user roles/monitoring.metricWriter roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${RUNTIME_SA}" --role="$ROLE"
done

for SECRET in nengok-phoenix-api-key nengok-dashboard-token nengok-gmp-config; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member="serviceAccount:${RUNTIME_SA}" --role="roles/secretmanager.secretAccessor"
done
```

---

## Deploy

### Via CI (recommended)

Pushing to `main` with changes under `nengok/server/**`, `frontend/**`, or
`deploy/**` triggers `.github/workflows/dashboard-deploy.yml`, which builds and
pushes the image, then renders `cloud-run.yaml` (substituting the image and
`PROJECT_ID`) and applies it with `gcloud run services replace`, followed by an
`allUsers` → `roles/run.invoker` binding for public access. Requires the
`GCP_PROJECT_ID`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, and `GCP_SERVICE_ACCOUNT`
repo secrets.

### Manually

```bash
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/nengok/nengok-dashboard:manual"

# Build with deploy/Dockerfile via Cloud Build (no local Docker required)
cat > /tmp/cloudbuild.yaml <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build", "-f", "deploy/Dockerfile", "-t", "${IMAGE}", "."]
images: ["${IMAGE}"]
EOF
gcloud builds submit --config /tmp/cloudbuild.yaml .

# Render + deploy the manifest
sed -e "s|REPLACED_BY_CI|${IMAGE}|g" -e "s|PROJECT_ID|${PROJECT_ID}|g" \
  deploy/cloud-run.yaml > /tmp/cloud-run.yaml
gcloud run services replace /tmp/cloud-run.yaml --region "$REGION"
gcloud run services add-iam-policy-binding nengok-dashboard \
  --region "$REGION" --member=allUsers --role=roles/run.invoker
```

---

## How each integration works

**Vertex AI.** The service sets `GOOGLE_GENAI_USE_VERTEXAI=true`,
`GOOGLE_CLOUD_PROJECT`, and `GOOGLE_CLOUD_LOCATION=global`. The `google-genai`
SDK then talks to Vertex using Application Default Credentials (the runtime
service account), so no Gemini API key is needed and traffic stays inside GCP.
Locally, set the same env vars or `gemini_use_vertex = true` /
`vertex_project = "…"` in `~/.nengok/config.toml` and run
`gcloud auth application-default login`. AI Studio (`GOOGLE_API_KEY`) remains
the default when the flag is off.

**Secret Manager.** `PHOENIX_API_KEY` and `NENGOK_DASHBOARD_AUTH_TOKEN` are
bound from secrets via `secretKeyRef`. The app keeps reading plain env vars, so
there is no app-code dependency on Secret Manager. Setting the dashboard token
makes `/api/v1/*` require `Authorization: Bearer <token>`; `/health` stays
public for the liveness probe.

**Cloud Logging.** Cloud Run sets `K_SERVICE`, which makes the CLI emit
Cloud-Logging-parseable JSON (a top-level `severity` field) to stderr. Cloud
Run forwards it automatically, no agent required. Override with
`NENGOK_LOG_FORMAT=text|json|gcp`.

**Cloud Monitoring.** The `collector` sidecar (Google's
`cloud-run-gmp-sidecar`) scrapes `localhost:8765/metrics` per
`runmonitoring.yaml` and writes to Managed Service for Prometheus. Series appear
under `prometheus.googleapis.com/nengok_*`. `NENGOK_METRICS_ENABLED=true` (set in
the manifest) mounts the `/metrics` endpoint. **Note:** the Cloud Run GMP
integration is launch-stage **ALPHA**; pin and re-verify the sidecar image tag
and `RunMonitoring` schema when upgrading.

Suggested alerts: cycle failures (`nengok_cycles_total{status!="ok"}`), token
burn (`nengok_gemini_tokens_total`), stage latency
(`nengok_cycle_duration_seconds`), and probe failures
(`run.googleapis.com/container/probe/failure_count`).

---

## Roadmap note

Per the issue #25 discussion, the remaining GCP products are deferred:

- **v0.2+ candidates:** GCS for artifacts, Cloud Scheduler / Pub/Sub / Eventarc
  (event-driven watch), IAP (replacing bearer auth), Cloud Armor, Cloud Build
  triggers, and Vertex AI Pipelines.

State persistence on Cloud SQL Postgres is no longer on this list: it lands in
v0.1 via `terraform/cloud_sql.tf` and the Auth Proxy sidecar above.
