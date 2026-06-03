# 零度武库 (Zero Arsenal)

AI 跑团小说工具 — 多 Agent · 确定性骰子 · 可扩展世界插件

## 快速启动

### 后端

```bash
# 安装依赖（建议 Python 3.11+，uv 或 pip）
cd zero-arsenal
pip install -e "backend/[dev]"

# 复制环境变量
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY

# 启动开发服务器
python -m backend.main
# 或
uvicorn backend.main:app --reload
```

API 文档：http://localhost:8000/docs

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端：http://localhost:5173

## 项目结构

```
zero-arsenal/
├── backend/
│   ├── main.py            # FastAPI 入口
│   ├── pyproject.toml
│   ├── api/               # REST + SSE 路由
│   ├── bus/               # 事件总线（asyncio.Queue）
│   ├── db/                # SQLite Schema + 连接管理
│   ├── engine/            # 骰子引擎（d10 骰池）
│   ├── memory/            # 四层混合记忆子系统
│   ├── tools/             # ToolRegistry + SKILL.md 加载器
│   ├── agents/            # LangGraph Agent 节点（Phase 2）
│   ├── extensions/        # WorldPlugin 扩展目录
│   │   ├── crossover/     # 综漫无限流
│   │   ├── wuxia/         # 武侠世界
│   │   └── infinite_arsenal/
│   ├── skills/            # SKILL.md 技能文件
│   └── data/
│       ├── sys_config/    # agents.json, mcp.json
│       ├── writing-styles/
│       └── dice-archive/  # 骰子 JSONL 归档
│
├── frontend/
│   └── src/
│       ├── lib/           # api.ts, sse.ts
│       ├── stores/        # Zustand (session, story)
│       ├── components/
│       │   └── parts/     # PartRenderer + 各类型 Part
│       └── pages/         # HomePage, SessionPage
│
└── docs/design/           # 13 个设计文档
```

## Phase 路线图

| Phase | 内容 | 状态 |
|-------|------|------|
| 1 | FastAPI 骨架 + SQLite + Bus/SSE + roller.py + memory/ | ✅ 完成 |
| 2 | LangGraph 7-Agent 图 + NarratorAgent 四阶段 + DM/NPC/World Agent | ✅ 完成 |
| 3 | PromptFragment Registry + WorldPlugin（crossover/wuxia/infinite_arsenal）| ✅ 完成 |
| 4 | TavernCommand DSL + RestrictedPython VM 变量执行 | ✅ 完成 |
| 5 | ChroniclerAgent 章节固化 + 四层混合记忆召回（向量+Bigram+图+认知权重）| ✅ 完成 |
| 6 | AgentProfile 权限模式 + ask 交互暂停/恢复 | ✅ 完成 |
| 7 | 三栏前端（章节树+故事流+骰子/角色面板）+ 37个文风 SKILL.md | ✅ 完成 |
| 8 | ToolRegistry（8个内置工具）+ OpenAI function calling 格式 | ✅ 完成 |
