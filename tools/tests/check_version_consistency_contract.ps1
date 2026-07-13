$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$checkScript = Join-Path $root "tools\check_version_consistency.ps1"

function Assert-True {
  param(
    [bool]$Condition,
    [string]$Message
  )

  if (-not $Condition) {
    throw $Message
  }
}

function Write-Utf8NoBom {
  param(
    [string]$Path,
    [string]$Content
  )

  $parent = Split-Path -Parent $Path
  New-Item -ItemType Directory -Path $parent -Force | Out-Null
  [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
}

function New-VersionFixture {
  param(
    [string]$Path,
    [string]$Version = "1.2.3-beta.4"
  )

  New-Item -ItemType Directory -Path $Path -Force | Out-Null
  Write-Utf8NoBom -Path (Join-Path $Path "apps\tauri-host\package.json") -Content (@{
      name = "@reflex-next/tauri-host"
      version = $Version
      private = $true
    } | ConvertTo-Json)
  Write-Utf8NoBom -Path (Join-Path $Path "apps\tauri-host\src-tauri\tauri.conf.json") -Content (@{
      productName = "Reflex"
      version = $Version
      identifier = "com.reflex.next"
    } | ConvertTo-Json)
  Write-Utf8NoBom -Path (Join-Path $Path "apps\tauri-host\src-tauri\Cargo.toml") -Content @"
[package]
name = "reflex-next-tauri-host"
version = "$Version"

[dependencies]
example = { version = "99.0.0" }
"@
  foreach ($package in @("reflex-core", "reflex-runtime")) {
    Write-Utf8NoBom -Path (Join-Path $Path "packages\$package\pyproject.toml") -Content @"
[build-system]
requires = ["setuptools>=68"]

[project]
name = "$package"
version = "$Version"

[project.optional-dependencies]
dev = ["pytest>=99"]
"@
  }

  # Independent workspace plugins intentionally have their own release cadence.
  Write-Utf8NoBom -Path (Join-Path $Path "plugins\example\pyproject.toml") -Content @"
[project]
name = "reflex-plugin-example"
version = "9.8.7"
"@

  & git -C $Path init --quiet
  & git -C $Path config user.email "version-contract@example.invalid"
  & git -C $Path config user.name "Version Contract"
  & git -C $Path config core.autocrlf false
  & git -C $Path add -- .
  & git -C $Path commit --quiet -m "fixture"
  & git -C $Path tag ("v" + $Version)
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to initialize Git fixture."
  }
}

function Invoke-Check {
  param(
    [string]$FixtureRoot,
    [string]$ScriptPath = $checkScript,
    [switch]$OmitRoot,
    [switch]$RequireTag
  )

  $output = @()
  try {
    $arguments = @{}
    if ($RequireTag) {
      $arguments.RequireTag = $true
    }
    if ($OmitRoot) {
      $output += @(& $ScriptPath @arguments)
    }
    else {
      $arguments.Root = $FixtureRoot
      $output += @(& $ScriptPath @arguments)
    }
    $exitCode = 0
  }
  catch {
    $output += $_.Exception.Message
    $exitCode = 1
  }

  return [PSCustomObject]@{
    ExitCode = $exitCode
    Output = @($output | ForEach-Object { $_.ToString() })
  }
}

function Set-JsonVersion {
  param(
    [string]$Path,
    [string]$Version
  )

  $value = Get-Content -Raw -Encoding UTF8 -LiteralPath $Path | ConvertFrom-Json
  $value.version = $Version
  Write-Utf8NoBom -Path $Path -Content ($value | ConvertTo-Json -Depth 10)
}

function Set-TomlSectionVersion {
  param(
    [string]$Path,
    [string]$Section,
    [string]$Version
  )

  $content = Get-Content -Raw -Encoding UTF8 -LiteralPath $Path
  $pattern = '(?ms)(^\[' + [regex]::Escape($Section) + '\]\s*.*?^version\s*=\s*")[^"]+(?=")'
  $updated = [regex]::Replace($content, $pattern, ('$1' + $Version), 1)
  Write-Utf8NoBom -Path $Path -Content $updated
}

