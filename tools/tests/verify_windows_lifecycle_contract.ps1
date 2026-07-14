$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$scriptPath = Join-Path $root "tools\verify_windows_lifecycle.ps1"

function Assert-True {
  param(
    [bool]$Condition,
    [string]$Message
  )

  if (-not $Condition) {
    throw $Message
  }
}

Assert-True (Test-Path -LiteralPath $scriptPath -PathType Leaf) "Lifecycle verifier is missing."
$content = Get-Content -Raw -Encoding UTF8 -LiteralPath $scriptPath

foreach ($required in @(
    "Assert-UnderTemp",
    "work_root_must_be_empty",
    "Invoke-SilentInstaller",
    "Invoke-SidecarProbe",
    "Invoke-HostProbe",
    "Invoke-SilentUninstaller",
    'ArgumentList @("/S")',
    '("/D=" + $Destination)',
    "EnvironmentVariables",
    "process.Kill()",
    "steps.ToArray()"
  )) {
  Assert-True ($content.Contains($required)) "Lifecycle verifier is missing required guard or phase: $required"
}

Assert-True ($content -notmatch "Stop-Process") "Lifecycle verifier must not stop arbitrary processes."
Assert-True ($content -notmatch "Get-Process.*Kill") "Lifecycle verifier must not kill discovered processes."
Write-Output "verify_windows_lifecycle contract checks passed."
