$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$verifyScript = Join-Path $root "tools\verify_backend.ps1"
$powershell = Join-Path $PSHOME "powershell.exe"

function Assert-True {
  param(
    [bool]$Condition,
    [string]$Message
  )

  if (-not $Condition) {
    throw $Message
  }
}

function Invoke-Verify {
  param([string[]]$Arguments)

  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    $output = @(& $powershell -NoProfile -ExecutionPolicy Bypass -File $verifyScript @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
  }
  finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
  return [PSCustomObject]@{
    ExitCode = $exitCode
    Output = @($output | ForEach-Object { $_.ToString() })
  }
}

Assert-True (Test-Path -LiteralPath $verifyScript -PathType Leaf) "tools\verify_backend.ps1 is missing."

$list = Invoke-Verify -Arguments @("-ListSteps")
Assert-True ($list.ExitCode -eq 0) "-ListSteps must return exit code 0."

$pythonSteps = @($list.Output | Where-Object { $_ -match '^\[STEP\] python:' })
Assert-True ($pythonSteps.Count -eq 9) "-ListSteps must expose exactly 9 Python test steps."
Assert-True (($pythonSteps | Where-Object { $_ -notmatch 'uv run --frozen --extra dev pytest tests' }).Count -eq 0) "Every Python step must use frozen dev dependencies."
Assert-True (($pythonSteps | Where-Object { $_ -notmatch 'lock=uv\.lock' }).Count -eq 0) "Every Python step must declare uv.lock usage."

$requiredPythonIds = @(
  "python:reflex-core",
  "python:reflex-runtime",
  "python:batch-runner",
  "python:history-sqlite",
  "python:markdown-preview",
  "python:provider-minimax",
  "python:provider-openai-compatible",
  "python:semantic-detector",
  "python:translator"
)
foreach ($id in $requiredPythonIds) {
  Assert-True (($list.Output | Where-Object { $_ -match ('^\[STEP\] ' + [regex]::Escape($id) + ' ') }).Count -eq 1) "Missing step: $id"
}

Assert-True (($list.Output | Where-Object { $_ -match '^\[STEP\] rust:tests .*cargo test --locked -- --test-threads=2' }).Count -eq 1) "Rust tests must use Cargo.lock and at most 2 test threads."
Assert-True (($list.Output | Where-Object { $_ -match '^\[STEP\] frontend:install .*npm ci' }).Count -eq 1) "Frontend install must use package-lock.json through npm ci."
Assert-True (($list.Output | Where-Object { $_ -match '^\[STEP\] frontend:tests .*npm test -- --maxWorkers=2' }).Count -eq 1) "Vitest must use at most 2 workers."
Assert-True (($list.Output | Where-Object { $_ -match '^\[STEP\] frontend:build .*npm run build' }).Count -eq 1) "Frontend production build must be part of verification."
Assert-True (($list.Output | Where-Object { $_ -match '^\[STEP\] security:secret-contract .*lock=none .*powershell .*scan_release_secrets_contract\.ps1' }).Count -eq 1) "Secret scanner contract tests must be part of verification."
Assert-True (($list.Output | Where-Object { $_ -match '^\[STEP\] security:secret-scan .*lock=none .*powershell .*scan_release_secrets\.ps1' }).Count -eq 1) "Tracked-file secret scanning must be part of verification."
Assert-True (($list.Output | Where-Object { $_ -match '^\[STEP\] security:dependency-contract .*heavy=False .*audit_dependencies_contract\.ps1' }).Count -eq 1) "Dependency-audit contract tests must be part of verification."
Assert-True (($list.Output | Where-Object { $_ -match '^\[STEP\] security:dependency-audit .*heavy=True .*audit_dependencies\.ps1' }).Count -eq 1) "The live dependency gate must be a resource-bounded heavy verification step."

$dryRun = Invoke-Verify -Arguments @("-DryRun", "-PythonProject", "reflex-core", "-SkipHeavy")
Assert-True ($dryRun.ExitCode -eq 0) "The focused dry-run must return exit code 0."
Assert-True (($dryRun.Output | Where-Object { $_ -match '^\[DRY-RUN\] python:reflex-core ' }).Count -eq 1) "The focused dry-run must select reflex-core."
Assert-True (($dryRun.Output | Where-Object { $_ -match '^\[DRY-RUN\] python:' }).Count -eq 1) "The focused dry-run must select only one Python project."
Assert-True (($dryRun.Output | Where-Object { $_ -match '^\[SKIP\] rust:tests .*SkipHeavy' }).Count -eq 1) "-SkipHeavy must skip Rust tests."
Assert-True (($dryRun.Output | Where-Object { $_ -match '^\[SKIP\] security:dependency-audit .*SkipHeavy' }).Count -eq 1) "-SkipHeavy must skip live dependency auditing."
Assert-True (($dryRun.Output | Where-Object { $_ -match '^\[SKIP\] frontend:tests .*SkipHeavy' }).Count -eq 1) "-SkipHeavy must skip frontend tests."

