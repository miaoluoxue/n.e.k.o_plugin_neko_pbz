# 影之刃零知识库数据

知识库是**数据驱动**的，Python/JS 不维护 Boss/武器/招式名单。

## 文件

- `seed.json`：基础实体（铃铛、杀气、铸魂、黑伤等）
- `seed_bosses.json`：Boss、小怪、铃铛
- `seed_equipment.json`：武器、影之武装、饰品、药瓶
- `seed_mechanics.json`：游戏机制
- `seed_tips.json`：玩法库与 Boss 建议池

所有 `seed*.json` 在启动时导入 SQLite；每次升级种子会刷新默认数据，
玩家纠正保存在 `corrections/`，不会被覆盖。

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

`boss`、`mob`、`bell`、`weapon`、`phantom_edge`、`accessory`、
`medicine`、`mechanic`、`playbook`

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
