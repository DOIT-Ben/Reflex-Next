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
    "Invoke-LegacyConfigProbe",
    "Invoke-SilentUninstaller",
    'ArgumentList @("/S")',
    '("/D=" + $Destination)',
    "Wait-ProductFilesRemoved",
    "uninstaller_product_files_timeout",
    "EnvironmentVariables",
    "REFLEX_LIFECYCLE_DATA_ROOT",
    "REFLEX_DIAGNOSTICS_ENABLED",
    "host_config_isolation_not_observed",
    "recovery.Count -lt 1",
    "legacy_config_triggered_recovery",
    "legacy-config-start",
    'isolated_data_root = $hostProbe.IsolatedDataRoot',
    "host_close_request_failed",
    "host_closed_instead_of_tray",
    "legacy_config_close_request_failed",
    "legacy_config_closed_instead_of_tray",
    "closeToTray",
    "CleanupTermination",
    "process.Kill()",
    "steps.ToArray()"
  )) {
  Assert-True ($content.Contains($required)) "Lifecycle verifier is missing required guard or phase: $required"
}

Assert-True ($content -notmatch "Stop-Process") "Lifecycle verifier must not stop arbitrary processes."
Assert-True ($content -notmatch "Get-Process.*Kill") "Lifecycle verifier must not kill discovered processes."
Write-Output "verify_windows_lifecycle contract checks passed."
