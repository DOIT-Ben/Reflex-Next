[CmdletBinding()]
param(
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "project_registry.ps1")
$registry = Get-ReflexProjectRegistry -RepositoryRoot $root
$cloudProjectPath = ([string](Get-ReflexRegistryProject -Registry $registry -ProjectId "reflex-cloud").path -replace "/", "\")
$containerName = "reflex-quality-postgres-smoke"
$postgresPort = 55432
$minimumFreePhysicalMB = 2048
$minimumFreeVirtualMB = 4096
$smokeTimeoutSeconds = 20
$smokeWatchdogSeconds = 90
$oldDatabaseUrl = [Environment]::GetEnvironmentVariable(
  "REFLEX_CLOUD_POSTGRES_TEST_URL",
  "Process"
)
$containerCreated = $false
$cleanupFailed = $false
$smokeExitCode = 1
$smokeTimedOut = $false
$smokeProcess = $null
$smokeOutputPath = Join-Path ([System.IO.Path]::GetTempPath()) (
  "reflex-cloud-smoke-{0}.out" -f [guid]::NewGuid().ToString("N")
)
$smokeErrorPath = Join-Path ([System.IO.Path]::GetTempPath()) (
  "reflex-cloud-smoke-{0}.err" -f [guid]::NewGuid().ToString("N")
)

function Stop-SmokeProcessTree {
  param(
    [Parameter(Mandatory = $false)]
    [System.Diagnostics.Process]$Process
  )

  if ($null -eq $Process) {
    return $true
  }
  try {
    if ($Process.HasExited) {
      return $true
    }
  }
  catch {
    return $false
  }

  & taskkill.exe /PID ([string]$Process.Id) /T /F *> $null
  try {
    $Process.WaitForExit(5000)
    return $Process.HasExited
  }
  catch {
    return $false
  }
}

if ($env:OS -ne "Windows_NT") {
  throw "postgres_smoke_requires_windows"
}
foreach ($command in @("docker", "uv")) {
  if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
    throw "postgres_smoke_dependency_missing"
  }
}

$memory = Get-CimInstance Win32_OperatingSystem
$freePhysicalMB = [math]::Floor([double]$memory.FreePhysicalMemory / 1024)
$freeVirtualMB = [math]::Floor([double]$memory.FreeVirtualMemory / 1024)
if (
  $freePhysicalMB -lt $minimumFreePhysicalMB -or
  $freeVirtualMB -lt $minimumFreeVirtualMB
) {
  throw "insufficient_memory_for_postgres_smoke"
}

if (Get-NetTCPConnection -LocalPort $postgresPort -ErrorAction SilentlyContinue) {
  throw "postgres_smoke_port_in_use"
}

& docker version --format "{{.Server.Version}}" *> $null
if ($LASTEXITCODE -ne 0) {
  throw "docker_engine_unavailable"
}
$namedContainers = @(
  & docker ps -a --filter "name=$containerName" --format "{{.Names}}"
)
if ($LASTEXITCODE -ne 0) {
  throw "docker_engine_unavailable"
}
if ($namedContainers -contains $containerName) {
  throw "postgres_smoke_container_exists"
}
$existingContainers = @(& docker ps --format "{{.ID}}")
if ($LASTEXITCODE -ne 0) {
  throw "docker_engine_unavailable"
}

if ($DryRun) {
  Write-Output (
    "[DRY-RUN] cloud:postgres-quality-smoke | memory-guard={0}MB/{1}MB | container={2}MB/0.5CPU | port=loopback:{3}" -f
    $minimumFreePhysicalMB,
    $minimumFreeVirtualMB,
    128,
    $postgresPort
  )
  return
}

