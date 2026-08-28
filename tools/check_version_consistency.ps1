[CmdletBinding()]
param(
  [string]$Root = "",
  [switch]$RequireTag,
  [switch]$IgnoreTag
)

$ErrorActionPreference = "Stop"

if ($RequireTag -and $IgnoreTag) {
  throw "RequireTag and IgnoreTag cannot be used together."
}

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

function Get-TextVersion {
  param(
    [string]$Path,
    [string]$Label
  )

  $lines = @(Get-Content -Encoding UTF8 -LiteralPath $Path)
  if ($lines.Count -ne 1 -or [string]::IsNullOrWhiteSpace($lines[0])) {
    throw ("{0} must contain exactly one non-empty version line: {1}" -f $Label, $Path)
  }

  return $lines[0].Trim()
}

function Get-NpmLockVersion {
  param(
    [string]$Path,
    [string]$Label
  )

  try {
    $raw = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    if ($PSVersionTable.PSVersion.Major -ge 6) {
      $document = $raw | ConvertFrom-Json -AsHashtable
    }
    else {
      Add-Type -AssemblyName System.Web.Extensions -ErrorAction Stop
      $serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer
      $document = $serializer.DeserializeObject($raw)
    }
  }
  catch {
    throw ("{0} is not valid JSON: {1}" -f $Label, $Path)
  }

  if (-not (@($document.Keys) -contains "version") -or
      $document["version"] -isnot [string] -or
      [string]::IsNullOrWhiteSpace($document["version"])) {
    throw ("{0} top-level version is missing: {1}" -f $Label, $Path)
  }
  if (-not (@($document.Keys) -contains "packages") -or $null -eq $document["packages"]) {
    throw ("{0} packages map is missing: {1}" -f $Label, $Path)
  }

  $packages = $document["packages"]
  if (-not (@($packages.Keys) -contains "")) {
    throw ("{0} root package entry is missing: {1}" -f $Label, $Path)
  }
  $rootPackage = $packages[""]
  if (-not (@($rootPackage.Keys) -contains "version") -or
      $rootPackage["version"] -isnot [string] -or
      [string]::IsNullOrWhiteSpace($rootPackage["version"])) {
    throw ("{0} root package version is missing: {1}" -f $Label, $Path)
  }
  if ((Normalize-ReleaseVersion $document["version"]) -cne (Normalize-ReleaseVersion $rootPackage["version"])) {
    throw ("{0} top-level and root package versions differ: {1}" -f $Label, $Path)
  }

  return $document["version"]
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

function Get-LockPackageVersion {
  param(
    [string]$Path,
    [string]$Package,
    [string]$Label
  )

  $currentPackage = ""
  $versions = @()
  foreach ($line in Get-Content -Encoding UTF8 -LiteralPath $Path) {
    if ($line -match '^\s*\[\[package\]\]\s*$') {
      $currentPackage = ""
      continue
    }
    if ($line -match '^\s*name\s*=\s*"([^"]+)"\s*(?:#.*)?$') {
      $currentPackage = $Matches[1]
      continue
    }
    if ($currentPackage -ne $Package) {
      continue
    }
    if ($line -match '^\s*version\s*=\s*"([^"]+)"\s*(?:#.*)?$') {
      $versions += $Matches[1]
    }
    elseif ($line -match '^\s*version\s*=') {
      throw ("{0} version must be a quoted string for package {1}: {2}" -f $Label, $Package, $Path)
    }
  }

  if ($versions.Count -eq 0) {
    throw ("{0} package version is missing for {1}: {2}" -f $Label, $Package, $Path)
  }
  if ($versions.Count -gt 1) {
    throw ("{0} declares package {1} more than once: {2}" -f $Label, $Package, $Path)
  }

  return $versions[0]
}

function Normalize-ReleaseVersion {
  param([string]$Version)

  $value = $Version.Trim()
  if ($value.StartsWith("v", [System.StringComparison]::OrdinalIgnoreCase)) {
    $value = $value.Substring(1)
  }

  $semVerPre = '^(?<major>0|[1-9]\d*)\.(?<minor>0|[1-9]\d*)\.(?<patch>0|[1-9]\d*)-(?<label>alpha|a|beta|b|rc)[.-]?(?<number>0|[1-9]\d*)$'
  $pep440Pre = '^(?<major>0|[1-9]\d*)\.(?<minor>0|[1-9]\d*)\.(?<patch>0|[1-9]\d*)(?<label>a|b|rc)(?<number>0|[1-9]\d*)$'
  if ($value -match $semVerPre -or $value -match $pep440Pre) {
    $label = switch ($Matches.label.ToLowerInvariant()) {
      "alpha" { "alpha"; break }
      "a" { "alpha"; break }
      "beta" { "beta"; break }
      "b" { "beta"; break }
      default { "rc"; break }
    }
    return ("{0}.{1}.{2}-{3}.{4}" -f $Matches.major, $Matches.minor, $Matches.patch, $label, $Matches.number)
  }

  return $value
}

function Assert-ReleaseVersion {
  param(
    [string]$Version,
    [string]$Label
  )

  $semVerPattern = '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$'
  $pep440PrePattern = '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:a|b|rc)(?:0|[1-9]\d*)$'
  if ($Version -notmatch $semVerPattern -and $Version -notmatch $pep440PrePattern) {
    throw ("{0} is not a valid semantic version: {1}" -f $Label, $Version)
  }
}

try {
  $resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
}
catch {
  throw "Version check root does not exist: $Root"
}

. (Join-Path $PSScriptRoot "project_registry.ps1")
$registry = Get-ReflexProjectRegistry -RepositoryRoot $resolvedRoot

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  throw "Git is required for the version consistency check."
}

