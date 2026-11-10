# Snapshot the pinned PBZ UE4SS runtime into the installer vendor directory.
# Only built-in UE4SS files and PBZ's loader proxy are copied. Third-party or
# user-installed Mods are intentionally excluded.
param(
    [string]$GameRoot = "E:\SteamLibrary\steamapps\common\PBZ",
    [string]$VendorRoot = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
if (-not $VendorRoot) {
    $VendorRoot = Join-Path $repo "installer\vendor"
}

function Get-Sha256([string]$Path) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try {
        $hash = $algorithm.ComputeHash($stream)
        return ([BitConverter]::ToString($hash)).Replace("-", "")
    } finally {
        $stream.Dispose()
        $algorithm.Dispose()
    }
}

$source = Join-Path $GameRoot "platform\steam"
$required = @(
    "PBZ.exe",
    "dwmapi.dll",
    "version.dll",
    "ue4ss\UE4SS.dll",
    "ue4ss\UE4SS-settings.ini",
    "ue4ss\MemberVariableLayout.ini",
    "ue4ss\LICENSE"
)
foreach ($relative in $required) {
    $path = Join-Path $source $relative
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing UE4SS dependency: $path"
    }
}

$builtInMods = @(
    "CheatManagerEnablerMod",
    "ConsoleCommandsMod",
    "ConsoleEnablerMod",
    "SplitScreenMod",
    "LineTraceMod",
    "BPML_GenericFunctions",
    "BPModLoaderMod",
    "Keybinds",
    "shared"
)

$dest = Join-Path $VendorRoot "ue4ss"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

foreach ($relative in @(
    "dwmapi.dll",
    "version.dll",
    "ue4ss\UE4SS.dll",
    "ue4ss\UE4SS-settings.ini",
    "ue4ss\MemberVariableLayout.ini",
    "ue4ss\LICENSE"
)) {
    $src = Join-Path $source $relative
    $dst = Join-Path $dest $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
    Copy-Item -LiteralPath $src -Destination $dst -Force
}

foreach ($relative in @(
    "ue4ss\UE4SS_SDK_Backends",
    "ue4ss\UE4SS_Signatures"
)) {
    $src = Join-Path $source $relative
    $dst = Join-Path $dest $relative
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    Copy-Item -Path (Join-Path $src "*") -Destination $dst -Recurse -Force
}

$modsRoot = Join-Path $source "ue4ss\Mods"
$modsDest = Join-Path $dest "ue4ss\Mods"
foreach ($name in $builtInMods) {
    $src = Join-Path $modsRoot $name
    if (-not (Test-Path -LiteralPath $src)) {
        throw "Missing built-in UE4SS mod: $src"
    }
    $dst = Join-Path $modsDest $name
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    Copy-Item -Path (Join-Path $src "*") -Destination $dst -Recurse -Force
}

$baseModsTxt = Join-Path $modsRoot "mods.txt.original"
if (-not (Test-Path -LiteralPath $baseModsTxt)) {
    $baseModsTxt = Join-Path $modsRoot "mods.txt"
}
New-Item -ItemType Directory -Force -Path $modsDest | Out-Null
Copy-Item -LiteralPath $baseModsTxt -Destination (Join-Path $modsDest "mods.txt") -Force

$modsJson = Join-Path $modsRoot "mods.json"
if (Test-Path -LiteralPath $modsJson) {
    Copy-Item -LiteralPath $modsJson -Destination (Join-Path $modsDest "mods.json") -Force
}

$gameVersion = (Get-Item -LiteralPath (Join-Path $source "PBZ.exe")).VersionInfo.FileVersion
$hashes = [ordered]@{}
foreach ($relative in @(
    "dwmapi.dll",
    "version.dll",
    "ue4ss\UE4SS.dll"
)) {
    $hashes[$relative] = Get-Sha256 (Join-Path $dest $relative)
}
$metadata = [ordered]@{
    schema = 1
    captured_utc = [DateTime]::UtcNow.ToString("o")
    game_version = $gameVersion
    runtime = "UE4SS v3.0.1 Beta #5ebd595"
    built_in_mods = $builtInMods
    hashes = $hashes
}
$metadata | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath (Join-Path $dest "vendor.json") -Encoding UTF8

Write-Host "UE4SS vendor snapshot -> $dest"
Write-Host "Third-party/user Mods were not copied."
