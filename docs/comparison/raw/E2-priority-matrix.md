## 横向综合建议（针对 zero-arsenal 的优先级矩阵）

基于三个平台的共同启示，以下是最值得立即实施的模式，按 **影响×实施成本** 排序：

### 🔴 高优先级 · 低成本（本迭代可做）

| 模式 | 参考来源 | 具体实施 |
|---|---|---|
| **Session创建Mode选择 + 一句话描述** | KoboldCpp | 新建Session第1步：4种类型卡片，每张附一句适用场景说明 |
| **所有危险操作加内联Warning** | KoboldCpp | 删除/重置/切换世界旁显示一行小字说明影响，无需弹窗 |
| **所有表单字段加Placeholder示例** | NovelAI | Memory字段风格：不是"请输入..."而是具体的示例填写提示 |
| **首次登录主题选择** | KoboldCpp | 4张主题预览卡，选完写localStorage，Hub立即变色 |
| **空状态加分类创建入口** | NovelAI+Chub | 世界/角色/Session各为空时，显示分类图标+简短说明而不是单个"+"按钮 |

### 🟡 高优先级 · 中等成本（下迭代）

| 模式 | 参考来源 | 具体实施 |
|---|---|---|
| **官方Quick Start场景模板库** | KoboldCpp+NovelAI | 5-6个完整可导入场景包（配合现有muv_luv/crossover扩展） |
| **角色创建必填"开场白"字段** | Chub.ai | 新建NPC时必填Initial Message，作为Session首条AI输出 |
| **Session状态指示器（自动保存）** | KoboldCpp | 顶部显示"已自动保存 X秒前"，消除丢失焦虑 |
| **AI辅助生成世界条目** | NovelAI Lore Generator | 对接现有add_lore MCP工具，前端封装"AI帮我填写"按钮 |

### 🟢 中等优先级 · 中等成本（规划中）

| 模式 | 参考来源 | 具体实施 |
|---|---|---|
| **角色创建的高级模式开关** | Chub.ai V2 Spec | 普通模式3个必填字段，高级模式展开完整psyche_model_json |
| **ChapterTree发现性优化** | Chub.ai Chat Tree | 工具栏加持久可见树形图标，初次出现Tooltip介绍功能 |
| **Chat Memory摘要面板** | Chub.ai | Session界面显示AI当前记忆摘要，提供"刷新摘要"按钮 |
| **设置面板分组折叠** | KoboldCpp | Session设置按外观/行为/AI参数/高级/实验性分组，高级默认折叠 |