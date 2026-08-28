[CmdletBinding()]
param(
  [string]$RepositoryRoot = "",
  [string]$PolicyPath = "",
  [string]$FixtureDirectory = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
  $RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
else {
  $RepositoryRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
}

. (Join-Path $PSScriptRoot "project_registry.ps1")

if ([string]::IsNullOrWhiteSpace($PolicyPath)) {
  $PolicyPath = Join-Path $PSScriptRoot "policies\dependency-audit-policy.json"
}

function ConvertFrom-StrictJson {
  param(
    [string]$Content,
    [string]$Label
  )

  if ([string]::IsNullOrWhiteSpace($Content)) {
    throw "empty_json:$Label"
  }
  try {
    return ($Content | ConvertFrom-Json)
  }
  catch {
    throw "invalid_json:$Label"
  }
}

function Read-JsonFile {
  param(
    [string]$Path,
    [string]$Label
  )

  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "missing_input:$Label"
  }
  return ConvertFrom-StrictJson -Content ([System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)) -Label $Label
}

function Invoke-CapturedCommand {
  param(
    [string]$Executable,
    [string[]]$Arguments,
    [string]$WorkDir
  )

  if (-not (Get-Command $Executable -ErrorAction SilentlyContinue)) {
    throw "missing_tool:$Executable"
  }

  $stderrPath = Join-Path ([System.IO.Path]::GetTempPath()) ("reflex-dependency-audit-stderr-" + [guid]::NewGuid().ToString("N") + ".txt")
  $pushed = $false
  $previousErrorActionPreference = $ErrorActionPreference
  try {
    Push-Location -LiteralPath $WorkDir
    $pushed = $true
    $ErrorActionPreference = "Continue"
    $stdout = @(& $Executable @Arguments 2> $stderrPath)
    $exitCode = $LASTEXITCODE
  }
  finally {
    $ErrorActionPreference = $previousErrorActionPreference
    if ($pushed) {
      Pop-Location
    }
    Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
  }

  return [PSCustomObject]@{
    ExitCode = $exitCode
    Stdout = ($stdout | ForEach-Object { $_.ToString() }) -join "`n"
  }
}

function Assert-ToolVersion {
  param(
    [string]$Executable,
    [string[]]$Arguments,
    [string]$ExpectedVersion,
    [string]$WorkDir
  )

  $result = Invoke-CapturedCommand -Executable $Executable -Arguments $Arguments -WorkDir $WorkDir
  if ($result.ExitCode -ne 0 -or $result.Stdout -notmatch ("(?<![0-9])" + [regex]::Escape($ExpectedVersion) + "(?![0-9])")) {
    throw "tool_version_mismatch:$Executable"
  }
}

function Get-RustAuditExceptionArguments {
  param(
    [object]$Policy,
    [string]$WorkDir
  )

  $arguments = [System.Collections.Generic.List[string]]::new()
  foreach ($exception in @($Policy.rust_advisory_exceptions)) {
    $id = [string]$exception.id
    $package = [string]$exception.package
    $version = [string]$exception.version
    $scope = [string]$exception.scope
    $expiresOn = [string]$exception.expires_on
    if ($id -notmatch '^RUSTSEC-[0-9]{4}-[0-9]{4}$' -or
        $package -notmatch '^[a-z0-9_-]{1,64}$' -or
        $version -notmatch '^[0-9A-Za-z.+-]{1,64}$' -or
        $scope -ne 'non-windows-transitive-only' -or
        $expiresOn -notmatch '^[0-9]{4}-[0-9]{2}-[0-9]{2}$') {
      throw "invalid_rust_advisory_exception"
    }
    try {
      $expiry = [DateTime]::ParseExact(
        $expiresOn,
        "yyyy-MM-dd",
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AssumeUniversal
      )
    }
    catch {
      throw "invalid_rust_advisory_exception_expiry"
    }
    if ($expiry.Date -lt [DateTime]::UtcNow.Date) {
      throw "expired_rust_advisory_exception"
    }

    $packageSpec = "$package@$version"
    $allTargets = Invoke-CapturedCommand -Executable "cargo" -Arguments @("tree", "--target", "all", "-i", $packageSpec) -WorkDir $WorkDir
    if ($allTargets.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($allTargets.Stdout)) {
      throw "stale_rust_advisory_exception"
    }
    $windowsTarget = Invoke-CapturedCommand -Executable "cargo" -Arguments @("tree", "-i", $packageSpec) -WorkDir $WorkDir
    if ($windowsTarget.ExitCode -ne 0 -or -not [string]::IsNullOrWhiteSpace($windowsTarget.Stdout)) {
      throw "unsafe_rust_advisory_exception"
    }
    $arguments.Add("--ignore")
    $arguments.Add($id)
  }
  return $arguments.ToArray()
}

