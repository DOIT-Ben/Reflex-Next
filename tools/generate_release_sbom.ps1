[CmdletBinding()]
param(
  [string]$RepositoryRoot = "",
  [string]$OutputDirectory = "",
  [string[]]$ReleasePath = @(),
  [string]$FixtureDirectory = "",
  [switch]$Verify
)

$ErrorActionPreference = "Stop"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$powerShellCommand = Get-Command pwsh.exe -ErrorAction SilentlyContinue
if ($null -eq $powerShellCommand) {
  $powerShellCommand = Get-Command powershell.exe -ErrorAction Stop
}
$powerShellExecutable = $powerShellCommand.Source

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
  $RepositoryRoot = Join-Path $PSScriptRoot ".."
}
$repository = (Resolve-Path -LiteralPath $RepositoryRoot -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath $repository -PathType Container)) {
  throw "invalid_repository_root"
}
. (Join-Path $PSScriptRoot "project_registry.ps1")

$temporaryOutput = $false
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
  if (-not $Verify) {
    throw "output_directory_required"
  }
  $OutputDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("reflex-sbom-" + [guid]::NewGuid().ToString("N"))
  $temporaryOutput = $true
}
$output = [System.IO.Path]::GetFullPath($OutputDirectory)

$registry = Get-ReflexProjectRegistry -RepositoryRoot $repository
$components = @(Get-ReflexSbomComponentCatalog -Registry $registry)
$pythonComponents = @($components | Where-Object { [string]$_.Id -like "python-*" })
$rustComponent = @($components | Where-Object { [string]$_.Id -eq "rust-tauri-host" })[0]
$nodeComponent = @($components | Where-Object { [string]$_.Id -eq "node-tauri-host" })[0]
if ($null -eq $rustComponent -or $null -eq $nodeComponent) {
  throw "project_registry_native_sbom_components_missing"
}
$rustOutputBaseName = $rustComponent.Id + ".cdx"

function Invoke-CapturedCommand {
  param(
    [string]$Executable,
    [string[]]$Arguments,
    [string]$WorkDir
  )

  if (-not (Get-Command $Executable -ErrorAction SilentlyContinue)) {
    throw "missing_tool:$Executable"
  }
  $stderrPath = Join-Path ([System.IO.Path]::GetTempPath()) ("reflex-sbom-stderr-" + [guid]::NewGuid().ToString("N") + ".txt")
  $previousErrorActionPreference = $ErrorActionPreference
  $pushed = $false
  try {
    Push-Location -LiteralPath $WorkDir
    $pushed = $true
    $ErrorActionPreference = "Continue"
    $stdout = @(& $Executable @Arguments 2> $stderrPath)
    $exitCode = $LASTEXITCODE
    $stderr = if (Test-Path -LiteralPath $stderrPath -PathType Leaf) {
      [System.IO.File]::ReadAllText($stderrPath, [System.Text.Encoding]::UTF8)
    }
    else {
      ""
    }
  }
  finally {
    $ErrorActionPreference = $previousErrorActionPreference
    if ($pushed) {
      Pop-Location
    }
    Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
  }
  return [PSCustomObject]@{
    ExitCode = $exitCode
    Stdout = ($stdout | ForEach-Object { $_.ToString() }) -join "`n"
    Stderr = $stderr
  }
}

function Assert-CommandSucceeded {
  param(
    [object]$Result,
    [string]$FailureCode
  )
  if ($Result.ExitCode -ne 0) {
    throw $FailureCode
  }
}

