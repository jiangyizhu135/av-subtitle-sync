# AV Subtitle Sync - Windows setup helper.
# Only: check python, create .venv, install package, copy example config.
# It never touches the registry, Defender, ExecutionPolicy, or downloads binaries.

$ErrorActionPreference = "Stop"

python --version
if ($LASTEXITCODE -ne 0) { Write-Error "Python not found on PATH"; exit 1 }

py -3.11 -m venv .venv
if ($LASTEXITCODE -ne 0) { python -m venv .venv }

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .

if (-Not (Test-Path ".env") -And (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Copied .env.example -> .env (fill in your WebDAV credentials)."
}

Write-Host ""
Write-Host "Done. Run instead of activating if scripts are blocked:"
Write-Host "  .\.venv\Scripts\python.exe -m subsync doctor"
Write-Host "  .\.venv\Scripts\subsync.exe doctor"
