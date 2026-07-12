param(
  [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $root "packages\reflex-runtime"
$python = Join-Path $runtimeDir ".venv\Scripts\python.exe"
$entry = Join-Path $root "tools\runtime_sidecar_entry.py"

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

$paths = @(
  (Join-Path $root "packages\reflex-runtime\src"),
  (Join-Path $root "packages\reflex-core\src"),
  (Join-Path $root "plugins\provider-minimax\src"),
  (Join-Path $root "plugins\provider-openai-compatible\src"),
  (Join-Path $root "plugins\history-sqlite\src"),
  (Join-Path $root "plugins\translator\src"),
  (Join-Path $root "plugins\markdown-preview\src"),
  (Join-Path $root "plugins\batch-runner\src"),
  (Join-Path $root "plugins\semantic-detector\src")
)

$collectModules = @(
  "reflex_runtime",
  "reflex_core",
  "reflex_provider_minimax",
  "reflex_provider_openai_compatible",
  "reflex_history_sqlite",
  "reflex_translator",
  "reflex_markdown_preview",
  "reflex_batch_runner",
  "reflex_semantic_detector"
)

$metadata = @(
  "reflex-runtime",
  "reflex-core",
  "reflex-provider-minimax",
  "reflex-provider-openai-compatible",
  "reflex-history-sqlite",
  "reflex-translator",
  "reflex-markdown-preview",
  "reflex-batch-runner",
  "reflex-plugin-semantic-detector"
)

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