function Get-Sha256 {
  param([string]$Path)
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Read-CycloneDxBom {
  param(
    [string]$Path,
    [string]$ExpectedName,
    [string]$ExpectedBomRefPrefix = ""
  )

  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "missing_sbom_output"
  }
  $file = Get-Item -LiteralPath $Path
  if ($file.Length -le 0 -or $file.Length -gt 64MB) {
    throw "invalid_sbom_size"
  }
  try {
    $bom = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
  }
  catch {
    throw "invalid_sbom_json"
  }
  if ($bom.bomFormat -ne "CycloneDX" -or [string]$bom.specVersion -ne "1.5" -or [int]$bom.version -lt 1) {
    throw "invalid_sbom_schema"
  }
  if ([string]$bom.metadata.component.name -ne $ExpectedName) {
    throw "invalid_sbom_root_component"
  }
  if (-not [string]::IsNullOrWhiteSpace($ExpectedBomRefPrefix) -and
      -not ([string]$bom.metadata.component.'bom-ref').StartsWith($ExpectedBomRefPrefix, [System.StringComparison]::Ordinal)) {
    throw "invalid_sbom_root_reference"
  }
  $refs = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
  foreach ($component in @($bom.components)) {
    $reference = [string]$component.'bom-ref'
    if ([string]::IsNullOrWhiteSpace([string]$component.name) -or [string]::IsNullOrWhiteSpace($reference)) {
      throw "invalid_sbom_component"
    }
    if (-not $refs.Add($reference)) {
      throw "duplicate_sbom_component"
    }
  }
  return [PSCustomObject]@{
    ComponentCount = @($bom.components).Count
  }
}

function Invoke-SecretScan {
  param([string]$Path)

  $scanner = Join-Path $repository "tools\scan_release_secrets.ps1"
  if (-not (Test-Path -LiteralPath $scanner -PathType Leaf)) {
    throw "missing_secret_scanner"
  }
  $result = Invoke-CapturedCommand -Executable $powerShellExecutable -Arguments @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $scanner,
    "-RepositoryRoot", $repository,
    "-SkipTrackedFiles",
    "-ReleasePath", $Path
  ) -WorkDir $repository
  if (-not [string]::IsNullOrWhiteSpace($result.Stdout)) {
    $result.Stdout -split "`n" | ForEach-Object { Write-Output $_ }
  }
  if ($result.ExitCode -ne 0) {
    throw "artifact_secret_scan_failed"
  }
}

