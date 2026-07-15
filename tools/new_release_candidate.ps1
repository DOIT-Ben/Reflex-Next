[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$InstallerPath,
  [Parameter(Mandatory = $true)]
  [string]$HostPath,
  [Parameter(Mandatory = $true)]
  [string]$RuntimePath,
  [Parameter(Mandatory = $true)]
  [string]$SbomDirectory,
  [Parameter(Mandatory = $true)]
  [string]$ReleaseNotesPath,
  [Parameter(Mandatory = $true)]
  [string]$RecoveryGuidePath,
  [Parameter(Mandatory = $true)]
  [string]$OutputDirectory,
  [string]$RepositoryRoot = "",
  [switch]$RequireSigned,
  [switch]$RequireTag,
  [switch]$RequireClean
)

$ErrorActionPreference = "Stop"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Resolve-RequiredFile {
  param([string]$Path, [string]$Code)

  try {
    $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
  }
  catch {
    throw $Code
  }
  if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
    throw $Code
  }
  return $resolved
}

function Resolve-RequiredDirectory {
  param([string]$Path, [string]$Code)

  try {
    $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
  }
  catch {
    throw $Code
  }
  if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
    throw $Code
  }
  return $resolved
}

function Get-Sha256 {
  param([string]$Path)
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-SafeLeafName {
  param([string]$Value)
  return (
    -not [string]::IsNullOrWhiteSpace($Value) -and
    [System.IO.Path]::GetFileName($Value) -ceq $Value -and
    $Value -notmatch '[\x00-\x1f]'
  )
}

function Get-AuthenticodeState {
  param([string]$Path)

  try {
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    $status = [string]$signature.Status
  }
  catch {
    $status = "UnknownError"
  }
  return [PSCustomObject]@{
    Status = $status
    Valid = $status -ceq "Valid"
  }
}

function Invoke-SecretScan {
  param([string]$Repository, [string]$Path)

  $scanner = Join-Path $Repository "tools\scan_release_secrets.ps1"
  if (-not (Test-Path -LiteralPath $scanner -PathType Leaf)) {
    throw "missing_secret_scanner"
  }
  $output = @(& powershell -NoProfile -ExecutionPolicy Bypass -File $scanner `
      -RepositoryRoot $Repository -SkipTrackedFiles -ReleasePath $Path 2>&1)
  if ($LASTEXITCODE -ne 0) {
    throw "release_secret_scan_failed"
  }
}

function Read-SbomManifest {
  param([string]$Directory, [string]$Repository)

  $manifestPath = Join-Path $Directory "sbom-manifest.json"
  if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "missing_sbom_manifest"
  }
  try {
    $manifest = [System.IO.File]::ReadAllText(
      $manifestPath,
      [System.Text.Encoding]::UTF8
    ) | ConvertFrom-Json
  }
  catch {
    throw "invalid_sbom_manifest"
  }
  if (
    [int]$manifest.schema_version -ne 1 -or
    [string]$manifest.format -cne "CycloneDX" -or
    [string]$manifest.spec_version -cne "1.5" -or
    [string]$manifest.target -cne "x86_64-pc-windows-msvc" -or
    @($manifest.components).Count -ne 11
  ) {
    throw "invalid_sbom_manifest"
  }

  $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
  $seenIds = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
  foreach ($component in @($manifest.components)) {
    $componentId = [string]$component.id
    $fileName = [string]$component.sbom_file
    $sourceLock = [string]$component.source_lock
    if (
      [string]::IsNullOrWhiteSpace($componentId) -or
      -not $seenIds.Add($componentId) -or
      -not (Test-SafeLeafName -Value $fileName) -or
      -not $seen.Add($fileName) -or
      [string]::IsNullOrWhiteSpace($sourceLock) -or
      $sourceLock.Contains("\") -or
      $sourceLock.Contains(":") -or
      $sourceLock.StartsWith("/", [System.StringComparison]::Ordinal) -or
      @($sourceLock.Split('/') | Where-Object { $_ -in @("", ".", "..") }).Count -ne 0
    ) {
      throw "invalid_sbom_manifest"
    }
    $lockPath = [System.IO.Path]::GetFullPath(
      (Join-Path $Repository $sourceLock.Replace('/', '\'))
    )
    if (
      -not $lockPath.StartsWith($Repository + "\", [System.StringComparison]::OrdinalIgnoreCase) -or
      -not (Test-Path -LiteralPath $lockPath -PathType Leaf) -or
      [string]$component.source_lock_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
      (Get-Sha256 -Path $lockPath) -cne [string]$component.source_lock_sha256
    ) {
      throw "stale_sbom_source_lock"
    }
    $componentPath = Join-Path $Directory $fileName
    if (-not (Test-Path -LiteralPath $componentPath -PathType Leaf)) {
      throw "missing_sbom_component"
    }
    if (
      [string]$component.sbom_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
      (Get-Sha256 -Path $componentPath) -cne [string]$component.sbom_sha256
    ) {
      throw "invalid_sbom_component_hash"
    }
    try {
      $bom = [System.IO.File]::ReadAllText(
        $componentPath,
        [System.Text.Encoding]::UTF8
      ) | ConvertFrom-Json
    }
    catch {
      throw "invalid_sbom_component"
    }
    if (
      [string]$bom.bomFormat -cne "CycloneDX" -or
      [string]$bom.specVersion -cne "1.5" -or
      [int]$bom.version -lt 1 -or
      [string]::IsNullOrWhiteSpace([string]$bom.metadata.component.name)
    ) {
      throw "invalid_sbom_component"
    }
  }

  $files = @(Get-ChildItem -LiteralPath $Directory -File -Force)
  $directories = @(Get-ChildItem -LiteralPath $Directory -Directory -Force)
  if ($files.Count -ne 12 -or $directories.Count -ne 0) {
    throw "unexpected_sbom_material"
  }
  return [PSCustomObject]@{
    Manifest = $manifest
    Path = $manifestPath
  }
}

function Read-ReleaseDocument {
  param([string]$Path, [string]$Code)

  $file = Get-Item -LiteralPath $Path
  if ($file.Length -le 0 -or $file.Length -gt 1MB) {
    throw $Code
  }
  try {
    $text = [System.IO.File]::ReadAllText($Path, (New-Object System.Text.UTF8Encoding($false, $true)))
  }
  catch {
    throw $Code
  }
  if ($text -match '(?i)\b(?:TODO|TBD|debug|test-only)\b') {
    throw $Code
  }
}

$staging = $null
try {
  if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = Join-Path $PSScriptRoot ".."
  }
  $repository = Resolve-RequiredDirectory -Path $RepositoryRoot -Code "invalid_repository_root"
  $installer = Resolve-RequiredFile -Path $InstallerPath -Code "installer_missing"
  $hostExecutable = Resolve-RequiredFile -Path $HostPath -Code "host_missing"
  $runtimeExecutable = Resolve-RequiredFile -Path $RuntimePath -Code "runtime_missing"
  $sbom = Resolve-RequiredDirectory -Path $SbomDirectory -Code "sbom_directory_missing"
  $releaseNotes = Resolve-RequiredFile -Path $ReleaseNotesPath -Code "release_notes_missing"
  $recoveryGuide = Resolve-RequiredFile -Path $RecoveryGuidePath -Code "recovery_guide_missing"

  $inputPaths = @($installer, $hostExecutable, $runtimeExecutable)
  if (@($inputPaths | Sort-Object -Unique).Count -ne 3) {
    throw "artifact_paths_not_unique"
  }

  $versionPath = Join-Path $repository "VERSION"
  if (-not (Test-Path -LiteralPath $versionPath -PathType Leaf)) {
    throw "version_file_missing"
  }
  $version = [System.IO.File]::ReadAllText($versionPath, [System.Text.Encoding]::UTF8).Trim()
  if ($version -cnotmatch '^\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?$') {
    throw "invalid_release_version"
  }
  if (
    [System.IO.Path]::GetFileName($installer) -cne "Reflex_${version}_x64-setup.exe" -or
    [System.IO.Path]::GetFileName($hostExecutable) -cne "Reflex.exe" -or
    [System.IO.Path]::GetFileName($runtimeExecutable) -cne "reflex-runtime.exe"
  ) {
    throw "artifact_name_mismatch"
  }
  foreach ($path in $inputPaths) {
    $length = (Get-Item -LiteralPath $path).Length
    if ($length -le 0 -or $length -gt 1GB) {
      throw "invalid_artifact_size"
    }
  }

  Read-ReleaseDocument -Path $releaseNotes -Code "invalid_release_notes"
  Read-ReleaseDocument -Path $recoveryGuide -Code "invalid_recovery_guide"
  $sbomState = Read-SbomManifest -Directory $sbom -Repository $repository

  $versionChecker = Join-Path $repository "tools\check_version_consistency.ps1"
  if (-not (Test-Path -LiteralPath $versionChecker -PathType Leaf)) {
    throw "missing_version_checker"
  }
  & $versionChecker -Root $repository -IgnoreTag | Out-Null

  $commitOutput = @(& git -C $repository rev-parse HEAD 2>$null)
  $commitExitCode = $LASTEXITCODE
  $commit = if ($commitOutput.Count -gt 0) { $commitOutput[0].Trim() } else { "" }
  if ($commitExitCode -ne 0 -or $commit -cnotmatch '^[a-f0-9]{40}$') {
    throw "git_commit_unavailable"
  }
  $trackedStatus = @(& git -C $repository status --porcelain --untracked-files=no 2>$null)
  if ($LASTEXITCODE -ne 0) {
    throw "git_status_unavailable"
  }
  $trackedClean = $trackedStatus.Count -eq 0
  $matchingTags = @(& git -C $repository tag --points-at HEAD --list "v$version" 2>$null)
  if ($LASTEXITCODE -ne 0) {
    throw "git_tag_unavailable"
  }
  $tagMatches = @($matchingTags | Where-Object { $_ -ceq "v$version" }).Count -eq 1

  $artifactDefinitions = @(
    [PSCustomObject]@{ Id = "installer"; Source = $installer; FileName = [System.IO.Path]::GetFileName($installer) },
    [PSCustomObject]@{ Id = "host"; Source = $hostExecutable; FileName = "Reflex.exe" },
    [PSCustomObject]@{ Id = "runtime"; Source = $runtimeExecutable; FileName = "reflex-runtime.exe" }
  )
  $signatureStates = @{}
  foreach ($artifact in $artifactDefinitions) {
    $signatureStates[$artifact.Id] = Get-AuthenticodeState -Path $artifact.Source
  }
  $signaturesValid = @($signatureStates.Values | Where-Object { -not $_.Valid }).Count -eq 0

  if ($RequireSigned -and -not $signaturesValid) {
    throw "release_signature_required"
  }
  if ($RequireTag -and -not $tagMatches) {
    throw "release_tag_required"
  }
  if ($RequireClean -and -not $trackedClean) {
    throw "clean_worktree_required"
  }

  $output = [System.IO.Path]::GetFullPath($OutputDirectory).TrimEnd('\')
  if (Test-Path -LiteralPath $output) {
    throw "output_directory_exists"
  }
  $outputParent = Split-Path -Parent $output
  $outputLeaf = Split-Path -Leaf $output
  if ([string]::IsNullOrWhiteSpace($outputParent) -or [string]::IsNullOrWhiteSpace($outputLeaf)) {
    throw "invalid_output_directory"
  }
  New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
  $staging = Join-Path $outputParent (".$outputLeaf.staging-" + [guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Path $staging -Force | Out-Null
  $artifactDirectory = Join-Path $staging "artifacts"
  $sbomOutput = Join-Path $staging "sbom"
  New-Item -ItemType Directory -Path $artifactDirectory, $sbomOutput -Force | Out-Null

  $manifestArtifacts = @()
  foreach ($artifact in $artifactDefinitions) {
    $destination = Join-Path $artifactDirectory $artifact.FileName
    Copy-Item -LiteralPath $artifact.Source -Destination $destination
    $state = $signatureStates[$artifact.Id]
    $manifestArtifacts += [ordered]@{
      id = $artifact.Id
      path = "artifacts/$($artifact.FileName)"
      size_bytes = (Get-Item -LiteralPath $destination).Length
      sha256 = Get-Sha256 -Path $destination
      authenticode_status = $state.Status
      signature_valid = [bool]$state.Valid
    }
  }
  Get-ChildItem -LiteralPath $sbom -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $sbomOutput
  }
  Copy-Item -LiteralPath $releaseNotes -Destination (Join-Path $staging "RELEASE_NOTES.md")
  Copy-Item -LiteralPath $recoveryGuide -Destination (Join-Path $staging "RECOVERY.md")

  $checksumEntries = @()
  foreach ($file in @(Get-ChildItem -LiteralPath $staging -File -Recurse | Sort-Object FullName)) {
    $relative = $file.FullName.Substring($staging.Length + 1).Replace('\', '/')
    $checksumEntries += ("{0} *{1}" -f (Get-Sha256 -Path $file.FullName), $relative)
  }
  $checksumsPath = Join-Path $staging "SHA256SUMS.txt"
  [System.IO.File]::WriteAllText(
    $checksumsPath,
    (($checksumEntries -join "`n") + "`n"),
    $utf8NoBom
  )

  $channel = "stable"
  if ($version -match '-(alpha|beta|rc)\.') {
    $channel = $Matches[1]
  }
  $releaseReady = $signaturesValid -and $tagMatches -and $trackedClean
  $manifest = [ordered]@{
    schema_version = 1
    product = "Reflex"
    version = $version
    channel = $channel
    target = "windows-x86_64"
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    git = [ordered]@{
      commit = $commit
      exact_tag = if ($tagMatches) { "v$version" } else { $null }
      tracked_worktree_clean = $trackedClean
    }
    gates = [ordered]@{
      version_consistent = $true
      tag_matches = $tagMatches
      artifacts_scanned = $true
      sbom_verified = $true
      signatures_valid = $signaturesValid
      release_ready = $releaseReady
    }
    artifacts = $manifestArtifacts
    sbom = [ordered]@{
      manifest_path = "sbom/sbom-manifest.json"
      manifest_sha256 = Get-Sha256 -Path (Join-Path $sbomOutput "sbom-manifest.json")
      component_count = @($sbomState.Manifest.components).Count
    }
    documents = [ordered]@{
      release_notes = "RELEASE_NOTES.md"
      recovery_guide = "RECOVERY.md"
    }
    checksums = [ordered]@{
      path = "SHA256SUMS.txt"
      sha256 = Get-Sha256 -Path $checksumsPath
      file_count = $checksumEntries.Count
    }
  }
  [System.IO.File]::WriteAllText(
    (Join-Path $staging "release-manifest.json"),
    (($manifest | ConvertTo-Json -Depth 10) + "`n"),
    $utf8NoBom
  )

  Invoke-SecretScan -Repository $repository -Path $staging
  [System.IO.Directory]::Move($staging, $output)
  $staging = $null
  Write-Output (
    "Release candidate material passed: version={0}; artifacts=3; sbom=11; release_ready={1}" -f
    $version, $releaseReady.ToString().ToLowerInvariant()
  )
}
catch {
  Write-Error $_.Exception.Message
  exit 1
}
finally {
  if ($null -ne $staging -and (Test-Path -LiteralPath $staging)) {
    Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
  }
}
