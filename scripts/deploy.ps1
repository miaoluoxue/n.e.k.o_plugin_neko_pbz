# 部署 neko_pbz：插件两个活目录 + PBZ 游戏 Mod（JS/Lua）。
# 只新增/更新本插件文件；不修改宿主代码与游戏 pak。
param(
    [string]$GameRoot = "E:\SteamLibrary\steamapps\common\PBZ",
    [switch]$SkipPlugin,
    [switch]$SkipMod,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$dev = Split-Path -Parent $PSScriptRoot
$liveRoots = @(
    "C:\Users\10093\AppData\Local\N.E.K.O\.neko-plugin-installations\plugins\neko_pbz",
    "C:\Users\10093\AppData\Local\N.E.K.O\plugins\neko_pbz"
)

if (-not $Force) {
    $running = @()
    if (-not $SkipMod) {
        $running += @(Get-Process -Name "PBZ" -ErrorAction SilentlyContinue |
            ForEach-Object { "PBZ ($($_.Id))" })
    }
    if (-not $SkipPlugin) {
        $running += @(Get-Process -Name "N.E.K.O" -ErrorAction SilentlyContinue |
            ForEach-Object { "N.E.K.O ($($_.Id))" })
    }
    if ($running.Count -gt 0) {
        throw "检测到运行中的进程：$($running -join ', ')。请先关闭游戏和 N.E.K.O，或显式使用 -Force。"
    }
}

function Copy-Plugin([string]$dest) {
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    $items = @("__init__.py", "plugin.toml", "core", "entries", "adapters", "perception", "static", "data", "i18n", "docs")
    foreach ($item in $items) {
        $src = Join-Path $dev $item
        if (-not (Test-Path -LiteralPath $src)) { continue }
        $dst = Join-Path $dest $item
        if ((Get-Item -LiteralPath $src).PSIsContainer) {
            New-Item -ItemType Directory -Force -Path $dst | Out-Null
            Copy-Item -Path (Join-Path $src "*") -Destination $dst -Recurse -Force
        } else {
            Copy-Item -LiteralPath $src -Destination $dst -Force
        }
    }
    Write-Host "plugin -> $dest"
}

function Add-JsMod([string]$configPath, [string]$id) {
    $text = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
    $match = [regex]::Match($text, 'module\.exports\s*=\s*(\{[\s\S]*\})\s*;')
    if (-not $match.Success) { throw "无法解析 $configPath" }
    $obj = $match.Groups[1].Value | ConvertFrom-Json
    $exists = @($obj.mods | Where-Object { $_.id -eq $id }).Count -gt 0
    if (-not $exists) {
        $entry = [pscustomobject]@{
            id = $id
            enabled = $true
            entry = "mods/$id/main.js"
        }
        $obj.mods = @($obj.mods) + $entry
        Copy-Item -LiteralPath $configPath -Destination ($configPath + ".bak.neko") -Force
        $json = $obj | ConvertTo-Json -Depth 10 -Compress
        Set-Content -LiteralPath $configPath -Value ("'use strict';`nmodule.exports = $json;`n") -Encoding UTF8
        Write-Host "js config += $id"
    } else {
        Write-Host "js config already has $id"
    }
}

function Ensure-ModsTxt([string]$path) {
    $text = if (Test-Path -LiteralPath $path) { Get-Content -LiteralPath $path -Raw } else { "" }
    if ($text -notmatch "(?m)^PBZNekoCompanion\s*:") {
        Copy-Item -LiteralPath $path -Destination ($path + ".bak.neko") -Force -ErrorAction SilentlyContinue
        Add-Content -LiteralPath $path -Value "PBZNekoCompanion : 1" -Encoding ASCII
        Write-Host "ue4ss mods.txt += PBZNekoCompanion"
    }
}

if (-not $SkipPlugin) {
    foreach ($root in $liveRoots) { Copy-Plugin $root }
}

if (-not $SkipMod) {
    if (-not (Test-Path -LiteralPath $GameRoot)) { throw "游戏目录不存在: $GameRoot" }
    $bridge = Join-Path $env:LOCALAPPDATA "ProjectPBZ\Saved\NekoBridge"
    $legacyBridge = Join-Path $GameRoot "ProjectPBZ\Saved\NekoBridge"
    foreach ($path in @($bridge, $legacyBridge)) {
        foreach ($slot in @("state", "mod_status", "game_heartbeat")) {
            New-Item -ItemType Directory -Force -Path (Join-Path $path $slot) | Out-Null
        }
    }

    $modSrc = Join-Path $dev "mod\pbz-neko-companion"
    $loader = Join-Path $GameRoot "ProjectPBZ\Content\JavaScript\PBZModLoader"
    $generated = Join-Path $loader "generated-mods\pbz-neko-companion"
    $legacy = Join-Path $GameRoot "ProjectPBZ\PBZModLoader\mods\pbz-neko-companion"
    foreach ($dst in @($generated, $legacy)) {
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        Copy-Item -Path (Join-Path $modSrc "*") -Destination $dst -Recurse -Force
        Write-Host "js mod -> $dst"
    }
    Add-JsMod (Join-Path $loader "generated-config.js") "pbz-neko-companion"

    $luaSrc = Join-Path $dev "mod\lua\PBZNekoCompanion"
    $luaDst = Join-Path $GameRoot "platform\steam\ue4ss\Mods\PBZNekoCompanion"
    New-Item -ItemType Directory -Force -Path $luaDst | Out-Null
    Copy-Item -Path (Join-Path $luaSrc "*") -Destination $luaDst -Recurse -Force
    Set-Content -LiteralPath (Join-Path $luaDst "enabled.txt") -Value "1" -Encoding ASCII
    Ensure-ModsTxt (Join-Path $GameRoot "platform\steam\ue4ss\Mods\mods.txt")
    Write-Host "lua mod -> $luaDst"
    Write-Host "bridge -> $bridge"
}

Write-Host "`n部署完成。重启游戏/插件后："
Write-Host "  - 当前面板使用安全模式，不自动注入游戏内 UMG"
Write-Host "  - 面板检查 state / mod_status / game_heartbeat 的 EasyCsv 槽位"
Write-Host "  - 实际桥接目录: $bridge"
