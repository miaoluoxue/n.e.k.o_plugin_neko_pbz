# 影之刃零游戏侧组件

UE4SS、PBZModLoader 代理、游戏侧 Mod 与开发脚本统一放在本目录。插件市场包
只发布 JS/Lua Mod 与运行时清单；可执行文件从固定 Release 资产下载并校验
SHA-256，避免市场安全扫描拒绝二进制。

```text
game_bundle/
├─ runtime-manifest.json  下载地址、大小与 SHA-256
├─ runtime/  本地开发缓存，不提交 Git、不进入市场包
├─ mod/
│  ├─ js/   PBZModLoader Mod
│  └─ lua/  UE4SS Lua Mod
└─ tools/   同步与开发部署脚本
```

面板入口 `pbz_install_game_mod` 会自动检测游戏目录，只安装本插件需要的文件，
并保留用户已有的 UE4SS、第三方 Mod 和配置。缺少 UE4SS 时才下载运行时。

验证新的游戏版本后，可刷新受控的 UE4SS 快照：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\game_bundle\tools\sync_vendor_ue4ss.ps1
```

开发环境部署当前工作区：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\game_bundle\tools\deploy.ps1
```
