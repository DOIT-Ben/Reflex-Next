$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$generator = Join-Path $root "tools\new_release_candidate.ps1"
$verifier = Join-Path $root "tools\verify_release_candidate.ps1"
$powershell = Join-Path $PSHOME "powershell.exe"
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

$components = @(
  [PSCustomObject]@{ Id = "python-reflex-core"; Name = "reflex-core"; Lock = "packages/reflex-core/uv.lock" },
  [PSCustomObject]@{ Id = "python-reflex-runtime"; Name = "reflex-runtime"; Lock = "packages/reflex-runtime/uv.lock" },
  [PSCustomObject]@{ Id = "python-reflex-cloud"; Name = "reflex-cloud"; Lock = "services/reflex-cloud/uv.lock" },
  [PSCustomObject]@{ Id = "python-batch-runner"; Name = "reflex-batch-runner"; Lock = "plugins/batch-runner/uv.lock" },
  [PSCustomObject]@{ Id = "python-history-sqlite"; Name = "reflex-history-sqlite"; Lock = "plugins/history-sqlite/uv.lock" },
  [PSCustomObject]@{ Id = "python-markdown-preview"; Name = "reflex-markdown-preview"; Lock = "plugins/markdown-preview/uv.lock" },
  [PSCustomObject]@{ Id = "python-provider-minimax"; Name = "reflex-provider-minimax"; Lock = "plugins/provider-minimax/uv.lock" },
  [PSCustomObject]@{ Id = "python-provider-openai-compatible"; Name = "reflex-provider-openai-compatible"; Lock = "plugins/provider-openai-compatible/uv.lock" },
  [PSCustomObject]@{ Id = "python-semantic-detector"; Name = "reflex-plugin-semantic-detector"; Lock = "plugins/semantic-detector/uv.lock" },
  [PSCustomObject]@{ Id = "python-translator"; Name = "reflex-translator"; Lock = "plugins/translator/uv.lock" },
  [PSCustomObject]@{ Id = "rust-tauri-host"; Name = "reflex-next-tauri-host"; Lock = "apps/tauri-host/src-tauri/Cargo.lock" },
  [PSCustomObject]@{ Id = "node-tauri-host"; Name = "tauri-host"; Lock = "apps/tauri-host/package-lock.json" }
)

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
      root_component = $component.Name
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
  ) ("A valid unsigned review candidate must be generated: " + $created.Stderr)
  Assert-True ($created.Stdout -match 'artifacts=3; sbom=12; release_ready=false') "Generator output must report bounded material and readiness."
  $manifestPath = Join-Path $output "release-manifest.json"
  Assert-True (Test-Path -LiteralPath $manifestPath -PathType Leaf) "Release manifest must be emitted."
  $manifest = [System.IO.File]::ReadAllText($manifestPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
  Assert-True ([string]$manifest.version -ceq $version) "Manifest version must match VERSION."
  Assert-True (@($manifest.artifacts).Count -eq 3) "Manifest must contain exactly three executable artifacts."
  Assert-True ([int]$manifest.sbom.component_count -eq 12) "Manifest must contain twelve component BOMs."
  Assert-True (-not [bool]$manifest.gates.signatures_valid) "Unsigned fixture artifacts must not be marked signed."
  Assert-True (-not [bool]$manifest.gates.release_ready) "Unsigned review material must not be release-ready."
  Assert-True ((Get-Content -Raw -Encoding UTF8 $manifestPath) -notmatch [regex]::Escape($root)) "Manifest must not leak absolute workspace paths."
  Assert-True (@(Get-ChildItem -LiteralPath $output -File -Recurse).Count -eq 20) "Candidate must have an exact bounded file set."

  $verified = Verify-Candidate -Directory $output
  Assert-True ($verified.ExitCode -eq 0) "Untampered review material must verify."
  Assert-True ($verified.Stdout -match 'files=20; release_ready=false') "Verifier must report bounded files and readiness."

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
  Assert-True ($tamperResult.Stderr.Trim() -ceq 'checksum_mismatch') "Tamper failure must use one stable stderr category."

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
  Assert-True ($traversalResult.Stderr.Trim() -ceq 'invalid_artifact_path') "Traversal failure must use one stable stderr category."

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
