# i18n 标准

locale 文件名采用 BCP-47：

- `zh-CN.json`：简体中文（默认）
- `zh-TW.json`：繁体中文
- `en.json`：英语

其他语言缺失时，宿主 SDK 会按 `locale_candidates()` 回退：

`具体 locale → 语言主标签 → default_locale → en`

键名使用点分命名：

```text
plugin.*     插件元信息
panel.*      面板标题
nav.*        导航
scan.*       侦察页
equipment.*  装备
knowledge.*  百晓
llm.*        独立 LLM
settings.*   调息
error.*      错误
```

新增文案时，先在 `zh-CN.json` 和 `en.json` 同时补键，再补 `zh-TW.json`。
不要在 Python/JS 里写死可翻译的 UI 文案。