$frontendSkip = Invoke-Verify -Arguments @("-DryRun", "-PythonProject", "reflex-core", "-SkipFrontend")
Assert-True ($frontendSkip.ExitCode -eq 0) "The frontend-skip dry-run must return exit code 0."
Assert-True (($frontendSkip.Output | Where-Object { $_ -match '^\[DRY-RUN\] rust:tests ' }).Count -eq 1) "-SkipFrontend must not skip Rust tests."
Assert-True (($frontendSkip.Output | Where-Object { $_ -match '^\[SKIP\] frontend:tests .*SkipFrontend' }).Count -eq 1) "-SkipFrontend must skip frontend tests."
Assert-True (($frontendSkip.Output | Where-Object { $_ -match '^\[SKIP\] frontend:build .*SkipFrontend' }).Count -eq 1) "-SkipFrontend must skip the frontend build."

$dependencySkip = Invoke-Verify -Arguments @("-DryRun", "-PythonProject", "reflex-core", "-SkipFrontend", "-SkipDependencyAudit")
Assert-True ($dependencySkip.ExitCode -eq 0) "The dependency-audit skip dry-run must return exit code 0."
Assert-True (($dependencySkip.Output | Where-Object { $_ -match '^\[SKIP\] security:dependency-audit .*SkipDependencyAudit' }).Count -eq 1) "-SkipDependencyAudit must skip only the live dependency gate."
Assert-True (($dependencySkip.Output | Where-Object { $_ -match '^\[DRY-RUN\] security:dependency-contract ' }).Count -eq 1) "-SkipDependencyAudit must keep dependency contract tests enabled."

$resourceProbeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("reflex-rust-resource-contract-" + [guid]::NewGuid().ToString("N"))
$resourceProbe = Join-Path $resourceProbeRoot "resources\runtime\reflex-runtime.exe"
$resourceFakeBin = Join-Path $resourceProbeRoot "bin"
New-Item -ItemType Directory -Path $resourceFakeBin -Force | Out-Null
try {
  $fakeUv = Join-Path $resourceFakeBin "uv.cmd"
  $fakeCargo = Join-Path $resourceFakeBin "cargo.cmd"
  [System.IO.File]::WriteAllText($fakeUv, "@exit /b 0`r`n", [System.Text.Encoding]::ASCII)
  [System.IO.File]::WriteAllText($fakeCargo, "@if not exist `"$resourceProbe`" exit /b 41`r`n@exit /b 0`r`n", [System.Text.Encoding]::ASCII)

  $originalPath = $env:PATH
  $originalResourcePath = $env:REFLEX_VERIFY_RUST_TEST_RESOURCE_PATH
  $env:PATH = "$resourceFakeBin;$originalPath"
  $env:REFLEX_VERIFY_RUST_TEST_RESOURCE_PATH = $resourceProbe
  $resourceLifecycle = Invoke-Verify -Arguments @("-PythonProject", "reflex-core", "-SkipFrontend", "-SkipDependencyAudit")

  Assert-True ($resourceLifecycle.ExitCode -eq 0) "Rust verification must create its temporary bundle resource before cargo runs."
  Assert-True (($resourceLifecycle.Output | Where-Object { $_ -eq '[SETUP] rust:tests | temporary-resource-created=true' }).Count -eq 1) "Rust verification must report temporary resource creation."
  Assert-True (($resourceLifecycle.Output | Where-Object { $_ -eq '[CLEANUP] rust:tests | temporary-resource-removed=true' }).Count -eq 1) "Rust verification must report temporary resource cleanup."
  Assert-True (-not (Test-Path -LiteralPath $resourceProbe)) "Rust verification must remove the temporary resource after cargo exits."
}
finally {
  $env:PATH = $originalPath
  $env:REFLEX_VERIFY_RUST_TEST_RESOURCE_PATH = $originalResourcePath
  Remove-Item -LiteralPath $resourceProbeRoot -Recurse -Force -ErrorAction SilentlyContinue
}

$fakeBin = Join-Path ([System.IO.Path]::GetTempPath()) ("reflex-verify-contract-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $fakeBin | Out-Null
try {
  $fakeUv = Join-Path $fakeBin "uv.cmd"
  [System.IO.File]::WriteAllText($fakeUv, "@exit /b 23`r`n", [System.Text.Encoding]::ASCII)
  $originalPath = $env:PATH
  $env:PATH = "$fakeBin;$originalPath"
  $failure = Invoke-Verify -Arguments @("-PythonProject", "reflex-core", "-SkipHeavy")
  Assert-True ($failure.ExitCode -ne 0) "A failed verification step must return a nonzero exit code."
}
finally {
  $env:PATH = $originalPath
  Remove-Item -LiteralPath $fakeBin -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Output "verify_backend contract checks passed."
