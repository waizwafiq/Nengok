#!/usr/bin/env bash
# Download a pinned cloud-sql-proxy binary and run it against the
# Cloud SQL instance named in CLOUD_SQL_INSTANCE_CONNECTION_NAME.
#
# The proxy binds 127.0.0.1:5432 so Nengok can talk to a hosted
# Cloud SQL Postgres instance through a local loopback. Pair with a
# DATABASE_URL of the form:
#   postgresql+psycopg://nengok-runtime%40<project>.iam@127.0.0.1:5432/nengok?sslmode=disable
# The 127.0.0.1 host is loopback so the Phase 14.3 TLS guard rewrites
# nothing; IAM auth is end-to-end inside the proxy.
#
# Required GCP roles on the calling principal:
#   roles/cloudsql.client
#   roles/cloudsql.instanceUser
#
# Run `gcloud auth application-default login` once before invoking
# this script. The proxy reads ADC for IAM authentication.

set -euo pipefail

PROXY_VERSION="${CLOUD_SQL_PROXY_VERSION:-2.13.0}"
INSTANCE="${CLOUD_SQL_INSTANCE_CONNECTION_NAME:?CLOUD_SQL_INSTANCE_CONNECTION_NAME is required (project:region:instance)}"
BIND_ADDR="${CLOUD_SQL_PROXY_BIND_ADDR:-127.0.0.1}"
BIND_PORT="${CLOUD_SQL_PROXY_PORT:-5432}"

BIN_DIR="${HOME}/.nengok/bin"
mkdir -p "${BIN_DIR}"

uname_s="$(uname -s)"
uname_m="$(uname -m)"

case "${uname_s}" in
    Linux*)  os_label="linux" ;;
    Darwin*) os_label="darwin" ;;
    *)
        echo "Unsupported OS: ${uname_s}" >&2
        exit 1
        ;;
esac

case "${uname_m}" in
    x86_64|amd64) arch_label="amd64" ;;
    arm64|aarch64) arch_label="arm64" ;;
    *)
        echo "Unsupported arch: ${uname_m}" >&2
        exit 1
        ;;
esac

BIN_NAME="cloud-sql-proxy-${PROXY_VERSION}-${os_label}-${arch_label}"
BIN_PATH="${BIN_DIR}/${BIN_NAME}"

if [[ ! -x "${BIN_PATH}" ]]; then
    download_url="https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v${PROXY_VERSION}/cloud-sql-proxy.${os_label}.${arch_label}"
    echo "Downloading cloud-sql-proxy ${PROXY_VERSION} for ${os_label}/${arch_label}..."
    curl -fSL "${download_url}" -o "${BIN_PATH}"
    chmod +x "${BIN_PATH}"
fi

echo "Starting cloud-sql-proxy ${PROXY_VERSION}"
echo "  instance: ${INSTANCE}"
echo "  bind:     ${BIND_ADDR}:${BIND_PORT}"
echo "  iam-auth: enabled"

exec "${BIN_PATH}" \
    --auto-iam-authn \
    --address "${BIND_ADDR}" \
    --port "${BIND_PORT}" \
    "${INSTANCE}"
