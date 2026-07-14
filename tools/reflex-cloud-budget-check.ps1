[CmdletBinding()]
param(
  [string]$BaseUrl = "",
  [string]$AnalyticsFile = "",
  [ValidateRange(1, 99)]
  [int]$WarningPercent = 80,
  [ValidateRange(2, 100)]
  [int]$CriticalPercent = 100,
  [ValidateRange(1, 120)]
  [int]$TimeoutSeconds = 10
)

$ErrorActionPreference = "Stop"

if ($WarningPercent -ge $CriticalPercent) {
  throw "WarningPercent must be lower than CriticalPercent."
}

if ($AnalyticsFile) {
  $analyticsPath = (Resolve-Path -LiteralPath $AnalyticsFile).Path
  $analytics = Get-Content -LiteralPath $analyticsPath -Raw -Encoding UTF8 | ConvertFrom-Json
}
else {
  if (-not $BaseUrl) {
    $BaseUrl = $env:REFLEX_CLOUD_BASE_URL
  }
  if (-not $BaseUrl) {
    throw "BaseUrl or REFLEX_CLOUD_BASE_URL is required."
  }
  $adminToken = $env:REFLEX_CLOUD_ADMIN_TOKEN
  if (-not $adminToken) {
    throw "REFLEX_CLOUD_ADMIN_TOKEN is required."
  }
  $uri = [uri]$BaseUrl
  $loopbackHosts = @("localhost", "127.0.0.1", "::1")
  if ($uri.Scheme -ne "https" -and $loopbackHosts -notcontains $uri.Host) {
    throw "Remote budget checks require HTTPS."
  }
  $endpoint = $BaseUrl.TrimEnd("/") + "/v1/admin/analytics/usage?days=1"
  $analytics = Invoke-RestMethod `
    -Uri $endpoint `
    -Method Get `
    -Headers @{ Authorization = "Bearer $adminToken" } `
    -TimeoutSec $TimeoutSeconds
}

$ratios = @()
foreach ($name in @("daily_request_usage_ratio", "daily_cost_usage_ratio")) {
  $value = $analytics.$name
  if ($null -ne $value) {
    $ratio = [double]$value
    if ($ratio -lt 0) {
      throw "Budget analytics contain a negative usage ratio."
    }
    $ratios += $ratio
  }
}
if ($ratios.Count -eq 0) {
  throw "Budget analytics are disabled or incomplete."
}

$usageRatio = ($ratios | Measure-Object -Maximum).Maximum
$usagePercent = [Math]::Round($usageRatio * 100, 2)
$status = "ok"
$exitCode = 0
if ($analytics.budget_exceeded -eq $true -or $usagePercent -ge $CriticalPercent) {
  $status = "critical"
  $exitCode = 2
}
elseif ($usagePercent -ge $WarningPercent) {
  $status = "warning"
  $exitCode = 1
}

$result = [ordered]@{
  schema_version = 1
  status = $status
  budget_date = [string]$analytics.daily_budget_date
  usage_percent = $usagePercent
  requests_remaining = $analytics.daily_requests_remaining
  cost_remaining_microusd = $analytics.daily_cost_remaining_microusd
}
Write-Output ($result | ConvertTo-Json -Compress)
exit $exitCode
