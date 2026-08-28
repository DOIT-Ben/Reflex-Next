$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$generator = Join-Path $root "tools\new_release_candidate.ps1"
$verifier = Join-Path $root "tools\verify_release_candidate.ps1"
. (Join-Path $root "tools\project_registry.ps1")
$powershellCommand = Get-Command pwsh.exe -ErrorAction SilentlyContinue
if ($null -eq $powershellCommand) {
  $powershellCommand = Get-Command powershell.exe -ErrorAction Stop
}
$powershell = $powershellCommand.Source
$probeRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
  "reflex-release-candidate-contract-" + [guid]::NewGuid().ToString("N")
)
$artifacts = Join-Path $probeRoot "artifacts"
$sbom = Join-Path $probeRoot "sbom"
$output = Join-Path $probeRoot "output"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$version = [System.IO.File]::ReadAllText(
  (Join-Path $root "VERSION"),
  [System.Text.Encoding]::UTF8
).Trim()

$registryPath = Join-Path $root "tools\project-registry.json"
$registry = Get-ReflexProjectRegistry -RepositoryRoot $root
$components = @(Get-ReflexSbomComponentCatalog -Registry $registry | ForEach-Object {
    [PSCustomObject]@{
      Id = [string]$_.Id
      Name = [string]$_.Name
      RootComponent = [string]$_.Name
      Lock = ([string]$_.Lock -replace "\\", "/")
    }
  })

function Assert-True {
  param([bool]$Condition, [string]$Message)
  if (-not $Condition) {
    throw $Message
  }
}

