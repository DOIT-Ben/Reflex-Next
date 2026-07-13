[CmdletBinding()]
param(
  [string]$Root = "",
  [switch]$RequireTag
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Root)) {
  $Root = Join-Path $PSScriptRoot ".."
}

function Get-JsonVersion {
  param(
    [string]$Path,
    [string]$Label
  )

  try {
    $document = Get-Content -Raw -Encoding UTF8 -LiteralPath $Path | ConvertFrom-Json
  }
  catch {
    throw ("{0} version manifest is not valid JSON: {1}" -f $Label, $Path)
  }

  if (-not ($document.PSObject.Properties.Name -contains "version")) {
    throw ("{0} version is missing: {1}" -f $Label, $Path)
  }
  if ($document.version -isnot [string] -or [string]::IsNullOrWhiteSpace($document.version)) {
    throw ("{0} version must be a non-empty string: {1}" -f $Label, $Path)
  }

  return $document.version
}

function Get-TomlSectionVersion {
  param(
    [string]$Path,
    [string]$Section,
    [string]$Label
  )

  $currentSection = ""
  $versions = @()
  foreach ($line in Get-Content -Encoding UTF8 -LiteralPath $Path) {
    if ($line -match '^\s*\[([^]]+)\]\s*(?:#.*)?$') {
      $currentSection = $Matches[1].Trim()
      continue
    }
    if ($currentSection -ne $Section) {
      continue
    }

    if ($line -match '^\s*version\s*=\s*"([^"]+)"\s*(?:#.*)?$') {
      $versions += $Matches[1]
    }
    elseif ($line -match "^\s*version\s*=\s*'([^']+)'\s*(?:#.*)?$") {
      $versions += $Matches[1]
    }
    elseif ($line -match '^\s*version\s*=') {
      throw ("{0} version must be a TOML string in [{1}]: {2}" -f $Label, $Section, $Path)
    }
  }

  if ($versions.Count -eq 0) {
    throw ("{0} version is missing from [{1}]: {2}" -f $Label, $Section, $Path)
  }
  if ($versions.Count -gt 1) {
    throw ("{0} declares version more than once in [{1}]: {2}" -f $Label, $Section, $Path)
  }

  return $versions[0]
}

function Assert-SemVer {
  param(
    [string]$Version,
    [string]$Label
  )

  $semVerPattern = '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$'
  if ($Version -notmatch $semVerPattern) {
    throw ("{0} is not a valid semantic version: {1}" -f $Label, $Version)
  }
}

try {
  $resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
}
catch {
  throw "Version check root does not exist: $Root"
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  throw "Git is required for the version consistency check."
}

$gitOutput = @(& git -C $resolvedRoot tag --points-at HEAD 2>&1)
if ($LASTEXITCODE -ne 0) {
  throw ("Unable to read Git tags at HEAD: {0}" -f (($gitOutput | ForEach-Object { $_.ToString() }) -join " "))
}

$releaseTagPattern = '^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$'
$releaseTags = @($gitOutput | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ -match $releaseTagPattern })
if ($releaseTags.Count -gt 1) {
  throw ("HEAD has multiple release tags: {0}" -f ($releaseTags -join ", "))
}
if ($RequireTag -and $releaseTags.Count -eq 0) {
  throw "HEAD does not have a v<SemVer> release tag."
}

$sources = @(
  [PSCustomObject]@{ Label = "Tauri"; Path = "apps\tauri-host\src-tauri\tauri.conf.json"; Kind = "json"; Version = $null },
  [PSCustomObject]@{ Label = "Cargo"; Path = "apps\tauri-host\src-tauri\Cargo.toml"; Kind = "toml"; Section = "package"; Version = $null },
  [PSCustomObject]@{ Label = "npm"; Path = "apps\tauri-host\package.json"; Kind = "json"; Version = $null },
  [PSCustomObject]@{ Label = "Python reflex-core"; Path = "packages\reflex-core\pyproject.toml"; Kind = "toml"; Section = "project"; Version = $null },
  [PSCustomObject]@{ Label = "Python reflex-runtime"; Path = "packages\reflex-runtime\pyproject.toml"; Kind = "toml"; Section = "project"; Version = $null }
)

foreach ($source in $sources) {
  $fullPath = Join-Path $resolvedRoot $source.Path
  if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
    throw ("{0} version manifest is missing: {1}" -f $source.Label, $source.Path)
  }

  if ($source.Kind -eq "json") {
    $source.Version = Get-JsonVersion -Path $fullPath -Label $source.Label
  }
  else {
    $source.Version = Get-TomlSectionVersion -Path $fullPath -Section $source.Section -Label $source.Label
  }
}

foreach ($source in $sources) {
  Assert-SemVer -Version $source.Version -Label $source.Label
  Write-Output ("[VERSION] {0} | version={1} | source={2}" -f $source.Label, $source.Version, $source.Path)
}

$baselineVersion = $sources[0].Version
$comparisonSources = @($sources)
if ($releaseTags.Count -eq 1) {
  $gitVersion = $releaseTags[0].Substring(1)
  $gitSource = [PSCustomObject]@{
    Label = "Git release tag"
    Path = ".git"
    Kind = "git"
    Version = $gitVersion
  }
  Assert-SemVer -Version $gitSource.Version -Label $gitSource.Label
  Write-Output ("[VERSION] {0} | version={1} | source={2}" -f $gitSource.Label, $gitSource.Version, $gitSource.Path)
  $comparisonSources += $gitSource
}

$mismatches = @($comparisonSources | Where-Object { $_.Version -cne $baselineVersion })
if ($mismatches.Count -gt 0) {
  $details = @($comparisonSources | ForEach-Object {
      "{0}={1} ({2})" -f $_.Label, $_.Version, $_.Path
    }) -join "; "
  throw ("Product release versions are inconsistent (baseline {0}={1}): {2}" -f $sources[0].Label, $baselineVersion, $details)
}

Write-Output "Version consistency check passed: $baselineVersion"
