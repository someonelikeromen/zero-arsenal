# 报告六：UX 差距分析与行动计划

> 生成时间：2026-06-03 | 数据来源：所有子代理 D13 维度汇总

这是本次调研最核心的产出——回答「其他项目有、我们没有或可以更友好」的完整清单，并给出优先级排序与具体实施方案。

---

## 1. 差距全景图

```
本地参考项目（可直接移植）
  MoRanJiangHu   → Toast栈 ★★★ | InAppConfirmModal ★★★ | SectionCollapse ★★★ | 五步向导参考 ★★
  ai-vn-game-system → UIFeedback层 ★★★ | 三步开局向导 ★★★ | welcome双CTA ★★★ | hint-text ★★
  ai-vn-system-backend → 状态机placeholder ★★★ | quick模板六卡片 ★★ | 能力badge空状态 ★★

外部竞品（最佳实践）
  SillyTavern    → 最低必填门槛 ★★★ | Advanced折叠 ★★★ | First Message自动触发 ★★★ | LED指示 ★★
  KoboldCpp      → 首次主题选择 ★★★ | 模式一句话描述 ★★★ | 危险操作内联Warning ★★★
  Open WebUI     → # 触发知识库 ★★★ | Valves自动配置UI ★★
  NovelAI        → Lore Generator AI填充 ★★ | Genre&Tags多选chip ★★
  Chub.ai        → Initial Message必填 ★★★ | V2 Spec高级模式开关 ★★
```

---

## 2. P0 行动项（本Sprint，成本极低，收益极高）

### P0-1：接线 Toast 通知系统

**现状**：`useUIStore.addNotification` 已定义，全项目零调用，无Toast UI渲染。
**参考**：MoRanJiangHu `notificationSystem.ts`（自研轻量，限4条，4200ms自动消失，三色tone）

**实施方案**：
```tsx
// 1. 在 App.tsx 或 SessionPage.tsx 末尾添加 ToastStack 组件
// 2. 组件从 useUIStore.notifications 读取数据渲染
// 3. 在以下操作后调用 addNotification：
//    - 创建/删除 世界/角色/会话 成功/失败
//    - 存档保存
//    - API Key测试结果
//    - 文件导入/导出

// Toast样式：fixed bottom-4 right-4，最多4条，有success/error/info三色
```

**工作量**：约2-4小时 | **影响**：高（每个操作有了反馈，消除操作成功/失败的不透明感）

---

### P0-2：统一确认对话框（替换 window.confirm）

**现状**：删除世界/角色/会话等危险操作使用`window.confirm`，样式与应用不一致，无法自定义按钮文案。
**参考**：MoRanJiangHu `useConfirmSystem.tsx` + `InAppConfirmModal.tsx`

**实施方案**：
```tsx
// 1. 创建 useConfirmDialog hook
const { requestConfirm } = useConfirmDialog()
// 2. 调用方式
const confirmed = await requestConfirm({
  title: "删除会话",
  message: `确认删除「${session.name}」？此操作不可撤销。`,
  confirmText: "删除",
  cancelText: "取消",
  danger: true  // 确认按钮显示为红色
})
// 3. 根组件挂载 ConfirmDialogModal（z-index最高层）
```

**工作量**：约3-4小时 | **影响**：高（品质感 + 防误操作）

---

### P0-3：危险操作内联 Warning 文字

**现状**：设置内某些破坏性操作（重置/清空/覆盖）无任何警告。
**参考**：KoboldCpp「Don't change this halfway through a story!」内联红色小字

**实施方案**：
```tsx
// 在各危险操作按钮下方/旁边添加一行小字
<button onClick={handleReset}>重置对话</button>
<p className="text-xs text-amber-500 mt-1">
  此操作将清空当前会话的所有消息，无法恢复
</p>
```

**工作量**：约1-2小时 | **影响**：高（防止误操作，成本最低的安全改进）

---

### P0-4：首次进入检测 + 顶部 Banner

**现状**：API Key未配置时，等到第一次生成才报错。新用户不知道需要先配置LLM。
**参考**：Open WebUI首次进入顶部模型配置Banner

**实施方案**：
```tsx
// HubPage 顶部：检测 settingsStore.llmConfigured 为 false 时显示
<Banner type="warning">
  未检测到 AI 模型配置。
  <Link to="/settings/llm">立即配置</Link>
  才能开始创作。
</Banner>
```

**工作量**：约1-2小时 | **影响**：高（消除新用户最常见的失败路径）

---

### P0-5：Hub 会话 Tab 重构（列表+创建合并）

