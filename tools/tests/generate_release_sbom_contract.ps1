$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$generator = Join-Path $root "tools\generate_release_sbom.ps1"
$probeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("reflex-sbom-contract-" + [guid]::NewGuid().ToString("N"))
$fixtures = Join-Path $probeRoot "fixtures"
$output = Join-Path $probeRoot "output"
$safeRelease = Join-Path $probeRoot "safe-release"
$unsafeRelease = Join-Path $probeRoot "unsafe-release"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$components = [ordered]@{
  "python-reflex-core" = "reflex-core"
  "python-reflex-runtime" = "reflex-runtime"
  "python-batch-runner" = "reflex-batch-runner"
  "python-history-sqlite" = "reflex-history-sqlite"
  "python-markdown-preview" = "reflex-markdown-preview"
  "python-provider-minimax" = "reflex-provider-minimax"
  "python-provider-openai-compatible" = "reflex-provider-openai-compatible"
  "python-semantic-detector" = "reflex-plugin-semantic-detector"
  "python-translator" = "reflex-translator"
  "rust-tauri-host" = "reflex-next-tauri-host"
  "node-tauri-host" = "tauri-host"
}

function Assert-True {
  param(
    [bool]$Condition,
    [string]$Message
  )
  if (-not $Condition) {
    throw $Message
  }
}

function Invoke-Generator {
  param(
    [string]$OutputPath,
    [string]$FixturePath,
    [string[]]$ReleasePaths = @()
  )
  $arguments = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", $generator,
    "-RepositoryRoot", $root,
    "-OutputDirectory", $OutputPath,
    "-FixtureDirectory", $FixturePath
  )
  if ($ReleasePaths.Count -gt 0) {
    $arguments += "-ReleasePath"
    $arguments += $ReleasePaths
  }
  $stdoutPath = Join-Path $probeRoot ("stdout-" + [guid]::NewGuid().ToString("N") + ".txt")
  $stderrPath = Join-Path $probeRoot ("stderr-" + [guid]::NewGuid().ToString("N") + ".txt")
  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    & powershell @arguments 1> $stdoutPath 2> $stderrPath
    return [PSCustomObject]@{
      ExitCode = $LASTEXITCODE
      Stdout = if (Test-Path $stdoutPath) { [System.IO.File]::ReadAllText($stdoutPath) } else { "" }
      Stderr = if (Test-Path $stderrPath) { [System.IO.File]::ReadAllText($stderrPath) } else { "" }
    }
  }
  finally {
    $ErrorActionPreference = $previousErrorActionPreference
    Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
  }
}

try {
  Assert-True (Test-Path -LiteralPath $generator -PathType Leaf) "tools\generate_release_sbom.ps1 is missing."
  New-Item -ItemType Directory -Path $fixtures, $safeRelease, $unsafeRelease -Force | Out-Null

  foreach ($entry in $components.GetEnumerator()) {
    $rootComponent = [ordered]@{
      type = "application"
      'bom-ref' = ($entry.Key + "@0.1.0")
      name = $entry.Value
      version = "0.1.0"
    }
    if ($entry.Key -eq "node-tauri-host") {
      $rootComponent.'bom-ref' = "@reflex-next/tauri-host@0.1.0"
    }
    $bom = [ordered]@{
      bomFormat = "CycloneDX"
      specVersion = "1.5"
      version = 1
      metadata = [ordered]@{
        component = $rootComponent
      }
      components = @(
        [ordered]@{
          type = "library"
          'bom-ref' = ("fixture-dependency-" + $entry.Key)
          name = "fixture-dependency"
          version = "1.0.0"
        }
      )
      dependencies = @()
    }
    [System.IO.File]::WriteAllText(
      (Join-Path $fixtures ($entry.Key + ".cdx.json")),
      (($bom | ConvertTo-Json -Depth 8) + "`n"),
      $utf8NoBom
    )
  }
  [System.IO.File]::WriteAllText((Join-Path $safeRelease "reflex-runtime.exe"), "safe fixture", $utf8NoBom)

  $success = Invoke-Generator -OutputPath $output -FixturePath $fixtures -ReleasePaths @($safeRelease)
  Assert-True ($success.ExitCode -eq 0) "Valid component BOMs and a clean release path must pass."
  Assert-True ($success.Stdout -match '11 component BOMs; 1 release paths scanned') "Success output must report bounded component and release counts."
  $manifestPath = Join-Path $output "sbom-manifest.json"
  Assert-True (Test-Path -LiteralPath $manifestPath -PathType Leaf) "SBOM manifest must be emitted."
  $manifest = [System.IO.File]::ReadAllText($manifestPath) | ConvertFrom-Json
  Assert-True (@($manifest.components).Count -eq 11) "Manifest must enumerate every product component."
  Assert-True (($manifest.components | Where-Object { $_.source_lock_sha256 -notmatch '^[a-f0-9]{64}$' }).Count -eq 0) "Every source lock must have a SHA-256 digest."
  Assert-True (($manifest.components | Where-Object { $_.sbom_sha256 -notmatch '^[a-f0-9]{64}$' }).Count -eq 0) "Every component BOM must have a SHA-256 digest."
  Assert-True ((Get-Content -Raw -Encoding UTF8 $manifestPath) -notmatch [regex]::Escape($root)) "Manifest must not leak absolute workspace paths."

  $stale = Invoke-Generator -OutputPath $output -FixturePath $fixtures
  Assert-True ($stale.ExitCode -ne 0) "A non-empty output directory must fail instead of mixing stale material."
  Assert-True ($stale.Stderr -match 'output_directory_not_empty') "Stale-output failure must have a stable category."

  $invalidFixtures = Join-Path $probeRoot "invalid-fixtures"
  Copy-Item -LiteralPath $fixtures -Destination $invalidFixtures -Recurse
  [System.IO.File]::WriteAllText((Join-Path $invalidFixtures "python-reflex-core.cdx.json"), '{"bomFormat":"SPDX"}', $utf8NoBom)
  $invalidOutput = Join-Path $probeRoot "invalid-output"
  $invalid = Invoke-Generator -OutputPath $invalidOutput -FixturePath $invalidFixtures
  Assert-True ($invalid.ExitCode -ne 0) "A malformed component BOM must fail."
  Assert-True ($invalid.Stderr -match 'invalid_sbom_schema') "Malformed BOM failure must have a stable category."

  $secret = ("gh" + "p_" + ("S" * 36))
  [System.IO.File]::WriteAllText((Join-Path $unsafeRelease "runtime.bin"), ("token=" + $secret), $utf8NoBom)
  $secretOutput = Join-Path $probeRoot "secret-output"
  $unsafe = Invoke-Generator -OutputPath $secretOutput -FixturePath $fixtures -ReleasePaths @($unsafeRelease)
  Assert-True ($unsafe.ExitCode -ne 0) "A release artifact containing a high-confidence secret must fail."
  Assert-True (($unsafe.Stdout + $unsafe.Stderr) -match 'artifact_secret_scan_failed') "Artifact scan failure must have a stable category."
  Assert-True (($unsafe.Stdout + $unsafe.Stderr) -notmatch [regex]::Escape($secret)) "Secret scanner output must remain redacted."
}
finally {
  Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Output "generate_release_sbom contract checks passed."
