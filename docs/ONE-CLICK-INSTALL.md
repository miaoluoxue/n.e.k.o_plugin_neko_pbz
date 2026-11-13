# 游戏侧一键安装

完整插件通过 N.E.K.O 插件市场统一发布，不再生成插件 ZIP。市场包携带游戏侧
JS/Lua Mod 与运行时清单；UE4SS 可执行文件从固定 Release 资产下载并校验
SHA-256，不进入仓库或 Market 插件包。

## 使用

1. 从 N.E.K.O 插件市场安装或更新 `neko_pbz`。
2. 关闭《影之刃零》。
3. 打开“影帐 → 调息 → 游戏侧组件”。
4. 点击“自动检测”。插件会显示检测到的游戏根目录和当前安装状态。
5. 点击“一键安装 UE4SS + Mod”。
6. 安装成功后，重新启动游戏和 N.E.K.O。

如果自动检测失败，可以在“游戏根目录”填写包含以下文件的目录：

```text
platform\steam\PBZ.exe
ProjectPBZ\
```

也可以填写 `platform\steam` 等子目录，插件会向上匹配真实游戏根目录。

## 路径检测

安装路径不写死盘符，按以下来源依次匹配：

1. 用户在面板中填写或上次保存的目录；
2. Windows 注册表中的 Steam 安装路径；
3. Steam `libraryfolders.vdf` 中的全部游戏库；
4. 各逻辑磁盘上的常见 Steam Library 布局；
5. 最终校验 `platform\steam\PBZ.exe` 与 `ProjectPBZ\PBZModLoader` 是否存在。

只有通过目录结构校验的路径才会执行写入。

## 安全边界

- 游戏运行中拒绝安装，不强制结束游戏进程。
- 缺少 UE4SS 时下载固定版本，大小和 SHA-256 必须与清单一致才解压。
- 已存在 `UE4SS.dll` 时，整个 UE4SS 核心目录保持原样。
- 现有其他 Lua Mod、PuerTS Mod 不删除、不移动、不重排。
- JS 源码写入 `ProjectPBZ\PBZModLoader\mods\pbz-neko-companion`，这是
  PBZModLoader 启动时扫描的持久来源目录。
- `ProjectPBZ\PBZModLoader\mods.ini` 只增加或启用
  `pbz-neko-companion=1`，保留已有 Mod 条目。
- `mods.txt` 只追加缺失的 `PBZNekoCompanion : 1`。
- `generated-config.js` / `generated-mods` 是启动时可能重建的派生缓存；
  实际启用状态以 `mods.ini` 和持久源码目录为准。
- 发现 UE4SS 目录残缺或代理 DLL 与内置版本冲突时停止，不覆盖已有环境。
- 修改前自动备份本插件目录、`mods.ini`、`mods.txt` 和生成缓存，备份位于：

```text
<游戏根目录>\_neko_pbz_backup\<时间戳>\
```

## 插件包内资源

- `game_bundle\runtime-manifest.json`：运行时下载地址、大小和 SHA-256
- `game_bundle\mod\js\pbz-neko-companion`
- `game_bundle\mod\lua\PBZNekoCompanion`

UE4SS 运行时 Release 资产只包含白名单同步的核心、签名、布局配置和内置依赖，
不收入用户现有的地图辅助、任务攻略或其他第三方 Mod。

## 开发验证

```powershell
ruff check .
python -m pytest -q
node --check .\game_bundle\mod\js\pbz-neko-companion\game_api.js
```

游戏目录检测和“不覆盖现有 Mod”的安装行为由 `tests\test_game_installer.py`
覆盖。
