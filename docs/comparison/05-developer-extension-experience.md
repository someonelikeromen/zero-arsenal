# 报告五：开发者与扩展体验对比

> 生成时间：2026-06-03 | 数据来源：L1-L4 子代理 D09+D12 维度

---

## 1. 扩展系统对比概览

| 项目 | 扩展机制 | 热加载 | 权限控制 | 配置UI自动化 | 文档完整性 |
|------|----------|--------|----------|--------------|------------|
| **zero-arsenal** | manifest.json + plugin.py + tools.py + hooks.py | 部分（watchfiles监听skills；生产需重启）| AgentProfile play/plan/review | ✗（手写前端） | △（04-extension-system.md详尽；无CONTRIBUTING）|
| **SillyTavern** | JS注入 + ST-Script脚本引擎 + Extension事件钩子 | ✓（前端扩展） | 有限（UI可见性） | ✗ | △（社区驱动）|
| **Open WebUI** | Python Functions/Pipelines + Valves自动UI | ✓（管理UI上传即生效） | Admin/User双层 | ✓（Pydantic→表单） | ✓（docs.openwebui.com）|
| **opencode** | Effect ToolRegistry + 工具定义钩子 + MCP完整 | ？ | per-tool allow/ask/deny + DB持久 | ✗ | ✓ |
| **pi** | registerTool(TypeBox) + registerCommand + UI dialog | ？ | 生命周期事件 | △ | △ |
| **MoRanJiangHu** | utils/moduleRegistry（window事件+lazy注册） | ✗ | ✗ | ✗ | ✗ |
| **ai-vn-game-system** | 无正式扩展机制 | N/A | N/A | N/A | ARCHITECTURE.md详尽 |

---

## 2. zero-arsenal 扩展系统深度分析

### 2.1 扩展结构

```
backend/extensions/<id>/
├─ manifest.json          # 元数据 + 权限声明
├─ plugin.py              # 生命周期：setup/teardown
├─ tools.py               # 注册到工具注册表
├─ hooks.py               # 事件钩子（pre/post生成等）
└─ skills/                # SKILL.md + 辅助脚本
   └─ <skill-name>/
       └─ SKILL.md
```

**manifest.json 字段**：agent_id、name、description、version、permissions（tools/hooks/agents）、inject_as（hook注入点）、applicable_worlds（可选，限定插件生效的世界扩展）

### 2.2 已完整实现的扩展

| 扩展ID | 完整度 | 主要工具 |
|--------|--------|----------|
| `crossover` | ✓ 较完整 | 积分/物品兑换/跨维度旅行 |
| `wuxia` | ✓ 较完整 | 武侠世界规则/武功技能 |
| `infinite_arsenal` | ✓ 较完整 | 武器系统/战斗辅助 |
| `web_scraper` | △ | URL内容抓取+lore写入 |
| `muv_luv` | △ STUB | MUV-LUV世界插件 |
| `gundam_seed` | △ STUB | 高达SEED世界插件 |

### 2.3 扩展开发体验评分

**优势**
- 扩展零侵入：通过manifest声明，不修改主代码库
- 三级优先级覆盖：内置 < 用户 < 项目，覆盖颗粒度精细
- `GET /config/extensions`运行时查询已注册扩展
- `LlmRoutesTab`运行时PUT改路由，无需重启——对开发者友好

**不足**
- 无`Hub → 扩展`管理面板（加载/卸载/查看状态全靠服务器日志）
- 配置项（如crossover积分倍率）需手写前端表单，不像Open WebUI的Valves自动渲染
- `plugin.py`无热重载；修改tools/hooks需重启服务
- 无官方CONTRIBUTING.md；开发者只有`04-extension-system.md`作为参考
- MCP Bridge尚未达到opencode生产级（缺OAuth、连接状态UI、stdio完整支持）

---

## 3. 竞品最佳实践提炼

### 3.1 Open WebUI：Valves自动渲染（★★★ 强烈推荐移植）

```python
# Open WebUI 扩展只需定义 Pydantic 模型
class Valves(BaseModel):
    bonus_multiplier: float = Field(1.5, description="积分倍率")
    max_items: int = Field(10, description="最大物品数")
    api_key: str = Field("", json_schema_extra={"format": "password"})
```
→ Admin UI自动渲染为带说明的数字输入框/密码框，`float`有步进，无需手写前端。

