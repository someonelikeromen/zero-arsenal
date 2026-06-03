# 报告三：功能完整度矩阵

> 生成时间：2026-06-03 | 数据来源：全部子代理 D06 维度

图例：✓ 完整实现 | △ 部分/基础 | ✗ 缺失 | ？ 未知/不适用

---

## 1. 核心功能矩阵

| 功能模块 | zero-arsenal | ai-vn-game-system | ai-vn-system-backend | MoRanJiangHu | SillyTavern | Open WebUI | NovelAI | Chub.ai | KoboldCpp |
|----------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **会话/存档管理** | △ | ✓ | △ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **多Agent流水线** | ✓ | △ | ✓ | △ | ✗ | △ | ✗ | ✗ | ✗ |
| **确定性骰子引擎** | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | △(宏) | ✗ |
| **SSE流式输出** | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **中断/重试生成** | △ | △ | △ | △ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **四层记忆系统** | △ | ✗ | △ | △ | △(Lorebook) | △(RAG) | △(Lorebook) | △ | △ |
| **世界插件/扩展** | △ | ✗ | ✗ | △ | △(Extensions) | △(Pipelines) | ✗ | ✗ | ✗ |
| **角色创建向导** | ✓ | ✓ | ✓ | ✓ | △ | △ | △ | △ | △ |
| **世界/背景创建** | △ | △ | △ | ✓ | △(Lorebook) | △(Knowledge) | △(Lorebook) | △ | △ |
| **开局/会话向导** | △ | ✓ | △ | ✓ | ✗ | ✗ | ✗ | ✗ | △ |
| **图像生成** | ✗ | ✗ | ✗ | ✓ | △(扩展) | △(内置) | ✗ | ✗ | ✗ |
| **多模型支持** | △ | △ | △ | ✓ | ✓ | ✓ | ✗(自有) | ✓ | ✓(本地) |
| **主题/深色模式** | △ | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **文风选择器UI** | ✗ | ✗ | ✗ | △ | ✗ | ✗ | △ | ✗ | ✗ |
| **抽卡/积分系统** | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **MCP工具集成** | △ | ✗ | ✗ | ✗ | ✗ | △ | ✗ | ✗ | ✗ |
| **云同步/备份** | ✗ | ✗ | ✗ | △(GitHub) | ✗ | ✓(多用户) | ✓(云端) | ✓(云端) | △(本地自动) |
| **移动端适配** | ✗ | ✗ | ✗ | △(Capacitor) | △ | ✓ | ✓ | ✓ | △ |
| **社区角色库** | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | △(Scenarios) | ✓ | △(场景) |
| **PNG角色卡导入/导出** | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✓ | ✗ |
| **多人/GM模式** | ✗ | ✗ | ✗ | ✗ | ✗ | △(多用户) | ✗ | ✗ | ✗ |
| **提示词管理UI** | △ | △ | △ | ✓ | ✓ | ✓ | △ | ✗ | ✓ |
| **扩展/插件开发** | ✓ | ✗ | ✗ | △ | ✓ | ✓ | ✗ | ✗ | ✗ |
| **自动测试套件** | △ | ✗ | △ | △ | △ | ✓ | ✗ | ✗ | ✗ |

---

## 2. zero-arsenal 功能完整度详细分析

### 2.1 已完整实现 ✓
- **8节点多Agent流水线**：rules→dm→parallel_npc_world→narrator→style→var→chronicler，LangGraph完整编排
- **d10确定性骰子引擎**：骰池、seed可复现、JSONL审计只追加，原生TRPG体验
- **SSE + PartRenderer**：17种Part类型，高频直引+低频lazy，Part状态机
- **扩展系统**：manifest声明式 + plugin/tools/hooks生命周期，零侵入
- **角色创建向导**：5步CreatorModal（quick/quiz/background→填表→SSE预览→保存）
- **抽卡/积分系统**：GachaEngine完整，后端API健全

### 2.2 部分实现 △（含待修复项）

| 模块 | 现状 | 差距 |
|------|------|------|
| 会话管理 | 后端完整；前端会话Tab只创建不列表，历史在存档Tab | Hub会话Tab合并列表+创建 |
| 记忆系统 | 四层召回实现；ChromaDB降级SQLite | Redis stub；无进度UI |
| 世界插件 | crossover/wuxia/infinite_arsenal较完整 | muv_luv/gundam_seed有STUB |
| Hub UI | 七Tab功能齐 | 信息架构分散；MCP面板stub |
| 主题系统 | dark/light store存在 | setTheme无UI调用，CSS固定暗色 |
| 中断生成 | 10s超时解锁 | 无取消按钮；SSE断线续传stub |
| 多模型 | LiteLLM支持；LlmRoutesTab可配 | 仅deepseek/openai为主；无状态指示 |

### 2.3 缺失 ✗（按影响排序）

| 功能 | 竞品现状 | 移植难度 | 建议来源 |
|------|----------|----------|----------|
| **Toast通知UI**（基础设施已有但未接线）| 所有竞品均有 | **极小** | 自研接线即可 |
| **文风选择器UI** | MoRanJiangHu有简单版 | 中 | 38个Skills已注册，前端接线 |
| **图像生成** | MoRanJiangHu完整实现 | 大 | 可作为扩展插件形式引入 |
| **PNG角色卡导入/导出** | SillyTavern / Chub.ai | 中 | 提升互操作性 |
| **云同步/备份UI** | MoRanJiangHu(GitHub)、商业产品 | 中-大 | 可参考MoRanJiangHu分卷方案 |
| **移动端适配** | MoRanJiangHu(Capacitor) | 大 | 低优先级 |
| **社区角色库** | Chub.ai为最佳 | 极大 | 长期目标 |

---

## 3. zero-arsenal 独有优势（竞品未有）

| 优势 | 描述 | 竞争壁垒 |
|------|------|----------|
| **确定性骰子引擎** | d10骰池 + seed复现 + JSONL审计，骰子结果不可被叙事篡改 | 高——竞品无原生TRPG引擎 |
| **多Agent流水线可视化** | LangGraph 8节点，各Agent职责清晰，可独立调参 | 高——竞品LLM单路或简单链 |
| **三级权限模式** | play/plan/review分离，review模式禁止掷骰/写叙事 | 高——面向创作协作场景 |
| **扩展WorldPlugin** | 每个插件有独立manifest、工具、钩子、技能，可热加载 | 中高——SillyTavern Extensions类似但更重 |
| **抽卡+积分经济** | GachaEngine + 商城UI，与叙事整合 | 高——独创TRPG电商融合 |

---

## 4. 近期功能补全路线图

```
P0（本Sprint）
├─ 接线 Toast/Confirm 基础设施（已有代码，只需连接）
├─ 修复 rules_agent 失败默认pass
└─ Hub 会话Tab 列表+创建合并

P1（下Sprint）
├─ 文风选择器UI（38 Skills数据已有）
├─ 会话创建多步向导（参考 ai-vn-game-system 三步结构）
├─ 首条叙事自动生成（参考 SillyTavern First Message）
└─ 设置面板 基础/高级 分层

P2（规划中）
├─ 取消生成按钮 + SSE可靠续传
├─ 角色/世界 PNG 导入导出
├─ 图像生成扩展插件
└─ 移动端响应式布局
```
