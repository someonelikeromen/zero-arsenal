# 报告二：UI/UX 深度分析

> 生成时间：2026-06-03 | 数据来源：全部子代理 D03+D04+D05+D07 维度

---

## 1. 信息架构（IA）对比

| 项目 | 主布局模式 | 导航层级 | 核心视图数 | IA 评分 |
|------|-----------|----------|-----------|---------|
| **zero-arsenal** | Hub七Tab + Session三栏（左ChapterTree\|中MessageThread\|右面板组） | 2 | 2（Hub / Session） | 3.5/5 |
| **ai-vn-game-system** | MPA多页（index/hub/shop/character/preset/settings） | 2 | 6 | 3/5（跨页跳转割裂） |
| **ai-vn-system-backend** | 三栏TRPG（left属性\|center聊天\|right工作流步骤） | 2 | 1主界面+Modals | 4/5 |
| **MoRanJiangHu** | home→new_game全屏向导→game三栏；无react-router | 2 | 3+大量Modal | 3.5/5（Modal泛滥）|
| **SillyTavern** | 中央聊天 + 右侧抽屉面板 + 顶部图标工具栏 | 3 | 1+抽屉 | 4/5 |
| **Open WebUI** | 左侧边栏历史+右侧聊天+顶部模型选择器 | 3 | 2（聊天/Workspace） | 4.5/5 |
| **NovelAI** | 三栏（Story库\|编辑器\|Story/Lorebook/Config Tab） | 3 | 1编辑器 | 4/5 |
| **Chub.ai** | Venus库+Mars对话+Mercury API三产品线；角色卡为核心 | 3 | 3 | 4/5 |
| **KoboldCpp** | 中央文本编辑 + 弹窗设置 + 首次主题选择 | 2 | 1 | 3.5/5 |

**关键观察**：zero-arsenal的Hub七Tab在信息架构上略微分散，会话创建与会话历史分离于不同Tab（会话Tab只创建，历史在存档Tab）是最突出的IA问题。

---

## 2. 首次使用步骤数对比

| 项目 | 首次可操作步骤数 | 首次可操作性评分 |
|------|-----------------|-----------------|
| **SillyTavern** | **2步**（进入→Temporary Chat即可输入） | 5/5 |
| **Chub.ai** | 4步（注册→浏览→点击角色→Chat） | 4/5（但API配置是隐藏障碍）|
| **KoboldCpp** | 3步（选主题→选模式→输入） | 4.5/5 |
| **Open WebUI** | 3步（注册→选模型→输入） | 4/5 |
| **NovelAI** | 3步（登录→模式选择→编辑器） | 3.5/5 |
| **MoRanJiangHu** | **5步**（进入→新游戏→五步向导→AI生成→游玩） | 3.5/5 |
| **ai-vn-game-system** | 5步（配置hub→选主角→选世界→存档→开始） | 3.5/5 |
| **zero-arsenal** | **5步**（配置LLM→创建世界→创建角色→创建会话→输入） | 2/5（无引导，用户自行探索）|
| **ai-vn-system-backend** | 5步 | 3/5 |

---

## 3. 流式输出 UX（D07）

| 项目 | 流式渲染 | 停止按钮 | 多备选Swipe | 内联状态指示 | 评分 |
|------|----------|----------|------------|-------------|------|
| **SillyTavern** | ✓ 逐token | ✓ 红色+保留内容 | ✓ 左右滑动 | ✓ 气泡内LED点 | 5/5 |
| **Open WebUI** | ✓ 多模型并排 | ✓ 方块图标 | △ 分支导航 | △ 打字光标 | 4.5/5 |
| **NovelAI** | ✓ | ✓ | ✗ | △ | 4/5 |
| **zero-arsenal** | ✓ SSE+17种Part类型 | ✗（无取消按钮！） | ✗ | △（InputBar显示Agent名+脉冲点）| 3/5 |
| **MoRanJiangHu** | ✓ | △ | ✗ | △ | 3/5 |
| **ai-vn-game-system** | ✓ SSE | △ | ✗ | ✗ | 2.5/5 |

**zero-arsenal的SSE架构已是最精细的**（17种Part类型 + PartRenderer + 可折叠reasoning/tool），但缺少用户最基本的"取消生成"操作。

---

## 4. 主题/自定义深度

