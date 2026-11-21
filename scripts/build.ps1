param([switch]$Debug)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$env:CARGO_HOME=Join-Path $projectRoot '.tools/cargo'
$env:RUSTUP_HOME=Join-Path $projectRoot '.tools/rustup'
$env:CARGO_TARGET_DIR=Join-Path $projectRoot 'src-tauri/target'
$compilerRoot=Get-ChildItem (Join-Path $projectRoot '.tools/msvc/VC/Tools/MSVC') -Directory | Sort-Object Name -Descending | Select-Object -First 1
$sdkRoot='C:\Program Files (x86)\Windows Kits\10'
$sdkVersion=(Get-ChildItem (Join-Path $sdkRoot 'Lib') -Directory | Sort-Object Name -Descending | Select-Object -First 1).Name
$env:PATH="$env:CARGO_HOME\bin;$($compilerRoot.FullName)\bin\Hostx64\x64;$sdkRoot\bin\$sdkVersion\x64;$env:PATH"
$env:LIB="$($compilerRoot.FullName)\lib\x64;$sdkRoot\Lib\$sdkVersion\ucrt\x64;$sdkRoot\Lib\$sdkVersion\um\x64"
$env:INCLUDE="$($compilerRoot.FullName)\include;$sdkRoot\Include\$sdkVersion\ucrt;$sdkRoot\Include\$sdkVersion\shared;$sdkRoot\Include\$sdkVersion\um;$sdkRoot\Include\$sdkVersion\winrt"
$priorEncodedFlags=$env:CARGO_ENCODED_RUSTFLAGS
if (-not $Debug) {
  $flags=if ($priorEncodedFlags) { @($priorEncodedFlags.Split([char]31)) } elseif ($env:RUSTFLAGS) { @($env:RUSTFLAGS -split '\s+' | Where-Object { $_ }) } else { @() }
  $flags+=@("--remap-path-prefix=$projectRoot=PoseSnap", "--remap-path-prefix=$env:CARGO_HOME=dependencies")
  $env:CARGO_ENCODED_RUSTFLAGS=$flags -join [char]31
}
Push-Location $projectRoot
try {
  & npm.cmd run icons
  if ($LASTEXITCODE) { throw 'Icon build failed' }
  $taskSource = & (Join-Path $projectRoot 'runtime/python/python.exe') -I -B (Join-Path $PSScriptRoot 'package.py') --source-signature
  if ($LASTEXITCODE -or $taskSource -notmatch '^[a-f0-9]{64}$') { throw 'Could not capture build inputs' }
  if ($Debug) { & npm.cmd run tauri -- build --debug --no-bundle } else { & npm.cmd run tauri -- build --no-bundle }
  if ($LASTEXITCODE) { throw 'Desktop build failed' }
  if (-not $Debug) {
    & (Join-Path $projectRoot 'runtime/python/python.exe') -I -B (Join-Path $PSScriptRoot 'package.py') --record-build --expect-source $taskSource
    if ($LASTEXITCODE) { throw 'Release identity verification failed' }
  }
} finally { $env:CARGO_ENCODED_RUSTFLAGS=$priorEncodedFlags; Pop-Location }
