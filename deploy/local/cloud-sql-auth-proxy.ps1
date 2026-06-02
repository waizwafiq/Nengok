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

$ErrorActionPreference = "Stop"

$ProxyVersion = if ($env:CLOUD_SQL_PROXY_VERSION) { $env:CLOUD_SQL_PROXY_VERSION } else { "2.13.0" }
$Instance = $env:CLOUD_SQL_INSTANCE_CONNECTION_NAME
if (-not $Instance) {
    Write-Error "CLOUD_SQL_INSTANCE_CONNECTION_NAME is required (project:region:instance)"
    exit 1
}
$BindAddr = if ($env:CLOUD_SQL_PROXY_BIND_ADDR) { $env:CLOUD_SQL_PROXY_BIND_ADDR } else { "127.0.0.1" }
$BindPort = if ($env:CLOUD_SQL_PROXY_PORT) { $env:CLOUD_SQL_PROXY_PORT } else { "5432" }

$BinDir = Join-Path $env:USERPROFILE ".nengok\bin"
if (-not (Test-Path $BinDir)) {
    New-Item -ItemType Directory -Path $BinDir | Out-Null
}

$Arch = if ([Environment]::Is64BitOperatingSystem) { "amd64" } else { "386" }
$BinName = "cloud-sql-proxy-$ProxyVersion-windows-$Arch.exe"
$BinPath = Join-Path $BinDir $BinName

if (-not (Test-Path $BinPath)) {
    $DownloadUrl = "https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v$ProxyVersion/cloud-sql-proxy-x64.exe"
    Write-Host "Downloading cloud-sql-proxy $ProxyVersion for windows/$Arch..."
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $BinPath -UseBasicParsing
}

Write-Host "Starting cloud-sql-proxy $ProxyVersion"
Write-Host "  instance: $Instance"
Write-Host "  bind:     ${BindAddr}:${BindPort}"
Write-Host "  iam-auth: enabled"

& $BinPath --auto-iam-authn --address $BindAddr --port $BindPort $Instance
exit $LASTEXITCODE
