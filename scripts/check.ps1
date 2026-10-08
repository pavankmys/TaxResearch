# Code quality check script for Windows PowerShell
# Runs ruff, mypy, and pytest
# Fails on first error

$ErrorActionPreference = "Stop"

Write-Host "TaxResearch: Code quality checks" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green

# Check if .venv exists
if (-not (Test-Path ".venv")) {
    Write-Host "Error: .venv not found. Run: python -m venv .venv" -ForegroundColor Red
    exit 1
}

$python = ".\.venv\Scripts\python"
$ruff = ".\.venv\Scripts\ruff"
$mypy = ".\.venv\Scripts\mypy"
$pytest = ".\.venv\Scripts\pytest"

# 1. Ruff lint
Write-Host "`nRunning ruff check..." -ForegroundColor Cyan
& $ruff check .
if ($LASTEXITCODE -ne 0) {
    Write-Host "Ruff check failed" -ForegroundColor Red
    exit 1
}

# 2. Ruff format check
Write-Host "`nRunning ruff format check..." -ForegroundColor Cyan
& $ruff format --check .
if ($LASTEXITCODE -ne 0) {
    Write-Host "Ruff format check failed" -ForegroundColor Red
    exit 1
}

# 3. MyPy type check
Write-Host "`nRunning mypy..." -ForegroundColor Cyan
& $mypy
if ($LASTEXITCODE -ne 0) {
    Write-Host "MyPy type check failed" -ForegroundColor Red
    exit 1
}

# 4. Pytest (exclude integration tests)
Write-Host "`nRunning pytest..." -ForegroundColor Cyan
& $pytest -m "not integration" --tb=short
if ($LASTEXITCODE -ne 0) {
    Write-Host "Pytest failed" -ForegroundColor Red
    exit 1
}

# 5. Web linting (if package.json exists)
if (Test-Path "apps/web/package.json") {
    Write-Host "`nRunning web linting..." -ForegroundColor Cyan
    & npm --prefix apps/web run lint
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Web lint failed" -ForegroundColor Red
        exit 1
    }
}

# 6. Web type check (if package.json exists)
if (Test-Path "apps/web/package.json") {
    Write-Host "`nRunning web typecheck..." -ForegroundColor Cyan
    & npm --prefix apps/web run typecheck
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Web typecheck failed" -ForegroundColor Red
        exit 1
    }
}

Write-Host "`n✓ All checks passed" -ForegroundColor Green
exit 0
