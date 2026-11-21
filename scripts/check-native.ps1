param([switch]$CheckOnly, [switch]$BuildDebug, [switch]$ValidateWorkspace, [switch]$VerifyDownloadSources)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:CARGO_HOME = Join-Path $projectRoot '.tools/cargo'
$env:RUSTUP_HOME = Join-Path $projectRoot '.tools/rustup'
$env:CARGO_TARGET_DIR = Join-Path $projectRoot 'src-tauri/target'
$env:TEMP = Join-Path $projectRoot 'temp/native-tests'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$compilerRoot = Get-ChildItem (Join-Path $projectRoot '.tools/msvc/VC/Tools/MSVC') -Directory | Sort-Object Name -Descending | Select-Object -First 1
$sdkRoot = 'C:\Program Files (x86)\Windows Kits\10'
$sdkVersion = (Get-ChildItem (Join-Path $sdkRoot 'Lib') -Directory | Sort-Object Name -Descending | Select-Object -First 1).Name
$env:PATH = "$env:CARGO_HOME\bin;$($compilerRoot.FullName)\bin\Hostx64\x64;$sdkRoot\bin\$sdkVersion\x64;$env:PATH"
$env:LIB = "$($compilerRoot.FullName)\lib\x64;$sdkRoot\Lib\$sdkVersion\ucrt\x64;$sdkRoot\Lib\$sdkVersion\um\x64"
$env:INCLUDE = "$($compilerRoot.FullName)\include;$sdkRoot\Include\$sdkVersion\ucrt;$sdkRoot\Include\$sdkVersion\shared;$sdkRoot\Include\$sdkVersion\um"
$task = if ($CheckOnly) { 'check' } elseif ($BuildDebug) { 'build' } else { 'test' }
if ($VerifyDownloadSources) {
    & (Join-Path $env:CARGO_HOME 'bin/cargo.exe') test --offline --manifest-path (Join-Path $projectRoot 'src-tauri/Cargo.toml') upstream_public_download_metadata -- --ignored --nocapture
} elseif ($ValidateWorkspace) {
    $env:POSESNAP_TEST_ROOT = $projectRoot
    & (Join-Path $env:CARGO_HOME 'bin/cargo.exe') test --offline --manifest-path (Join-Path $projectRoot 'src-tauri/Cargo.toml') workspace_components_and_private_gpu_worker -- --ignored --nocapture
} else {
    & (Join-Path $env:CARGO_HOME 'bin/cargo.exe') $task --offline --manifest-path (Join-Path $projectRoot 'src-tauri/Cargo.toml')
}
if ($LASTEXITCODE) { throw 'Native development check failed' }
