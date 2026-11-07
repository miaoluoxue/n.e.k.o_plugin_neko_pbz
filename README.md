# 影之刃零 · 猫娘陪玩（neko_pbz）

N.E.K.O 插件 + UE5 游戏内 Mod。让宿主当前猫娘陪主人玩《Phantom Blade Zero / 影之刃零》：

- 读局面：生命、杀气、战斗状态、当前武器、影之武装、饰品；
- 多槽位随身：主/副武器、多个影之武装、多个饰品、药瓶/快捷道具；
- 读世界：区域、Boss、前方敌人、铃铛、任务；
- 跨会话记忆：Boss 尝试/死亡/首杀、装备、偏好、约定；
- 知识库：Boss、小怪、铃铛、武器、影之武装、铸魂；
- 画面识别：游戏内 F11 截图，交给宿主视觉模型；`pbz_look` 工具按需看画面；
- Boss 前从已验证建议池随机 1~3 条；
- 独立 LLM（OpenAI 兼容 / OpenAI / Anthropic / Gemini），只做记忆摘要与知识整理；
- 台词/情绪/TTS 全部由宿主当前猫人设负责，游戏内字幕与语音使用同一段最终回复。

## 面板

面板按《影之刃零》重做为“影帐”战报台，不是小游戏面板的复刻：

- **战局**：区域/场景、猫娘最近一句、气血/杀气环、随身装备、Boss、前向雷达；
- **侦察**：独立罗盘页，Boss、小怪、方位、距离、铃铛与手动刷新；
- **交锋**：Boss 交手记录、事件流；
- **忆卷**：跨会话记忆、约定、本地统计；
- **百晓**：分类覆盖统计、按 Boss/小怪/装备/药瓶/机制/玩法库筛选、种子重载；
- **灵犀**：独立 LLM 配置、测试连接、Token 账；
- **调息**：TTS/字幕/主动说话/剧透等级/Boss 建议条数/静默。

「调息」提供四套**结构风格**：水墨卷轴 / 戏台花窗 / 江湖战报 / 青绿山水；
每套风格可叠加墨夜/宣纸/赤影/青锋辅助配色。
舒适/紧凑密度、90%~115% 缩放、
减少动效、隐藏雷达、隐藏灵犀摘要与忆卷导出。

面板底部居中显示「影之刃零 · PHANTOM BLADE ZERO × N.E.K.O」。
侧栏标题固定为「影帐 / PBZ × N.E.K.O / 江湖陪玩」；战局有一条常驻侦察带，
切换风格后仍可看到敌情、Boss 与铃铛摘要。

## 明确边界

- 不读取背包、仓库、材料数量；
- 不修改游戏存档、数值、输入；
- 不修改宿主代码；
- 只新增独立 Mod 目录与插件目录。

### 运行独立性

- 不 import 任何其他插件；
- 独立 LLM 客户端已 vendor 到本插件 `adapters/`，运行时不需要 `neko_arcade`；
- 游戏 Mod 只 require `ue` / `puerts` / 本地文件；游戏自带 `Library/TsHelper`
  只作为可选加速，缺失时有 UWorld/UObject 原生回退；
- 不依赖 `PBZQuestGuide`、`pbz-map-helper` 或其他社区 Mod。

## 目录

```text
neko_pbz/
├─ core/       桥接、事件、记忆、知识库、宿主语音
├─ entries/    生命周期、面板、LLM 工具
├─ static/     插件面板
├─ data/       配置与知识库种子
├─ mod/
│  ├─ pbz-neko-companion/   PuerTS JS：只读状态 + 字幕
│  └─ lua/PBZNekoCompanion/ UE4SS Lua：读 reply.txt + F10
├─ scripts/deploy.ps1      一键部署
└─ tests/                  单元测试
```

## 持久化数据

所有可写配置与记忆都在插件自己的 `data/`：