$gitOutput = @(& git -C $resolvedRoot tag --points-at HEAD 2>&1)
if ($LASTEXITCODE -ne 0) {
  throw ("Unable to read Git tags at HEAD: {0}" -f (($gitOutput | ForEach-Object { $_.ToString() }) -join " "))
}

$releaseTagPattern = '^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$'
$releaseTags = @($gitOutput | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ -match $releaseTagPattern })
if ($IgnoreTag) {
  $releaseTags = @()
}
if ($releaseTags.Count -gt 1) {
  throw ("HEAD has multiple release tags: {0}" -f ($releaseTags -join ", "))
}
if ($RequireTag -and $releaseTags.Count -eq 0) {
  throw "HEAD does not have a v<SemVer> release tag."
}

$sources = @(
  [PSCustomObject]@{ Label = "Release version file"; Path = "VERSION"; Kind = "text"; Version = $null },
  [PSCustomObject]@{ Label = "Tauri"; Path = "apps\tauri-host\src-tauri\tauri.conf.json"; Kind = "json"; Version = $null },
  [PSCustomObject]@{ Label = "Cargo"; Path = "apps\tauri-host\src-tauri\Cargo.toml"; Kind = "toml"; Section = "package"; Version = $null },
  [PSCustomObject]@{ Label = "npm"; Path = "apps\tauri-host\package.json"; Kind = "json"; Version = $null },
  [PSCustomObject]@{ Label = "npm lockfile"; Path = "apps\tauri-host\package-lock.json"; Kind = "npm-lock"; Version = $null },
  [PSCustomObject]@{ Label = "Cargo lockfile"; Path = "apps\tauri-host\src-tauri\Cargo.lock"; Kind = "lock"; Package = "reflex-next-tauri-host"; Version = $null }
)

$productProjects = @($registry.projects | Where-Object {
    $_.kind -eq "python" -and $_.version_policy -eq "product"
  })
