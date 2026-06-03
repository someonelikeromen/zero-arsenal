# 贡献指南 (CONTRIBUTING)

欢迎为「零度武库 ZeroArsenal」贡献代码。本文档涵盖环境搭建、扩展开发、代码规范与 PR 流程。

---

## 1. 环境搭建

### 1.1 后端（Python 3.11+）

```bash
cd zero-arsenal
pip install -e "backend/[dev]"        # 安装含 dev 依赖（pytest 等）

cp .env.example .env                  # 复制环境变量，至少填入一个 LLM API Key
python -m backend.main                # 启动开发服务器
# 或 uvicorn backend.main:app --reload
```

- API 文档：http://localhost:8000/docs
- 各环境变量含义见 [`.env.example`](../.env.example) 中文注释。

### 1.2 前端（Node 18+）

```bash
cd frontend
npm install
npm run dev                           # http://localhost:5173
```

### 1.3 运行测试

```bash
# 后端
cd zero-arsenal
pytest backend/                       # 全量
pytest backend/ -m "not stub"         # 跳过未实现的桩测试（见第 4 节）

# 前端类型检查 + lint
cd frontend
npm run typecheck                     # tsc --noEmit
npm run lint
```

---

## 2. 扩展开发

ZeroArsenal 的世界设定、专属工具、生命周期钩子全部通过**扩展**实现，互不侵入核心代码。

### 2.1 三级加载目录（优先级从低到高）

| 级别 | 路径 | 用途 |
|---|---|---|
| 内置 | `backend/extensions/` | 随仓库分发 |
| 用户 | `~/.zero-arsenal/extensions/` | 个人本地扩展 |
| 项目 | `.zero-arsenal/extensions/` | 项目级覆盖（最高优先级） |

同名 `id` 高优先级目录会覆盖低优先级。也可用环境变量 `ZERO_ARSENAL_EXTENSIONS_OVERRIDE`（分号分隔）追加路径。

### 2.2 从骨架开始

复制骨架模板目录并去掉前缀下划线：

```bash
cp -r backend/extensions/_template backend/extensions/my_world
```

> `_template` 目录以下划线开头，**加载器会自动跳过**，仅作复制源。详见 [`backend/extensions/_template/README.md`](../backend/extensions/_template/README.md)。

### 2.3 扩展文件结构

| 文件 | 必需 | 作用 | 导出符号 |
|---|---|---|---|
| `manifest.json` | ✅ | 元数据 + 入口点；**只有含此文件的目录才被识别** | — |
| `plugin.py` | 可选 | `WorldPlugin` 子类：世界设定 / 初始属性 / 铁律 / 提示词片段 / 权限覆盖 | `PLUGIN` |
| `tools.py` | 可选 | 扩展工具集，自动注册到 `ToolRegistry` | `TOOLS: list[ToolDef]` |
| `hooks.py` | 可选 | 18 类生命周期钩子（回合 / 章节 / 工具 / 记忆 / NPC / 叙事等） | `HOOKS` 或 `*Hooks` 类 |
| `agents.py` | 可选 | 自定义 LangGraph 节点 | `AGENT_NODES` |
| `skills/` `rules/` `prompts/` | 可选 | Markdown 资产（文风 / 铁律 / 提示词片段） | — |

### 2.4 关键约束（务必遵守）

- `plugin.py` / `tools.py` / `hooks.py` 通过 `spec_from_file_location` 动态加载，**无包上下文**：
  - 模块顶层**不要直接用相对导入**（`from ..x import y` 会失败）。
  - `plugin.py` / `tools.py` 用双路兜底：`try: from ...pkg import X` / `except ImportError: from backend.pkg import X`。
  - `hooks.py` 应**完全自包含**，钩子类必须能**无参实例化**。
- 工具执行受 `plugin.permission_overlay` 约束：`allow` / `ask`（暂停等待确认）/ `deny`。
- 钩子方法签名统一：`async def <event>(self, ctx: dict) -> dict`，返回（可修改的）`ctx`。

### 2.5 验证加载

```bash
python -c "from backend.extensions.extension_loader import discover_extensions; print(list(discover_extensions()))"
```

新扩展 `id` 应出现在输出列表中。

---

## 3. 代码规范

### 3.1 脚本通用化（见 `.cursor/rules/06-script-generalization.mdc`）

- **零硬编码绝对路径**，用 `argparse` 参数 + 环境变量 + 合理默认值。
- 提供 `main()` 函数供 import 调用（双模式：CLI + import）。
- 输出统一为 JSON 可序列化 `dict`，含 `ok: bool` 字段。
- 顶部写自描述文档头（用途 / 用法 / 环境变量）。

### 3.2 错误处理

- **禁止 `except Exception: pass`**。至少 `logger.warning(...)` 记录，安全相关路径必须 **fail-closed**（拒绝而非放行）。
- 前端 catch 块统一调用 `notify.error(...)`（toast），不要只 `console.error`。

### 3.3 前端约定

- 状态管理用 Zustand store（`frontend/src/stores/`）。
- API 调用统一走 `frontend/src/lib/api.ts` 客户端，失败抛出 Error。
- 危险操作用 `requestConfirm(...)` 统一确认弹窗，禁止原生 `window.confirm()` / `alert()`。
- 配色统一使用 `zinc-*` 色阶（勿混用 `gray-*`）。

---

## 4. 测试约定

- 未实现/占位的桩测试用 `@pytest.mark.stub` 标注，CI 单独分组、不计入失败门槛。
- 新功能至少补一条 happy-path 测试；修 bug 时补一条回归测试。
- 涉及降级行为（Redis / 记忆 / VariableVM）的改动，更新 [`ARCHITECTURE.md`](./ARCHITECTURE.md)。

---

## 5. PR 流程

1. 从最新主分支切出特性分支：`feat/xxx` / `fix/xxx` / `docs/xxx`。
2. 小步提交，提交信息遵循 `type: 简述`（`feat` / `fix` / `docs` / `refactor` / `test`）。
3. 提交前本地跑通：后端 `pytest -m "not stub"`、前端 `npm run typecheck && npm run lint`。
4. PR 描述包含：**变更动机**、**改动范围**、**测试方式**、**截图**（涉及 UI 时）。
5. 不提交密钥文件（`.env` 等）。
6. 改动公共行为时同步更新对应文档（README / ARCHITECTURE / 扩展 README）。

---

## 6. 目录速查

```
zero-arsenal/
├── backend/
│   ├── api/routers/      # REST + SSE 路由
│   ├── agents/           # LangGraph Agent 节点 + 取消机制
│   ├── engine/           # 骰子 / 战斗引擎
│   ├── memory/           # 四层混合记忆
│   ├── extensions/       # 世界插件（_template 为骨架）
│   ├── tools/            # ToolRegistry
│   └── hooks/            # HookManager
├── frontend/src/
│   ├── lib/              # api.ts, sse.ts, bindSSEToStores.ts
│   ├── stores/           # Zustand
│   ├── components/       # 面板 / Part 渲染器
│   └── pages/            # HomePage, SessionPage, SettingsPage
└── docs/                 # 设计文档 / CONTRIBUTING / ARCHITECTURE
```