```text
data/
├─ config/
│  ├─ general.json       陪伴/桥接/剧透/建议条数
│  ├─ llm.json           独立 LLM（Key 仅本机）
│  └─ ui.json            主题/密度/缩放/动效
├─ memory/
│  ├─ _global/profile.json
│  ├─ <存档>/
│  │  ├─ save.json
│  │  ├─ bosses.json
│  │  ├─ facts.json
│  │  ├─ preferences.json
│  │  ├─ promises.json
│  │  └─ sessions/*.json
│  └─ exports/*.json
└─ knowledge/
   ├─ seed.json              基础条目
   ├─ seed_bosses.json       Boss/小怪/铃铛
   ├─ seed_equipment.json    武器/影之武装/饰品/药瓶
   ├─ seed_mechanics.json    杀气/切换武器/药瓶/破防等机制
   ├─ seed_tips.json         玩法库 + 已验证 Boss 建议
   ├─ pbz_knowledge.db
   └─ corrections/*.json
```

旧版单文件 SQLite 记忆会自动迁移到目录结构，原 DB 改名为 `.db.migrated` 保留。

首批知识库包含 86 个实体：12 Boss、8 类小怪、7 铃铛、11 武器、
14 影之武装、10 饰品、8 药瓶、12 机制、4 玩法库条目；
14 条已验证通用建议，9 条 Boss 专属建议等待实机核验。

## 部署

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy.ps1
```

脚本会：

1. 复制插件到两个活插件目录；
2. 复制 JS Mod 到 `PBZModLoader\generated-mods\pbz-neko-companion`；
3. 更新 `generated-config.js`（先备份 `.bak.neko`）；
4. 复制 Lua Mod 到 UE4SS，并在 `mods.txt` 注册；
5. 创建 `ProjectPBZ\Saved\NekoBridge`。

重启游戏与插件后，游戏内 `F10` 显示/隐藏字幕。

## TTS

- 插件通过 `push_message(..., ai_behavior="respond")` 把事实交给宿主；
- 宿主用当前猫娘人设生成回复并 TTS；
- 插件从 `ctx.bus.conversations` 取最终 AI 文本，写入 `reply.json` / `reply.txt`；
- 游戏内字幕显示同一段文本。

`read` 只注入上下文，不触发语音；`blind` 只用于系统提示。

## 画面识别

- 只截《影之刃零》窗口，不截桌面；
- 游戏内 **F11** 触发一次视觉侦察（游戏在前台）；
- 截图通过宿主 `push_message` 的 image part 交给宿主视觉模型；
- `pbz_look` LLM 工具返回一帧截图 + `vision_prompt`，由宿主视觉模型分析；
- 本插件不自建视觉模型，也不持续录屏；默认仅在手动触发时截图。

## 独立 LLM

复用了 `neko_arcade` 已验证的 LLM 客户端（OpenAI 兼容 / OpenAI / Anthropic / Gemini），
不重复造轮子。它只用于：

- 会话结束时的记忆摘要；
- 后续知识整理/查询辅助。

猫娘的最终台词、情绪与 TTS 仍走宿主 LLM，插件不会用独立 LLM 抢宿主的人设表达。

**调用优先级**：

1. 已启用独立 LLM 且填了 Provider + Model → 用独立 LLM；
2. 未配置/未启用 → 自动回退宿主主体 LLM（`__call_llm` / `call_llm`）；
3. 两者都不可用 → 记忆摘要使用本地规则，不阻塞游戏。

面板「灵犀」可以配置 Provider、Model、API Key、Base URL、超时、每分钟调用上限，
并查看调用次数与 token 统计。API Key 只保存在插件自己的 `data/config/llm.json`，
不会回传给前端。

## P0 核验

首次进游戏后，把以下文件发回来或直接看面板：

- `ProjectPBZ\Saved\NekoBridge\state.json`
- `ProjectPBZ\Saved\NekoBridge\heartbeat.json`

重点确认：

- `capabilities.vitals` 是否读到生命/杀气；
- `capabilities.enemy_classes` 是否发现敌人/Boss 类；
- `player.equipment` 是否读到当前武器/影之武装/饰品；
- `bell` 是否读到附近铃铛；
- `quests` 是否有当前任务。

读不到的字段会保持 `null`，不会猜测，也不会回退到背包。

## 测试

```powershell
python -m pytest -q
node --check mod\pbz-neko-companion\main.js
```

## 文档

完整设计讨论稿：[docs/DESIGN-影之刃零陪玩插件.md](docs/DESIGN-影之刃零陪玩插件.md)
