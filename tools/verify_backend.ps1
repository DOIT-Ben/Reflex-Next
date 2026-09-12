[CmdletBinding()]
param(
  [switch]$ListSteps,
  [switch]$DryRun,
  [switch]$SkipFrontend,
  [switch]$SkipHeavy,
  [switch]$SkipDependencyAudit,
  [switch]$SkipReleaseMaterials,
  [string[]]$PythonProject = @()
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "project_registry.ps1")
$registry = Get-ReflexProjectRegistry -RepositoryRoot $root
$powerShellCommandName = if (Get-Command pwsh.exe -ErrorAction SilentlyContinue) {
  "pwsh.exe"
}
else {
  "powershell.exe"
}
$pythonCatalog = @($registry.projects | Where-Object {
    $_.kind -eq "python" -and $_.verify -eq $true
  })
if ($pythonCatalog.Count -eq 0) {
  throw "Project registry has no verifiable Python projects."
}
$knownPythonProjects = @($pythonCatalog | ForEach-Object { [string]$_.id })
if (@($PythonProject).Count -eq 0) {
  $PythonProject = $knownPythonProjects
}
foreach ($selectedProject in @($PythonProject)) {
  if ($knownPythonProjects -notcontains $selectedProject) {
    throw "Unknown Python project in project registry: $selectedProject"
  }
}
$runtimeProject = Get-ReflexRegistryProject -Registry $registry -ProjectId "reflex-runtime"
$cloudProject = Get-ReflexRegistryProject -Registry $registry -ProjectId "reflex-cloud"
$historyProject = Get-ReflexRegistryProject -Registry $registry -ProjectId "history-sqlite"
$runtimeProjectPath = ([string]$runtimeProject.path -replace "/", "\")
$runtimeLockPath = ([string]$runtimeProject.lock -replace "/", "\")
$cloudProjectPath = ([string]$cloudProject.path -replace "/", "\")
$cloudLockPath = ([string]$cloudProject.lock -replace "/", "\")
$historyProjectPath = ([string]$historyProject.path -replace "/", "\")
$historyLockPath = ([string]$historyProject.lock -replace "/", "\")
$rustTestResourcePath = Join-Path ([System.IO.Path]::GetTempPath()) ("reflex-rust-test-" + [guid]::NewGuid().ToString("N") + "\resources\runtime\reflex-runtime.exe")
$soakReportPath = Join-Path ([System.IO.Path]::GetTempPath()) ("reflex-soak-smoke-" + [guid]::NewGuid().ToString("N") + ".json")

if ($env:REFLEX_VERIFY_RUST_TEST_RESOURCE_PATH) {
  $candidatePath = [System.IO.Path]::GetFullPath($env:REFLEX_VERIFY_RUST_TEST_RESOURCE_PATH)
  $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd("\") + "\"
  if (-not $candidatePath.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "REFLEX_VERIFY_RUST_TEST_RESOURCE_PATH must be located under the system temporary directory."
  }
  $rustTestResourcePath = $candidatePath
}

function New-RustTestResource {
  param([string]$Path)

  if (Test-Path -LiteralPath $Path -PathType Leaf) {
    return $false
  }
  if (Test-Path -LiteralPath $Path) {
    throw "Rust test resource path exists but is not a file: $Path"
  }

  $parent = Split-Path -Parent $Path
  New-Item -ItemType Directory -Path $parent -Force | Out-Null
  [System.IO.File]::WriteAllBytes($Path, [byte[]]::new(0))
  return $true
}

function Remove-RustTestResource {
  param(
    [string]$Path,
    [bool]$Created
  )

  if (-not $Created) {
    return
  }

  Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
  $directory = Split-Path -Parent $Path
  $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd("\")
  for ($index = 0; $index -lt 4; $index++) {
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
      break
    }
    $directoryFullPath = [System.IO.Path]::GetFullPath($directory).TrimEnd("\")
    if ($directoryFullPath -ieq $tempRoot -or
        -not $directoryFullPath.StartsWith($tempRoot + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
      break
    }
    if (@(Get-ChildItem -LiteralPath $directory -Force).Count -ne 0) {
      break
    }
    Remove-Item -LiteralPath $directory -Force
    $directory = Split-Path -Parent $directory
  }
}

function New-VerificationStep {
  param(
    [string]$Id,
    [string]$Category,
    [string]$WorkDir,
    [string]$LockFile,
    [string]$Executable,
    [string[]]$Arguments,
    [bool]$Heavy = $false,
    [bool]$Frontend = $false,
    [string]$PythonProjectName = ""
  )

  return [PSCustomObject]@{
    Id = $Id
    Category = $Category
    WorkDir = $WorkDir
    LockFile = $LockFile
    Executable = $Executable
    Arguments = $Arguments
    Heavy = $Heavy
    Frontend = $Frontend
    PythonProjectName = $PythonProjectName
  }
}

$pythonProjects = @($pythonCatalog | ForEach-Object {
    @{ Name = [string]$_.id; Path = ([string]$_.path -replace "/", "\") }
  })

$steps = @()
$steps += New-VerificationStep `
  -Id "governance:project-registry-contract" `
  -Category "governance" `
  -WorkDir "." `
  -LockFile "" `
  -Executable $powerShellCommandName `
  -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "tools\tests\project_registry_contract.ps1")

$steps += New-VerificationStep `
  -Id "security:secret-contract" `
  -Category "security" `
  -WorkDir "." `
  -LockFile "" `
  -Executable $powerShellCommandName `
  -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "tools\tests\scan_release_secrets_contract.ps1")

$steps += New-VerificationStep `
  -Id "security:secret-scan" `
  -Category "security" `
  -WorkDir "." `
  -LockFile "" `
  -Executable $powerShellCommandName `
  -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "tools\scan_release_secrets.ps1")

$steps += New-VerificationStep `
  -Id "release:version-contract" `
  -Category "release" `
  -WorkDir "." `
  -LockFile "" `
  -Executable $powerShellCommandName `
  -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "tools\tests\check_version_consistency_contract.ps1")

$steps += New-VerificationStep `
  -Id "release:version-consistency" `
  -Category "release" `
  -WorkDir "." `
  -LockFile "" `
  -Executable $powerShellCommandName `
  -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "tools\check_version_consistency.ps1", "-IgnoreTag")

$steps += New-VerificationStep `
  -Id "release:candidate-contract" `
  -Category "release" `
  -WorkDir "." `
  -LockFile "" `
  -Executable $powerShellCommandName `
  -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "tools\tests\release_candidate_contract.ps1")

$steps += New-VerificationStep `
  -Id "security:dependency-contract" `
  -Category "security" `
  -WorkDir "." `
  -LockFile "" `
  -Executable $powerShellCommandName `
  -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "tools\tests\audit_dependencies_contract.ps1")

$steps += New-VerificationStep `
  -Id "supply-chain:sbom-contract" `
  -Category "supply-chain" `
  -WorkDir "." `
  -LockFile "" `
  -Executable $powerShellCommandName `
  -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "tools\tests\generate_release_sbom_contract.ps1")

$steps += New-VerificationStep `
  -Id "tools:provider-smoke-contract" `
  -Category "tools" `
  -WorkDir "." `
  -LockFile $runtimeLockPath `
  -Executable "uv" `
  -Arguments @("run", "--frozen", "--project", $runtimeProjectPath, "--extra", "dev", "pytest", "tools\tests\test_provider_smoke.py", "-q")

$steps += New-VerificationStep `
  -Id "tools:cloud-postgres-quality-contract" `
  -Category "tools" `
  -WorkDir "." `
  -LockFile $cloudLockPath `
  -Executable "uv" `
  -Arguments @("run", "--frozen", "--project", $cloudProjectPath, "--extra", "dev", "pytest", "tools\tests\test_reflex_cloud_postgres_quality_release_smoke.py", "-q")

$steps += New-VerificationStep `
  -Id "tools:history-upgrade-contract" `
  -Category "tools" `
  -WorkDir "." `
  -LockFile $runtimeLockPath `
  -Executable "uv" `
  -Arguments @("run", "--frozen", "--project", $runtimeProjectPath, "--extra", "dev", "--extra", "builtins", "pytest", "tools\tests\test_history_upgrade_smoke.py", "-q")

$steps += New-VerificationStep `
  -Id "tools:cross-version-history-upgrade-contract" `
  -Category "tools" `
  -WorkDir "." `
  -LockFile $runtimeLockPath `
  -Executable "uv" `
  -Arguments @("run", "--frozen", "--project", $runtimeProjectPath, "--extra", "dev", "--extra", "builtins", "pytest", "tools\tests\test_cross_version_history_upgrade_smoke.py", "-q")

$steps += New-VerificationStep `
  -Id "tools:benchmark-contract" `
  -Category "tools" `
  -WorkDir "." `
  -LockFile $runtimeLockPath `
  -Executable "uv" `
  -Arguments @("run", "--frozen", "--project", $runtimeProjectPath, "--extra", "dev", "pytest", "tools\tests\test_benchmark_backend.py", "-q")

$steps += New-VerificationStep `
  -Id "tools:history-benchmark-contract" `
  -Category "tools" `
  -WorkDir "." `
  -LockFile $historyLockPath `
  -Executable "uv" `
  -Arguments @("run", "--frozen", "--project", $historyProjectPath, "--extra", "dev", "pytest", "tools\tests\test_benchmark_history_sqlite.py", "-q")

$steps += New-VerificationStep `
  -Id "tools:history-benchmark-small-smoke" `
  -Category "tools" `
  -WorkDir "." `
  -LockFile $historyLockPath `
  -Executable "uv" `
  -Arguments @("run", "--frozen", "--project", $historyProjectPath, "--extra", "dev", "python", "tools\benchmark_history_sqlite.py", "--record-count", "10", "--profile", "small", "--storage-sample-every", "10") `
  -Heavy $true

$steps += New-VerificationStep `
  -Id "tools:history-benchmark-heavy-smoke" `
  -Category "tools" `
  -WorkDir "." `
  -LockFile $historyLockPath `
  -Executable "uv" `
  -Arguments @("run", "--frozen", "--project", $historyProjectPath, "--extra", "dev", "python", "tools\benchmark_history_sqlite.py", "--record-count", "2", "--profile", "heavy", "--storage-sample-every", "2") `
  -Heavy $true

$steps += New-VerificationStep `
  -Id "tools:soak-contract" `
  -Category "tools" `
  -WorkDir "." `
  -LockFile $runtimeLockPath `
  -Executable "uv" `
  -Arguments @("run", "--frozen", "--project", $runtimeProjectPath, "--extra", "dev", "pytest", "tools\tests\test_soak_backend.py", "-q")

$steps += New-VerificationStep `
  -Id "tools:soak-smoke" `
  -Category "tools" `
  -WorkDir "." `
  -LockFile $runtimeLockPath `
  -Executable "uv" `
  -Arguments @("run", "--frozen", "--project", $runtimeProjectPath, "--extra", "dev", "python", "tools\soak_backend.py", "--iterations", "100", "--batch-size", "4", "--timeout-seconds", "15", "--cancel-every", "2", "--json-output", $soakReportPath) `
  -Heavy $true

$steps += New-VerificationStep `
  -Id "tools:plugin-history-soak-contract" `
  -Category "tools" `
  -WorkDir "." `
  -LockFile $historyLockPath `
  -Executable "uv" `
  -Arguments @("run", "--frozen", "--project", $historyProjectPath, "--extra", "dev", "pytest", "tools\tests\test_soak_plugin_history.py", "tools\tests\test_windows_resource_probe.py", "-q")

$steps += New-VerificationStep `
  -Id "tools:plugin-history-soak-smoke" `
  -Category "tools" `
  -WorkDir "." `
  -LockFile $historyLockPath `
  -Executable "uv" `
  -Arguments @("run", "--frozen", "--project", $historyProjectPath, "--extra", "dev", "python", "tools\soak_plugin_history.py", "--iterations", "100", "--warmup-iterations", "20", "--sample-every", "20") `
  -Heavy $true

foreach ($project in $pythonProjects) {
  $steps += New-VerificationStep `
    -Id ("python:" + $project.Name) `
    -Category "python" `
    -WorkDir $project.Path `
    -LockFile "uv.lock" `
    -Executable "uv" `
    -Arguments @("run", "--frozen", "--extra", "dev", "pytest", "tests") `
    -PythonProjectName $project.Name
}

$steps += New-VerificationStep `
  -Id "security:dependency-audit" `
  -Category "security" `
  -WorkDir "." `
  -LockFile "" `
  -Executable $powerShellCommandName `
  -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "tools\audit_dependencies.ps1") `
  -Heavy $true

$steps += New-VerificationStep `
  -Id "supply-chain:sbom" `
  -Category "supply-chain" `
  -WorkDir "." `
  -LockFile "" `
  -Executable $powerShellCommandName `
  -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "tools\generate_release_sbom.ps1", "-Verify") `
  -Heavy $true

$steps += New-VerificationStep `
  -Id "rust:format" `
  -Category "rust" `
  -WorkDir "apps\tauri-host\src-tauri" `
  -LockFile "Cargo.lock" `
  -Executable "cargo" `
  -Arguments @("fmt", "--check")

$steps += New-VerificationStep `
  -Id "rust:clippy" `
  -Category "rust" `
  -WorkDir "apps\tauri-host\src-tauri" `
  -LockFile "Cargo.lock" `
  -Executable "cargo" `
  -Arguments @("clippy", "--locked", "--all-targets", "--all-features", "--", "-D", "warnings")

$steps += New-VerificationStep `
  -Id "rust:tests" `
  -Category "rust" `
  -WorkDir "apps\tauri-host\src-tauri" `
  -LockFile "Cargo.lock" `
  -Executable "cargo" `
  -Arguments @("test", "--locked", "--", "--test-threads=2")

$steps += New-VerificationStep `
  -Id "frontend:install" `
  -Category "frontend" `
  -WorkDir "apps\tauri-host" `
  -LockFile "package-lock.json" `
  -Executable "npm" `
  -Arguments @("ci") `
  -Frontend $true

$steps += New-VerificationStep `
  -Id "frontend:typecheck" `
  -Category "frontend" `
  -WorkDir "apps\tauri-host" `
  -LockFile "package-lock.json" `
  -Executable "npm" `
  -Arguments @("run", "typecheck") `
  -Frontend $true

$steps += New-VerificationStep `
  -Id "frontend:lint" `
  -Category "frontend" `
  -WorkDir "apps\tauri-host" `
  -LockFile "package-lock.json" `
  -Executable "npm" `
  -Arguments @("run", "lint") `
  -Frontend $true

$steps += New-VerificationStep `
  -Id "frontend:tests" `
  -Category "frontend" `
  -WorkDir "apps\tauri-host" `
  -LockFile "package-lock.json" `
  -Executable "npm" `
  -Arguments @("test", "--", "--maxWorkers=2") `
  -Frontend $true

$steps += New-VerificationStep `
  -Id "frontend:build" `
  -Category "frontend" `
  -WorkDir "apps\tauri-host" `
  -LockFile "package-lock.json" `
  -Executable "npm" `
  -Arguments @("run", "build") `
  -Frontend $true

function Get-CommandText {
  param($Step)

  return (@($Step.Executable) + @($Step.Arguments)) -join " "
}

function Get-SkipReason {
  param($Step)

  if ($Step.Category -eq "python" -and $PythonProject -notcontains $Step.PythonProjectName) {
    return "PythonProject"
  }

  if ($SkipHeavy -and $Step.Heavy) {
    return "SkipHeavy"
  }

  if ($SkipDependencyAudit -and $Step.Id -eq "security:dependency-audit") {
    return "SkipDependencyAudit"
  }

  if ($SkipReleaseMaterials -and $Step.Id -eq "supply-chain:sbom") {
    return "SkipReleaseMaterials"
  }

  if ($SkipFrontend -and $Step.Frontend) {
    return "SkipFrontend"
  }

  return ""
}

if ($ListSteps) {
  foreach ($step in $steps) {
    $commandText = Get-CommandText -Step $step
    $lockLabel = if ([string]::IsNullOrWhiteSpace($step.LockFile)) { "none" } else { $step.LockFile }
    Write-Output ("[STEP] {0} | category={1} | heavy={2} | workdir={3} | lock={4} | command={5}" -f $step.Id, $step.Category, $step.Heavy, $step.WorkDir, $lockLabel, $commandText)
  }
  return
}

foreach ($step in $steps) {
  $skipReason = Get-SkipReason -Step $step
  if ($skipReason) {
    Write-Output ("[SKIP] {0} | reason={1}" -f $step.Id, $skipReason)
    continue
  }

  $workDir = Join-Path $root $step.WorkDir
  if (-not (Test-Path -LiteralPath $workDir -PathType Container)) {
    throw "Verification work directory is missing: $($step.WorkDir)"
  }
  if (-not [string]::IsNullOrWhiteSpace($step.LockFile)) {
    $lockFile = Join-Path $workDir $step.LockFile
    if (-not (Test-Path -LiteralPath $lockFile -PathType Leaf)) {
      throw "Verification lock file is missing: $($step.WorkDir)\$($step.LockFile)"
    }
  }

  $commandText = Get-CommandText -Step $step
  if ($DryRun) {
    Write-Output ("[DRY-RUN] {0} | workdir={1} | command={2}" -f $step.Id, $step.WorkDir, $commandText)
    continue
  }

  if (-not (Get-Command $step.Executable -ErrorAction SilentlyContinue)) {
    throw "Required command is unavailable: $($step.Executable)"
  }

  Write-Output ("[RUN] {0} | workdir={1}" -f $step.Id, $step.WorkDir)
  $locationPushed = $false
  $createdRustTestResource = $false
  try {
    if ($step.Category -eq "rust") {
      $createdRustTestResource = New-RustTestResource -Path $rustTestResourcePath
      Write-Output ("[SETUP] {0} | temporary-resource-created={1}" -f $step.Id, $createdRustTestResource.ToString().ToLowerInvariant())
    }

    Push-Location -LiteralPath $workDir
    $locationPushed = $true
    & $step.Executable @($step.Arguments)
    $exitCode = $LASTEXITCODE
  }
  finally {
    if ($locationPushed) {
      Pop-Location
    }
    if ($step.Category -eq "rust") {
      Remove-RustTestResource -Path $rustTestResourcePath -Created $createdRustTestResource
      if ($createdRustTestResource) {
        Write-Output ("[CLEANUP] {0} | temporary-resource-removed=true" -f $step.Id)
      }
    }
    if ($step.Id -eq "tools:soak-smoke" -and (Test-Path -LiteralPath $soakReportPath -PathType Leaf)) {
      Remove-Item -LiteralPath $soakReportPath -Force -ErrorAction SilentlyContinue
    }
  }

  if ($exitCode -ne 0) {
    throw "Verification step failed with exit code ${exitCode}: $($step.Id)"
  }
  Write-Output ("[PASS] {0}" -f $step.Id)
}

if ($DryRun) {
  Write-Output "Backend verification dry-run passed."
}
else {
  Write-Output "Backend verification passed."
}
