[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$PackageDirectory,
  [string]$RepositoryRoot = "",
  [switch]$RequireReady
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project_registry.ps1")

$powerShellCommand = Get-Command pwsh.exe -ErrorAction SilentlyContinue
if ($null -eq $powerShellCommand) {
  $powerShellCommand = Get-Command powershell.exe -ErrorAction Stop
}
$powerShellExecutable = $powerShellCommand.Source

function Get-Sha256 {
  param([string]$Path)
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-SafeRelativePath {
  param([string]$Value)

  if (
    [string]::IsNullOrWhiteSpace($Value) -or
    $Value.StartsWith("/", [System.StringComparison]::Ordinal) -or
    $Value.Contains("\") -or
    $Value.Contains(":") -or
    $Value -match '[\x00-\x1f]'
  ) {
    return $false
  }
  foreach ($segment in $Value.Split('/')) {
    if ([string]::IsNullOrWhiteSpace($segment) -or $segment -in @(".", "..")) {
      return $false
    }
  }
  return $true
}

function Resolve-PackagePath {
  param([string]$Root, [string]$Relative, [string]$Code)

  if (-not (Test-SafeRelativePath -Value $Relative)) {
    throw $Code
  }
  $candidate = [System.IO.Path]::GetFullPath((Join-Path $Root $Relative.Replace('/', '\')))
  if (-not $candidate.StartsWith($Root + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw $Code
  }
  if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
    throw $Code
  }
  return $candidate
}

function Get-AuthenticodeStatus {
  param([string]$Path)
  try {
    return [string](Get-AuthenticodeSignature -LiteralPath $Path).Status
  }
  catch {
    return "UnknownError"
  }
}

function Invoke-SecretScan {
  param([string]$Repository, [string]$Path)

  $scanner = Join-Path $Repository "tools\scan_release_secrets.ps1"
  if (-not (Test-Path -LiteralPath $scanner -PathType Leaf)) {
    throw "missing_secret_scanner"
  }
  $output = @(& $powerShellExecutable -NoProfile -ExecutionPolicy Bypass -File $scanner `
      -RepositoryRoot $Repository -SkipTrackedFiles -ReleasePath $Path 2>&1)
  if ($LASTEXITCODE -ne 0) {
    throw "release_secret_scan_failed"
  }
}

try {
  if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = Join-Path $PSScriptRoot ".."
  }
  $repository = (Resolve-Path -LiteralPath $RepositoryRoot -ErrorAction Stop).Path
  $packageInput = Get-Item -LiteralPath $PackageDirectory -Force -ErrorAction Stop
  if ($packageInput.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
    throw "package_reparse_point_forbidden"
  }
  $package = (Resolve-Path -LiteralPath $PackageDirectory -ErrorAction Stop).Path.TrimEnd('\')
  $registry = Get-ReflexProjectRegistry -RepositoryRoot $repository
  $expectedSbomComponents = @(Get-ReflexSbomComponentCatalog -Registry $registry | ForEach-Object {
      [PSCustomObject]@{
        Id = [string]$_.Id
        RootComponent = [string]$_.Name
        SourceLock = ([string]$_.Lock -replace "\\", "/")
      }
    })
  $expectedSbomById = @{}
  foreach ($expected in $expectedSbomComponents) {
    if ($expectedSbomById.ContainsKey([string]$expected.Id)) {
      throw "project_registry_duplicate_sbom_id"
    }
    $expectedSbomById[[string]$expected.Id] = $expected
  }
  if (-not (Test-Path -LiteralPath $package -PathType Container)) {
    throw "invalid_package_directory"
  }
  $reparseFiles = @(Get-ChildItem -LiteralPath $package -Recurse -Force | Where-Object {
      $_.Attributes -band [System.IO.FileAttributes]::ReparsePoint
    })
  if ($reparseFiles.Count -ne 0) {
    throw "package_reparse_point_forbidden"
  }

  $manifestPath = Join-Path $package "release-manifest.json"
  if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "release_manifest_missing"
  }
  try {
    $manifest = [System.IO.File]::ReadAllText(
      $manifestPath,
      [System.Text.Encoding]::UTF8
    ) | ConvertFrom-Json
  }
  catch {
    throw "invalid_release_manifest"
  }

  $versionPath = Join-Path $repository "VERSION"
  $versionChecker = Join-Path $repository "tools\check_version_consistency.ps1"
  if (
    -not (Test-Path -LiteralPath $versionPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $versionChecker -PathType Leaf)
  ) {
    throw "release_source_unavailable"
  }
  $sourceVersion = [System.IO.File]::ReadAllText(
    $versionPath,
    [System.Text.Encoding]::UTF8
  ).Trim()
  if ($sourceVersion -cne [string]$manifest.version) {
    throw "release_version_mismatch"
  }
  & $versionChecker -Root $repository -IgnoreTag | Out-Null

  $commitOutput = @(& git -C $repository rev-parse HEAD 2>$null)
  $commitExitCode = $LASTEXITCODE
  $sourceCommit = if ($commitOutput.Count -gt 0) { $commitOutput[0].Trim() } else { "" }
  if (
    $commitExitCode -ne 0 -or
    $sourceCommit -cnotmatch '^[a-f0-9]{40}$' -or
    $sourceCommit -cne [string]$manifest.git.commit
  ) {
    throw "release_source_commit_mismatch"
  }
  $trackedStatus = @(& git -C $repository status --porcelain --untracked-files=all 2>$null)
  if ($LASTEXITCODE -ne 0) {
    throw "release_source_status_unavailable"
  }
  $sourceTrackedClean = $trackedStatus.Count -eq 0
  if ($sourceTrackedClean -ne [bool]$manifest.git.tracked_worktree_clean) {
    throw "release_source_cleanliness_mismatch"
  }
  $matchingTags = @(& git -C $repository tag --points-at HEAD --list "v$sourceVersion" 2>$null)
  if ($LASTEXITCODE -ne 0) {
    throw "release_source_tag_unavailable"
  }
  $sourceTagMatches = @($matchingTags | Where-Object {
      $_ -ceq "v$sourceVersion"
    }).Count -eq 1
  if (
    $sourceTagMatches -ne [bool]$manifest.gates.tag_matches -or
    ($sourceTagMatches -and [string]$manifest.git.exact_tag -cne "v$sourceVersion") -or
    (-not $sourceTagMatches -and $null -ne $manifest.git.exact_tag)
  ) {
    throw "release_source_tag_mismatch"
  }
  if (
    [int]$manifest.schema_version -ne 2 -or
    [string]$manifest.product -cne "Reflex" -or
    [string]$manifest.version -cnotmatch '^\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?$' -or
    [string]$manifest.channel -notin @("alpha", "beta", "rc", "stable") -or
    [string]$manifest.target -cne "windows-x86_64" -or
    @($manifest.artifacts).Count -ne 3
  ) {
    throw "invalid_release_manifest"
  }

  $checksumsRelative = [string]$manifest.checksums.path
  if ($checksumsRelative -cne "SHA256SUMS.txt") {
    throw "invalid_checksums_path"
  }
  $checksumsPath = Resolve-PackagePath -Root $package -Relative $checksumsRelative -Code "invalid_checksums_path"
  if (
    [string]$manifest.checksums.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
    (Get-Sha256 -Path $checksumsPath) -cne [string]$manifest.checksums.sha256
  ) {
    throw "checksums_file_mismatch"
  }

  $checksumMap = @{}
  foreach ($line in [System.IO.File]::ReadAllLines($checksumsPath, [System.Text.Encoding]::UTF8)) {
    if ($line -cnotmatch '^([a-f0-9]{64}) \*(.+)$') {
      throw "invalid_checksum_entry"
    }
    $relative = $Matches[2]
    if (-not (Test-SafeRelativePath -Value $relative) -or $checksumMap.ContainsKey($relative)) {
      throw "invalid_checksum_entry"
    }
    $checksumMap[$relative] = $Matches[1]
  }
  if ($checksumMap.Count -ne [int]$manifest.checksums.file_count) {
    throw "checksum_count_mismatch"
  }

  foreach ($entry in $checksumMap.GetEnumerator()) {
    $path = Resolve-PackagePath -Root $package -Relative $entry.Key -Code "checksummed_file_missing"
    if ((Get-Sha256 -Path $path) -cne $entry.Value) {
      throw "checksum_mismatch"
    }
  }

  $artifactIds = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
  foreach ($artifact in @($manifest.artifacts)) {
    $id = [string]$artifact.id
    $relative = [string]$artifact.path
    $expectedArtifactPath = @{
      installer = "artifacts/Reflex_${sourceVersion}_x64-setup.exe"
      host = "artifacts/Reflex.exe"
      runtime = "artifacts/reflex-runtime.exe"
    }[$id]
    if ($id -notin @("installer", "host", "runtime") -or -not $artifactIds.Add($id)) {
      throw "invalid_artifact_manifest"
    }
    if ($relative -cne $expectedArtifactPath) {
      throw "invalid_artifact_manifest"
    }
    $path = Resolve-PackagePath -Root $package -Relative $relative -Code "invalid_artifact_path"
    if (
      -not $checksumMap.ContainsKey($relative) -or
      [long]$artifact.size_bytes -ne (Get-Item -LiteralPath $path).Length -or
      [string]$artifact.sha256 -cne $checksumMap[$relative] -or
      [string]$artifact.authenticode_status -cne (Get-AuthenticodeStatus -Path $path) -or
      [bool]$artifact.signature_valid -ne ([string]$artifact.authenticode_status -ceq "Valid")
    ) {
      throw "artifact_manifest_mismatch"
    }
  }

  $documents = [ordered]@{
    release_notes = "RELEASE_NOTES.md"
    recovery_guide = "RECOVERY.md"
    privacy_notice = "PRIVACY.md"
    third_party_notices = "THIRD-PARTY-NOTICES.md"
    support_guide = "SUPPORT.md"
    troubleshooting_guide = "TROUBLESHOOTING.md"
  }
  if (
    @($manifest.documents.PSObject.Properties).Count -ne $documents.Count -or
    @($documents.Values | Sort-Object -Unique).Count -ne $documents.Count -or
    @($manifest.documents.PSObject.Properties | ForEach-Object { [string]$_.Value } | Sort-Object -Unique).Count -ne $documents.Count
  ) {
    throw "document_manifest_mismatch"
  }
  foreach ($key in @($documents.Keys)) {
    if ([string]$manifest.documents.($key) -cne [string]$documents[$key]) {
      throw "document_manifest_mismatch"
    }
  }
  foreach ($document in @($documents.Values)) {
    if ([string]::IsNullOrWhiteSpace($document) -or -not $checksumMap.ContainsKey($document)) {
      throw "document_manifest_mismatch"
    }
    Resolve-PackagePath -Root $package -Relative $document -Code "document_missing" | Out-Null
  }
  $sourceDocuments = [ordered]@{
    release_notes = Join-Path $repository ("docs\releases\v" + $sourceVersion + ".md")
    recovery_guide = Join-Path $repository "docs\RELEASE-RECOVERY.md"
    privacy_notice = Join-Path $repository "docs\PRIVACY.md"
    third_party_notices = Join-Path $repository "docs\THIRD-PARTY-NOTICES.md"
    support_guide = Join-Path $repository "docs\SUPPORT.md"
    troubleshooting_guide = Join-Path $repository "docs\TROUBLESHOOTING.md"
  }
  foreach ($key in @($sourceDocuments.Keys)) {
    $source = [string]$sourceDocuments[$key]
    $relative = [string]$documents[$key]
    if (
      -not (Test-Path -LiteralPath $source -PathType Leaf) -or
      (Get-Sha256 -Path $source) -cne $checksumMap[$relative]
    ) {
      throw "release_document_source_mismatch"
    }
  }

  $sbomRelative = [string]$manifest.sbom.manifest_path
  if ($sbomRelative -cne "sbom/sbom-manifest.json") {
    throw "sbom_manifest_mismatch"
  }
  $sbomManifestPath = Resolve-PackagePath -Root $package -Relative $sbomRelative -Code "sbom_manifest_missing"
  if (
    -not $checksumMap.ContainsKey($sbomRelative) -or
    [string]$manifest.sbom.manifest_sha256 -cne $checksumMap[$sbomRelative] -or
    [int]$manifest.sbom.component_count -ne $expectedSbomComponents.Count
  ) {
    throw "sbom_manifest_mismatch"
  }
  try {
    $sbomManifest = [System.IO.File]::ReadAllText(
      $sbomManifestPath,
      [System.Text.Encoding]::UTF8
    ) | ConvertFrom-Json
  }
  catch {
    throw "invalid_sbom_manifest"
  }
  if (@($sbomManifest.components).Count -ne $expectedSbomComponents.Count) {
    throw "invalid_sbom_manifest"
  }
  $seenSbomIds = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
  $seenSbomFiles = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
  foreach ($component in @($sbomManifest.components)) {
    $componentId = [string]$component.id
    $fileName = [string]$component.sbom_file
    $sourceLock = [string]$component.source_lock
    if (
      [System.IO.Path]::GetFileName($fileName) -cne $fileName -or
      [string]::IsNullOrWhiteSpace($sourceLock) -or
      $sourceLock.Contains("\") -or
      $sourceLock.Contains(":") -or
      $sourceLock.StartsWith("/", [System.StringComparison]::Ordinal) -or
      @($sourceLock.Split('/') | Where-Object { $_ -in @("", ".", "..") }).Count -ne 0
    ) {
      throw "invalid_sbom_component"
    }
    if (
      -not $expectedSbomById.ContainsKey($componentId) -or
      -not $seenSbomIds.Add($componentId) -or
      $fileName -cne "$componentId.cdx.json" -or
      -not $seenSbomFiles.Add($fileName)
    ) {
      throw "invalid_sbom_component"
    }
    $expected = $expectedSbomById[$componentId]
    if (
      [string]$component.root_component -cne [string]$expected.RootComponent -or
      ($sourceLock -replace "\\", "/") -cne [string]$expected.SourceLock
    ) {
      throw "invalid_sbom_component"
    }
    $sourceLockPath = [System.IO.Path]::GetFullPath(
      (Join-Path $repository $sourceLock.Replace('/', '\'))
    )
    if (
      -not $sourceLockPath.StartsWith($repository + "\", [System.StringComparison]::OrdinalIgnoreCase) -or
      -not (Test-Path -LiteralPath $sourceLockPath -PathType Leaf) -or
      [string]$component.source_lock_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
      (Get-Sha256 -Path $sourceLockPath) -cne [string]$component.source_lock_sha256
    ) {
      throw "stale_sbom_source_lock"
    }
    $relative = "sbom/$fileName"
    if (
      -not $checksumMap.ContainsKey($relative) -or
      [string]$component.sbom_sha256 -cne $checksumMap[$relative]
    ) {
      throw "invalid_sbom_component"
    }
    $componentPath = Resolve-PackagePath -Root $package -Relative $relative -Code "invalid_sbom_component"
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
      [string]$bom.metadata.component.name -cne [string]$expected.RootComponent
    ) {
      throw "invalid_sbom_component"
    }
  }
  if (
    $seenSbomIds.Count -ne $expectedSbomComponents.Count -or
    @($expectedSbomComponents | Where-Object {
        -not $seenSbomIds.Contains([string]$_.Id)
      }).Count -ne 0
  ) {
    throw "invalid_sbom_component"
  }

  $expectedFiles = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
  [void]$expectedFiles.Add("release-manifest.json")
  [void]$expectedFiles.Add($checksumsRelative)
  foreach ($relative in @(
      "artifacts/Reflex_${sourceVersion}_x64-setup.exe",
      "artifacts/Reflex.exe",
      "artifacts/reflex-runtime.exe"
    )) {
    [void]$expectedFiles.Add($relative)
  }
  foreach ($relative in $documents.Values) {
    [void]$expectedFiles.Add([string]$relative)
  }
  [void]$expectedFiles.Add("sbom/sbom-manifest.json")
  foreach ($expected in $expectedSbomComponents) {
    [void]$expectedFiles.Add("sbom/$([string]$expected.Id).cdx.json")
  }
  $actualFiles = @(
    Get-ChildItem -LiteralPath $package -File -Recurse -Force | ForEach-Object {
      $_.FullName.Substring($package.Length + 1).Replace('\', '/')
    }
  )
  if (
    $actualFiles.Count -ne $expectedFiles.Count -or
    @($actualFiles | Where-Object { -not $expectedFiles.Contains($_) }).Count -ne 0
  ) {
    throw "unexpected_package_file"
  }

  $computedSignatureGate = @($manifest.artifacts | Where-Object {
      -not [bool]$_.signature_valid
    }).Count -eq 0
  $computedReady = (
    [bool]$manifest.gates.version_consistent -and
    $sourceTagMatches -and
    [bool]$manifest.gates.artifacts_scanned -and
    [bool]$manifest.gates.sbom_verified -and
    $computedSignatureGate -and
    $sourceTrackedClean
  )
  if (
    [bool]$manifest.gates.signatures_valid -ne $computedSignatureGate -or
    [bool]$manifest.gates.release_ready -ne $computedReady
  ) {
    throw "release_gate_mismatch"
  }
  if ($RequireReady -and -not $computedReady) {
    throw "release_not_ready"
  }

  Invoke-SecretScan -Repository $repository -Path $package
  Write-Output (
    "Release candidate verification passed: version={0}; files={1}; release_ready={2}" -f
    [string]$manifest.version,
    $actualFiles.Count,
    $computedReady.ToString().ToLowerInvariant()
  )
}
catch {
  [Console]::Error.WriteLine([string]$_.Exception.Message)
  exit 1
}
