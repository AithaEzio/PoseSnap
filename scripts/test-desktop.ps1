param(
    [switch]$CheckOnly,
    [switch]$PrepareOnly,
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)
$ErrorActionPreference = 'Stop'

function Get-CoreHash([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-','') }
    finally { $hash.Dispose(); $stream.Dispose() }
}

function Get-CoreFile([string]$Root, [string]$Relative) {
    if (-not $Relative -or $Relative.Contains('\') -or $Relative.Contains(':') -or
        [IO.Path]::IsPathRooted($Relative) -or ($Relative.Split('/') -contains '..')) {
        throw "Invalid build file path: $Relative"
    }
    $path = Join-Path $Root $Relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Build file is missing: $path" }
    $entry = Get-Item -LiteralPath $path
    while ($entry.FullName -ne $Root) {
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Linked build path is unsupported: $($entry.FullName)" }
        $entry = Get-Item -LiteralPath (Split-Path -Parent $entry.FullName)
    }
    return $path
}

try {
    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    $version = (Get-Content -LiteralPath (Join-Path $ProjectRoot 'package.json') -Raw | ConvertFrom-Json).version
    if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'The project application version is invalid.' }
    $releaseRoot = Join-Path $ProjectRoot 'release'
    $candidates = @(Get-ChildItem -LiteralPath $releaseRoot -Directory -Filter "PoseSnap-$version*-Windows-x64" | ForEach-Object {
        if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Linked build directory is unsupported: $($_.FullName)" }
        $manifestPath = Join-Path $_.FullName 'manifest.json'
        if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
            $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
            if ($manifest.version -eq $version -and $manifest.schema -eq 2 -and $manifest.kind -eq 'portable-core') {
                [pscustomobject]@{Root=$_.FullName; Manifest=$manifest; Created=[DateTimeOffset]::Parse($manifest.created)}
            }
        }
    })
    if (-not $candidates.Count) { throw "No packaged v$version build was found in release. Build and package the app first; this shortcut does not compile it." }
    $selected = $candidates | Sort-Object Created,Root -Descending | Select-Object -First 1
    $root = $selected.Root
    $manifest = $selected.Manifest
    Write-Host "Checking newest packaged PoseSnap v$version ($($manifest.candidate))..."

    # Verify the newest selection; corruption must never silently launch an older build.
    foreach ($record in $manifest.files.PSObject.Properties) {
        $path = Get-CoreFile $root $record.Name
        if ($record.Value.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or
            (Get-Item -LiteralPath $path).Length -ne $record.Value.size -or
            (Get-CoreHash $path) -ne $record.Value.sha256) {
            throw "Build checksum failed: $path. Rebuild or re-extract this candidate; no older build was launched."
        }
    }
    foreach ($required in @('PoseSnap.exe','worker/main.py','manifests/build-receipt.json')) {
        if (-not $manifest.files.PSObject.Properties[$required]) { throw "Build manifest omits $required" }
    }
    $app = Get-CoreFile $root 'PoseSnap.exe'
    $build = Get-Content -LiteralPath (Get-CoreFile $root 'manifests/build-receipt.json') -Raw | ConvertFrom-Json
    if ($manifest.sourceSha256 -notmatch '^[a-f0-9]{64}$' -or $build.source.sha256 -ne $manifest.sourceSha256 -or
        $build.applicationVersion -ne $version -or $build.executableSha256 -ne $manifest.files.'PoseSnap.exe'.sha256 -or
        (Get-Item -LiteralPath $app).VersionInfo.ProductVersion -ne $version) {
        throw 'The executable, manifest and build receipt disagree. Rebuild this candidate.'
    }
    Write-Host "Selected: $app"
    Write-Host "Build date: $($selected.Created.ToUniversalTime().ToString('u'))"
    Write-Host 'This build reuses compatible project engines and keeps its own settings/history.'
    if ($CheckOnly) { Write-Host 'Verification passed. No application was launched.'; exit 0 }
    if (Get-Process -Name PoseSnap -ErrorAction SilentlyContinue) { throw 'Close existing PoseSnap windows, then run Test-PoseSnap.cmd again.' }
    $python = Join-Path (Split-Path -Parent $PSScriptRoot) 'runtime/python/python.exe'
    & $python -X utf8 -I -B (Join-Path $PSScriptRoot 'prepare-test-engines.py') --project $ProjectRoot --build $root
    if ($LASTEXITCODE -ne 0) { throw 'Project engine reuse failed. No model downloads were started.' }
    if ($PrepareOnly) { Write-Host 'Test engines are prepared. No application was launched.'; exit 0 }
    $process = Start-Process -FilePath $app -WorkingDirectory $root -WindowStyle Normal -PassThru
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "PoseSnap exited with code $($process.ExitCode). Check $root\logs for diagnostics." }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