**移植到zero-arsenal的方案**：
1. 在`manifest.json`添加`config_schema`字段（Pydantic JSON Schema格式）
2. Hub扩展Tab自动解析schema，用通用`<SchemaForm>`组件渲染
3. 配置值通过`PUT /extensions/{id}/config`持久化

工作量：**中**（前端SchemaForm组件约200行，后端扩展config API约50行）

### 3.2 opencode：Permission ask流（★★★ 高价值）

```
当工具申请危险权限时：
  → EventBus发送 permission.asked 事件
  → 前端弹出确认对话框（显示工具名+权限说明+Once/Always/Reject选项）
  → 用户选择 → 结果写入 permission_grants DB
  → 后续相同工具自动记住选择
```

**移植方案**：
1. `bus/events.py`添加`PermissionAskEvent`
2. SessionPage添加`PermissionAskModal`组件
3. 数据库添加`permission_grants`表

工作量：**中**（主要是前端Modal + 后端DB表）

### 3.3 SillyTavern：扩展下载市场（★★ 中期目标）

SillyTavern Extensions通过内置"下载扩展"UI，从GitHub列表拉取JS文件，无需手动放置文件。

**移植思路**：Hub扩展Tab添加"市场"入口，维护`extensions-registry.json`（含扩展名/描述/版本/下载URL），点击一键安装到`extensions/`目录。

工作量：**大**（需要扩展签名验证、沙箱安全审查）

### 3.4 MoRanJiangHu：moduleRegistry Modal系统（★★ 中等推荐）

```typescript
// 注册
moduleRegistry.register('worldbook', () => import('./WorldbookModal'))
// 触发
window.dispatchEvent(new CustomEvent('modal:open', { detail: { id: 'worldbook' } }))
```

**移植价值**：zero-arsenal Hub已有多个Modal，统一用事件注册可以让扩展注册自己的配置Modal，无需侵入主路由。

工作量：**小**（约100行工具函数 + 现有Modal改造注册）

---

## 4. 技能格式对比（Skill YAML frontmatter进化）

| 版本 | 来源 | 核心字段 |
|------|------|----------|
| 极简版 | superpowers | `name`+`description`，靠正文门禁（HARD-GATE）|
| 注入版 | pi | frontmatter + `<skill name= location=>` XML注入 |
| 完整版 | zero-arsenal | `name/description/trigger/phases/priority/inject_as/applicable_worlds` |

zero-arsenal的skill格式最丰富，允许按phases、worlds精确控制激活时机——这是TRPG场景下的正确设计。

**待补强**：superpowers的"HARD-GATE无批准禁止执行"语义，可映射为zero-arsenal的`review`权限模式，确保GM确认后才执行关键技能。

---

## 5. 开发者快速上手路径优化建议

### 当前上手流程（约6步）
```
1. git clone
2. 安装Python依赖（uv sync）
3. 安装前端依赖（npm install）
4. 配置.env（LLM API key）
5. 初始化数据库（python init_db.py）
6. 启动前后端（两个终端）
```

### 建议改进
```
建议增加：
- make dev 或 ./start.sh 一键启动
- .env.example 含每个变量的注释说明
- docs/CONTRIBUTING.md（扩展开发快速模板）
- extensions/_template/ 骨架扩展（含5个文件的最小实现）
- Hub "开发者模式" 入口（查看当前extension注册状态、tool列表、bus事件日志）
```

---

## 6. 优先行动项

| 优先级 | 行动 | 工作量 | 参考 |
|--------|------|--------|------|
| **P1** | 扩展配置Valves自动渲染UI | 中 | Open WebUI |
| **P1** | Hub扩展Tab：加载/状态/配置面板 | 中 | SillyTavern市场思路 |
| **P1** | `extensions/_template/`骨架扩展 | 小 | opencode工具定义钩子 |
| **P1** | `docs/CONTRIBUTING.md` | 小 | — |
| **P2** | Permission ask事件流（前端确认Modal） | 中 | opencode |
| **P2** | moduleRegistry统一Modal注册 | 小 | MoRanJiangHu |
| **P2** | MCP Bridge达到生产级（OAuth+状态UI）| 大 | opencode |
