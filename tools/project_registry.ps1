function Test-ReflexRegistrySafeRelativePath {
  param([string]$Value)

  if (
    [string]::IsNullOrWhiteSpace($Value) -or
    $Value.StartsWith('/', [System.StringComparison]::Ordinal) -or
    $Value.StartsWith('\', [System.StringComparison]::Ordinal) -or
    $Value.Contains(':') -or
    $Value -match '[\x00-\x1f]'
  ) {
    return $false
  }

  foreach ($segment in $Value.Replace('\', '/').Split('/')) {
    if ([string]::IsNullOrWhiteSpace($segment) -or $segment -in @('.', '..')) {
      return $false
    }
  }
  return $true
}

function Resolve-ReflexRegistryPath {
  param(
    [string]$RepositoryRoot,
    [string]$Value,
    [string]$ProjectId,
    [string]$Field
  )

  if (-not (Test-ReflexRegistrySafeRelativePath -Value $Value)) {
    throw "project_registry_unsafe_path:${ProjectId}:$Field"
  }

  $root = $RepositoryRoot.TrimEnd('\')
  $candidate = [System.IO.Path]::GetFullPath(
    (Join-Path $root ($Value.Replace('/', '\')))
  )
  if (-not $candidate.StartsWith($root + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "project_registry_path_escape:${ProjectId}:$Field"
  }
  $current = $candidate
  while ($true) {
    if (Test-Path -LiteralPath $current) {
      $item = Get-Item -LiteralPath $current -Force
      if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "project_registry_reparse_point:${ProjectId}:$Field"
      }
    }
    if ($current -ieq $root) {
      break
    }
    $parent = Split-Path -Parent $current
    if ([string]::IsNullOrWhiteSpace($parent) -or $parent -ieq $current) {
      break
    }
    $current = $parent
  }
  return $candidate
}

function Get-ReflexRegistryProject {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Registry,
    [Parameter(Mandatory = $true)]
    [string]$ProjectId
  )

  $matches = @($Registry.projects | Where-Object { [string]$_.id -ceq $ProjectId })
  if ($matches.Count -ne 1) {
    throw "project_registry_project_not_unique:$ProjectId"
  }
  return $matches[0]
}

function Get-ReflexSbomComponentCatalog {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Registry
  )

  $components = @(
    @($Registry.projects | Where-Object {
        $_.kind -eq 'python' -and $_.sbom -eq $true
      } | ForEach-Object {
        [PSCustomObject]@{
          Id = "python-$([string]$_.id)"
          Name = [string]$_.package_name
          Project = ([string]$_.path -replace '/', '\')
          Lock = ([string]$_.lock -replace '/', '\')
          BomRefPrefix = ''
        }
      })
    @($Registry.sbom_components | ForEach-Object {
        [PSCustomObject]@{
          Id = [string]$_.id
          Name = [string]$_.root_component
          Project = ([string]$_.project -replace '/', '\')
          Lock = ([string]$_.source_lock -replace '/', '\')
          BomRefPrefix = [string]$_.bom_ref_prefix
        }
      })
  )
  if ($components.Count -eq 0) {
    throw 'project_registry_has_no_sbom_components'
  }

  $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
  foreach ($component in $components) {
    if (-not $seen.Add([string]$component.Id)) {
      throw "project_registry_duplicate_sbom_id:$($component.Id)"
    }
  }
  return $components
}

function Get-ReflexProjectRegistry {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot
  )

  try {
    $root = (Resolve-Path -LiteralPath $RepositoryRoot -ErrorAction Stop).Path
  }
  catch {
    throw "project_registry_root_missing"
  }
  if (-not (Test-Path -LiteralPath $root -PathType Container)) {
    throw "project_registry_root_missing"
  }

  $registryPath = Join-Path $root "tools\project-registry.json"
  if (-not (Test-Path -LiteralPath $registryPath -PathType Leaf)) {
    throw "project_registry_missing"
  }

  try {
    $registry = [System.IO.File]::ReadAllText(
      $registryPath,
      [System.Text.Encoding]::UTF8
    ) | ConvertFrom-Json
  }
  catch {
    throw "project_registry_invalid_json"
  }

  if ([int]$registry.schema_version -ne 1) {
    throw "project_registry_unsupported_schema"
  }

  $projects = @($registry.projects)
  if ($projects.Count -eq 0) {
    throw "project_registry_empty"
  }

  $seenIds = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
  $seenPaths = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
  $seenLocks = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
  foreach ($project in $projects) {
    $projectId = [string]$project.id
    if (
      [string]::IsNullOrWhiteSpace($projectId) -or
      $projectId -notmatch '^[a-z0-9]+(?:-[a-z0-9]+)*$' -or
      -not $seenIds.Add($projectId)
    ) {
      throw "project_registry_invalid_project_id"
    }

    if ([string]$project.kind -cne 'python') {
      throw "project_registry_unsupported_project_kind:$projectId"
    }

    $packageName = [string]$project.package_name
    if ([string]::IsNullOrWhiteSpace($packageName) -or $packageName -notmatch '^[a-z0-9]+(?:[-_.][a-z0-9]+)*$') {
      throw "project_registry_invalid_package_name:$projectId"
    }
    $module = [string]$project.module
    if ([string]::IsNullOrWhiteSpace($module) -or $module -notmatch '^[a-z][a-z0-9_]*$') {
      throw "project_registry_invalid_module:$projectId"
    }

    if ([string]$project.role -notin @('core', 'runtime', 'host', 'service', 'plugin', 'product-extension')) {
      throw "project_registry_invalid_role:$projectId"
    }
    foreach ($booleanField in @('sidecar', 'verify', 'sbom')) {
      $property = $project.PSObject.Properties[$booleanField]
      if ($null -eq $property -or $null -eq $property.Value -or $property.Value.GetType().FullName -ne 'System.Boolean') {
        throw "project_registry_invalid_boolean:${projectId}:${booleanField}"
      }
    }
    if ([string]$project.version_policy -notin @('product', 'plugin')) {
      throw "project_registry_invalid_version_policy:$projectId"
    }
    $lockPackages = @($project.version_lock_packages)
    if ($lockPackages.Count -eq 0) {
      throw "project_registry_empty_version_lock_packages:$projectId"
    }
    $seenLockPackages = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    foreach ($lockPackage in $lockPackages) {
      if ([string]$lockPackage -notmatch '^[a-z0-9]+(?:[-_.][a-z0-9]+)*$' -or
          -not $seenLockPackages.Add([string]$lockPackage)) {
        throw "project_registry_invalid_version_lock_packages:$projectId"
      }
    }

    $projectPath = Resolve-ReflexRegistryPath `
      -RepositoryRoot $root `
      -Value ([string]$project.path) `
      -ProjectId $projectId `
      -Field 'path'
    $lockPath = Resolve-ReflexRegistryPath `
      -RepositoryRoot $root `
      -Value ([string]$project.lock) `
      -ProjectId $projectId `
      -Field 'lock'
    if (-not $seenPaths.Add($projectPath) -or -not $seenLocks.Add($lockPath)) {
      throw "project_registry_duplicate_path_or_lock:$projectId"
    }
    $expectedLock = (([string]$project.path).Replace('\', '/').TrimEnd('/') + '/uv.lock')
    if (([string]$project.lock).Replace('\', '/') -cne $expectedLock) {
      throw "project_registry_lock_mismatch:${projectId}"
    }
    if (-not (Test-Path -LiteralPath $projectPath -PathType Container)) {
      throw "project_registry_project_path_missing:$projectId"
    }
    if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
      throw "project_registry_lock_path_missing:$projectId"
    }
  }

  $sbomComponents = @($registry.sbom_components)
  if ($sbomComponents.Count -eq 0) {
    throw 'project_registry_sbom_components_missing'
  }
  $seenSbomIds = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
  $seenSbomLocks = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
  foreach ($component in $sbomComponents) {
    $componentId = [string]$component.id
    if ([string]::IsNullOrWhiteSpace($componentId) -or
        $componentId -notmatch '^[a-z0-9]+(?:-[a-z0-9]+)*$' -or
        -not $seenSbomIds.Add($componentId)) {
      throw "project_registry_invalid_sbom_component_id"
    }
    $rootComponent = [string]$component.root_component
    if ([string]::IsNullOrWhiteSpace($rootComponent)) {
      throw "project_registry_invalid_sbom_root_component:$componentId"
    }
    $projectPath = Resolve-ReflexRegistryPath -RepositoryRoot $root -Value ([string]$component.project) -ProjectId $componentId -Field 'sbom_project'
    if (-not (Test-Path -LiteralPath $projectPath -PathType Container)) {
      throw "project_registry_sbom_project_missing:$componentId"
    }
    $lockPath = Resolve-ReflexRegistryPath -RepositoryRoot $root -Value ([string]$component.source_lock) -ProjectId $componentId -Field 'sbom_lock'
    if (-not $seenSbomLocks.Add($lockPath) -or -not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
      throw "project_registry_invalid_sbom_lock:$componentId"
    }
    foreach ($field in @('bom_ref_prefix')) {
      $property = $component.PSObject.Properties[$field]
      if ($null -eq $property -or $null -eq $property.Value -or $property.Value.GetType().FullName -ne 'System.String') {
        throw "project_registry_invalid_sbom_field:${componentId}:${field}"
      }
    }
  }

  return $registry
}