$rustGeneratedPath = Join-Path $repository (Join-Path $rustComponent.Project ($rustOutputBaseName + ".json"))
try {
  $lockHashes = @{}
  foreach ($component in $components) {
    $lockPath = Join-Path $repository $component.Lock
    if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
      throw "missing_lock_file:$($component.Id)"
    }
    $lockHashes[$component.Lock] = Get-Sha256 -Path $lockPath
  }

  if (Test-Path -LiteralPath $output) {
    if (-not (Test-Path -LiteralPath $output -PathType Container)) {
      throw "invalid_output_directory"
    }
    if (@(Get-ChildItem -LiteralPath $output -Force).Count -ne 0) {
      throw "output_directory_not_empty"
    }
  }
  else {
    New-Item -ItemType Directory -Path $output -Force | Out-Null
  }

  if ([string]::IsNullOrWhiteSpace($FixtureDirectory)) {
    $uvVersion = Invoke-CapturedCommand -Executable "uv" -Arguments @("--version") -WorkDir $repository
    Assert-CommandSucceeded -Result $uvVersion -FailureCode "uv_version_check_failed"
    if ($uvVersion.Stdout -notmatch '^uv 0\.11\.13(?:\s|$)') {
      throw "uv_version_mismatch"
    }

    $npmVersion = Invoke-CapturedCommand -Executable "npm" -Arguments @("--version") -WorkDir $repository
    Assert-CommandSucceeded -Result $npmVersion -FailureCode "npm_version_check_failed"
    $npmMajor = 0
    if (-not [int]::TryParse(($npmVersion.Stdout.Trim() -split '\.')[0], [ref]$npmMajor) -or $npmMajor -lt 9) {
      throw "npm_version_unsupported"
    }

    $cargoCycloneDxVersion = Invoke-CapturedCommand -Executable "cargo" -Arguments @("cyclonedx", "--version") -WorkDir $repository
    Assert-CommandSucceeded -Result $cargoCycloneDxVersion -FailureCode "cargo_cyclonedx_missing"
    if ($cargoCycloneDxVersion.Stdout -notmatch '(?<![0-9])0\.5\.9(?![0-9])') {
      throw "cargo_cyclonedx_version_mismatch"
    }

    foreach ($component in $pythonComponents) {
      $destination = Join-Path $output ($component.Id + ".cdx.json")
      $result = Invoke-CapturedCommand -Executable "uv" -Arguments @(
        "export",
        "--project", (Join-Path $repository $component.Project),
        "--frozen",
        "--no-dev",
        "--preview-features", "sbom-export",
        "--format", "cyclonedx1.5",
        "--output-file", $destination
      ) -WorkDir $repository
      Assert-CommandSucceeded -Result $result -FailureCode "python_sbom_generation_failed:$($component.Id)"
    }

    if (Test-Path -LiteralPath $rustGeneratedPath) {
      throw "rust_sbom_staging_path_exists"
    }
    $rustResult = Invoke-CapturedCommand -Executable "cargo" -Arguments @(
      "cyclonedx",
      "--manifest-path", (Join-Path $repository (Join-Path $rustComponent.Project "Cargo.toml")),
      "--format", "json",
      "--spec-version", "1.5",
      "--target", "x86_64-pc-windows-msvc",
      "--override-filename", $rustOutputBaseName,
      "--quiet"
    ) -WorkDir $repository
    Assert-CommandSucceeded -Result $rustResult -FailureCode "rust_sbom_generation_failed"
    if (-not (Test-Path -LiteralPath $rustGeneratedPath -PathType Leaf)) {
      throw "rust_sbom_output_missing"
    }
    Move-Item -LiteralPath $rustGeneratedPath -Destination (Join-Path $output ($rustComponent.Id + ".cdx.json"))

    $nodeResult = Invoke-CapturedCommand -Executable "npm" -Arguments @(
      "sbom",
      "--package-lock-only",
      "--omit=dev",
      "--sbom-format", "cyclonedx"
    ) -WorkDir (Join-Path $repository $nodeComponent.Project)
    Assert-CommandSucceeded -Result $nodeResult -FailureCode "node_sbom_generation_failed"
    [System.IO.File]::WriteAllText((Join-Path $output ($nodeComponent.Id + ".cdx.json")), $nodeResult.Stdout + "`n", $utf8NoBom)
  }
  else {
    $fixture = (Resolve-Path -LiteralPath $FixtureDirectory -ErrorAction Stop).Path
    foreach ($component in $components) {
      $filename = $component.Id + ".cdx.json"
      $source = Join-Path $fixture $filename
      if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "missing_fixture_sbom:$($component.Id)"
      }
      Copy-Item -LiteralPath $source -Destination (Join-Path $output $filename)
    }
  }

  $manifestComponents = @()
  foreach ($component in $components) {
    $filename = $component.Id + ".cdx.json"
    $sbomPath = Join-Path $output $filename
    $validated = Read-CycloneDxBom -Path $sbomPath -ExpectedName $component.Name -ExpectedBomRefPrefix $component.BomRefPrefix
    $lockPath = Join-Path $repository $component.Lock
    $currentLockHash = Get-Sha256 -Path $lockPath
    if ($currentLockHash -ne $lockHashes[$component.Lock]) {
      throw "lock_file_changed_during_generation:$($component.Id)"
    }
    $ecosystem = ($component.Id -split '-')[0]
    $manifestComponents += [ordered]@{
      id = $component.Id
      ecosystem = $ecosystem
       root_component = $component.Name
      source_lock = ($component.Lock -replace '\\', '/')
      source_lock_sha256 = $currentLockHash
      sbom_file = $filename
      sbom_sha256 = Get-Sha256 -Path $sbomPath
      dependency_components = $validated.ComponentCount
    }
  }

  $manifest = [ordered]@{
    schema_version = 1
    format = "CycloneDX"
    spec_version = "1.5"
    target = "x86_64-pc-windows-msvc"
    components = $manifestComponents
  }
  $manifestJson = $manifest | ConvertTo-Json -Depth 8
  [System.IO.File]::WriteAllText((Join-Path $output "sbom-manifest.json"), $manifestJson + "`n", $utf8NoBom)

  Invoke-SecretScan -Path $output
  foreach ($path in $ReleasePath) {
    $resolvedReleasePath = (Resolve-Path -LiteralPath $path -ErrorAction Stop).Path
    Invoke-SecretScan -Path $resolvedReleasePath
  }

  Write-Output ("SBOM generation passed: {0} component BOMs; {1} release paths scanned." -f $components.Count, @($ReleasePath).Count)
}
finally {
  Remove-Item -LiteralPath $rustGeneratedPath -Force -ErrorAction SilentlyContinue
  if ($temporaryOutput) {
    Remove-Item -LiteralPath $output -Recurse -Force -ErrorAction SilentlyContinue
  }
}