try {
  $containerId = & docker run `
    --rm `
    -d `
    --name $containerName `
    --memory=128m `
    --cpus=0.5 `
    -p "127.0.0.1:${postgresPort}:5432" `
    --tmpfs "/var/lib/postgresql/data:rw,size=96m" `
    -e "POSTGRES_DB=reflex_cloud_test" `
    -e "POSTGRES_USER=reflex_cloud" `
    -e "POSTGRES_HOST_AUTH_METHOD=trust" `
    postgres:16-alpine `
    -c shared_buffers=16MB `
    -c max_connections=10 `
    -c work_mem=1MB `
    -c maintenance_work_mem=8MB `
    -c fsync=off `
    -c synchronous_commit=off `
    -c full_page_writes=off
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($containerId)) {
    throw "postgres_smoke_container_start_failed"
  }
  $containerCreated = $true

  $ready = $false
  for ($attempt = 0; $attempt -lt 30; $attempt++) {
    & docker exec $containerName pg_isready -U reflex_cloud -d reflex_cloud_test *> $null
    if ($LASTEXITCODE -eq 0) {
      $ready = $true
      break
    }
    Start-Sleep -Seconds 1
  }
  if (-not $ready) {
    throw "postgres_smoke_container_not_ready"
  }

  [Environment]::SetEnvironmentVariable(
    "REFLEX_CLOUD_POSTGRES_TEST_URL",
    "postgresql+psycopg://reflex_cloud@127.0.0.1:${postgresPort}/reflex_cloud_test",
    "Process"
  )
  Push-Location -LiteralPath $root
  try {
    $smokeProcess = Start-Process `
      -FilePath "uv" `
      -ArgumentList @(
        "run",
        "--isolated",
        "--frozen",
        "--project",
        $cloudProjectPath,
        "--extra",
        "postgres",
        "python",
        "tools\reflex_cloud_postgres_quality_release_smoke.py",
        "--timeout-seconds",
        $smokeTimeoutSeconds
      ) `
      -WorkingDirectory $root `
      -RedirectStandardOutput $smokeOutputPath `
      -RedirectStandardError $smokeErrorPath `
      -WindowStyle Hidden `
      -PassThru
    if (-not $smokeProcess.WaitForExit($smokeWatchdogSeconds * 1000)) {
      $smokeTimedOut = $true
      if (-not (Stop-SmokeProcessTree -Process $smokeProcess)) {
        $cleanupFailed = $true
      }
      $smokeExitCode = 124
    }
    else {
      $smokeExitCode = $smokeProcess.ExitCode
    }
    if (Test-Path -LiteralPath $smokeOutputPath -PathType Leaf) {
      $smokeOutput = Get-Content -LiteralPath $smokeOutputPath -Raw
      if (-not [string]::IsNullOrWhiteSpace($smokeOutput)) {
        Write-Output $smokeOutput.TrimEnd()
      }
    }
    if ($smokeExitCode -ne 0 -and (Test-Path -LiteralPath $smokeErrorPath -PathType Leaf)) {
      $smokeError = Get-Content -LiteralPath $smokeErrorPath -Raw
      if (-not [string]::IsNullOrWhiteSpace($smokeError)) {
        Write-Output $smokeError.TrimEnd()
      }
    }
  }
  finally {
    Pop-Location
  }
}
finally {
  [Environment]::SetEnvironmentVariable(
    "REFLEX_CLOUD_POSTGRES_TEST_URL",
    $oldDatabaseUrl,
    "Process"
  )
  if ($smokeProcess -and -not $smokeProcess.HasExited) {
    if (-not (Stop-SmokeProcessTree -Process $smokeProcess)) {
      $cleanupFailed = $true
    }
  }
  if ($containerCreated) {
    & docker stop --time 10 $containerName *> $null
    if ($LASTEXITCODE -ne 0) {
      $cleanupFailed = $true
    }
  }
  Remove-Item -LiteralPath $smokeOutputPath, $smokeErrorPath -Force -ErrorAction SilentlyContinue
}

if ($cleanupFailed) {
  throw "postgres_smoke_cleanup_failed"
}
if ($smokeExitCode -ne 0) {
  if ($smokeTimedOut) {
    throw "postgres_smoke_timeout"
  }
  throw "postgres_smoke_failed"
}

$remainingNamed = @(
  & docker ps -a --filter "name=$containerName" --format "{{.Names}}"
)
if ($LASTEXITCODE -ne 0 -or $remainingNamed -contains $containerName) {
  throw "postgres_smoke_cleanup_failed"
}
$runningAfter = @(& docker ps --format "{{.ID}}")
if ($LASTEXITCODE -ne 0) {
  throw "docker_engine_unavailable"
}
if (@($existingContainers | Where-Object { $runningAfter -notcontains $_ }).Count -ne 0) {
  throw "existing_container_interrupted"
}

Write-Output "Reflex Cloud PostgreSQL quality release smoke passed."
