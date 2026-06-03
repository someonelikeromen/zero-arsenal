# 扩展骨架模板 `_template`

ZeroArsenal 世界插件 / 工具 / 钩子的最小可运行骨架。**本目录以 `_` 开头，加载器会自动跳过**，仅作为复制源。

## 快速开始

1. **复制目录**并重命名（不要以 `_` 开头）：

   ```
   backend/extensions/my_world/
   ```

2. **改 `manifest.json`** 的 `id` / `display_name` / `description`。只有含 `manifest.json` 的目录才会被加载器识别。

3. 按需修改下面 5 个文件，未用到的可删除（除 `manifest.json` 外都是可选的）。

## 文件说明

| 文件 | 作用 | 加载方式 |
|---|---|---|
| `manifest.json` | 元数据 + 入口点声明 | 必需，决定是否被发现 |
| `plugin.py` | `WorldPlugin` 子类：世界设定、初始属性、世界铁律、提示词片段、权限覆盖 | 导出 `PLUGIN` 实例 |
| `tools.py` | 扩展工具集，自动注册到 `ToolRegistry` | 导出 `TOOLS: list[ToolDef]` |
| `hooks.py` | 生命周期钩子（回合/章节/工具/记忆等 18 类事件） | 导出 `HOOKS` 实例 / `*Hooks` 类 |
| `__init__.py` | 包导出（loader 不依赖，仅供常规 import） | 可选 |

## 重要约束

- **`plugin.py` / `tools.py` / `hooks.py` 通过 `spec_from_file_location` 动态加载，无包上下文。**
  - 模块顶层**不要直接用相对导入**（`from ..x import y` 会失败）。
  - `plugin.py` / `tools.py` 用 `try: from ...x import y / except: from backend.x import y` 双路兜底（见模板内写法）。
  - `hooks.py` 应**完全自包含**（不导入引擎内部模块），钩子类必须能无参实例化。
- 工具受 `plugin.permission_overlay` 约束（`allow` / `ask` / `deny`）。
- 钩子方法签名统一为 `async def name(self, ctx: dict) -> dict`，返回（可修改的）`ctx`。

## 可用钩子事件

`on_session_start` · `on_session_end` · `on_session_error` ·
`on_turn_start` · `on_turn_end` ·
`before_tool_call` · `after_tool_call` ·
`before_agent_node` · `after_agent_node` ·
`before_var_update` · `after_var_update` ·
`before_npc_response` · `after_npc_response` ·
`after_narrative_generated` · `after_style_applied` ·
`before_memory_compress` · `on_roll_check` · `on_chapter_end`

实现哪个方法就注册哪个，全部可选。

## 验证加载

```bash
python -c "from backend.extensions.extension_loader import discover_extensions; print(list(discover_extensions()))"
```

重命名后的扩展 id 应出现在输出列表中（`_template` 不会出现，符合预期）。