if ($productProjects.Count -eq 0) {
  throw "Project registry has no product Python projects."
}
foreach ($project in $productProjects) {
  $projectPath = ([string]$project.path -replace "/", "\")
  $manifestPath = $projectPath + "\pyproject.toml"
  $sources += [PSCustomObject]@{
    Label = "Python $([string]$project.id)"
    Path = $manifestPath
    Kind = "toml"
    Section = "project"
    Version = $null
  }
  $lockPackages = @($project.version_lock_packages)
  if ($lockPackages.Count -eq 0) {
    throw ("Product project has no version lock packages: {0}" -f $project.id)
  }
  foreach ($packageName in $lockPackages) {
    $sources += [PSCustomObject]@{
      Label = "Python $([string]$project.id) lock: $([string]$packageName)"
      Path = ([string]$project.lock -replace "/", "\")
      Kind = "lock"
      Package = [string]$packageName
      Version = $null
    }
  }
}

foreach ($source in $sources) {
  $fullPath = Join-Path $resolvedRoot $source.Path
  if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
    throw ("{0} version manifest is missing: {1}" -f $source.Label, $source.Path)
  }

  switch ($source.Kind) {
    "text" {
      $source.Version = Get-TextVersion -Path $fullPath -Label $source.Label
    }
    "json" {
      $source.Version = Get-JsonVersion -Path $fullPath -Label $source.Label
    }
    "toml" {
      $source.Version = Get-TomlSectionVersion -Path $fullPath -Section $source.Section -Label $source.Label
    }
    "npm-lock" {
      $source.Version = Get-NpmLockVersion -Path $fullPath -Label $source.Label
    }
    "lock" {
      $source.Version = Get-LockPackageVersion -Path $fullPath -Package $source.Package -Label $source.Label
    }
    default {
      throw ("Unsupported version source kind: {0}" -f $source.Kind)
    }
  }
}

$pluginVersionSources = @($registry.projects | Where-Object {
    $_.kind -eq "python" -and $_.version_policy -eq "plugin"
  })
foreach ($project in $pluginVersionSources) {
  $manifestPath = ([string]$project.path -replace "/", "\") + "\pyproject.toml"
  $lockPath = ([string]$project.lock -replace "/", "\")
  $manifestFullPath = Join-Path $resolvedRoot $manifestPath
  $lockFullPath = Join-Path $resolvedRoot $lockPath
  $manifestVersion = Get-TomlSectionVersion `
    -Path $manifestFullPath `
    -Section "project" `
    -Label ("Plugin " + [string]$project.id)
  $lockVersion = Get-LockPackageVersion `
    -Path $lockFullPath `
    -Package ([string]$project.package_name) `
    -Label ("Plugin lock " + [string]$project.id)
  Assert-ReleaseVersion -Version $manifestVersion -Label ("Plugin " + [string]$project.id)
  Assert-ReleaseVersion -Version $lockVersion -Label ("Plugin lock " + [string]$project.id)
  if ((Normalize-ReleaseVersion $manifestVersion) -cne (Normalize-ReleaseVersion $lockVersion)) {
    throw ("Plugin version and lock differ: {0} manifest={1}; lock={2}" -f $project.id, $manifestVersion, $lockVersion)
  }
  Write-Output ("[PLUGIN-VERSION] {0} | version={1} | source={2}" -f $project.id, $manifestVersion, $manifestPath)
}

foreach ($source in $sources) {
  Assert-ReleaseVersion -Version $source.Version -Label $source.Label
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
  Assert-ReleaseVersion -Version $gitSource.Version -Label $gitSource.Label
  Write-Output ("[VERSION] {0} | version={1} | source={2}" -f $gitSource.Label, $gitSource.Version, $gitSource.Path)
  $comparisonSources += $gitSource
}

$mismatches = @($comparisonSources | Where-Object {
    (Normalize-ReleaseVersion $_.Version) -cne (Normalize-ReleaseVersion $baselineVersion)
  })
if ($mismatches.Count -gt 0) {
  $details = @($comparisonSources | ForEach-Object {
      "{0}={1} ({2})" -f $_.Label, $_.Version, $_.Path
    }) -join "; "
  throw ("Product release versions are inconsistent (baseline {0}={1}): {2}" -f $sources[0].Label, $baselineVersion, $details)
}

Write-Output "Version consistency check passed: $baselineVersion"
