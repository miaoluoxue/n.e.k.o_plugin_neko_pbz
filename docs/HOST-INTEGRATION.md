# 宿主接入与权限清单

本文区分三件事：

1. **N.E.K.O 宿主能力接入**：生命周期、UI、工具、消息和对话通道；
2. **宿主 UI 权限**：`plugin.toml` 中允许面板执行的界面 API；
3. **本机操作系统能力**：文件、注册表、进程、截图和可选网络访问。

宿主 UI 权限不等同于 Python 进程的操作系统权限。Python 插件运行在当前
Windows 用户下，文件系统、注册表、`tasklist` 和网络访问由代码自行约束。

## 接入总览

```text
N.E.K.O 宿主
├─ @lifecycle
│  ├─ startup：注册静态面板、插件列表动作
│  ├─ command loop：启动 PbzService 后台轮询
│  └─ shutdown：停止任务、会话、SQLite 与心跳
├─ 静态 UI
│  ├─ static/index.html：影帐面板
│  └─ docs/ui/guide.md：简短使用指南
├─ @plugin_entry
│  ├─ 状态/设置/知识/记忆/即时陪玩
│  └─ 游戏目录检测与一键安装
├─ @llm_tool
│  ├─ 状态、任务、Boss、路线、装备与知识查询
│  ├─ 偏好、约定、记忆与目标控制
│  └─ 截图交给宿主视觉模型
├─ push_message
│  ├─ respond：隐藏事实注入 LLM，生成一次猫娘回复
│  ├─ read：只注入上下文，不触发回复
│  └─ blind：只显示，不进入 LLM
└─ ctx.bus.conversations.get
   └─ 读取宿主最终 AI 台词并同步到游戏字幕
```

## 宿主 UI 权限

`plugin.toml` 目前只声明宿主支持的 UI surface 权限：

| Surface | 权限 | 用途 |
|---|---|---|
| 影帐面板 | `state:read` | 通过 `@ui.context` / `get_panel_state` 读取面板状态 |
| 影帐面板 | `action:call` | 调用设置、查询、记忆、即时陪玩和游戏侧安装入口 |
| 使用指南 | `state:read` | 宿主预览文档时保持默认状态读取能力 |

明确**不申请**：

- `config:read`
- `config:write`
- `document:parse`
- `logs:read`
- `runs:read`

面板配置通过专用 `@plugin_entry` 完成，不直接读取或改写宿主配置。

`action:call` 是当前面板最重要的权限，因为“一键安装游戏侧组件”也会通过
受控 entry 执行。该入口仍要求 `confirm=true`，并在后端再次校验游戏目录、
游戏进程、现有 UE4SS 和代理 DLL 冲突。

## 必需宿主能力

| 能力 | 用途 | 缺失后的行为 |
|---|---|---|
| `@lifecycle` | 启动/停止后台服务 | 插件无法建立实时状态循环 |
| `@ui.context` + 静态 UI | 影帐面板、状态与设置 | 仅聊天工具仍可用，面板不可用 |
| `@plugin_entry` | 面板动作和受控操作 | 按钮与设置无法执行 |
| `@llm_tool` | 让宿主猫娘在聊天中查询事实 | 只能使用面板，无法自然调用插件 |
| `push_message` | 生成猫娘回复、注入上下文、游戏字幕源 | 无法主动陪玩或同步最终台词 |
| `data_path()` | 配置、记忆、知识库、日志 | 插件无法持久化，服务降级为空状态 |
| `target_lanlan` 解析 | 多角色会话定向推送 | 多猫娘环境可能静默丢消息 |

## 条件使用的能力

### 对话总线

`ctx.bus.conversations.get()` 用于获取宿主最终生成的 AI 台词，再写入游戏
`reply.txt`。这是“TTS 听到的内容”和“游戏字幕显示的内容”一致的来源。

如果旧宿主不提供 conversations：

- 插件仍能通过 `push_message` 生成宿主回复；
- 游戏字幕无法确认最终台词，超时后使用本地 fallback；
- 面板会显示 `host_bus=false`。

### 宿主 LLM

插件默认不直接调用宿主 LLM。主要模式是：

- 插件通过 `push_message(ai_behavior="respond")` 交事实；
- 宿主使用当前猫娘人设生成回复和 TTS；
- 插件不硬编码最终台词。

