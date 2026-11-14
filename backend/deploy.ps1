# Build the web app, then deploy the API and site to Modal. Run from anywhere:
#   .\backend\deploy.ps1
# Set $env:MEMEPEDIA_APP = "memepedia-staging" first to deploy a throwaway copy instead of the live app.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

Push-Location (Join-Path $repo "web")
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    # Empty overrides web/.env.local, so the site calls the API on its own origin.
    $env:VITE_API_BASE = ""
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "web build failed" }
} finally { Pop-Location }

Push-Location (Join-Path $repo "backend")
try {
    uv run --with modal modal deploy deploy.py
    if ($LASTEXITCODE -ne 0) { throw "modal deploy failed" }
} finally { Pop-Location }
