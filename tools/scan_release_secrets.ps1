[CmdletBinding()]
param(
  [string]$RepositoryRoot = "",
  [string[]]$ReleasePath = @(),
  [switch]$SkipTrackedFiles
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
  $RepositoryRoot = Join-Path $PSScriptRoot ".."
}

try {
  $repository = (Resolve-Path -LiteralPath $RepositoryRoot -ErrorAction Stop).Path
}
catch {
  Write-Error "Repository root does not exist."
  exit 2
}

if (-not (Test-Path -LiteralPath $repository -PathType Container)) {
  Write-Error "Repository root is not a directory."
  exit 2
}

$regexOptions = [System.Text.RegularExpressions.RegexOptions]::IgnoreCase -bor
  [System.Text.RegularExpressions.RegexOptions]::CultureInvariant
$binaryStringRegex = New-Object System.Text.RegularExpressions.Regex(
  '[\x20-\x7E]+',
  [System.Text.RegularExpressions.RegexOptions]::CultureInvariant
)
$binarySeparatorRegex = New-Object System.Text.RegularExpressions.Regex(
  '[^\x20-\x7E]+',
  [System.Text.RegularExpressions.RegexOptions]::CultureInvariant
)
$binaryTrailingStringRegex = New-Object System.Text.RegularExpressions.Regex(
  '[\x20-\x7E]+$',
  [System.Text.RegularExpressions.RegexOptions]::CultureInvariant
)

function New-SecretRule {
  param(
    [string]$Name,
    [string]$Pattern,
    [int]$CaptureGroup = 0,
    [bool]$RequireEntropy = $false,
    [bool]$CheckPlaceholder = $true
  )

  return [PSCustomObject]@{
    Name = $Name
    Regex = New-Object System.Text.RegularExpressions.Regex($Pattern, $script:regexOptions)
    CaptureGroup = $CaptureGroup
    RequireEntropy = $RequireEntropy
    CheckPlaceholder = $CheckPlaceholder
  }
}

$contentRules = @(
  New-SecretRule -Name "private-key" -Pattern '-----BEGIN\s+(?:(?:RSA|EC|DSA|OPENSSH|ENCRYPTED)\s+|PGP\s+)?PRIVATE\s+KEY(?:\s+BLOCK)?-----' -CheckPlaceholder $false
  New-SecretRule -Name "provider-api-key" -Pattern '\bsk-(?:(?:cp|proj|ant)-[A-Za-z0-9_-]{16,}|[A-Za-z0-9]{32,})\b'
  New-SecretRule -Name "aws-access-key" -Pattern '\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'
  New-SecretRule -Name "github-token" -Pattern '\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b'
  New-SecretRule -Name "slack-token" -Pattern '\bxox[baprs]-[A-Za-z0-9-]{20,}\b'
  New-SecretRule -Name "google-api-key" -Pattern '\bAIza[0-9A-Za-z_-]{35}\b'
  New-SecretRule -Name "stripe-live-key" -Pattern '\b(?:sk|rk)_live_[0-9A-Za-z]{20,}\b'
  New-SecretRule -Name "authorization-token" -Pattern '\bBearer\s+([A-Za-z0-9._~+/=-]{20,})' -CaptureGroup 1
  New-SecretRule -Name "jwt-token" -Pattern '\b(eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b' -CaptureGroup 1
  New-SecretRule -Name "credential-url" -Pattern '://[^\s:/@]+:([^\s/@]{12,})@' -CaptureGroup 1 -RequireEntropy $true
  New-SecretRule -Name "credential-assignment" -Pattern '(?:^|[\s{,])["'']?[A-Za-z0-9_.-]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|secret[_-]?key|password|passwd|pwd)[A-Za-z0-9_.-]*["'']?\s*(?:=|:)\s*["'']?([^\s"'',;}\]]{16,})' -CaptureGroup 1 -RequireEntropy $true
)

$placeholderMarkers = @(
  "your_api",
  "your-api",
  "your.key",
  "example",
  "sample",
  "dummy",
  "fake-token",
  "fake_key",
  "fixture",
  "placeholder",
  "redacted",
  "masked",
  "replace-me",
  "replace_me",
  "changeme",
  "change-me",
  "not-a-real",
  "not_real",
  "insert-key",
  "insert_key",
  "sk-test-",
  "test-token",
  "test_token",
  '${'
)