function Get-Sha256 {
  param([string]$Path)
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Update-ChecksumEntry {
  param(
    [string]$Directory,
    [string]$RelativePath
  )

  $checksumPath = Join-Path $Directory "SHA256SUMS.txt"
  $lines = [System.IO.File]::ReadAllLines($checksumPath, [System.Text.Encoding]::UTF8)
  $pattern = '^([a-f0-9]{64}) \*' + [regex]::Escape($RelativePath) + '$'
  $replacement = "{0} *{1}" -f (Get-Sha256 -Path (Join-Path $Directory $RelativePath.Replace('/', '\'))), $RelativePath
  $matched = $false
  $updated = @($lines | ForEach-Object {
      if ($_ -match $pattern) {
        $matched = $true
        $replacement
      }
      else {
        $_
      }
    })
  Assert-True $matched ("Checksum entry is missing: " + $RelativePath)
  [System.IO.File]::WriteAllText($checksumPath, (($updated -join "`n") + "`n"), $utf8NoBom)
}

function Invoke-Captured {
  param([string]$Script, [string[]]$Arguments)

  $stdoutPath = Join-Path $probeRoot ("stdout-" + [guid]::NewGuid().ToString("N") + ".txt")
  $stderrPath = Join-Path $probeRoot ("stderr-" + [guid]::NewGuid().ToString("N") + ".txt")
  try {
    $processArguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Script) + $Arguments
    $quotedArguments = @($processArguments | ForEach-Object {
        $value = [string]$_
        if ($value.Contains('"')) {
          throw "invalid_contract_process_argument"
        }
        if ($value -match '\s') { '"' + $value + '"' } else { $value }
      })
    $process = Start-Process `
      -FilePath $powershell `
      -ArgumentList ($quotedArguments -join ' ') `
      -RedirectStandardOutput $stdoutPath `
      -RedirectStandardError $stderrPath `
      -WindowStyle Hidden `
      -Wait `
      -PassThru
    return [PSCustomObject]@{
      ExitCode = $process.ExitCode
      Stdout = if (Test-Path -LiteralPath $stdoutPath) {
        [System.IO.File]::ReadAllText($stdoutPath, [System.Text.Encoding]::UTF8)
      } else { "" }
      Stderr = if (Test-Path -LiteralPath $stderrPath) {
        [System.IO.File]::ReadAllText($stderrPath, [System.Text.Encoding]::UTF8)
      } else { "" }
    }
  }
  finally {
    Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
  }
}

function New-Candidate {
  param([string]$Destination, [string[]]$ExtraArguments = @())

  $arguments = @(
    "-RepositoryRoot", $root,
    "-InstallerPath", (Join-Path $artifacts "Reflex_${version}_x64-setup.exe"),
    "-HostPath", (Join-Path $artifacts "Reflex.exe"),
    "-RuntimePath", (Join-Path $artifacts "reflex-runtime.exe"),
    "-SbomDirectory", $sbom,
    "-ReleaseNotesPath", (Join-Path $root "docs\releases\v0.7.0-alpha.8.md"),
    "-RecoveryGuidePath", (Join-Path $root "docs\RELEASE-RECOVERY.md"),
    "-PrivacyNoticePath", (Join-Path $root "docs\PRIVACY.md"),
    "-ThirdPartyNoticesPath", (Join-Path $root "docs\THIRD-PARTY-NOTICES.md"),
    "-SupportGuidePath", (Join-Path $root "docs\SUPPORT.md"),
    "-TroubleshootingGuidePath", (Join-Path $root "docs\TROUBLESHOOTING.md"),
    "-OutputDirectory", $Destination
  )
  $arguments += $ExtraArguments
  return Invoke-Captured -Script $generator -Arguments $arguments
}

function Verify-Candidate {
  param([string]$Directory, [string[]]$ExtraArguments = @())

  $arguments = @(
    "-RepositoryRoot", $root,
    "-PackageDirectory", $Directory
  )
  $arguments += $ExtraArguments
  return Invoke-Captured -Script $verifier -Arguments $arguments
}

try {
  Assert-True (Test-Path -LiteralPath $generator -PathType Leaf) "Release candidate generator is missing."
  Assert-True (Test-Path -LiteralPath $verifier -PathType Leaf) "Release candidate verifier is missing."
  $generatorSource = [System.IO.File]::ReadAllText($generator, [System.Text.Encoding]::UTF8)
  $verifierSource = [System.IO.File]::ReadAllText($verifier, [System.Text.Encoding]::UTF8)
  Assert-True ($generatorSource -match 'status --porcelain --untracked-files=all') "Candidate generation must include untracked worktree files in cleanliness checks."
  Assert-True ($verifierSource -match 'status --porcelain --untracked-files=all') "Candidate verification must include untracked worktree files in cleanliness checks."
  Assert-True ($verifierSource -match 'packageInput\.Attributes.*ReparsePoint') "Candidate verification must reject a reparse-point package root before resolving it."
  Assert-True ($verifierSource -match 'Get-ReflexSbomComponentCatalog') "Candidate verification must use the shared SBOM component catalog."
  New-Item -ItemType Directory -Path $artifacts, $sbom -Force | Out-Null

  [System.IO.File]::WriteAllText(
    (Join-Path $artifacts "Reflex_${version}_x64-setup.exe"),
    "safe installer fixture",
    $utf8NoBom
  )
  [System.IO.File]::WriteAllText(
    (Join-Path $artifacts "Reflex.exe"),
    "safe host fixture",
    $utf8NoBom
  )
  [System.IO.File]::WriteAllText(
    (Join-Path $artifacts "reflex-runtime.exe"),
    "safe runtime fixture",
    $utf8NoBom
  )

  $manifestComponents = @()
  foreach ($component in $components) {
    $bom = [ordered]@{
      bomFormat = "CycloneDX"
      specVersion = "1.5"
      version = 1
      metadata = [ordered]@{
        component = [ordered]@{
          type = "application"
          'bom-ref' = "$($component.Id)@$version"
          name = $component.Name
          version = $version
        }
      }
      components = @()
      dependencies = @()
    }
    $fileName = "$($component.Id).cdx.json"
    $bomPath = Join-Path $sbom $fileName
    [System.IO.File]::WriteAllText(
      $bomPath,
      (($bom | ConvertTo-Json -Depth 8) + "`n"),
      $utf8NoBom
    )
    $lockPath = Join-Path $root $component.Lock.Replace('/', '\')
    $manifestComponents += [ordered]@{
      id = $component.Id
      ecosystem = ($component.Id -split '-')[0]
      root_component = if ($component.RootComponent) { $component.RootComponent } else { $component.Name }
      source_lock = $component.Lock
      source_lock_sha256 = Get-Sha256 -Path $lockPath
      sbom_file = $fileName
      sbom_sha256 = Get-Sha256 -Path $bomPath
      dependency_components = 0
    }
  }
  $sbomManifest = [ordered]@{
    schema_version = 1
    format = "CycloneDX"
    spec_version = "1.5"
    target = "x86_64-pc-windows-msvc"
    components = $manifestComponents
  }
  [System.IO.File]::WriteAllText(
    (Join-Path $sbom "sbom-manifest.json"),
    (($sbomManifest | ConvertTo-Json -Depth 8) + "`n"),
    $utf8NoBom
  )

  $created = New-Candidate -Destination $output
  Assert-True (
    $created.ExitCode -eq 0
  ) ("A valid unsigned review candidate must be generated: " + $created.Stderr + "; stdout: " + $created.Stdout)
  Assert-True ($created.Stdout -match ("artifacts=3; sbom=$($components.Count); release_ready=false")) "Generator output must report bounded material and readiness."
  $manifestPath = Join-Path $output "release-manifest.json"
  Assert-True (Test-Path -LiteralPath $manifestPath -PathType Leaf) "Release manifest must be emitted."
  $manifest = [System.IO.File]::ReadAllText($manifestPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
  Assert-True ([int]$manifest.schema_version -eq 2) "Release manifest must use schema version 2."
  Assert-True ([string]$manifest.version -ceq $version) "Manifest version must match VERSION."
  Assert-True (@($manifest.artifacts).Count -eq 3) "Manifest must contain exactly three executable artifacts."
  Assert-True ([int]$manifest.sbom.component_count -eq $components.Count) "Manifest must contain every registered component BOM."
  $expectedDocuments = [ordered]@{
    release_notes = "RELEASE_NOTES.md"
    recovery_guide = "RECOVERY.md"
    privacy_notice = "PRIVACY.md"
    third_party_notices = "THIRD-PARTY-NOTICES.md"
    support_guide = "SUPPORT.md"
    troubleshooting_guide = "TROUBLESHOOTING.md"
  }
  Assert-True (@($manifest.documents.PSObject.Properties).Count -eq $expectedDocuments.Count) "Manifest must contain exactly the public release documents."
  foreach ($entry in $expectedDocuments.GetEnumerator()) {
    Assert-True ([string]$manifest.documents.($entry.Key) -ceq $entry.Value) ("Release document mapping drifted: " + $entry.Key)
    Assert-True (Test-Path -LiteralPath (Join-Path $output $entry.Value) -PathType Leaf) ("Release document is missing: " + $entry.Value)
  }
  Assert-True ([int]$manifest.checksums.file_count -eq ($components.Count + 10)) "Manifest must checksum every artifact, SBOM and public document."
  Assert-True (-not [bool]$manifest.gates.signatures_valid) "Unsigned fixture artifacts must not be marked signed."
  Assert-True (-not [bool]$manifest.gates.release_ready) "Unsigned review material must not be release-ready."
  Assert-True ((Get-Content -Raw -Encoding UTF8 $manifestPath) -notmatch [regex]::Escape($root)) "Manifest must not leak absolute workspace paths."
  Assert-True (@(Get-ChildItem -LiteralPath $output -File -Recurse).Count -eq ($components.Count + 12)) "Candidate must have an exact bounded file set."

  $verified = Verify-Candidate -Directory $output
  Assert-True ($verified.ExitCode -eq 0) "Untampered review material must verify."
  Assert-True ($verified.Stdout -match ("files=$($components.Count + 12); release_ready=false")) "Verifier must report bounded files and readiness."

  $rootReparse = Join-Path $probeRoot "root-reparse"
  try {
    New-Item -ItemType Junction -Path $rootReparse -Target $output -Force | Out-Null
    $rootReparseResult = Verify-Candidate -Directory $rootReparse
    Assert-True ($rootReparseResult.ExitCode -ne 0) "A reparse-point package root must fail verification."
    Assert-True ($rootReparseResult.Stderr.Trim() -ceq 'package_reparse_point_forbidden') "Package-root reparse rejection must use one stable stderr category."
  }
  finally {
    if (Test-Path -LiteralPath $rootReparse -PathType Any) {
      $rootReparseItem = Get-Item -LiteralPath $rootReparse -Force
      if (($rootReparseItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) {
        throw "root_reparse_cleanup_target_not_reparse_point"
      }
      # Remove only the junction itself.  PowerShell Remove-Item can throw a
      # NullReferenceException on directory junctions on some Windows builds.
      [System.IO.Directory]::Delete($rootReparse, $false)
    }
  }

  $mappingTampered = Join-Path $probeRoot "mapping-tampered"
  Copy-Item -LiteralPath $output -Destination $mappingTampered -Recurse
  $mappingSbomPath = Join-Path $mappingTampered "sbom\sbom-manifest.json"
  $mappingSbom = [System.IO.File]::ReadAllText($mappingSbomPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
  $firstComponent = @($mappingSbom.components)[0]
  $secondComponent = @($mappingSbom.components)[1]
  $firstComponent.source_lock = $secondComponent.source_lock
  $firstComponent.source_lock_sha256 = Get-Sha256 -Path (Join-Path $root $secondComponent.source_lock.Replace('/', '\'))
  [System.IO.File]::WriteAllText(
    $mappingSbomPath,
    (($mappingSbom | ConvertTo-Json -Depth 10) + "`n"),
    $utf8NoBom
  )
  Update-ChecksumEntry -Directory $mappingTampered -RelativePath "sbom/sbom-manifest.json"
  $mappingManifestPath = Join-Path $mappingTampered "release-manifest.json"
  $mappingManifest = [System.IO.File]::ReadAllText($mappingManifestPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
  $mappingManifest.sbom.manifest_sha256 = Get-Sha256 -Path $mappingSbomPath
  $mappingManifest.checksums.sha256 = Get-Sha256 -Path (Join-Path $mappingTampered "SHA256SUMS.txt")
  [System.IO.File]::WriteAllText(
    $mappingManifestPath,
    (($mappingManifest | ConvertTo-Json -Depth 10) + "`n"),
    $utf8NoBom
  )
  $mappingResult = Verify-Candidate -Directory $mappingTampered
  Assert-True ($mappingResult.ExitCode -ne 0) "An SBOM component mapped to another registered lock must fail verification."
  Assert-True ($mappingResult.Stderr.Trim() -ceq "invalid_sbom_component") ("SBOM mapping rejection must use one stable stderr category. Actual stderr: " + $mappingResult.Stderr.Trim() + "; stdout: " + $mappingResult.Stdout.Trim())

  $duplicateSbom = Join-Path $probeRoot "duplicate-sbom"
  Copy-Item -LiteralPath $output -Destination $duplicateSbom -Recurse
  $duplicateSbomPath = Join-Path $duplicateSbom "sbom\sbom-manifest.json"
  $duplicateSbomManifest = [System.IO.File]::ReadAllText($duplicateSbomPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
  $duplicateSbomManifest.components[1].id = [string]$duplicateSbomManifest.components[0].id
  [System.IO.File]::WriteAllText(
    $duplicateSbomPath,
    (($duplicateSbomManifest | ConvertTo-Json -Depth 10) + "`n"),
    $utf8NoBom
  )
  Update-ChecksumEntry -Directory $duplicateSbom -RelativePath "sbom/sbom-manifest.json"
  $duplicateSbomReleaseManifestPath = Join-Path $duplicateSbom "release-manifest.json"
  $duplicateSbomReleaseManifest = [System.IO.File]::ReadAllText($duplicateSbomReleaseManifestPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
  $duplicateSbomReleaseManifest.sbom.manifest_sha256 = Get-Sha256 -Path $duplicateSbomPath
  $duplicateSbomReleaseManifest.checksums.sha256 = Get-Sha256 -Path (Join-Path $duplicateSbom "SHA256SUMS.txt")
  [System.IO.File]::WriteAllText(
    $duplicateSbomReleaseManifestPath,
    (($duplicateSbomReleaseManifest | ConvertTo-Json -Depth 10) + "`n"),
    $utf8NoBom
  )
  $duplicateSbomResult = Verify-Candidate -Directory $duplicateSbom
  Assert-True ($duplicateSbomResult.ExitCode -ne 0) "Duplicate SBOM component ids must fail verification."
  Assert-True ($duplicateSbomResult.Stderr.Trim() -ceq "invalid_sbom_component") "Duplicate SBOM rejection must use one stable stderr category."

  $extraFile = Join-Path $probeRoot "extra-file"
  Copy-Item -LiteralPath $output -Destination $extraFile -Recurse
  [System.IO.File]::WriteAllText((Join-Path $extraFile "debug.txt"), "unexpected", $utf8NoBom)
  $extraFileResult = Verify-Candidate -Directory $extraFile
  Assert-True ($extraFileResult.ExitCode -ne 0) "An extra release file must fail verification."
  Assert-True ($extraFileResult.Stderr.Trim() -ceq "unexpected_package_file") "Extra-file rejection must use one stable stderr category."

  $artifactNameDrift = Join-Path $probeRoot "artifact-name-drift"
  Copy-Item -LiteralPath $output -Destination $artifactNameDrift -Recurse
  $artifactNameManifestPath = Join-Path $artifactNameDrift "release-manifest.json"
  $artifactNameManifest = [System.IO.File]::ReadAllText($artifactNameManifestPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
  $hostArtifact = @($artifactNameManifest.artifacts | Where-Object { $_.id -ceq "host" })[0]
  $hostArtifact.path = "artifacts/Reflex-debug.exe"
  [System.IO.File]::WriteAllText(
    $artifactNameManifestPath,
    (($artifactNameManifest | ConvertTo-Json -Depth 10) + "`n"),
    $utf8NoBom
  )
  $artifactNameResult = Verify-Candidate -Directory $artifactNameDrift
  Assert-True ($artifactNameResult.ExitCode -ne 0) "An artifact filename drift must fail verification."
  Assert-True ($artifactNameResult.Stderr.Trim() -ceq "invalid_artifact_manifest") "Artifact filename rejection must use one stable stderr category."

  $missingFile = Join-Path $probeRoot "missing-file"
  Copy-Item -LiteralPath $output -Destination $missingFile -Recurse
  Remove-Item -LiteralPath (Join-Path $missingFile "artifacts\Reflex.exe") -Force
  $missingFileResult = Verify-Candidate -Directory $missingFile
  Assert-True ($missingFileResult.ExitCode -ne 0) "A missing release file must fail verification."
  Assert-True ($missingFileResult.Stderr.Trim() -ceq "checksummed_file_missing") "Missing-file rejection must use one stable stderr category."

  $legacySchema = Join-Path $probeRoot "legacy-schema"
  Copy-Item -LiteralPath $output -Destination $legacySchema -Recurse
  $legacyManifestPath = Join-Path $legacySchema "release-manifest.json"
  $legacyManifest = [System.IO.File]::ReadAllText($legacyManifestPath) | ConvertFrom-Json
  $legacyManifest.schema_version = 1
  [System.IO.File]::WriteAllText(
    $legacyManifestPath,
    (($legacyManifest | ConvertTo-Json -Depth 10) + "`n"),
    $utf8NoBom
  )
  $legacyResult = Verify-Candidate -Directory $legacySchema
  Assert-True ($legacyResult.ExitCode -ne 0) "A legacy release manifest schema must fail verification."
  Assert-True ($legacyResult.Stderr.Trim() -ceq 'invalid_release_manifest') "Legacy schema rejection must use one stable stderr category."

  $duplicateDocuments = Join-Path $probeRoot "duplicate-documents"
  Copy-Item -LiteralPath $output -Destination $duplicateDocuments -Recurse
  $duplicateManifestPath = Join-Path $duplicateDocuments "release-manifest.json"
  $duplicateManifest = [System.IO.File]::ReadAllText($duplicateManifestPath) | ConvertFrom-Json
  $duplicateManifest.documents.support_guide = $duplicateManifest.documents.privacy_notice
  [System.IO.File]::WriteAllText(
    $duplicateManifestPath,
    (($duplicateManifest | ConvertTo-Json -Depth 10) + "`n"),
    $utf8NoBom
  )
  $duplicateResult = Verify-Candidate -Directory $duplicateDocuments
  Assert-True ($duplicateResult.ExitCode -ne 0) "Duplicate public document mappings must fail verification."
  Assert-True ($duplicateResult.Stderr.Trim() -ceq 'document_manifest_mismatch') "Duplicate document rejection must use one stable stderr category."

  $ready = Verify-Candidate -Directory $output -ExtraArguments @("-RequireReady")
  Assert-True ($ready.ExitCode -ne 0) "Unsigned material must fail the formal readiness gate."
  Assert-True ($ready.Stderr.Trim() -ceq 'release_not_ready') "Readiness failure must use one stable stderr category."

  $existing = New-Candidate -Destination $output
  Assert-True ($existing.ExitCode -ne 0) "An existing output directory must not be overwritten."
  Assert-True ($existing.Stderr.Trim() -ceq 'output_directory_exists') "Existing-output failure must use one stable stderr category."

  $signedOutput = Join-Path $probeRoot "signed-required"
  $signed = New-Candidate -Destination $signedOutput -ExtraArguments @("-RequireSigned")
  Assert-True ($signed.ExitCode -ne 0) "Unsigned artifacts must fail when signatures are required."
  Assert-True ($signed.Stderr.Trim() -ceq 'release_signature_required') "Signature failure must use one stable stderr category."
  Assert-True (-not (Test-Path -LiteralPath $signedOutput)) "Failed generation must not leave a candidate directory."

  $tampered = Join-Path $probeRoot "tampered"
  Copy-Item -LiteralPath $output -Destination $tampered -Recurse
  [System.IO.File]::AppendAllText(
    (Join-Path $tampered "artifacts\Reflex.exe"),
    "tampered",
    $utf8NoBom
  )
  $tamperResult = Verify-Candidate -Directory $tampered
  Assert-True ($tamperResult.ExitCode -ne 0) "A modified artifact must fail verification."
  Assert-True ($tamperResult.Stderr.Trim() -ceq 'checksum_mismatch') ("Tamper failure must use one stable stderr category. Actual stderr: " + $tamperResult.Stderr.Trim() + "; stdout: " + $tamperResult.Stdout.Trim())

  $traversal = Join-Path $probeRoot "traversal"
  Copy-Item -LiteralPath $output -Destination $traversal -Recurse
  $traversalManifestPath = Join-Path $traversal "release-manifest.json"
  $traversalManifest = [System.IO.File]::ReadAllText($traversalManifestPath) | ConvertFrom-Json
  $traversalManifest.artifacts[0].path = "../outside.exe"
  [System.IO.File]::WriteAllText(
    $traversalManifestPath,
    (($traversalManifest | ConvertTo-Json -Depth 10) + "`n"),
    $utf8NoBom
  )
  $traversalResult = Verify-Candidate -Directory $traversal
  Assert-True ($traversalResult.ExitCode -ne 0) "A parent traversal path must fail verification."
  Assert-True ($traversalResult.Stderr.Trim() -ceq 'invalid_artifact_manifest') "Traversal failure must use one stable stderr category."

  $documentDrift = Join-Path $probeRoot "document-drift"
  Copy-Item -LiteralPath $output -Destination $documentDrift -Recurse
  $supportPath = Join-Path $documentDrift "SUPPORT.md"
  [System.IO.File]::AppendAllText($supportPath, "`nsource drift`n", $utf8NoBom)
  $documentChecksumsPath = Join-Path $documentDrift "SHA256SUMS.txt"
  $supportHash = Get-Sha256 -Path $supportPath
  $replacedSupport = 0
  $documentChecksums = @([System.IO.File]::ReadAllLines($documentChecksumsPath) | ForEach-Object {
      if ($_ -match '^[a-f0-9]{64} \*SUPPORT\.md$') {
        $replacedSupport += 1
        "$supportHash *SUPPORT.md"
      }
      else {
        $_
      }
    })
  Assert-True ($replacedSupport -eq 1) "Support document must have exactly one checksum entry."
  [System.IO.File]::WriteAllText(
    $documentChecksumsPath,
    (($documentChecksums -join "`n") + "`n"),
    $utf8NoBom
  )
  $documentManifestPath = Join-Path $documentDrift "release-manifest.json"
  $documentManifest = [System.IO.File]::ReadAllText($documentManifestPath) | ConvertFrom-Json
  $documentManifest.checksums.sha256 = Get-Sha256 -Path $documentChecksumsPath
  [System.IO.File]::WriteAllText(
    $documentManifestPath,
    (($documentManifest | ConvertTo-Json -Depth 10) + "`n"),
    $utf8NoBom
  )
  $documentDriftResult = Verify-Candidate -Directory $documentDrift
  Assert-True ($documentDriftResult.ExitCode -ne 0) "A rewritten public document must fail source binding."
  Assert-True ($documentDriftResult.Stderr.Trim() -ceq 'release_document_source_mismatch') "Document source drift must use one stable stderr category."

  $secret = "gh" + "p_" + ("S" * 36)
  [System.IO.File]::WriteAllText(
    (Join-Path $artifacts "Reflex_${version}_x64-setup.exe"),
    ("token=" + $secret),
    $utf8NoBom
  )
  $secretOutput = Join-Path $probeRoot "secret-output"
  $secretResult = New-Candidate -Destination $secretOutput
  Assert-True ($secretResult.ExitCode -ne 0) "A secret-bearing artifact must fail generation."
  Assert-True (($secretResult.Stdout + $secretResult.Stderr) -match 'release_secret_scan_failed') "Secret failure must use a stable category."
  Assert-True (($secretResult.Stdout + $secretResult.Stderr) -notmatch [regex]::Escape($secret)) "Secret scanner output must remain redacted."
  Assert-True (-not (Test-Path -LiteralPath $secretOutput)) "Secret failure must not leave a candidate directory."
}
finally {
  Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Output "release candidate contract checks passed."
