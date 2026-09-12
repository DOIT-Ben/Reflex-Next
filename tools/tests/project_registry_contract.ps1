$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$registryPath = Join-Path $root "tools\project-registry.json"
$verifyScript = Join-Path $root "tools\verify_backend.ps1"
. (Join-Path $root "tools\project_registry.ps1")

function Assert-True {
  param([bool]$Condition, [string]$Message)
  if (-not $Condition) { throw $Message }
}

Assert-True (Test-Path -LiteralPath $registryPath -PathType Leaf) "Project registry is missing."
$registry = Get-ReflexProjectRegistry -RepositoryRoot $root
Assert-True ([int]$registry.schema_version -eq 1) "Project registry schema must be version 1."

$projects = @($registry.projects)
Assert-True ($projects.Count -gt 0) "Project registry must contain at least one Python project."
Assert-True ((@($projects | ForEach-Object { [string]$_.id } | Sort-Object -Unique)).Count -eq $projects.Count) "Project registry ids must be unique."
Assert-True ((@($projects | ForEach-Object { [string]$_.path } | Sort-Object -Unique)).Count -eq $projects.Count) "Project registry paths must be unique."
Assert-True ((@($projects | ForEach-Object { [string]$_.lock } | Sort-Object -Unique)).Count -eq $projects.Count) "Project registry locks must be unique."
Assert-True (@($registry.sbom_components).Count -ge 2) "Project registry must define non-Python SBOM components."

