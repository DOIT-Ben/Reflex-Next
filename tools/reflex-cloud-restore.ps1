[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$BackupFile,
  [Parameter(Mandatory = $true)]
  [string]$TargetDatabase,
  [string]$ComposeFile = "",
  [string]$ProjectName = "reflex-cloud",
  [string]$ManifestFile,
  [switch]$ConfirmRestore,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Invoke-Compose {
  param([string[]]$Arguments)

  if ($DryRun) {
    Write-Output ("[DRY-RUN] docker compose " + ($Arguments -join " "))
    return
  }

  & docker compose --project-name $ProjectName --file $script:ComposePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "docker compose failed with exit code $LASTEXITCODE."
  }
}

if (-not $ComposeFile) {
  $ComposeFile = Join-Path $PSScriptRoot "..\services\reflex-cloud\docker-compose.yml"
}
$script:ComposePath = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $ComposeFile).Path)
$backupPath = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $BackupFile).Path)
if ($TargetDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
  throw "TargetDatabase must contain only PostgreSQL identifier characters."
}
if ($TargetDatabase.Equals("reflex_cloud", [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "Direct restore into the production database reflex_cloud is refused. Restore into an isolated database."
}
if ($TargetDatabase -notmatch '^reflex_cloud_restore(?:_[A-Za-z0-9_]+)?$') {
  throw "TargetDatabase must use the isolated reflex_cloud_restore name prefix."
}
if (-not $ConfirmRestore -and -not $DryRun) {
  throw "Restoring replaces the isolated target database. Re-run with -ConfirmRestore."
}

if ($ManifestFile) {
  $manifestPath = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $ManifestFile).Path)
  $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
  $expectedHash = [string]$manifest.sha256
  if ($expectedHash -notmatch '^[0-9a-fA-F]{64}$') {
    throw "Manifest has no valid SHA256 value."
  }
  $actualHash = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash
  if (-not $actualHash.Equals($expectedHash, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Backup SHA256 does not match the manifest."
  }
}

$backupInfo = Get-Item -LiteralPath $backupPath
if ($backupInfo.Length -le 0) {
  throw "Backup file is empty."
}
$id = [guid]::NewGuid().ToString("N")
$containerPath = "/tmp/reflex-cloud-restore-$id.dump"
try {
  Invoke-Compose @("cp", $backupPath, "postgres:$containerPath")
  Invoke-Compose @("exec", "-T", "-u", "postgres", "postgres", "dropdb", "--username", "reflex_cloud", "--if-exists", "--maintenance-db", "postgres", $TargetDatabase)
  Invoke-Compose @("exec", "-T", "-u", "postgres", "postgres", "createdb", "--username", "reflex_cloud", "--maintenance-db", "postgres", $TargetDatabase)
  Invoke-Compose @("exec", "-T", "-u", "postgres", "postgres", "pg_restore", "--username", "reflex_cloud", "--exit-on-error", "--no-owner", "--no-privileges", "--dbname", $TargetDatabase, $containerPath)
  $query = "SELECT current_database() || ' tables=' || count(*) FROM pg_tables WHERE schemaname = 'public';"
  Invoke-Compose @("exec", "-T", "-u", "postgres", "postgres", "psql", "--username", "reflex_cloud", "--dbname", $TargetDatabase, "-Atqc", $query)
  if (-not $DryRun) {
    Write-Output "Isolated restore completed: database=$TargetDatabase"
  }
}
finally {
  if (-not $DryRun) {
    try {
      Invoke-Compose @("exec", "-T", "postgres", "rm", "-f", $containerPath)
    }
    catch {
      Write-Warning "Could not remove temporary container restore: $containerPath"
    }
  }
}