function ConvertTo-SafeIdentifier {
  param(
    [object]$Value,
    [string]$Fallback = "unknown"
  )

  $text = [string]$Value
  if ($text -match '^[A-Za-z0-9_.@/+-]{1,120}$') {
    return $text
  }
  return $Fallback
}

function Add-VulnerabilityFinding {
  param(
    [System.Collections.Generic.List[object]]$Findings,
    [string]$Ecosystem,
    [object]$Package,
    [object]$Advisory
  )

  $Findings.Add([PSCustomObject]@{
    Category = "vulnerability"
    Ecosystem = $Ecosystem
    Package = ConvertTo-SafeIdentifier -Value $Package
    Detail = ConvertTo-SafeIdentifier -Value $Advisory -Fallback "advisory"
  })
}

function Test-InternalPackage {
  param(
    [string]$Name,
    [object]$Policy
  )

  foreach ($prefix in @($Policy.licenses.ignore_internal_package_prefixes)) {
    if ($Name.StartsWith([string]$prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
      return $true
    }
  }
  return $false
}

function Add-LicenseFinding {
  param(
    [System.Collections.Generic.List[object]]$Findings,
    [System.Collections.Generic.List[object]]$ToolFailures,
    [string]$Ecosystem,
    [object]$Package,
    [object]$Version,
    [object]$License,
    [object]$Policy
  )

  $packageName = [string]$Package
  if (Test-InternalPackage -Name $packageName -Policy $Policy) {
    return
  }

  $versionText = [string]$Version
  $overrideKey = ($packageName.ToLowerInvariant() + "@" + $versionText)
  $overrideProperty = @($Policy.licenses.package_overrides.$Ecosystem.PSObject.Properties | Where-Object { $_.Name.Equals($overrideKey, [System.StringComparison]::OrdinalIgnoreCase) }) | Select-Object -First 1
  $licenseText = if ($overrideProperty) { ([string]$overrideProperty.Value).Trim() } else { ([string]$License).Trim() }
  $unknown = @($Policy.licenses.unknown_markers) | Where-Object { $licenseText.Equals([string]$_, [System.StringComparison]::OrdinalIgnoreCase) }
  if ($unknown.Count -gt 0) {
    $Findings.Add([PSCustomObject]@{
      Category = "forbidden_license"
      Ecosystem = $Ecosystem
      Package = ConvertTo-SafeIdentifier -Value $packageName
      Detail = "unknown"
    })
    return
  }

  foreach ($pattern in @($Policy.licenses.forbidden_patterns)) {
    if ($licenseText -match [string]$pattern) {
      $Findings.Add([PSCustomObject]@{
        Category = "forbidden_license"
        Ecosystem = $Ecosystem
        Package = ConvertTo-SafeIdentifier -Value $packageName
        Detail = "policy_match"
      })
      return
    }
  }

  $allowed = @($Policy.licenses.allowed_expressions.$Ecosystem) | Where-Object { $licenseText.Equals([string]$_, [System.StringComparison]::Ordinal) }
  if ($allowed.Count -eq 0) {
    $Findings.Add([PSCustomObject]@{
      Category = "forbidden_license"
      Ecosystem = $Ecosystem
      Package = ConvertTo-SafeIdentifier -Value $packageName
      Detail = "unclassified"
    })
  }
}

function Read-FixtureInputs {
  param([string]$Directory)

  return [PSCustomObject]@{
    PythonVulnerabilities = Read-JsonFile -Path (Join-Path $Directory "python-vulnerabilities.json") -Label "python-vulnerabilities"
    PythonLicenses = Read-JsonFile -Path (Join-Path $Directory "python-licenses.json") -Label "python-licenses"
    RustVulnerabilities = Read-JsonFile -Path (Join-Path $Directory "rust-vulnerabilities.json") -Label "rust-vulnerabilities"
    RustLicenses = Read-JsonFile -Path (Join-Path $Directory "rust-licenses.json") -Label "rust-licenses"
    NpmVulnerabilities = Read-JsonFile -Path (Join-Path $Directory "npm-vulnerabilities.json") -Label "npm-vulnerabilities"
    NpmLicenses = Read-JsonFile -Path (Join-Path $Directory "npm-licenses.json") -Label "npm-licenses"
  }
}

function Invoke-LiveInputs {
  param(
    [string]$Root,
    [object]$Policy,
    [object]$Registry
  )

  Assert-ToolVersion -Executable "cargo" -Arguments @("audit", "--version") -ExpectedVersion ([string]$Policy.tools.cargo_audit) -WorkDir $Root
  Assert-ToolVersion -Executable "cargo" -Arguments @("install", "--list") -ExpectedVersion ([string]$Policy.tools.cargo_license) -WorkDir $Root
  Assert-ToolVersion -Executable "npx" -Arguments @("--yes", ("npm@" + [string]$Policy.tools.npm), "--version") -ExpectedVersion ([string]$Policy.tools.npm) -WorkDir $Root

  $pythonVulnerabilities = [System.Collections.Generic.List[object]]::new()
  $pythonLicenses = [System.Collections.Generic.List[object]]::new()
  $pythonProjects = @($Registry.projects | Where-Object {
      $_.kind -eq "python" -and $_.verify -eq $true
    })
  foreach ($project in $pythonProjects) {
    $relativeProject = ([string]$project.path).Replace("/", "\")
    $projectPath = Join-Path $Root $relativeProject
    if (-not (Test-Path -LiteralPath (Join-Path $projectPath "uv.lock") -PathType Leaf)) {
      throw "missing_lock:python"
    }

    $sync = Invoke-CapturedCommand -Executable "uv" -Arguments @("sync", "--frozen", "--no-dev") -WorkDir $projectPath
    if ($sync.ExitCode -ne 0) {
      throw "tool_failed:uv_sync"
    }
    $python = Invoke-CapturedCommand -Executable "uv" -Arguments @("run", "--frozen", "--no-dev", "python", "-c", "import sys; print(sys.executable)") -WorkDir $projectPath
    if ($python.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($python.Stdout)) {
      throw "tool_failed:uv_python"
    }
    $pythonPath = ($python.Stdout -split "`n")[-1].Trim()
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
      throw "invalid_python_path"
    }
    $site = Invoke-CapturedCommand -Executable $pythonPath -Arguments @("-c", "import json,site; print(json.dumps(site.getsitepackages()))") -WorkDir $projectPath
    if ($site.ExitCode -ne 0) {
      throw "tool_failed:python_site"
    }
    $sitePaths = @(ConvertFrom-StrictJson -Content $site.Stdout -Label "python-site")

    $auditArguments = @("--from", ("pip-audit==" + [string]$Policy.tools.pip_audit), "pip-audit", "--format", "json", "--progress-spinner", "off", "--desc", "off", "--aliases", "off")
    foreach ($sitePath in $sitePaths) {
      $auditArguments += @("--path", [string]$sitePath)
    }
    $audit = Invoke-CapturedCommand -Executable "uvx" -Arguments $auditArguments -WorkDir $projectPath
    $auditJson = ConvertFrom-StrictJson -Content $audit.Stdout -Label "python-vulnerabilities"
    if ($audit.ExitCode -ne 0 -and @($auditJson.dependencies | ForEach-Object { @($_.vulns) }).Count -eq 0) {
      throw "tool_failed:pip_audit"
    }
    foreach ($dependency in @($auditJson.dependencies)) {
      $pythonVulnerabilities.Add($dependency)
    }

    $licenses = Invoke-CapturedCommand -Executable "uvx" -Arguments @("--from", ("pip-licenses==" + [string]$Policy.tools.pip_licenses), "pip-licenses", "--python", $pythonPath, "--from", "all", "--format", "json") -WorkDir $projectPath
    if ($licenses.ExitCode -ne 0) {
      throw "tool_failed:pip_licenses"
    }
    foreach ($license in @(ConvertFrom-StrictJson -Content $licenses.Stdout -Label "python-licenses")) {
      $pythonLicenses.Add($license)
    }
  }

  $rustPath = Join-Path $Root "apps\tauri-host\src-tauri"
  if (-not (Test-Path -LiteralPath (Join-Path $rustPath "Cargo.lock") -PathType Leaf)) {
    throw "missing_lock:rust"
  }
  $rustAuditArguments = @("audit", "--json")
  $rustAuditArguments += @(Get-RustAuditExceptionArguments -Policy $Policy -WorkDir $rustPath)
  $rustAudit = Invoke-CapturedCommand -Executable "cargo" -Arguments $rustAuditArguments -WorkDir $rustPath
  $rustAuditJson = ConvertFrom-StrictJson -Content $rustAudit.Stdout -Label "rust-vulnerabilities"
  if ($rustAudit.ExitCode -ne 0 -and [int]$rustAuditJson.vulnerabilities.found -eq 0) {
    throw "tool_failed:cargo_audit"
  }
  $rustLicenses = Invoke-CapturedCommand -Executable "cargo" -Arguments @("license", "--json") -WorkDir $rustPath
  if ($rustLicenses.ExitCode -ne 0) {
    throw "tool_failed:cargo_license"
  }

  $npmPath = Join-Path $Root "apps\tauri-host"
  if (-not (Test-Path -LiteralPath (Join-Path $npmPath "package-lock.json") -PathType Leaf)) {
    throw "missing_lock:npm"
  }
  $npmAudit = Invoke-CapturedCommand -Executable "npx" -Arguments @("--yes", ("npm@" + [string]$Policy.tools.npm), "audit", "--json") -WorkDir $npmPath
  $npmAuditJson = ConvertFrom-StrictJson -Content $npmAudit.Stdout -Label "npm-vulnerabilities"
  if ($npmAudit.ExitCode -ne 0 -and [int]$npmAuditJson.metadata.vulnerabilities.total -eq 0) {
    throw "tool_failed:npm_audit"
  }
  $licenseJavaScript = "const fs=require('fs');const p=JSON.parse(fs.readFileSync(process.argv[1],'utf8')).packages||{};const out=Object.entries(p).filter(([k])=>k.startsWith('node_modules/')).map(([k,v])=>({name:k.slice(13),version:v.version||'',license:v.license||''}));process.stdout.write(JSON.stringify(out));"
  $npmLicenses = Invoke-CapturedCommand -Executable "node" -Arguments @("-e", $licenseJavaScript, (Join-Path $npmPath "package-lock.json")) -WorkDir $npmPath
  if ($npmLicenses.ExitCode -ne 0) {
    throw "tool_failed:npm_license_inventory"
  }

  return [PSCustomObject]@{
    PythonVulnerabilities = [PSCustomObject]@{ dependencies = @($pythonVulnerabilities) }
    PythonLicenses = @($pythonLicenses)
    RustVulnerabilities = $rustAuditJson
    RustLicenses = ConvertFrom-StrictJson -Content $rustLicenses.Stdout -Label "rust-licenses"
    NpmVulnerabilities = $npmAuditJson
    NpmLicenses = ConvertFrom-StrictJson -Content $npmLicenses.Stdout -Label "npm-licenses"
  }
}

try {
  $policy = Read-JsonFile -Path $PolicyPath -Label "policy"
  if ([int]$policy.schema_version -ne 1) {
    throw "unsupported_policy_schema"
  }

  $registry = Get-ReflexProjectRegistry -RepositoryRoot $RepositoryRoot
  if ([string]::IsNullOrWhiteSpace($FixtureDirectory)) {
    $inputs = Invoke-LiveInputs -Root $RepositoryRoot -Policy $policy -Registry $registry
  }
  else {
    $inputs = Read-FixtureInputs -Directory (Resolve-Path -LiteralPath $FixtureDirectory).Path
  }

  $vulnerabilities = [System.Collections.Generic.List[object]]::new()
  $licenses = [System.Collections.Generic.List[object]]::new()
  $toolFailures = [System.Collections.Generic.List[object]]::new()

  foreach ($dependency in @($inputs.PythonVulnerabilities.dependencies)) {
    if (Test-InternalPackage -Name ([string]$dependency.name) -Policy $policy) {
      continue
    }
    foreach ($vulnerability in @($dependency.vulns)) {
      Add-VulnerabilityFinding -Findings $vulnerabilities -Ecosystem "python" -Package $dependency.name -Advisory $vulnerability.id
    }
  }
  foreach ($item in @($inputs.PythonLicenses)) {
    $metadataLicense = [string]$item.'License-Metadata'
    $pythonLicense = if ($null -ne $item.License) {
      $item.License
    }
    elseif (-not [string]::IsNullOrWhiteSpace($metadataLicense) -and -not $metadataLicense.Equals("UNKNOWN", [System.StringComparison]::OrdinalIgnoreCase)) {
      $metadataLicense
    }
    else {
      $item.'License-Classifier'
    }
    Add-LicenseFinding -Findings $licenses -ToolFailures $toolFailures -Ecosystem "python" -Package $item.Name -Version $item.Version -License $pythonLicense -Policy $policy
  }

  foreach ($vulnerability in @($inputs.RustVulnerabilities.vulnerabilities.list)) {
    Add-VulnerabilityFinding -Findings $vulnerabilities -Ecosystem "rust" -Package $vulnerability.package.name -Advisory $vulnerability.advisory.id
  }
  foreach ($item in @($inputs.RustLicenses)) {
    Add-LicenseFinding -Findings $licenses -ToolFailures $toolFailures -Ecosystem "rust" -Package $item.name -Version $item.version -License $item.license -Policy $policy
  }

  foreach ($property in @($inputs.NpmVulnerabilities.vulnerabilities.PSObject.Properties)) {
    Add-VulnerabilityFinding -Findings $vulnerabilities -Ecosystem "npm" -Package $property.Name -Advisory "npm-advisory"
  }
  foreach ($item in @($inputs.NpmLicenses)) {
    Add-LicenseFinding -Findings $licenses -ToolFailures $toolFailures -Ecosystem "npm" -Package $item.name -Version $item.version -License $item.license -Policy $policy
  }

  foreach ($finding in @($vulnerabilities | Sort-Object Ecosystem, Package, Detail -Unique)) {
    Write-Output ("[FAIL] category=vulnerability ecosystem={0} package={1} advisory={2}" -f $finding.Ecosystem, $finding.Package, $finding.Detail)
  }
  foreach ($finding in @($licenses | Sort-Object Ecosystem, Package -Unique)) {
    Write-Output ("[FAIL] category=forbidden_license ecosystem={0} package={1} license={2}" -f $finding.Ecosystem, $finding.Package, $finding.Detail)
  }
  foreach ($failure in @($toolFailures | Sort-Object Ecosystem, Package -Unique)) {
    Write-Output ("[FAIL] category=tool_failure ecosystem={0} package={1} reason={2}" -f $failure.Ecosystem, $failure.Package, $failure.Detail)
  }

  if ($toolFailures.Count -gt 0) {
    exit [int]$policy.exit_codes.tool_failure
  }
  if ($vulnerabilities.Count -gt 0) {
    exit [int]$policy.exit_codes.vulnerability
  }
  if ($licenses.Count -gt 0) {
    exit [int]$policy.exit_codes.forbidden_license
  }

  Write-Output "Dependency audit passed."
  exit [int]$policy.exit_codes.passed
}
catch {
  Write-Output "[FAIL] category=tool_failure ecosystem=gate tool=audit_dependencies reason=unavailable_or_invalid"
  exit 22
}
