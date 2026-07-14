$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$auditScript = Join-Path $root "tools\audit_dependencies.ps1"
$policyPath = Join-Path $root "tools\policies\dependency-audit-policy.json"
$powershell = Join-Path $PSHOME "powershell.exe"

function Assert-True {
  param([bool]$Condition, [string]$Message)
  if (-not $Condition) {
    throw $Message
  }
}

function Write-Utf8Json {
  param([string]$Path, [object]$Value)
  $json = $Value | ConvertTo-Json -Depth 12
  [System.IO.File]::WriteAllText($Path, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function New-CleanFixture {
  param([string]$Path)
  New-Item -ItemType Directory -Path $Path -Force | Out-Null
  Write-Utf8Json (Join-Path $Path "python-vulnerabilities.json") @{ dependencies = @(
    @{ name = "httpx"; version = "0.28.1"; vulns = @() },
    @{ name = "reflex-runtime"; version = "0.1.0"; vulns = @(@{}) }
  ) }
  Write-Utf8Json (Join-Path $Path "python-licenses.json") @(
    @{ Name = "httpx"; Version = "0.28.1"; License = "BSD-3-Clause" },
    @{ Name = "anyio"; Version = "4.14.1"; License = "UNKNOWN" },
    @{ Name = "certifi"; Version = "2026.6.17"; "License-Metadata" = "MPL-2.0"; "License-Classifier" = "Mozilla Public License 2.0" }
  )
  Write-Utf8Json (Join-Path $Path "rust-vulnerabilities.json") @{ vulnerabilities = @{ found = 0; list = @() } }
  Write-Utf8Json (Join-Path $Path "rust-licenses.json") @(@{ name = "serde"; version = "1.0.0"; license = "Apache-2.0 OR MIT" })
  Write-Utf8Json (Join-Path $Path "npm-vulnerabilities.json") @{ vulnerabilities = @{}; metadata = @{ vulnerabilities = @{ total = 0 } } }
  Write-Utf8Json (Join-Path $Path "npm-licenses.json") @(@{ name = "svelte"; version = "5.0.0"; license = "MIT" })
}

function Invoke-AuditFixture {
  param([string]$Path)
  $oldPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    $output = @(& $powershell -NoProfile -ExecutionPolicy Bypass -File $auditScript -RepositoryRoot $root -PolicyPath $policyPath -FixtureDirectory $Path 2>&1)
    $exitCode = $LASTEXITCODE
  }
  finally {
    $ErrorActionPreference = $oldPreference
  }
  return [PSCustomObject]@{ ExitCode = $exitCode; Output = @($output | ForEach-Object { $_.ToString() }) }
}

Assert-True (Test-Path -LiteralPath $auditScript -PathType Leaf) "Dependency audit script is missing."
Assert-True (Test-Path -LiteralPath $policyPath -PathType Leaf) "Dependency audit policy is missing."
$policy = Get-Content -Raw -Encoding UTF8 $policyPath | ConvertFrom-Json
$auditSource = [System.IO.File]::ReadAllText($auditScript, [System.Text.Encoding]::UTF8)
Assert-True (@($policy.licenses.allowed_expressions.python).Count -gt 0) "Python licenses require an explicit allowlist."
Assert-True (@($policy.licenses.allowed_expressions.rust).Count -gt 0) "Rust licenses require an explicit allowlist."
Assert-True (@($policy.licenses.allowed_expressions.npm).Count -gt 0) "npm licenses require an explicit allowlist."
Assert-True (@($policy.rust_advisory_exceptions).Count -gt 0) "Rust advisory exceptions must be explicit and reviewable."
$expectedRustLicenseOverrides = @{
  "hyper-rustls@0.27.9" = "Apache-2.0 OR ISC OR MIT"
  "ring@0.17.14" = "Apache-2.0 AND ISC"
  "rustls@0.23.42" = "Apache-2.0 OR ISC OR MIT"
  "ryu@1.0.23" = "Apache-2.0 OR BSL-1.0"
  "webpki-roots@1.0.8" = "CDLA-Permissive-2.0"
}
foreach ($entry in $expectedRustLicenseOverrides.GetEnumerator()) {
  $override = @($policy.licenses.package_overrides.rust.PSObject.Properties | Where-Object { $_.Name -eq $entry.Key }) | Select-Object -First 1
  Assert-True ($null -ne $override) ("Missing reviewed Rust license override: " + $entry.Key)
  Assert-True ([string]$override.Value -eq $entry.Value) ("Rust license override drifted: " + $entry.Key)
  Assert-True (@($policy.licenses.allowed_expressions.rust) -contains $entry.Value) ("Reviewed Rust license must remain explicitly allowed: " + $entry.Key)
}
foreach ($exception in @($policy.rust_advisory_exceptions)) {
  Assert-True ([string]$exception.scope -eq "non-windows-transitive-only") "Rust advisory exceptions must be limited to non-Windows transitive dependencies."
  Assert-True ([string]$exception.expires_on -match '^[0-9]{4}-[0-9]{2}-[0-9]{2}$') "Rust advisory exceptions require an expiry date."
  Assert-True (-not [string]::IsNullOrWhiteSpace([string]$exception.rationale)) "Rust advisory exceptions require a written rationale."
}
Assert-True ($auditSource -match 'cargo.*tree.*--target.*all') "Rust exceptions must prove that the package exists only in another target graph."
Assert-True ($auditSource -match 'expired_rust_advisory_exception') "Rust exceptions must fail closed after their expiry date."
Assert-True ($auditSource -match '\$previousErrorActionPreference = \$ErrorActionPreference') "Native command capture must preserve the caller error preference."
Assert-True ($auditSource -match '\$ErrorActionPreference = "Continue"') "Native stderr must not turn a successful tool exit into a PowerShell exception."
Assert-True ($auditSource -notmatch '--omit=dev') "npm auditing must include devDependencies from the full lockfile."
Assert-True ($auditSource -match 'npm@.*audit.*--json') "npm auditing must use the pinned npm tool against the full lockfile."

$probeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("reflex-dependency-audit-contract-" + [guid]::NewGuid().ToString("N"))
try {
  $cleanPath = Join-Path $probeRoot "clean"
  New-CleanFixture $cleanPath
  $clean = Invoke-AuditFixture $cleanPath
  Assert-True ($clean.ExitCode -eq 0) ("Clean dependency reports must pass. Output: " + ($clean.Output -join "; "))
  Assert-True (($clean.Output -join "`n") -eq "Dependency audit passed.") "Clean output must stay concise."

  $secretProbe = "synthetic-sensitive-value-never-print"
  foreach ($ecosystem in @("python", "rust", "npm")) {
    $path = Join-Path $probeRoot ("vulnerability-" + $ecosystem)
    New-CleanFixture $path
    if ($ecosystem -eq "python") {
      Write-Utf8Json (Join-Path $path "python-vulnerabilities.json") @{ dependencies = @(@{ name = "httpx"; version = "0"; vulns = @(@{ id = "PYSEC-1"; description = $secretProbe }) }) }
    }
    elseif ($ecosystem -eq "rust") {
      Write-Utf8Json (Join-Path $path "rust-vulnerabilities.json") @{ vulnerabilities = @{ found = 1; list = @(@{ advisory = @{ id = "RUSTSEC-1"; description = $secretProbe }; package = @{ name = "serde"; version = "0" } }) } }
    }
    else {
      Write-Utf8Json (Join-Path $path "npm-vulnerabilities.json") @{ vulnerabilities = @{ vite = @{ severity = "high"; via = @($secretProbe) } }; metadata = @{ vulnerabilities = @{ total = 1 } } }
    }
    $result = Invoke-AuditFixture $path
    $text = $result.Output -join "`n"
    Assert-True ($result.ExitCode -eq 20) "$ecosystem vulnerabilities must use exit code 20."
    Assert-True ($text -match ("category=vulnerability ecosystem=" + $ecosystem)) "$ecosystem vulnerability category is missing."
    Assert-True ($text -notmatch [regex]::Escape($secretProbe)) "Raw vulnerability details must be redacted."
  }

  $licensePath = Join-Path $probeRoot "forbidden-license"
  New-CleanFixture $licensePath
  Write-Utf8Json (Join-Path $licensePath "python-licenses.json") @(@{ Name = "blocked-package"; Version = "1"; License = "GPL-3.0-only" })
  $license = Invoke-AuditFixture $licensePath
  Assert-True ($license.ExitCode -eq 21) "Forbidden licenses must use exit code 21."
  Assert-True (($license.Output -join "`n") -match 'category=forbidden_license ecosystem=python package=blocked-package license=policy_match') "Forbidden-license output must be stable and redacted."

  $unknownPath = Join-Path $probeRoot "unknown-license"
  New-CleanFixture $unknownPath
  Write-Utf8Json (Join-Path $unknownPath "npm-licenses.json") @(@{ name = "unknown-package"; version = "1"; license = "UNKNOWN" })
  $unknown = Invoke-AuditFixture $unknownPath
  Assert-True ($unknown.ExitCode -eq 21) "Unknown licenses must use the forbidden-license exit code."
  Assert-True (($unknown.Output -join "`n") -match 'category=forbidden_license ecosystem=npm package=unknown-package license=unknown') "Unknown licenses must be classified explicitly."

  $unclassifiedPath = Join-Path $probeRoot "unclassified-license"
  New-CleanFixture $unclassifiedPath
  Write-Utf8Json (Join-Path $unclassifiedPath "rust-licenses.json") @(@{ name = "new-license-package"; version = "1"; license = "LicenseRef-New-Unreviewed" })
  $unclassified = Invoke-AuditFixture $unclassifiedPath
  Assert-True ($unclassified.ExitCode -eq 21) "Unclassified licenses must use the forbidden-license exit code."
  Assert-True (($unclassified.Output -join "`n") -match 'category=forbidden_license ecosystem=rust package=new-license-package license=unclassified') "Unclassified licenses must not enter silently."

  $failurePath = Join-Path $probeRoot "tool-failure"
  New-CleanFixture $failurePath
  [System.IO.File]::WriteAllText((Join-Path $failurePath "rust-licenses.json"), "not-json", [System.Text.Encoding]::UTF8)
  $failure = Invoke-AuditFixture $failurePath
  Assert-True ($failure.ExitCode -eq 22) "Malformed tool output must use exit code 22."
  Assert-True (($failure.Output -join "`n") -eq '[FAIL] category=tool_failure ecosystem=gate tool=audit_dependencies reason=unavailable_or_invalid') "Tool failure output must not expose raw errors."
}
finally {
  Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Output "audit_dependencies contract checks passed."
