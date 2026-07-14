$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Assert-True {
  param([bool]$Condition, [string]$Message)
  if (-not $Condition) {
    throw $Message
  }
}

function Read-Utf8 {
  param([string]$Path)
  return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

$composePath = Join-Path $root "services\reflex-cloud\docker-compose.yml"
$caddyPath = Join-Path $root "services\reflex-cloud\Caddyfile"
$dockerfilePath = Join-Path $root "services\reflex-cloud\Dockerfile"
$backupPath = Join-Path $root "tools\reflex-cloud-backup.ps1"
$restorePath = Join-Path $root "tools\reflex-cloud-restore.ps1"
$budgetCheckPath = Join-Path $root "tools\reflex-cloud-budget-check.ps1"

foreach ($path in @($composePath, $caddyPath, $dockerfilePath, $backupPath, $restorePath, $budgetCheckPath)) {
  Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing cloud operations file: $path"
}

$compose = Read-Utf8 $composePath
$caddy = Read-Utf8 $caddyPath
$dockerfile = Read-Utf8 $dockerfilePath
$backup = Read-Utf8 $backupPath
$restore = Read-Utf8 $restorePath
$budgetCheck = Read-Utf8 $budgetCheckPath

Assert-True ($compose -match 'profiles:\s*\["public"\]') "Compose must keep Caddy behind the public profile."
Assert-True ($compose -match 'REFLEX_CLOUD_GLOBAL_DAILY_REQUEST_LIMIT') "Compose must pass the global request budget."
Assert-True ($compose -match 'REFLEX_CLOUD_GLOBAL_DAILY_COST_BUDGET_MICROUSD') "Compose must pass the cost budget."
Assert-True ($compose -match 'read_only:\s*true') "Cloud services must retain a read-only root filesystem."
Assert-True ($caddy -match 'request_body') "Caddy must enforce an upload request body limit."
Assert-True ($caddy -match 'flush_interval\s+-1') "Caddy must stream SSE responses without buffering."
Assert-True ($dockerfile -match 'uv:0\.11\.13') "Cloud image builds must pin uv."
Assert-True ($dockerfile -match 'uv sync --frozen') "Cloud image builds must use the frozen lock file."
Assert-True ($backup -match 'pg_dump --format=custom') "Backup must use PostgreSQL custom format."
Assert-True ($backup -match 'Get-FileHash.*SHA256') "Backup must emit a SHA256 manifest."
Assert-True ($backup -match 'docker compose') "Backup must use the Compose Postgres service."
Assert-True ($restore -match 'ConfirmRestore') "Restore must require explicit confirmation."
Assert-True ($restore -match 'reflex_cloud.*refused') "Restore must refuse the production database."
Assert-True ($restore -match 'pg_restore') "Restore must invoke pg_restore."
Assert-True ($restore -match 'dropdb.*TargetDatabase') "Restore must replace only the selected isolated database."
Assert-True ($budgetCheck -match 'REFLEX_CLOUD_ADMIN_TOKEN') "Budget checks must read the admin token from the environment."
Assert-True ($budgetCheck -match 'Remote budget checks require HTTPS') "Remote budget checks must require HTTPS."
Assert-True ($budgetCheck -match 'exit \$exitCode') "Budget checks must expose monitoring exit codes."

$powershell = Join-Path $PSHOME "powershell.exe"
$dryOutputDirectory = Join-Path ([System.IO.Path]::GetTempPath()) "reflex-cloud-ops-contract"
function Invoke-ChildScript {
  param([string[]]$Arguments)
  $previous = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    $output = @(& $powershell @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
  }
  finally {
    $ErrorActionPreference = $previous
  }
  return [PSCustomObject]@{ ExitCode = $exitCode; Output = @($output) }
}

$dryResult = Invoke-ChildScript @(
  "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $backupPath,
  "-OutputDirectory", $dryOutputDirectory, "-DryRun"
)
Assert-True ($dryResult.ExitCode -eq 0) "Backup dry-run must parse and return zero."
Assert-True (($dryResult.Output | Where-Object { $_.ToString() -match '\[DRY-RUN\]' }).Count -ge 1) "Backup dry-run must expose planned Compose commands."

$restoreFixture = Join-Path $root "services\reflex-cloud\README.md"
$restoreDryResult = Invoke-ChildScript @(
  "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $restorePath,
  "-BackupFile", $restoreFixture, "-TargetDatabase", "reflex_cloud_restore", "-DryRun"
)
Assert-True ($restoreDryResult.ExitCode -eq 0) "Restore dry-run must parse and return zero."
Assert-True (($restoreDryResult.Output | Where-Object { $_.ToString() -match 'pg_restore' }).Count -eq 1) "Restore dry-run must plan pg_restore."

$refused = Invoke-ChildScript @(
  "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $restorePath,
  "-BackupFile", $restoreFixture, "-TargetDatabase", "reflex_cloud", "-DryRun"
)
Assert-True ($refused.ExitCode -ne 0) "Restore must refuse the production database even in dry-run mode."
Assert-True (($refused.Output -join "\n") -match 'production database') "Production restore refusal must be explicit."

$unscoped = Invoke-ChildScript @(
  "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $restorePath,
  "-BackupFile", $restoreFixture, "-TargetDatabase", "other_database", "-DryRun"
)
Assert-True ($unscoped.ExitCode -ne 0) "Restore must refuse database names outside the isolated prefix."
Assert-True (($unscoped.Output -join "\n") -match 'isolated') "Unscoped restore refusal must be explicit."

$budgetFixtureRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("reflex-cloud-budget-contract-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $budgetFixtureRoot | Out-Null
try {
  $budgetFixture = Join-Path $budgetFixtureRoot "analytics.json"
  $cases = @(
    @{ Ratio = 0.4; Exceeded = $false; ExitCode = 0; Status = "ok" },
    @{ Ratio = 0.85; Exceeded = $false; ExitCode = 1; Status = "warning" },
    @{ Ratio = 1.0; Exceeded = $true; ExitCode = 2; Status = "critical" }
  )
  foreach ($case in $cases) {
    $payload = [ordered]@{
      daily_budget_date = "2026-07-15"
      daily_request_usage_ratio = $case.Ratio
      daily_cost_usage_ratio = 0.25
      daily_requests_remaining = 10
      daily_cost_remaining_microusd = 1000
      budget_exceeded = $case.Exceeded
    } | ConvertTo-Json -Compress
    [System.IO.File]::WriteAllText($budgetFixture, $payload, [System.Text.UTF8Encoding]::new($false))
    $result = Invoke-ChildScript @(
      "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $budgetCheckPath,
      "-AnalyticsFile", $budgetFixture
    )
    Assert-True ($result.ExitCode -eq $case.ExitCode) "Budget check exit code mismatch for $($case.Status)."
    $jsonLine = $result.Output | Where-Object { $_.ToString().StartsWith("{") } | Select-Object -Last 1
    $report = $jsonLine.ToString() | ConvertFrom-Json
    Assert-True ($report.status -eq $case.Status) "Budget check status mismatch for $($case.Status)."
  }
}
finally {
  Remove-Item -LiteralPath $budgetFixtureRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Output "Reflex Cloud operations contract checks passed."
