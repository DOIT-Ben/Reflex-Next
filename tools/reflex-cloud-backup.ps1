[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$OutputDirectory,
  [string]$ComposeFile = "",
  [string]$ProjectName = "reflex-cloud",
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
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
$stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
$id = [guid]::NewGuid().ToString("N")
$dumpName = "reflex-cloud-postgres-$stamp.dump"
$dumpPath = Join-Path $outputPath $dumpName
$manifestPath = Join-Path $outputPath ($dumpName + ".json")
$partialDumpPath = Join-Path $outputPath (".$dumpName.$id.partial")
$partialManifestPath = $partialDumpPath + ".json"
$containerPath = "/tmp/reflex-cloud-backup-$id.dump"
$committed = $false

if (-not $DryRun) {
  New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
  foreach ($target in @($dumpPath, $manifestPath, $partialDumpPath, $partialManifestPath)) {
    if (Test-Path -LiteralPath $target) {
      throw "Backup target already exists: $target"
    }
  }
}

$dumpCommand = 'pg_dump --format=custom --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "' + $containerPath + '"'
try {
  Invoke-Compose @("exec", "-T", "-u", "postgres", "postgres", "sh", "-c", $dumpCommand)
  Invoke-Compose @("cp", "postgres:$containerPath", $partialDumpPath)

  if ($DryRun) {
    Write-Output "[DRY-RUN] backup=$dumpPath"
    exit 0
  }

  $fileInfo = Get-Item -LiteralPath $partialDumpPath
  if ($fileInfo.Length -le 0) {
    throw "pg_dump produced an empty backup."
  }
  $hash = (Get-FileHash -LiteralPath $partialDumpPath -Algorithm SHA256).Hash.ToLowerInvariant()
  $manifest = [ordered]@{
    schema_version = 1
    created_at_utc = [DateTime]::UtcNow.ToString("o")
    format = "postgres-custom"
    file = $dumpName
    bytes = $fileInfo.Length
    sha256 = $hash
    compose_service = "postgres"
  }
  $manifestJson = $manifest | ConvertTo-Json -Depth 4
  [System.IO.File]::WriteAllText(
    $partialManifestPath,
    $manifestJson,
    [System.Text.UTF8Encoding]::new($false)
  )
  Move-Item -LiteralPath $partialDumpPath -Destination $dumpPath
  Move-Item -LiteralPath $partialManifestPath -Destination $manifestPath
  $committed = $true
  Write-Output "Backup created: $dumpPath"
  Write-Output "SHA256: $hash"
}
finally {
  if (-not $DryRun) {
    if (-not $committed) {
      foreach ($target in @($partialDumpPath, $partialManifestPath, $dumpPath, $manifestPath)) {
        Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
      }
    }
    try {
      Invoke-Compose @("exec", "-T", "-u", "postgres", "postgres", "rm", "-f", $containerPath)
    }
    catch {
      Write-Warning "Could not remove temporary container backup: $containerPath"
    }
  }
}
