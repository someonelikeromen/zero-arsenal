# 零度武库 (Zero Arsenal)

AI 跑团小说工具 — 多 Agent 叙事 · 确定性 d10 骰池 · 可扩展世界插件 · SSE 实时前端

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## 特性

- **LangGraph 多 Agent 管线**：规则审查 → DM 门禁 → 骰子 → NPC/世界 → 四阶段叙事 → 文风 → 变量 → 章节固化
- **四层混合记忆**：向量（chromadb）+ Bigram 词法兜底 + 图扩散 + 认知权重；支持 viewer 五视角召回
- **世界扩展**：`crossover` / `wuxia` / `infinite_arsenal` / `muv_luv` / `gundam_seed` 等，Hook + 专属工具 + 铁律 Markdown
- **角色卡 v4**：OCEAN、多部位 HP、经济/徽章、jsonschema 校验
- **前端**：章节树、Part 流式渲染、Hub 会话管理、Tailwind v4

## 文档

| 文档 | 说明 |
|------|------|
| [docs/开发须知.md](docs/开发须知.md) | **协作者入口**（环境、代码地图、PR） |
| [docs/PROGRESS.md](docs/PROGRESS.md) | **当前进度**与待办 |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | 贡献规范与扩展开发细节 |
| [docs/design/00-README.md](docs/design/00-README.md) | 设计文档索引（实现权威来源） |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构与降级行为 |
| [docs/FIX_VERIFICATION_2026-06.md](docs/FIX_VERIFICATION_2026-06.md) | 2026-06 复审核查台账 |

## 快速启动

### 一键启动（推荐，Windows）

在独立 PowerShell / 命令行窗口分别拉起前后端：

```powershell
cd zero-arsenal
.\scripts\start-all.ps1      # 同时开两个窗口
# 或分别启动：
.\scripts\start-backend.ps1  # 仅后端
.\scripts\start-frontend.ps1 # 仅前端
```

也可双击 `scripts\start-all.cmd`（等同上述脚本）。

### 手动启动

**后端**

```bash
cd zero-arsenal
pip install -e "backend/[dev]"

cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY 或其它 LLM Key

python -m backend.main
```

API 文档：<http://localhost:8001/docs>（端口由 `.env` 中 `PORT` 决定，默认 8001）

**前端**

```bash
cd frontend
npm install
npm run dev
```

前端：<http://localhost:5173>

## 项目结构

```
zero-arsenal/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── api/                 # REST + SSE
│   ├── agents/              # LangGraph 节点
│   ├── bus/                 # 事件总线（内存 / Redis）
│   ├── db/                  # SQLite + 角色卡 v4
│   ├── engine/              # 骰子、战斗、VariableVM
│   ├── memory/              # 混合记忆子系统
│   ├── tools/               # ToolRegistry、MCP 桥
│   ├── extensions/          # 世界插件
│   ├── skills/              # 预置 SKILL.md
│   └── data/                # 配置、文风库等
├── frontend/src/            # React + Zustand + SSE
└── docs/                    # 设计、进度、开发须知
```

## 进度摘要

2026-06 复审修复（`173d921`）及第二轮收尾后，**P0–P5 主路径已通**。路由侧降级日志、长列表虚拟滚动与流式细粒度订阅均已完成；最新核查以 [docs/PROGRESS.md](docs/PROGRESS.md) 和 [docs/FIX_VERIFICATION_2026-06.md](docs/FIX_VERIFICATION_2026-06.md) 为准。

| 里程碑 | 状态 |
|--------|------|
| 骨架 + Agent + 扩展 + 记忆 + 权限 + 前端 | ✅ |
| 2026-06 安全/崩溃/设计对齐复审 | ✅ |
| 路由降级日志、虚拟滚动 windowing | ✅ |

## 协作开发

1. Fork 本仓库，从 `main` 切分支（`feat/` / `fix/` / `docs/`）
2. 阅读 [docs/开发须知.md](docs/开发须知.md)
3. 本地跑通测试后提 PR（见 [CONTRIBUTING.md](docs/CONTRIBUTING.md)）
4. **勿提交** `.env`、数据库文件或 API Key

## 部署提示

- **单实例**：默认内存事件总线即可（`--workers 1`）。
- **多实例**：设置 `REDIS_URL` 并安装 `redis`；可选 `ZERO_ARSENAL_API_TOKEN` 开启 API 鉴权。浏览器端如需访问受保护 API，可在 `localStorage.zero_arsenal_api_token` 保存同一 token；SSE 因原生 `EventSource` 限制会使用短 query 参数传递该 token。
- 变量脚本需安装 `RestrictedPython`（见 [ARCHITECTURE.md](docs/ARCHITECTURE.md)）。

## 许可证

[MIT](LICENSE)