function Test-PlaceholderValue {
  param([string]$Value)

  $normalized = $Value.Trim().Trim('"', "'").ToLowerInvariant()
  foreach ($marker in $script:placeholderMarkers) {
    if ($normalized.Contains($marker)) {
      return $true
    }
  }

  if ($normalized -match '^(?:x+|\*+|0+|1+|-+|_+)$') {
    return $true
  }
  return $false
}

function Test-HighEntropyValue {
  param([string]$Value)

  $normalized = $Value.Trim().Trim('"', "'")
  if ($normalized.Length -lt 16) {
    return $false
  }

  $classes = 0
  if ($normalized -cmatch '[a-z]') { $classes++ }
  if ($normalized -cmatch '[A-Z]') { $classes++ }
  if ($normalized -match '[0-9]') { $classes++ }
  if ($normalized -match '[^A-Za-z0-9]') { $classes++ }
  if ($classes -lt 2) {
    return $false
  }

  $distinct = @($normalized.ToCharArray() | Sort-Object -Unique).Count
  return $distinct -ge 6
}

$findings = New-Object System.Collections.ArrayList
$findingKeys = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)

function Add-Finding {
  param(
    [string]$DisplayPath,
    [int]$LineNumber,
    [string]$Rule
  )

  $key = "${DisplayPath}`0${LineNumber}`0${Rule}"
  if ($script:findingKeys.Add($key)) {
    [void]$script:findings.Add([PSCustomObject]@{
      Path = $DisplayPath
      Line = $LineNumber
      Rule = $Rule
    })
  }
}

function Test-CredentialFileName {
  param([string]$Path)

  $leaf = [System.IO.Path]::GetFileName($Path).ToLowerInvariant()
  if ($leaf -match '^\.env(?:\..+)?$') {
    return $leaf -notmatch '^\.env\.(?:example|sample|template|dist)$'
  }

  if ($leaf -match '^(?:credentials\.json|service-account(?:-key)?\.json|id_rsa|id_ed25519|\.netrc)$') {
    return $true
  }

  $extension = [System.IO.Path]::GetExtension($leaf)
  return $extension -in @(".p12", ".pfx", ".key", ".jks", ".keystore")
}

function Invoke-ContentRules {
  param(
    [string]$Content,
    [string]$DisplayPath,
    [int]$LineNumber
  )

  foreach ($rule in $script:contentRules) {
    foreach ($match in $rule.Regex.Matches($Content)) {
      $value = $match.Groups[$rule.CaptureGroup].Value
      if ($rule.CheckPlaceholder -and (Test-PlaceholderValue -Value $value)) {
        continue
      }
      if ($rule.RequireEntropy -and -not (Test-HighEntropyValue -Value $value)) {
        continue
      }

      Add-Finding -DisplayPath $DisplayPath -LineNumber $LineNumber -Rule $rule.Name
      break
    }
  }
}

function Get-FileProbe {
  param([string]$Path)

  $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
  try {
    $buffer = New-Object byte[] 8192
    $count = $stream.Read($buffer, 0, $buffer.Length)
  }
  finally {
    $stream.Dispose()
  }

  $encoding = New-Object System.Text.UTF8Encoding($false, $true)
  $isText = $true
  if ($count -ge 3 -and $buffer[0] -eq 0xEF -and $buffer[1] -eq 0xBB -and $buffer[2] -eq 0xBF) {
    $encoding = New-Object System.Text.UTF8Encoding($true, $true)
  }
  elseif ($count -ge 2 -and $buffer[0] -eq 0xFF -and $buffer[1] -eq 0xFE) {
    $encoding = [System.Text.Encoding]::Unicode
  }
  elseif ($count -ge 2 -and $buffer[0] -eq 0xFE -and $buffer[1] -eq 0xFF) {
    $encoding = [System.Text.Encoding]::BigEndianUnicode
  }
  else {
    for ($index = 0; $index -lt $count; $index++) {
      if ($buffer[$index] -eq 0) {
        $isText = $false
        break
      }
    }
  }

  return [PSCustomObject]@{
    IsText = $isText
    Encoding = $encoding
  }
}

function Scan-TextFile {
  param(
    [string]$Path,
    [string]$DisplayPath,
    [System.Text.Encoding]$Encoding
  )

  $reader = New-Object System.IO.StreamReader($Path, $Encoding, $true)
  try {
    $lineNumber = 0
    while (-not $reader.EndOfStream) {
      $line = $reader.ReadLine()
      $lineNumber++
      Invoke-ContentRules -Content $line -DisplayPath $DisplayPath -LineNumber $lineNumber
    }
  }
  finally {
    $reader.Dispose()
  }
}