| 项目 | 主题切换 | 自定义CSS | 命名主题 | 即选即生效 |
|------|----------|----------|----------|-----------|
| **SillyTavern** | ✓ 深度极高 | ✓ 完整CSS编辑器 | ✓ | ✓ |
| **KoboldCpp** | ✓ | ✓ | ✓（Modern/Nostalgia/Tako等）| ✓ |
| **MoRanJiangHu** | ✓（5+主题+CSS变量）| ✗ | ✓（ink/azure/ember等）| ✓ 实时预览 |
| **Open WebUI** | △（浅色/深色+主题色）| ✗（普通用户）| ✗ | ✓ |
| **zero-arsenal** | △（store存在但无UI调用）| ✗ | ✗ | ✗ |
| **ai-vn-game-system** | ✗ | ✗ | ✗ | — |

**zero-arsenal的主题基础设施已存在**（dark/light在useUIStore），只需约3小时工作接线UI开关 + 整理light模式CSS变量即可对齐竞品基本水平。

---

## 5. 设置面板分层对比

| 项目 | 分层策略 | 新手/专家模式 | 高级折叠 |
|------|----------|--------------|---------|
| **SillyTavern** | 章节分组 + Zen Sliders/Mad Lab Mode一键切换 | ✓ | ✓ Advanced Definitions |
| **KoboldCpp** | Appearance/Context/Sampling/Advanced/Experimental五层；Experimental有Risk警告 | △ | ✓ Advanced默认折叠 |
| **Open WebUI** | Admin Settings vs User Settings双层架构 | ✓ | ✓ |
| **MoRanJiangHu** | 20+ Tab分域（api/image/prompt/theme等） | ✗（无基础/高级开关）| ✗ |
| **zero-arsenal** | 七子Tab平铺 | ✗ | ✗ |

**建议**：zero-arsenal设置面板采用KoboldCpp的Experimental分组模式：
```
基础 → AI参数 → 提示词 → [折叠]高级 → [折叠⚠️]实验性
```

---

## 6. 空状态设计质量评分

| 项目 | 空状态覆盖率 | 设计质量 | 有CTA按钮 | 有引导文案 |
|------|------------|---------|----------|----------|
| **Open WebUI** | 高 | ✓ 带图标引导卡片 | ✓ | ✓ |
| **Chub.ai** | 高（靠社区内容天然消除）| ✓ | ✓ | △ |
| **MoRanJiangHu** | 中 | ✓ 统一组件 | ✓ | ✓ |
| **ai-vn-game-system** | 中 | ✓ welcome-screen双CTA | ✓ | ✓ |
| **zero-arsenal** | 低-中 | △ 纯文字「暂无...」 | △ 部分有 | ✗ |
| **SillyTavern** | 低 | △ | ✓ | ✗ |
| **NovelAI** | 低 | △ | ✓ | ✗ |

---

## 7. 上手难度综合评分

| 项目 | 新手友好度 | 老手效率 | 综合 |
|------|-----------|---------|------|
| **KoboldCpp** | 4.5 | 3.5 | 4.0 |
| **SillyTavern** | 3.5（学习曲线陡）| 5.0 | 4.3 |
| **Open WebUI** | 4.0 | 4.5 | 4.3 |
| **Chub.ai** | 4.0 | 3.5 | 3.8 |
| **MoRanJiangHu** | 3.5 | 4.0 | 3.8 |
| **NovelAI** | 3.0 | 4.5 | 3.8 |
| **ai-vn-game-system** | 3.5 | 3.5 | 3.5 |
| **zero-arsenal** | **2.0** | **3.5** | **2.8** |
| **ai-vn-system-backend** | 2.5 | 3.0 | 2.8 |

**结论**：zero-arsenal的架构和功能深度已达到或超越多数竞品，但新手友好度严重落后，主要问题集中在：无引导→无演示→无即时反馈三点。

---

## 8. 各项目最佳UI模式速查

| 模式 | 最佳实现 | 移植难度 |
|------|----------|---------|
| 气泡内嵌LED状态指示 | SillyTavern | 小 |
| First Message自动触发 | SillyTavern / Chub.ai | 小 |
| 最低门槛创建（名称唯一必填）| SillyTavern | 小 |
| 首次主题选择弹窗 | KoboldCpp | 小 |
| 模式一句话描述 | KoboldCpp | 小 |
| 危险操作内联Warning文字 | KoboldCpp | 小 |
| # 触发知识库注入 | Open WebUI | 小 |
| Advanced折叠 | SillyTavern / KoboldCpp | 小 |
| Toast通知系统 | MoRanJiangHu（自研轻量）| 小 |
| Promise式确认框 | MoRanJiangHu useConfirmSystem | 小 |
| 会话创建多步向导 | MoRanJiangHu / ai-vn-game-system | 中-大 |
| 文件夹即工作区 | Open WebUI | 中 |
| Valves自动配置UI | Open WebUI | 中 |
| PNG角色卡单文件 | SillyTavern | 大 |