兼容代码会探测旧的 `__call_llm` / `call_llm` 回调，但宿主没有该能力时
自动跳过。独立 LLM 只用于记忆整理和辅助生成，属于可选配置。

### 宿主视觉模型

F11、面板视觉侦察和 `pbz_look` 工具会：

1. 用 Win32 枚举 PBZ 窗口；
2. 用 Pillow 截取游戏窗口并压缩 JPEG；
3. 通过 `push_message` 或 `@llm_tool` 图像部件交给宿主视觉模型。

插件不内置视觉模型，也不持续录屏。

### TTS

插件没有直接调用宿主 TTS 的权限。宿主对 `visibility=["chat"]` 的最终回复
自行播放 TTS。插件只控制是否触发回复和文本长度，不输出 audio part。

## 本机操作系统能力

| 范围 | 访问方式 | 原因 | 约束 |
|---|---|---|---|
| 插件数据目录 | 读写 | JSON 配置、记忆、知识种子、SQLite 和日志 | 只落在 `data_path()` |
| PBZ 桥接目录 | 读写 | 状态、事件、回复、心跳 | 仅 `%LOCALAPPDATA%\ProjectPBZ\Saved\NekoBridge` |
| 游戏安装目录 | 读取校验、用户点击后写入 | 一键安装 UE4SS 与本插件 Mod | 不修改存档、Pak、原游戏 EXE |
| Steam 注册表 | 只读 | 发现 Steam 安装目录 | 只读 HKCU/HKLM 的 Steam 路径 |
| `libraryfolders.vdf` | 只读 | 枚举 Steam Library | 只读取路径字段 |
| 逻辑磁盘枚举 | 只读 | 处理非标准 Steam Library 布局 | 只检查常见相对目录 |
| `tasklist` | 进程查询 | 防止游戏运行时安装 | 不结束进程 |
| 游戏窗口截图 | 屏幕捕获 | 视觉侦察 | 只截 PBZ 窗口，默认要求前台 |
| Windows DPAPI | 当前用户加密 | 保护独立 LLM API Key | `CryptProtectData` |
| SQLite | 本地读写 | 知识库与检索 | 数据库在插件数据目录 |
| 外网 HTTPS | 按需 | UE4SS 运行时下载、独立 LLM | 安装缺少的运行时或启用独立 LLM 时 |

## 游戏侧一键安装权限

“调息 → 游戏侧组件 → 一键安装”会执行以下受控写入：

- 创建 `_neko_pbz_backup/<时间戳>`；
- 仅在缺少 `UE4SS.dll` 时下载固定版本，并在 SHA-256 校验通过后安装；
- 仅在代理 DLL 缺失且无冲突时写入 `dwmapi.dll`、`version.dll`；
- 更新本插件自己的 JS/Lua Mod 目录；
- 向 `ProjectPBZ\PBZModLoader\mods` 写入持久 JS 源码；
- 向 `mods.ini` 增加或启用 `pbz-neko-companion=1`；
- 向 `generated-config.js` 插入本插件条目（派生缓存，游戏启动时可重建）；
- 向 `mods.txt` 追加 `PBZNekoCompanion : 1`；
- 创建桥接目录。

安装不会：

- 删除或重排其他 Mod；
- 覆盖已有 UE4SS；
- 修改游戏存档或数值；
- 注入键鼠输入；
- 结束运行中的游戏进程。

如果游戏目录不可写、Steam 检测失败或代理 DLL 冲突，入口返回明确错误，
用户可手动填写游戏根目录后重试。

## 数据与隐私

- 不读取背包、仓库或材料数量；
- 不读取浏览器、桌面或其他应用窗口；
- 不上传截图，除非用户主动触发视觉侦察并交给宿主视觉模型；
- 独立 LLM Key 只存本机，优先使用当前用户 DPAPI；
- 游戏侧安装资源随插件市场包分发，但本机 `data/config`、`data/memory`、
  API Key、诊断和 SQLite 数据库不进入发行包。

## 最小权限结论

建议宿主只授予本插件面板：

```toml
permissions = ["state:read", "action:call"]
```

指南只保留 `state:read`。插件当前不需要宿主配置写入、日志读取、运行记录读取、
文档解析或宿主键值 Store，因此 `plugin.store.enabled` 已关闭。

操作系统层必须使用当前用户普通权限运行。若游戏目录需要管理员权限，应由用户
自行调整目录权限或选择可写安装位置，插件不主动提权。
