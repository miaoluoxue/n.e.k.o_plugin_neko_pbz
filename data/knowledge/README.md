# 影之刃零知识库数据

知识库是**数据驱动**的，Python/JS 不维护 Boss/武器/招式名单。

## 文件

- `seed.json`：基础实体（铃铛、杀气、铸魂、黑伤等）
- `seed_bosses.json`：Boss、小怪、铃铛
- `seed_equipment.json`：武器、影之武装、饰品、药瓶
- `seed_mechanics.json`：游戏机制
- `seed_tips.json`：玩法库与 Boss 建议池
- `seed_world.json`：区域与探索玩法
- `seed_game_catalog.json`：物品名称、分类与紧凑获取位置
- `seed_game_bosses.json`：首领点位、首领组与短攻略
- `seed_game_quests.json`：任务步骤、目标点、前置、失败提醒与奖励
- `seed_game_guide.json`：探索路线、铃铛、收集物与挑战
- `seed_game_npcs.json`：NPC 位置、用途与对话节点
- `seed_game_regions.json`：区域章节与收集覆盖
- `sources.json`：离线来源、导入日期、置信度和版权边界

所有 `seed*.json` 在启动时导入 SQLite；每次升级种子会刷新默认数据，
玩家纠正保存在 `corrections/`，启动和“重载种子”后会重新应用到数据库。

## 刷新

```powershell
node ..\..\scripts\import_pbz_game_data.js
node ..\..\scripts\import_pbz_game_data.js --game "D:\Games\PBZ"
```

导入器只读取本机安装目录并生成上述结构化 JSON；插件运行时不需要 Node。
只保留紧凑事实，不复制安装包脚本、二进制资源或攻略全文。

## 实体格式

```json
{
  "id": "boss.example",
  "type": "boss",
  "name": "示例 Boss",
  "aliases": ["别名"],
  "region": "区域",
  "spoiler_level": 1,
  "confidence": 0.5,
  "source": "catalog",
  "facts": {
    "category": "Boss",
    "threat": "高",
    "recommended_defense": "先观察起手",
    "tip": "只写已验证的信息"
  }
}
```

`type` 可用：

`boss`、`quest`、`route`、`collectible`、`npc`、`item`、`mob`、`bell`、
`weapon`、`phantom_edge`、`accessory`、`medicine`、`mechanic`、`playbook`、
`region`、`guide`

## 建议池

```json
{
  "boss_id": "boss.generic",
  "text": "建议文本",
  "tags": ["defense:observe"],
  "spoiler_level": 1,
  "weight": 1.0,
  "verified": true,
  "source": "curated"
}
```

只有 `verified: true` 的建议会进入 Boss 前 1~3 条随机池。
未实机确认的 Boss 专属建议必须写 `false`，插件不会把它当事实播报。