Assert-True (Test-Path -LiteralPath $checkScript -PathType Leaf) "tools\check_version_consistency.ps1 is missing."

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("reflex-version-contract-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
  $consistentRoot = Join-Path $tempRoot "consistent"
  New-VersionFixture -Path $consistentRoot
  $consistent = Invoke-Check -FixtureRoot $consistentRoot
  Assert-True ($consistent.ExitCode -eq 0) "A consistent release fixture must pass. Output: $($consistent.Output -join ' | ')"
  Assert-True (($consistent.Output | Where-Object { $_ -eq "Version consistency check passed: 1.2.3-beta.4" }).Count -eq 1) "Success output must report the common release version."

  $fixtureScript = Join-Path $consistentRoot "tools\check_version_consistency.ps1"
  New-Item -ItemType Directory -Path (Split-Path -Parent $fixtureScript) -Force | Out-Null
  Copy-Item -LiteralPath $checkScript -Destination $fixtureScript
  $defaultRoot = Invoke-Check -FixtureRoot $consistentRoot -ScriptPath $fixtureScript -OmitRoot
  Assert-True ($defaultRoot.ExitCode -eq 0) "Without -Root, the checker must resolve the repository from its own tools directory. Output: $($defaultRoot.Output -join ' | ')"

  Set-TomlSectionVersion -Path (Join-Path $consistentRoot "plugins\example\pyproject.toml") -Section "project" -Version "7.7.7"
  $independentPlugin = Invoke-Check -FixtureRoot $consistentRoot
  Assert-True ($independentPlugin.ExitCode -eq 0) "Independent plugin package versions must not be compared with the product release."

  $mismatchCases = @(
    @{ Path = "apps\tauri-host\src-tauri\tauri.conf.json"; Kind = "json"; Label = "Tauri" },
    @{ Path = "apps\tauri-host\src-tauri\Cargo.toml"; Kind = "toml"; Section = "package"; Label = "Cargo" },
    @{ Path = "apps\tauri-host\package.json"; Kind = "json"; Label = "npm" },
    @{ Path = "packages\reflex-core\pyproject.toml"; Kind = "toml"; Section = "project"; Label = "Python reflex-core" },
    @{ Path = "packages\reflex-runtime\pyproject.toml"; Kind = "toml"; Section = "project"; Label = "Python reflex-runtime" }
  )
  foreach ($case in $mismatchCases) {
    $manifestPath = Join-Path $consistentRoot $case.Path
    $originalContent = Get-Content -Raw -Encoding UTF8 -LiteralPath $manifestPath
    if ($case.Kind -eq "json") {
      Set-JsonVersion -Path $manifestPath -Version "1.2.4"
    }
    else {
      Set-TomlSectionVersion -Path $manifestPath -Section $case.Section -Version "1.2.4"
    }
    $result = Invoke-Check -FixtureRoot $consistentRoot
    Write-Utf8NoBom -Path $manifestPath -Content $originalContent
    Assert-True ($result.ExitCode -ne 0) "$($case.Label) version drift must fail."
    Assert-True (($result.Output | Where-Object { $_ -match [regex]::Escape($case.Label) }).Count -gt 0) "$($case.Label) failure must identify the drifting source."
  }

  & git -C $consistentRoot tag -d "v1.2.3-beta.4" | Out-Null
  & git -C $consistentRoot tag "v1.2.4"
  $gitMismatch = Invoke-Check -FixtureRoot $consistentRoot
  & git -C $consistentRoot tag -d "v1.2.4" | Out-Null
  & git -C $consistentRoot tag "v1.2.3-beta.4"
  Assert-True ($gitMismatch.ExitCode -ne 0) "A Git release tag that differs from manifests must fail."
  Assert-True (($gitMismatch.Output | Where-Object { $_ -match 'Git release tag' }).Count -gt 0) "Git mismatch output must identify the release tag."

  & git -C $consistentRoot tag "v1.2.4"
  $multipleTags = Invoke-Check -FixtureRoot $consistentRoot
  & git -C $consistentRoot tag -d "v1.2.4" | Out-Null
  Assert-True ($multipleTags.ExitCode -ne 0) "Multiple release tags at HEAD must always fail."
  Assert-True (($multipleTags.Output | Where-Object { $_ -match 'multiple release tags' }).Count -gt 0) "Multiple-tag failure must explain the ambiguity."

  & git -C $consistentRoot tag -d "v1.2.3-beta.4" | Out-Null
  $untaggedDefault = Invoke-Check -FixtureRoot $consistentRoot
  $untaggedRequired = Invoke-Check -FixtureRoot $consistentRoot -RequireTag
  & git -C $consistentRoot tag "v1.2.3-beta.4"
  Assert-True ($untaggedDefault.ExitCode -eq 0) "An untagged HEAD must pass by default when product manifests agree. Output: $($untaggedDefault.Output -join ' | ')"
  Assert-True (($untaggedDefault.Output | Where-Object { $_ -eq "Version consistency check passed: 1.2.3-beta.4" }).Count -eq 1) "Untagged default mode must report the manifest baseline version."
  Assert-True ($untaggedRequired.ExitCode -ne 0) "-RequireTag must reject an untagged HEAD."
  Assert-True (($untaggedRequired.Output | Where-Object { $_ -match 'HEAD.*release tag' }).Count -gt 0) "-RequireTag failure must explain the missing HEAD release tag."

  $runtimeManifest = Join-Path $consistentRoot "packages\reflex-runtime\pyproject.toml"
  $runtimeContent = Get-Content -Raw -Encoding UTF8 -LiteralPath $runtimeManifest
  Remove-Item -LiteralPath $runtimeManifest -Force
  $missing = Invoke-Check -FixtureRoot $consistentRoot
  Write-Utf8NoBom -Path $runtimeManifest -Content $runtimeContent
  Assert-True ($missing.ExitCode -ne 0) "A missing product version manifest must fail."
  Assert-True (($missing.Output | Where-Object { $_ -match 'reflex-runtime' }).Count -gt 0) "Missing manifest output must identify reflex-runtime."
}
finally {
  Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Output "check_version_consistency contract checks passed."