function Resolve-RegistryPath {
  param([string]$Value, [string]$Field, [string]$ProjectId)

  Assert-True (-not [string]::IsNullOrWhiteSpace($Value)) ("Registry $Field is empty: " + $ProjectId)
  Assert-True (-not [System.IO.Path]::IsPathRooted($Value)) ("Registry $Field must be relative: " + $ProjectId)
  Assert-True (@($Value.Replace("/", "\").Split("\") | Where-Object { $_ -in @("", ".", "..") }).Count -eq 0) ("Registry $Field contains unsafe segments: " + $ProjectId)
  $fullPath = [System.IO.Path]::GetFullPath((Join-Path $root ($Value -replace "/", "\")))
  $rootPrefix = $root.TrimEnd("\") + "\"
  Assert-True ($fullPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) ("Registry $Field escapes repository: " + $ProjectId)
  return $fullPath
}

foreach ($project in $projects) {
  $projectId = [string]$project.id
  Assert-True ($projectId -match '^[a-z0-9]+(?:-[a-z0-9]+)*$') ("Project id is not a safe identifier: " + $projectId)
  $packageName = [string]$project.package_name
  Assert-True ($packageName -match '^[a-z0-9]+(?:[-_.][a-z0-9]+)*$') ("Package name is not a safe identifier: " + $projectId)
  $module = [string]$project.module
  Assert-True ($module -match '^[a-z][a-z0-9_]*$') ("Python module is not a safe identifier: " + $projectId)
  $projectPath = Resolve-RegistryPath -Value ([string]$project.path) -Field "path" -ProjectId ([string]$project.id)
  $lockPath = Resolve-RegistryPath -Value ([string]$project.lock) -Field "lock" -ProjectId ([string]$project.id)
  Assert-True ([string]$project.kind -eq "python") ("Unsupported project kind: " + [string]$project.id)
  $manifestPath = Join-Path $projectPath "pyproject.toml"
  $sourcePath = Join-Path $projectPath "src"
  $modulePath = Join-Path $sourcePath $module
  Assert-True (Test-Path -LiteralPath $manifestPath -PathType Leaf) ("Project manifest is missing: " + [string]$project.id)
  Assert-True (Test-Path -LiteralPath $lockPath -PathType Leaf) ("Project lock is missing: " + [string]$project.id)
  Assert-True (Test-Path -LiteralPath $sourcePath -PathType Container) ("Project source directory is missing: " + [string]$project.id)
  Assert-True (Test-Path -LiteralPath $modulePath -PathType Container) ("Project module directory is missing: " + [string]$project.id)
  $projectItem = Get-Item -LiteralPath $projectPath
  $sourceItem = Get-Item -LiteralPath $sourcePath
  $lockItem = Get-Item -LiteralPath $lockPath
  $sourceReparsePoints = @(Get-ChildItem -LiteralPath $sourcePath -Recurse -Force | Where-Object {
      $_.Attributes -band [System.IO.FileAttributes]::ReparsePoint
    })
  Assert-True (-not ($projectItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) ("Project path cannot be a reparse point: " + [string]$project.id)
  Assert-True (-not ($sourceItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) ("Project source directory cannot be a reparse point: " + [string]$project.id)
  Assert-True (-not ($lockItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) ("Project lock cannot be a reparse point: " + [string]$project.id)
  Assert-True ($sourceReparsePoints.Count -eq 0) ("Project source tree cannot contain reparse points: " + [string]$project.id)
  $manifestText = [System.IO.File]::ReadAllText($manifestPath, [System.Text.Encoding]::UTF8)
  $nameMatch = [regex]::Match($manifestText, '(?m)^name\s*=\s*"([^"]+)"')
  Assert-True ($nameMatch.Success -and $nameMatch.Groups[1].Value -ceq $packageName) ("Registry package name does not match pyproject.toml: " + [string]$project.id)
  Assert-True ($project.verify -eq $true) ("Project is not covered by verification: " + [string]$project.id)
  Assert-True ($project.sbom -eq $true -or $project.sbom -eq $false) ("Project SBOM flag is invalid: " + [string]$project.id)
  Assert-True ($project.sidecar -eq $true -or $project.sidecar -eq $false) ("Project Sidecar flag is invalid: " + [string]$project.id)
  Assert-True (@("product", "plugin") -contains [string]$project.version_policy) ("Project version policy is invalid: " + [string]$project.id)
  $lockPackages = @($project.version_lock_packages)
  Assert-True ($lockPackages.Count -gt 0) ("Project version lock package list is empty: " + [string]$project.id)
  Assert-True ((@($lockPackages | Sort-Object -Unique)).Count -eq $lockPackages.Count) ("Project version lock packages must be unique: " + [string]$project.id)
  foreach ($lockPackage in $lockPackages) {
    Assert-True ([string]$lockPackage -match '^[a-z0-9]+(?:[-_.][a-z0-9]+)*$') ("Version lock package is not a safe identifier: " + [string]$project.id)
  }
}

$discoveredProjectPaths = @(
  foreach ($scope in @("packages", "plugins", "services")) {
    $scopePath = Join-Path $root $scope
    if (Test-Path -LiteralPath $scopePath -PathType Container) {
      Get-ChildItem -LiteralPath $scopePath -Filter "pyproject.toml" -File -Recurse -Force | Where-Object {
        $_.FullName -notmatch '\\(\.git|\.venv|node_modules|target)(\\|$)'
      } | ForEach-Object { (Get-Item -LiteralPath $_.DirectoryName -Force).FullName }
    }
  }
) | Sort-Object -Unique
$registeredProjectPaths = @(
  $projects | ForEach-Object {
    [System.IO.Path]::GetFullPath((Join-Path $root (([string]$_.path) -replace "/", "\")))
  }
) | Sort-Object -Unique
Assert-True ($discoveredProjectPaths.Count -eq $registeredProjectPaths.Count) "Every Python project manifest must be registered exactly once."
Assert-True (@(Compare-Object -ReferenceObject $discoveredProjectPaths -DifferenceObject $registeredProjectPaths).Count -eq 0) "Discovered Python project paths must exactly match the registry."

$responses = $projects | Where-Object { $_.id -eq "provider-openai-responses" } | Select-Object -First 1
Assert-True ($null -ne $responses) "OpenAI Responses Provider must be registered."
Assert-True ($responses.sbom -eq $true) "OpenAI Responses Provider must be in SBOM generation."

$sidecarBuilderPath = Join-Path $root "tools\build_runtime_sidecar.ps1"
Assert-True (Test-Path -LiteralPath $sidecarBuilderPath -PathType Leaf) "Runtime Sidecar builder is missing."
$sidecarBuilder = [System.IO.File]::ReadAllText($sidecarBuilderPath, [System.Text.Encoding]::UTF8)
Assert-True ($sidecarBuilder -match '\$_\.sidecar -eq \$true') "Runtime Sidecar builder must select Sidecar projects from the registry."
Assert-True ($sidecarBuilder -match '\[string\]\$_\.module') "Runtime Sidecar builder must derive collected modules from the registry."
Assert-True ($sidecarBuilder -match '\[string\]\$_\.package_name') "Runtime Sidecar builder must derive package metadata from the registry."

$registryConsumers = @(
  "verify_backend.ps1",
  "audit_dependencies.ps1",
  "check_version_consistency.ps1",
  "generate_release_sbom.ps1",
  "build_runtime_sidecar.ps1",
  "new_release_candidate.ps1",
  "verify_release_candidate.ps1",
  "verify_cloud.ps1",
  "verify_cloud_postgres_quality_release.ps1"
)
foreach ($consumer in $registryConsumers) {
  $consumerPath = Join-Path $root ("tools\" + $consumer)
  Assert-True (Test-Path -LiteralPath $consumerPath -PathType Leaf) ("Registry consumer is missing: " + $consumer)
  $consumerSource = [System.IO.File]::ReadAllText($consumerPath, [System.Text.Encoding]::UTF8)
  Assert-True ($consumerSource -match 'project_registry\.ps1') ("Registry consumer must load the shared registry loader: " + $consumer)
  Assert-True ($consumerSource -match 'Get-ReflexProjectRegistry') ("Registry consumer must call the shared registry loader: " + $consumer)
}
$sbomConsumers = @(
  "generate_release_sbom.ps1",
  "new_release_candidate.ps1",
  "verify_release_candidate.ps1"
)
foreach ($consumer in $sbomConsumers) {
  $consumerPath = Join-Path $root ("tools\" + $consumer)
  $consumerSource = [System.IO.File]::ReadAllText($consumerPath, [System.Text.Encoding]::UTF8)
  Assert-True ($consumerSource -match 'Get-ReflexSbomComponentCatalog') ("SBOM consumer must use the shared component catalog: " + $consumer)
}

$productionToolFiles = @(Get-ChildItem -LiteralPath (Join-Path $root "tools") -Filter "*.ps1" -File -Recurse | Where-Object {
    $_.FullName -notmatch ([regex]::Escape((Join-Path $root "tools\tests"))) -and
    $_.Name -cne "project_registry.ps1"
  })
foreach ($toolFile in $productionToolFiles) {
  $toolSource = [System.IO.File]::ReadAllText($toolFile.FullName, [System.Text.Encoding]::UTF8)
  Assert-True ($toolSource -notmatch 'project-registry\.json') ("Production tool must not read the registry JSON directly: " + $toolFile.FullName)
}

$pathProbeRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
  "reflex-project-registry-path-contract-" + [guid]::NewGuid().ToString("N")
)
try {
  New-Item -ItemType Directory -Path (Join-Path $pathProbeRoot "tools") -Force | Out-Null
  $unsafeRegistry = [ordered]@{
    schema_version = 1
    projects = @(
      [ordered]@{
        id = "unsafe-project"
        kind = "python"
         path = "..\outside"
         package_name = "reflex-unsafe-project"
         lock = "packages/unsafe/uv.lock"
         module = "reflex_unsafe_project"
         sidecar = $false
         role = "plugin"
         verify = $true
         sbom = $false
         version_policy = "plugin"
         version_lock_packages = @("reflex-unsafe-project")
      }
    )
  }
  [System.IO.File]::WriteAllText(
    (Join-Path $pathProbeRoot "tools\project-registry.json"),
    ($unsafeRegistry | ConvertTo-Json -Depth 8),
    (New-Object System.Text.UTF8Encoding($false))
  )
  $pathError = ""
  try {
    Get-ReflexProjectRegistry -RepositoryRoot $pathProbeRoot | Out-Null
  }
  catch {
    $pathError = [string]$_.Exception.Message
  }
  Assert-True ($pathError -ceq "project_registry_unsafe_path:unsafe-project:path") "Registry loader must reject paths escaping the repository."

  $misalignedRegistry = [ordered]@{
    schema_version = 1
    projects = @(
      [ordered]@{
        id = "misaligned-project"
        kind = "python"
         path = "packages/reflex-core"
         package_name = "reflex-core"
         lock = "packages/reflex-runtime/uv.lock"
         module = "reflex_core"
         sidecar = $true
         role = "core"
         verify = $true
         sbom = $true
         version_policy = "product"
         version_lock_packages = @("reflex-core")
      }
    )
  }
  [System.IO.File]::WriteAllText(
    (Join-Path $pathProbeRoot "tools\project-registry.json"),
    ($misalignedRegistry | ConvertTo-Json -Depth 8),
    (New-Object System.Text.UTF8Encoding($false))
  )
  $lockError = ""
  try {
    Get-ReflexProjectRegistry -RepositoryRoot $pathProbeRoot | Out-Null
  }
  catch {
    $lockError = [string]$_.Exception.Message
  }
  Assert-True ($lockError -ceq "project_registry_lock_mismatch:misaligned-project") "Registry loader must bind each lock file to its project directory."

  $outsideRoot = Join-Path $pathProbeRoot "outside"
  $junctionRoot = Join-Path $pathProbeRoot "packages"
  New-Item -ItemType Directory -Path $outsideRoot -Force | Out-Null
  New-Item -ItemType Junction -Path $junctionRoot -Target $outsideRoot -Force | Out-Null
  $reparseRegistry = [ordered]@{
    schema_version = 1
    projects = @(
      [ordered]@{
        id = "reparse-project"
        kind = "python"
         path = "packages/reparse-project"
         package_name = "reflex-reparse-project"
         lock = "packages/reparse-project/uv.lock"
         module = "reflex_reparse_project"
         sidecar = $true
         role = "plugin"
         verify = $true
         sbom = $true
         version_policy = "plugin"
         version_lock_packages = @("reflex-reparse-project")
      }
    )
  }
  [System.IO.File]::WriteAllText(
    (Join-Path $pathProbeRoot "tools\project-registry.json"),
    ($reparseRegistry | ConvertTo-Json -Depth 8),
    (New-Object System.Text.UTF8Encoding($false))
  )
  $reparseError = ""
  try {
    Get-ReflexProjectRegistry -RepositoryRoot $pathProbeRoot | Out-Null
  }
  catch {
    $reparseError = [string]$_.Exception.Message
  }
  Assert-True ($reparseError -ceq "project_registry_reparse_point:reparse-project:path") "Registry loader must reject reparse points in parent path components."
}
finally {
  Remove-Item -LiteralPath $pathProbeRoot -Recurse -Force -ErrorAction SilentlyContinue
}

$listPath = Join-Path ([System.IO.Path]::GetTempPath()) ("reflex-project-registry-contract-" + [guid]::NewGuid().ToString("N") + ".txt")
$powerShellCommand = if (Get-Command pwsh.exe -ErrorAction SilentlyContinue) {
  "pwsh.exe"
}
else {
  "powershell.exe"
}
try {
  & $powerShellCommand -NoProfile -ExecutionPolicy Bypass -File $verifyScript -ListSteps 1> $listPath
  Assert-True ($LASTEXITCODE -eq 0) "Verification step listing failed."
  $steps = Get-Content -Encoding UTF8 -LiteralPath $listPath
  foreach ($project in @($projects)) {
    $id = "python:" + [string]$project.id
    Assert-True (@($steps | Where-Object { $_ -match ("^\[STEP\] " + [regex]::Escape($id) + " ") }).Count -eq 1) ("Missing verification step: " + $id)
  }
  Assert-True (@($steps | Where-Object { $_ -match "^\[STEP\] governance:project-registry-contract " }).Count -eq 1) "Project registry contract must be a verification step."
}
finally {
  Remove-Item -LiteralPath $listPath -Force -ErrorAction SilentlyContinue
}

Write-Output "project registry contract checks passed."

exit 0
