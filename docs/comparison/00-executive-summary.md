# 报告零：执行摘要

> 生成时间：2026-06-03 | 覆盖项目：9个（4本地前身 + 5外部竞品）

---

## TL;DR（一句话）

**zero-arsenal 的技术架构和核心功能已超越大多数竞品，但新手体验严重落后（2/5 vs 竞品均值 3.8/5），主要原因是5个高价值、低成本的基础 UX 组件尚未接线，修复成本合计约 12-18 小时。**

---

## 竞争位置快照

```
技术深度  zero-arsenal ████████░░  8/10  （多Agent+骰子引擎+扩展系统，竞品罕见）
功能完整  zero-arsenal ██████░░░░  6/10  （核心功能齐但文风/主题/移动端缺）
新手体验  zero-arsenal ████░░░░░░  4/10  （竞品均值7/10，差距最大）
开发扩展  zero-arsenal ███████░░░  7/10  （扩展系统完整，文档和热加载偏弱）
自定义   zero-arsenal █████░░░░░  5/10  （LLM路由完整；主题/文风UI缺失）
```

---

## 核心发现（跨6个子代理）

### 发现1：基础设施完备但未接线（内部债务）

| 已有但未用 | 位置 | 修复成本 |
|-----------|------|---------|
| `useUIStore.addNotification` Toast基础设施 | `frontend/stores/useUIStore.ts` | **2小时** |
| dark/light主题切换store | `useUIStore.setTheme` | **2小时** |
| 38个writing-styles HTTP API | `GET /config/writing-styles` | **1天** |
| `CharacterCreator`5步向导（仅角色，无会话对等向导）| `components/CharacterCreator.tsx` | 参考已有设计 |

**结论**：最高ROI的改进不是新功能，是"把已写好的东西接上"。

### 发现2：竞品的新手策略可分三类

| 策略 | 代表 | zero-arsenal当前状态 |
|------|------|---------------------|
| **内容驱动**（社区内容消除空白）| Chub.ai | ✗ 无社区 |
| **向导驱动**（分步引导完成配置）| MoRanJiangHu / KoboldCpp | △ 仅角色有5步向导 |
| **零门槛驱动**（立刻可用）| SillyTavern（Temp Chat）| ✗ 需5步配置 |

**建议**：short-term走**向导驱动**（成本可控）；long-term考虑**内容驱动**（官方模板库）。

### 发现3：本地前身项目是最快的移植来源

MoRanJiangHu 和 ai-vn-game-system 已解决了 zero-arsenal 当前最紧迫的 UX 问题，代码已存在于 `E:\plu\` 目录，移植成本极低：

| 功能 | 来源 | 零距离移植（直接参考） |
|------|------|----------------------|
| Promise式InAppConfirmModal | MoRanJiangHu | ✓ |
| 右下角Toast栈（限4条+三色） | MoRanJiangHu | ✓ |
| SectionCollapse渐进披露 | MoRanJiangHu | ✓ |
| welcome-screen双CTA | ai-vn-game-system | ✓ |
| 状态机输入框placeholder | ai-vn-system-backend | ✓ |

### 发现4：zero-arsenal 拥有竞品无法复制的核心壁垒

- **确定性骰子引擎（d10骰池+seed复现+JSONL审计）**：所有竞品无原生TRPG引擎
- **多Agent流水线（LangGraph 8节点）**：竞品为单LLM或简单链
- **三级权限模式（play/plan/review）**：面向GM+玩家协作场景独有
- **积分/抽卡经济系统（GachaEngine）**：完全独创的TRPG电商融合

这些壁垒是zero-arsenal的核心差异化，应在新手引导中主动宣传（如Welcome Screen展示「确定性骰子」「多Agent编排」等能力badge，参考ai-vn-system-backend的WelcomeScreen能力badge设计）。

---

## P0 立即行动（本Sprint，≈12-18小时）

| # | 行动 | 预估工时 | 预期效果 |
|---|------|---------|---------|
| 1 | **接线Toast通知UI**（useUIStore.addNotification已有） | 2-4h | 所有操作有成功/失败反馈 |
| 2 | **统一确认对话框**（替换window.confirm） | 3-4h | 删除操作品质感+防误操作 |
| 3 | **危险操作内联Warning文字** | 1-2h | 防误操作成本最低的改进 |
| 4 | **首次进入LLM配置检测+Banner** | 1-2h | 消除新用户首次失败路径 |
| 5 | **Hub会话Tab合并列表+创建** | 4-6h | 修复核心IA问题 |
| | **合计** | **~12-18h** | **新手体验 2/5 → 3.5/5** |

---

## P1 下一迭代（≈5-8天）

| # | 行动 | 预估工时 |
|---|------|---------|
| 1 | 会话创建4步向导（含游戏类型选择+模式描述） | 2-3天 |
| 2 | First Message自动触发（NPC开场白机制） | 1天 |
| 3 | 文风选择器UI（接线38个已有Skills） | 1-2天 |
| 4 | 状态机输入框placeholder（4种状态） | 2-4h |
| 5 | 设置面板基础/高级分层（折叠MCP/Scraper） | 4-8h |
| 6 | 角色创建最低门槛快速模式 | 4-8h |

---

## P2 规划中（≈2-4周）

| # | 行动 | 影响 |
|---|------|------|
| 1 | 官方Quick Start模板库（5-6个完整场景包）| 高（对标KoboldCpp）|
| 2 | AI辅助Lore Generator（封装现有add_lore MCP） | 高（对标NovelAI）|
| 3 | 取消生成按钮 + SSE可靠续传 | 中高 |
| 4 | 叙事气泡内嵌LED状态指示 | 中（对标SillyTavern）|
| 5 | 角色/世界PNG卡导入导出 | 中（互操作性）|
| 6 | 扩展Valves自动配置UI | 中（开发者体验）|
| 7 | 首次登录主题选择引导 | 中（对标KoboldCpp）|
| 8 | # 触发Lorebook注入 | 中（对标Open WebUI）|

---

## 参考报告

| 报告 | 文件 |
|------|------|
| 架构与代码质量对比 | `01-architecture-code-quality.md` |
| UI/UX深度分析 | `02-ui-ux-analysis.md` |
| 功能完整度矩阵 | `03-feature-completeness-matrix.md` |
| 用户旅程对比 | `04-user-journey-comparison.md` |
| 开发者与扩展体验 | `05-developer-extension-experience.md` |
| UX差距与行动计划 | `06-ux-gap-action-plan.md` |
| 原始数据缓存 | `raw/` 目录（6份JSON）|
