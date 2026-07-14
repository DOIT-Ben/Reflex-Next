[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$InstallerPath,
  [string]$WorkRoot = "",
  [switch]$KeepWorkRoot
)

$ErrorActionPreference = "Stop"

function Resolve-RequiredFile {
  param([string]$Path)

  $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
  if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
    throw "installer_path_is_not_a_file"
  }
  return $resolved
}

function Assert-UnderTemp {
  param([string]$Path)

  $resolved = [System.IO.Path]::GetFullPath($Path).TrimEnd("\")
  $temp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd("\")
  if (-not $resolved.StartsWith($temp + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "work_root_must_be_under_temp"
  }
  return $resolved
}

function Invoke-SilentInstaller {
  param(
    [string]$Path,
    [string]$Destination
  )

  $process = Start-Process -FilePath $Path -ArgumentList @(
    "/S",
    ("/D=" + $Destination)
  ) -Wait -PassThru -WindowStyle Hidden
  if ($process.ExitCode -ne 0) {
    throw "installer_exit_code_$($process.ExitCode)"
  }
}

function Assert-InstalledFiles {
  param([string]$Destination)

  foreach ($relative in @(
      "Reflex.exe",
      "runtime\reflex-runtime.exe",
      "uninstall.exe"
    )) {
    if (-not (Test-Path -LiteralPath (Join-Path $Destination $relative) -PathType Leaf)) {
      throw "installed_file_missing:$relative"
    }
  }
}

function Assert-ProductFilesRemoved {
  param([string]$Destination)

  foreach ($relative in @(
      "Reflex.exe",
      "runtime\reflex-runtime.exe",
      "uninstall.exe"
    )) {
    if (Test-Path -LiteralPath (Join-Path $Destination $relative)) {
      throw "uninstalled_file_remains:$relative"
    }
  }
}

function Invoke-SidecarProbe {
  param([string]$Path)

  $startInfo = New-Object System.Diagnostics.ProcessStartInfo
  $startInfo.FileName = $Path
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.RedirectStandardInput = $true
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true

  $process = New-Object System.Diagnostics.Process
  $process.StartInfo = $startInfo
  if (-not $process.Start()) {
    throw "sidecar_start_failed"
  }

  try {
    $process.StandardInput.WriteLine('{"version":1,"request_id":"lifecycle-ping","type":"ping","payload":{}}')
    $process.StandardInput.WriteLine('{"version":1,"request_id":"lifecycle-shutdown","type":"shutdown","payload":{}}')
    $process.StandardInput.Close()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    if (-not $process.WaitForExit(15000)) {
      throw "sidecar_shutdown_timeout"
    }
    if ($process.ExitCode -ne 0) {
      throw "sidecar_exit_code_$($process.ExitCode)"
    }
    if (-not [string]::IsNullOrWhiteSpace($stderr)) {
      throw "sidecar_stderr_not_empty"
    }

    $events = @(
      $stdout -split "`r?`n" |
        Where-Object { $_ } |
        ForEach-Object { $_ | ConvertFrom-Json }
    )
    if ($events.Count -ne 2) {
      throw "sidecar_event_count_$($events.Count)"
    }
    if ($events[0].request_id -ne "lifecycle-ping" -or
        $events[0].event.data.message -ne "pong" -or
        $events[1].request_id -ne "lifecycle-shutdown" -or
        $events[1].event.data.message -ne "shutdown") {
      throw "sidecar_protocol_mismatch"
    }
  }
  finally {
    if (-not $process.HasExited) {
      $process.Kill()
      $process.WaitForExit()
    }
    $process.Dispose()
  }
}

function Invoke-HostProbe {
  param(
    [string]$Path,
    [string]$ProfileRoot,
    [string]$TemporaryRoot
  )

  $config = Join-Path $ProfileRoot "config"
  $data = Join-Path $ProfileRoot "data"
  New-Item -ItemType Directory -Path $config, $data -Force | Out-Null
  [System.IO.File]::WriteAllText(
    (Join-Path $config "config.json"),
    "{lifecycle-invalid-config",
    (New-Object System.Text.UTF8Encoding($false))
  )

  $startInfo = New-Object System.Diagnostics.ProcessStartInfo
  $startInfo.FileName = $Path
  $startInfo.WorkingDirectory = Split-Path -Parent $Path
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.EnvironmentVariables["TEMP"] = $TemporaryRoot
  $startInfo.EnvironmentVariables["TMP"] = $TemporaryRoot
  $startInfo.EnvironmentVariables["REFLEX_LIFECYCLE_DATA_ROOT"] = $ProfileRoot
  $startInfo.EnvironmentVariables["REFLEX_DIAGNOSTICS_ENABLED"] = "1"

  $process = New-Object System.Diagnostics.Process
  $process.StartInfo = $startInfo
  if (-not $process.Start()) {
    throw "host_start_failed"
  }

  try {
    Start-Sleep -Seconds 6
    if ($process.HasExited) {
      throw "host_exited_before_start_probe"
    }
    $closeRequested = $process.CloseMainWindow()
    $forcedTermination = $false
    $process.WaitForExit(5000) | Out-Null
    if (-not $process.HasExited) {
      $process.Kill()
      $process.WaitForExit()
      $forcedTermination = $true
    }
    $diagnostics = Join-Path $data "diagnostics\host-diagnostics.jsonl"
    if (-not (Test-Path -LiteralPath $diagnostics -PathType Leaf)) {
      throw "host_isolation_diagnostics_missing"
    }
    $recovery = @(
      Get-Content -LiteralPath $diagnostics -Encoding UTF8 |
        Where-Object { $_ } |
        ForEach-Object { $_ | ConvertFrom-Json } |
        Where-Object { $_.event -eq "config_recovery" -and $_.status -eq "defaulted" }
    )
    if ($recovery.Count -lt 1) {
      throw "host_config_isolation_not_observed"
    }
    return [PSCustomObject]@{
      CloseRequested = [bool]$closeRequested
      ForcedTermination = $forcedTermination
      IsolatedDataRoot = $true
    }
  }
  finally {
    if (-not $process.HasExited) {
      $process.Kill()
      $process.WaitForExit()
    }
    $process.Dispose()
  }
}

function Invoke-SilentUninstaller {
  param([string]$Destination)

  $uninstaller = Join-Path $Destination "uninstall.exe"
  if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
    throw "uninstaller_missing"
  }
  $process = Start-Process -FilePath $uninstaller -ArgumentList @("/S") -Wait -PassThru -WindowStyle Hidden
  if ($process.ExitCode -ne 0) {
    throw "uninstaller_exit_code_$($process.ExitCode)"
  }
  Start-Sleep -Milliseconds 500
}

$installer = Resolve-RequiredFile -Path $InstallerPath
$ownedRoot = $false
if ([string]::IsNullOrWhiteSpace($WorkRoot)) {
  $root = Join-Path ([System.IO.Path]::GetTempPath()) ("reflex-lifecycle-" + [guid]::NewGuid().ToString("N"))
  $ownedRoot = $true
}
else {
  $root = Assert-UnderTemp -Path $WorkRoot
  if (Test-Path -LiteralPath $root) {
    if (@(Get-ChildItem -LiteralPath $root -Force).Count -ne 0) {
      throw "work_root_must_be_empty"
    }
  }
}

$install = Join-Path $root "install"
$profile = Join-Path $root "profile"
$sentinel = Join-Path $install "overlay-sentinel.txt"
$steps = New-Object System.Collections.Generic.List[object]

function Add-Pass {
  param(
    [string]$Step,
    [hashtable]$Details = @{}
  )
  [void]$steps.Add([PSCustomObject]@{
      step = $Step
      status = "passed"
      details = [PSCustomObject]$Details
    })
  Write-Output ("[PASS] " + $Step)
}

try {
  New-Item -ItemType Directory -Path $root -Force | Out-Null

  Invoke-SilentInstaller -Path $installer -Destination $install
  Assert-InstalledFiles -Destination $install
  Add-Pass -Step "install"

  Invoke-SidecarProbe -Path (Join-Path $install "runtime\reflex-runtime.exe")
  Add-Pass -Step "sidecar-ping-shutdown"

  $hostProbe = Invoke-HostProbe `
    -Path (Join-Path $install "Reflex.exe") `
    -ProfileRoot $profile `
    -TemporaryRoot $root
  Add-Pass -Step "host-start" -Details @{
    close_requested = $hostProbe.CloseRequested
    forced_termination = $hostProbe.ForcedTermination
    isolated_data_root = $hostProbe.IsolatedDataRoot
  }

  [System.IO.File]::WriteAllText($sentinel, "overlay-preserved")
  Invoke-SilentInstaller -Path $installer -Destination $install
  Assert-InstalledFiles -Destination $install
  if (-not (Test-Path -LiteralPath $sentinel -PathType Leaf)) {
    throw "overlay_sentinel_not_preserved"
  }
  Add-Pass -Step "overlay-install"

  Invoke-SilentUninstaller -Destination $install
  Assert-ProductFilesRemoved -Destination $install
  $sentinelPreserved = Test-Path -LiteralPath $sentinel -PathType Leaf
  Add-Pass -Step "uninstall" -Details @{ unknown_file_preserved = $sentinelPreserved }

  if ($sentinelPreserved) {
    Remove-Item -LiteralPath $sentinel -Force
  }
  Invoke-SilentInstaller -Path $installer -Destination $install
  Assert-InstalledFiles -Destination $install
  Add-Pass -Step "reinstall"

  Invoke-SilentUninstaller -Destination $install
  Assert-ProductFilesRemoved -Destination $install
  $remaining = @(Get-ChildItem -LiteralPath $install -Recurse -Force -File -ErrorAction SilentlyContinue)
  if ($remaining.Count -ne 0) {
    throw "final_install_directory_not_empty"
  }
  Add-Pass -Step "final-cleanup"

  $result = [PSCustomObject]@{
    status = "passed"
    installer = $installer
    work_root = $root
    steps = @($steps.ToArray())
  }
  Write-Output ("LIFECYCLE_RESULT=" + (ConvertTo-Json -InputObject $result -Compress -Depth 5))
}
catch {
  $result = [PSCustomObject]@{
    status = "failed"
    installer = $installer
    work_root = $root
    error = $_.Exception.Message
    steps = @($steps.ToArray())
  }
  Write-Output ("LIFECYCLE_RESULT=" + (ConvertTo-Json -InputObject $result -Compress -Depth 5))
  throw
}
finally {
  if ($ownedRoot -and -not $KeepWorkRoot -and (Test-Path -LiteralPath $root)) {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
  }
}