**现状**：Sessions Tab只有创建按钮，历史会话在「存档」Tab，两处割裂。
**参考**：所有竞品均将创建和历史放在同一个视图。

**实施方案**：Sessions Tab显示会话列表（最近N条+搜索），顶部有「新建会话」按钮，「存档」Tab改为「章节快照」（仅存chapter_anchors）。

**工作量**：约4-6小时 | **影响**：高（IA核心问题修复）

---

## 3. P1 行动项（下Sprint，成本小-中，收益高）

### P1-1：Session 创建向导（4步）

**现状**：单页表单，无引导，无开场生成。
**参考**：ai-vn-game-system 三步向导 + MoRanJiangHu 五步向导

**建议的4步结构**：
```
Step 1: 选择游戏类型
  - TRPG战役（有GM/规则裁判/骰子）
  - 单人RP（沉浸式角色扮演）  
  - AI写作协作（长篇叙事）
  - 沙盒探索（开放世界）
  每个选项配一句话说明 ← 学KoboldCpp模式描述

Step 2: 选择或创建世界
  - 从已有世界模板选择（卡片展示，有预览）
  - 快速创建（仅填世界名+世界类型chip）
  - 从官方模板库加载 ← P2功能，先占位

Step 3: 选择或创建主角
  - 从已有角色选择
  - 快速创建（仅名称必填）
  - 跳过（AI随机生成）

Step 4: 开局设定
  - 开场情境描述（可选，有placeholder示例）
  - 或选择开局预设（如：城市街头/废土废墟/校园）
  - 「生成并开始」按钮 ← AI生成第一条叙事
```

**工作量**：约2-3天 | **影响**：极高（直接解决新手最大摩擦点）

---

### P1-2：First Message 自动触发

**现状**：会话创建后，Session页面显示空白聊天区，用户不知道输什么。
**参考**：SillyTavern / Chub.ai — 进入会话NPC先发第一条消息

**实施方案**：
1. `WorldPlugin`扩展支持`opening_scene`字段（一段开场描述，AI格式化）
2. `CharacterCreator`添加`first_message`字段（角色的开场独白）
3. 会话创建后自动调用NarratorAgent生成开场叙事
4. 开场叙事以`Part.narrative`形式推送到SessionPage

**工作量**：约1天（后端1-2个API端点 + 前端自动触发逻辑）| **影响**：高

---

### P1-3：文风选择器 UI（接线38个已有Skills）

**现状**：`GET /config/writing-styles`已实现，38个writing-styles已注册为Skills，前端无UI入口（STUB_ANALYSIS标注为死API）。
**参考**：noveldemo文风README的四层分类（骨架/节奏/心理/温度）

**实施方案**：
```
Session 创建向导 Step 4 或 Session 页右侧面板：
文风配置区
├─ 骨架层（必选一）：网文 / 零度写作 / 紙芝居 / 江南式 ...
├─ 节奏层（默认激活）：小此爽写 / 节奏大师 ...
└─ [折叠] 高级层：心理层 / 温度层

→ 选择后 PUT /sessions/{id}/writing-styles
→ SessionNarrator 的 style 节点应用选中文风
```

**工作量**：约1-2天 | **影响**：高（unlock已有功能，对老手价值极大）

---

### P1-4：输入框状态机 Placeholder

**现状**：输入框placeholder为静态「输入你的行动...」
**参考**：ai-vn-system-backend — 按状态切换四种placeholder

**实施方案**：
```typescript
const placeholderMap = {
  no_llm_config:   "请先在设置中配置 AI 模型...",
  no_world:        "请先选择或创建一个世界...",
  no_session:      "请先创建一个会话...",
  generating:      `${currentAgent} 正在思考...`,
  ready:           "输入你的行动，或 /help 查看指令...",
}
```

**工作量**：约1-2小时 | **影响**：中高（明确告知用户当前状态）

---

### P1-5：角色创建"最低门槛"模式

**现状**：5步向导对快速体验而言偏重。
**参考**：SillyTavern — 只有名称必填，其余全可选

**实施方案**：CreatorModal 增加「快速创建」入口，一个输入框（角色名）+ 一个下拉（角色类型：人类/机器人/精灵等）→ 点击「创建」→ AI自动生成最小档案（基于名称+类型推断）→ 进入会话可随时回来完善。

**工作量**：约半天 | **影响**：中（降低初次使用摩擦）

---

### P1-6：设置面板基础/高级分层

**现状**：七Tab平铺，MCP/Scraper等高级功能和基础LLM设置并列。
**参考**：KoboldCpp Experimental分区 + SillyTavern Mad Lab Mode

