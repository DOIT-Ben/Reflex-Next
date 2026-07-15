[CmdletBinding()]
param(
  [switch]$DryRun,
  [switch]$SkipDocker,
  [switch]$NoSync
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$cloudProject = Join-Path $root "services\reflex-cloud"
$contract = Join-Path $root "tools\tests\reflex_cloud_ops_contract.ps1"

function Invoke-Step {
  param(
    [string]$Name,
    [string]$WorkDir,
    [string]$Executable,
    [string[]]$Arguments,
    [switch]$Skip
  )

  $commandText = (@($Executable) + @($Arguments)) -join " "
  if ($Skip) {
    Write-Output "[SKIP] $Name"
    return
  }
  if ($DryRun) {
    Write-Output "[DRY-RUN] $Name | workdir=$WorkDir | command=$commandText"
    return
  }
  if (-not (Get-Command $Executable -ErrorAction SilentlyContinue)) {
    throw "Required command is unavailable: $Executable"
  }
  Push-Location -LiteralPath $WorkDir
  try {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
      throw "Cloud verification step failed with exit code ${LASTEXITCODE}: $Name"
    }
  }
  finally {
    Pop-Location
  }
  Write-Output "[PASS] $Name"
}

Invoke-Step -Name "cloud:operations-contract" -WorkDir $root -Executable "powershell" -Arguments @(
  "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $contract
)
$cloudTestArguments = @("run", "--frozen")
if ($NoSync) {
  $cloudTestArguments += "--no-sync"
}
$cloudTestArguments += @("--extra", "dev", "pytest", "-q")
Invoke-Step -Name "cloud:tests" -WorkDir $cloudProject -Executable "uv" -Arguments $cloudTestArguments

$composeArguments = @("compose", "--profile", "public", "-f", "services/reflex-cloud/docker-compose.yml", "config", "--quiet")
if ($SkipDocker) {
  Invoke-Step -Name "cloud:compose-config" -WorkDir $root -Executable "docker" -Arguments $composeArguments -Skip
}
elseif ($DryRun) {
  Invoke-Step -Name "cloud:compose-config" -WorkDir $root -Executable "docker" -Arguments $composeArguments
}
else {
  $names = @(
    "REFLEX_POSTGRES_PASSWORD",
    "REFLEX_CLOUD_ADMIN_TOKEN",
    "REFLEX_CLOUD_TOKEN_PEPPER",
    "REFLEX_CLOUD_PROVIDER_API_KEY",
    "REFLEX_CLOUD_PROVIDER_PRICING_VERSION",
    "REFLEX_CLOUD_PROVIDER_INPUT_USD_PER_MILLION_TOKENS",
    "REFLEX_CLOUD_PROVIDER_OUTPUT_USD_PER_MILLION_TOKENS",
    "REFLEX_CLOUD_GLOBAL_DAILY_REQUEST_LIMIT",
    "REFLEX_CLOUD_GLOBAL_DAILY_COST_BUDGET_MICROUSD"
  )
  $oldValues = @{}
  try {
    foreach ($name in $names) {
      $oldValues[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
      [Environment]::SetEnvironmentVariable($name, ("contract-" + $name.ToLowerInvariant()).PadRight(32, "x"), "Process")
    }
    Invoke-Step -Name "cloud:compose-config" -WorkDir $root -Executable "docker" -Arguments $composeArguments
  }
  finally {
    foreach ($name in $names) {
      [Environment]::SetEnvironmentVariable($name, $oldValues[$name], "Process")
    }
  }
}

Write-Output "Reflex Cloud verification passed."