function Scan-BinaryFile {
  param(
    [string]$Path,
    [string]$DisplayPath
  )

  $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
  try {
    $buffer = New-Object byte[] 65536
    $carry = ""
    $singleByteEncoding = [System.Text.Encoding]::GetEncoding(28591)
    while (($count = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
      $chunk = $carry + $singleByteEncoding.GetString($buffer, 0, $count)
      $scanChunk = $script:binarySeparatorRegex.Replace($chunk, "`n")
      Invoke-ContentRules -Content $scanChunk -DisplayPath $DisplayPath -LineNumber 0

      $carry = ""
      $trailingRun = $script:binaryTrailingStringRegex.Match($chunk)
      if ($trailingRun.Success -and ($trailingRun.Index + $trailingRun.Length) -eq $chunk.Length) {
        $carry = $trailingRun.Value
        if ($carry.Length -gt 512) {
          $carry = $carry.Substring($carry.Length - 512)
        }
      }
    }
  }
  finally {
    $stream.Dispose()
  }
}

function Scan-File {
  param(
    [string]$Path,
    [string]$DisplayPath
  )

  if (Test-CredentialFileName -Path $Path) {
    Add-Finding -DisplayPath $DisplayPath -LineNumber 0 -Rule "credential-file"
  }

  try {
    $probe = Get-FileProbe -Path $Path
    if ($probe.IsText) {
      Scan-TextFile -Path $Path -DisplayPath $DisplayPath -Encoding $probe.Encoding
    }
    else {
      Scan-BinaryFile -Path $Path -DisplayPath $DisplayPath
    }
  }
  catch {
    Add-Finding -DisplayPath $DisplayPath -LineNumber 0 -Rule "unreadable-file"
  }
}

function Get-ReleaseDisplayPath {
  param(
    [string]$ReleaseRoot,
    [System.IO.FileInfo]$File
  )

  if (Test-Path -LiteralPath $ReleaseRoot -PathType Leaf) {
    return $File.Name
  }

  $rootPrefix = $ReleaseRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar) +
    [System.IO.Path]::DirectorySeparatorChar
  return $File.FullName.Substring($rootPrefix.Length) -replace '/', '\'
}

if (-not $SkipTrackedFiles) {
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "git is required to enumerate tracked files."
    exit 2
  }

  $trackedPaths = @(& git -C $repository -c core.quotepath=false ls-files 2>$null)
  if ($LASTEXITCODE -ne 0) {
    Write-Error "Unable to enumerate tracked files."
    exit 2
  }

  foreach ($relativePath in $trackedPaths) {
    if ([string]::IsNullOrWhiteSpace($relativePath)) {
      continue
    }
    $fullPath = Join-Path $repository $relativePath
    if (Test-Path -LiteralPath $fullPath -PathType Leaf) {
      Scan-File -Path $fullPath -DisplayPath ($relativePath -replace '/', '\')
    }
  }
}

$visitedReleaseFiles = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
foreach ($requestedPath in $ReleasePath) {
  try {
    $resolvedPath = (Resolve-Path -LiteralPath $requestedPath -ErrorAction Stop).Path
  }
  catch {
    Write-Error "Release path does not exist."
    exit 2
  }

  if (Test-Path -LiteralPath $resolvedPath -PathType Leaf) {
    $releaseFiles = @(Get-Item -LiteralPath $resolvedPath -Force)
  }
  else {
    $releaseFiles = @(Get-ChildItem -LiteralPath $resolvedPath -File -Recurse -Force -ErrorAction Stop)
  }

  foreach ($file in $releaseFiles) {
    if ($visitedReleaseFiles.Add($file.FullName)) {
      $displayPath = Get-ReleaseDisplayPath -ReleaseRoot $resolvedPath -File $file
      Scan-File -Path $file.FullName -DisplayPath $displayPath
    }
  }
}

foreach ($finding in @($findings | Sort-Object Path, Line, Rule)) {
  $location = $finding.Path
  if ($finding.Line -gt 0) {
    $location = "${location}:$($finding.Line)"
  }
  Write-Output ("{0} | rule={1}" -f $location, $finding.Rule)
}

if ($findings.Count -gt 0) {
  exit 1
}
exit 0