**实施方案**：
```
Settings 分组：
基础设置
  └─ AI 模型配置（已有，重命名）
  └─ 界面主题（接线现有store）
  └─ 快捷键

[折叠] 高级设置
  └─ Prompt 管理
  └─ LLM 路由详情

[折叠⚠️] 实验性功能
  └─ MCP 工具（标注 BETA）
  └─ 网络抓取规则
```

**工作量**：约半天 | **影响**：中（降低新用户被高级选项压倒的焦虑）

---

## 4. P2 行动项（规划中，成本中-大）

| 编号 | 行动 | 参考来源 | 工作量 | 影响 |
|------|------|---------|--------|------|
| P2-1 | 官方 Quick Start 场景模板库（5-6个完整可导入包）| KoboldCpp + NovelAI | 大（内容制作+导入机制）| 高 |
| P2-2 | AI辅助世界条目生成（Lore Generator）| NovelAI Lore Generator | 中（前端封装现有add_lore MCP）| 高 |
| P2-3 | 取消生成按钮 + SSE可靠断线续传 | SillyTavern Stop按钮 | 大 | 中高 |
| P2-4 | 角色/世界 PNG 卡格式导入导出 | SillyTavern / Chub.ai | 中 | 中 |
| P2-5 | 世界条目触发关键词可视化 | SillyTavern Lorebook | 小 | 中 |
| P2-6 | 输入框 # 触发知识库注入 | Open WebUI RAG | 小 | 中 |
| P2-7 | 首次登录主题选择引导（3张预览卡）| KoboldCpp | 小 | 中 |
| P2-8 | Session顶栏：当前模型+token估算 | 多竞品 | 小 | 中 |
| P2-9 | 叙事气泡内嵌 LED 状态指示（生成中/完成/错误）| SillyTavern | 小 | 中 |
| P2-10 | 多备选回复 Swipe（ChapterTree分支）| SillyTavern / Open WebUI | 大 | 中 |
| P2-11 | 扩展 Valves 自动配置 UI | Open WebUI | 中 | 开发者体验 |
| P2-12 | 角色/会话"开场白"必填字段 | Chub.ai Initial Message | 小（字段+触发逻辑）| 中 |

---

## 5. 本地项目直接移植清单

以下来自本地前身项目，代码可直接参考或复制，无需从头设计：

| 来源 | 功能 | 源文件 | 移植工作量 |
|------|------|--------|-----------|
| MoRanJiangHu | InAppConfirmModal + useConfirmSystem | `hooks/useConfirmSystem.tsx` | **极小** |
| MoRanJiangHu | Toast通知栈 | `hooks/useGame/ui/notificationSystem.ts` | **极小** |
| MoRanJiangHu | SectionCollapse渐进披露 | `components/ui/SectionCollapse.tsx` | **极小** |
| MoRanJiangHu | 空状态组件（title+desc+dashed border）| `imageManagerHelpers.tsx` | **极小** |
| ai-vn-game-system | UIFeedback层（toast/confirmDanger/renderEmpty）| `public/ui-feedback.js` | 小（需改写为React）|
| ai-vn-game-system | welcome-screen双CTA | `public/index.html` | 小 |
| ai-vn-game-system | 三步会话创建向导结构 | `public/app.js modalNewGame` | 中（需React化）|
| ai-vn-game-system | hint-text动态上下文 | `public/character.js NG_TYPE_HINTS` | 小 |
| ai-vn-system-backend | quick模板六卡片 | `ProtagonistGeneratorModal.jsx` | 小（已是React）|
| ai-vn-system-backend | 状态机placeholder | `frontend/src/App.jsx` | **极小** |
| ai-vn-system-backend | STEP工作流侧栏（SSE高亮当前节点）| `frontend/src/components/` | 中 |

---

## 6. 综合优先度矩阵（影响×成本）

```
高影响
  │
  │  [P0] Toast接线      [P0] 首次检测Banner   [P1] 会话创建向导
  │  [P0] 确认框统一     [P1] First Message    [P1] 文风选择器
  │  [P0] 危险Warning    [P0] Hub会话Tab重构   [P2] 官方模板库
  │
  │  [P1] 状态机Placeholder  [P1] 高级设置折叠  [P2] Lore Generator
  │  [P1] 最低门槛创建                          [P2] 取消生成
  │
低影响
  ├──────────────────────────────────────────────────────────
     低成本（<4h）      中成本（1-3天）        高成本（>1周）
```

**最高ROI区域**（右上象限中的P0任务）：5个P0项合计约12-18小时工作，能将新手友好度从2/5提升至3.5/5。
