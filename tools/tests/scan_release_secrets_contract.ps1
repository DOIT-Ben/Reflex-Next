$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$scanScript = Join-Path $root "tools\scan_release_secrets.ps1"
$powershellCommand = Get-Command pwsh.exe -ErrorAction SilentlyContinue
if ($null -eq $powershellCommand) {
  $powershellCommand = Get-Command powershell.exe -ErrorAction Stop
}
$powershell = $powershellCommand.Source

function Assert-True {
  param(
    [bool]$Condition,
    [string]$Message
  )

  if (-not $Condition) {
    throw $Message
  }
}

function Write-Utf8File {
  param(
    [string]$Path,
    [string]$Content
  )

  $parent = Split-Path -Parent $Path
  if ($parent) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
  }
  [System.IO.File]::WriteAllText($Path, $Content, (New-Object System.Text.UTF8Encoding($false)))
}

function Invoke-Scan {
  param(
    [string]$RepositoryRoot,
    [string[]]$ReleasePath = @(),
    [switch]$SkipTrackedFiles
  )

  $arguments = @("-RepositoryRoot", $RepositoryRoot)
  foreach ($path in $ReleasePath) {
    $arguments += @("-ReleasePath", $path)
  }
  if ($SkipTrackedFiles) {
    $arguments += "-SkipTrackedFiles"
  }

  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    $output = @(& $powershell -NoProfile -ExecutionPolicy Bypass -File $scanScript @arguments 2>&1)
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

function Initialize-TestRepository {
  param([string]$Path)

  New-Item -ItemType Directory -Path $Path -Force | Out-Null
  & git -C $Path init --quiet
  if ($LASTEXITCODE -ne 0) {
    throw "Unable to initialize contract-test repository."
  }
  & git -C $Path config core.autocrlf false
  if ($LASTEXITCODE -ne 0) {
    throw "Unable to configure contract-test repository."
  }
}

function Add-TestFiles {
  param(
    [string]$RepositoryRoot,
    [string[]]$Paths
  )

  & git -C $RepositoryRoot add -- @Paths
  if ($LASTEXITCODE -ne 0) {
    throw "Unable to stage contract-test files."
  }
}

$probeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("reflex-secret-scan-contract-" + [guid]::NewGuid().ToString("N"))
$repository = Join-Path $probeRoot "repository"
$release = Join-Path $probeRoot "release"

try {
  Assert-True (Test-Path -LiteralPath $scanScript -PathType Leaf) "tools\scan_release_secrets.ps1 is missing."
  Initialize-TestRepository -Path $repository

  Write-Utf8File -Path (Join-Path $repository "safe.txt") -Content @"
api_key = YOUR_API_KEY_HERE
password = <password>
token = example-token-for-documentation
api_key = provider-fixture-key
Authorization: Bearer fixture-private-value
api_key = sk-test-1234567890abcdef
This fixture discusses password, credentials, and private keys without containing one.
"@
  Write-Utf8File -Path (Join-Path $repository ".env.example") -Content "MINIMAX_API_KEY=replace-me"
  Write-Utf8File -Path (Join-Path $repository "compose.yml") -Content 'MINIMAX_API_KEY: ${MINIMAX_API_KEY:?set MINIMAX_API_KEY}'
  Copy-Item -LiteralPath $scanScript -Destination (Join-Path $repository "scan_release_secrets.ps1")
  Add-TestFiles -RepositoryRoot $repository -Paths @("safe.txt", ".env.example", "compose.yml", "scan_release_secrets.ps1")

  $clean = Invoke-Scan -RepositoryRoot $repository
  Assert-True ($clean.ExitCode -eq 0) "Placeholders and ordinary security words must not fail the scan."
  Assert-True ($clean.Output.Count -eq 0) "A clean scan must not emit noisy output."

  $untrackedToken = ("gh" + "p_" + ("U" * 36))
  Write-Utf8File -Path (Join-Path $repository "untracked.txt") -Content ("token=" + $untrackedToken)
  $untracked = Invoke-Scan -RepositoryRoot $repository
  Assert-True ($untracked.ExitCode -eq 0) "Untracked repository files must not be included in the tracked-file gate."
  Assert-True (($untracked.Output -join "`n") -notmatch [regex]::Escape($untrackedToken)) "Scanner output must never echo untracked content."

  $providerToken = ("sk" + "-cp-" + ("A7_" * 16))
  $genericCredential = (("Km9!qR2#" * 4) + "Vz7")
  $privateKeyHeader = ("-----BEGIN " + "PRIVATE KEY-----")
  Write-Utf8File -Path (Join-Path $repository "tracked-config.txt") -Content (("MINIMAX_API_KEY=" + $providerToken) + "`nCLIENT_SECRET=" + $genericCredential)
  Write-Utf8File -Path (Join-Path $repository "tracked-key.pem") -Content ($privateKeyHeader + "`nsynthetic-fixture")
  Add-TestFiles -RepositoryRoot $repository -Paths @("tracked-config.txt", "tracked-key.pem")

  $tracked = Invoke-Scan -RepositoryRoot $repository
  $trackedOutput = $tracked.Output -join "`n"
  Assert-True ($tracked.ExitCode -ne 0) "Tracked high-confidence secrets must fail the scan."
  Assert-True ($trackedOutput -match 'tracked-config\.txt:1 \| rule=provider-api-key') "Provider token findings must include only location and rule."
  Assert-True ($trackedOutput -match 'tracked-config\.txt:2 \| rule=credential-assignment') "Generic high-entropy credentials must be detected."
  Assert-True ($trackedOutput -match 'tracked-key\.pem:1 \| rule=private-key') "Private-key findings must include only location and rule."
  Assert-True ($trackedOutput -notmatch [regex]::Escape($providerToken)) "Provider tokens must never be echoed."
  Assert-True ($trackedOutput -notmatch [regex]::Escape($genericCredential)) "Generic credentials must never be echoed."
  Assert-True ($trackedOutput -notmatch [regex]::Escape($privateKeyHeader)) "Private-key material must never be echoed."
  Assert-True (($tracked.Output | Where-Object { $_ -notmatch '^.+(?::\d+)? \| rule=[a-z0-9-]+$' }).Count -eq 0) "Finding output must contain only a file location and rule name."

  $releaseOnly = Invoke-Scan -RepositoryRoot $repository -ReleasePath @((Join-Path $repository "safe.txt")) -SkipTrackedFiles
  Assert-True ($releaseOnly.ExitCode -eq 0) "Artifact-only mode must not rescan tracked repository files."
  Assert-True ($releaseOnly.Output.Count -eq 0) "Artifact-only mode must emit only findings from requested release paths."

  & git -C $repository rm --cached --quiet -- "tracked-config.txt" "tracked-key.pem"
  Assert-True ($LASTEXITCODE -eq 0) "Unable to reset tracked secret fixtures."

  $authorizationToken = (("aB3_" * 10) + "z9")
  $binaryToken = ("gh" + "o_" + ("D8mQ2v" * 6))
  Write-Utf8File -Path (Join-Path $release "app\settings.json") -Content ('{"authorization":"Bearer ' + $authorizationToken + '"}')
  Write-Utf8File -Path (Join-Path $release "app\.env.production") -Content "API_KEY=YOUR_API_KEY_HERE"
  [System.IO.File]::WriteAllBytes(
    (Join-Path $release "app\runtime.bin"),
    ([byte[]](0, 1, 2, 0) + [System.Text.Encoding]::ASCII.GetBytes("token=" + $binaryToken))
  )
  [System.IO.File]::WriteAllBytes(
    (Join-Path $release "app\compiled.bin"),
    ([System.Text.Encoding]::ASCII.GetBytes("https://user:Ab3!") +
      [byte[]](0) +
      [System.Text.Encoding]::ASCII.GetBytes("Cd4Ef5Gh6Jk7@"))
  )

  $releaseResult = Invoke-Scan -RepositoryRoot $repository -ReleasePath @($release) -SkipTrackedFiles
  $releaseOutput = $releaseResult.Output -join "`n"
  Assert-True ($releaseResult.ExitCode -ne 0) "Release-directory secrets and credential files must fail the scan."
  Assert-True ($releaseOutput -match 'settings\.json:1 \| rule=authorization-token') "Release content findings must identify location and rule."
  Assert-True ($releaseOutput -match '\.env\.production \| rule=credential-file') "Credential filenames must be blocked even when their values are placeholders."
  Assert-True ($releaseOutput -match 'runtime\.bin \| rule=github-token') "Binary release files must be scanned for embedded high-confidence tokens."
  Assert-True ($releaseOutput -notmatch 'compiled\.bin \| rule=credential-url') "Binary control bytes must delimit printable credential candidates."
  Assert-True ($releaseOutput -notmatch [regex]::Escape($authorizationToken)) "Authorization tokens must never be echoed."
  Assert-True ($releaseOutput -notmatch [regex]::Escape($binaryToken)) "Binary tokens must never be echoed."
  Assert-True (($releaseResult.Output | Where-Object { $_ -notmatch '^.+(?::\d+)? \| rule=[a-z0-9-]+$' }).Count -eq 0) "Release findings must remain machine-readable and redacted."
  Assert-True (($releaseResult.Output | Where-Object { $_ -notmatch '^app\\.+(?::\d+)? \| rule=[a-z0-9-]+$' }).Count -eq 0) "Release findings must use paths relative to the requested release directory."
}
finally {
  Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Output "scan_release_secrets contract checks passed."
