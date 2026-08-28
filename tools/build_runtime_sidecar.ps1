param(
  [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "project_registry.ps1")
$registry = Get-ReflexProjectRegistry -RepositoryRoot $root
$runtimeProject = Get-ReflexRegistryProject -Registry $registry -ProjectId "reflex-runtime"
$runtimeDir = Join-Path $root ([string]$runtimeProject.path -replace "/", "\")
$python = Join-Path $runtimeDir ".venv\Scripts\python.exe"
$entry = Join-Path $root "tools\runtime_sidecar_entry.py"
$sidecarProjects = @($registry.projects | Where-Object {
    $_.kind -eq "python" -and $_.sidecar -eq $true
  })
if ($sidecarProjects.Count -eq 0) {
  throw "Project registry has no Runtime Sidecar projects."
}

& uv sync --frozen --project $runtimeDir --extra dev --extra builtins
if ($LASTEXITCODE -ne 0) {
  throw "Runtime Python environment synchronization failed."
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
  throw "Runtime Python environment is unavailable."
}

if (-not $OutputDir) {
  $OutputDir = Join-Path $root "apps\tauri-host\src-tauri\resources\runtime"
}

$workDir = Join-Path $root "tools\.runtime-sidecar-build"
$specDir = Join-Path $workDir "spec"
$distDir = Join-Path $workDir "dist"

Remove-Item -LiteralPath $workDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $workDir -Force | Out-Null
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$paths = @($sidecarProjects | ForEach-Object {
    Join-Path $root (([string]$_.path -replace "/", "\") + "\src")
  })

$collectModules = @($sidecarProjects | ForEach-Object { [string]$_.module })

$metadata = @($sidecarProjects | ForEach-Object { [string]$_.package_name })

$arguments = @(
  "-m", "PyInstaller",
  "--noconfirm",
  "--clean",
  "--onefile",
  "--noupx",
  "--name", "reflex-runtime",
  "--distpath", $distDir,
  "--workpath", (Join-Path $workDir "work"),
  "--specpath", $specDir
)

$templatePack = Join-Path $root "template-packs\builtin"
if (-not (Test-Path -LiteralPath $templatePack -PathType Container)) {
  throw "Built-in template pack is unavailable."
}
$arguments += @(
  "--add-data",
  ("{0}{1}template-packs\builtin" -f $templatePack, [System.IO.Path]::PathSeparator)
)

foreach ($path in $paths) {
  $arguments += @("--paths", $path)
}

foreach ($module in $collectModules) {
  $arguments += @("--collect-submodules", $module)
}

foreach ($distribution in $metadata) {
  $arguments += @("--copy-metadata", $distribution)
}

$arguments += $entry
& $python @arguments
if ($LASTEXITCODE -ne 0) {
  throw "Runtime Sidecar build failed."
}

$sidecar = Join-Path $distDir "reflex-runtime.exe"
if (-not (Test-Path -LiteralPath $sidecar -PathType Leaf)) {
  throw "Runtime Sidecar output is missing."
}

Copy-Item -LiteralPath $sidecar -Destination (Join-Path $OutputDir "reflex-runtime.exe") -Force
