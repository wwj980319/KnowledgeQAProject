## Global Constraints

- 模型 API 只能接入 Claude API，模型 ID 精确为 `claude-sonnet-5`，通过官方 `anthropic` SDK 调用
- Embedding 用本地 `BAAI/bge-small-zh-v1.5`（512 维），禁止调用任何第三方 embedding API
- **本项目当前无 git，所有任务省略 commit 步骤**（用户明确要求 bypass git 操作）
- venv 位于项目根 `.venv`（Python 3.11），所有命令前先 `source .venv/bin/activate`
- 敏感配置（`ANTHROPIC_API_KEY`、`JWT_SECRET`）只放 `.env`，`.env` 不进版本库，提供 `.env.example`
- 依赖 Docker Desktop 运行 postgres/redis；**若 Docker 未安装或未启动，停下与用户人工交互**（用户开场要求）
- 测试中一律 mock Claude API 调用（不消耗真实配额）；sentence-transformers 测试可用真模型（本地免费）


### Task 10: README 与面试材料

**Files:**
- Create: `README.md`, `docs/面试问答准备.md`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-07-16-knowledge-qa-design.md`（架构图、选型表、权衡）、PRD 第十二节问题清单
- Produces:
  - `README.md` 章节：项目简介 / 架构图（复用设计文档第二节 ASCII 图）/ 技术选型表（复用设计文档第一节并加"为什么"列）/ 快速开始（cp .env.example .env → 填 ANTHROPIC_API_KEY → docker compose up --build）/ API 一览表 / 关键设计权衡（全局缓存维度、固定窗口限流、pgvector 单库、本地 embedding 四条，各含"选择原因 + 局限 + 扩展方向"）
  - `docs/面试问答准备.md`：逐条回答 PRD 第十二节 6 个问题，每条按"设计思路 → 权衡 → 踩坑/扩展"结构

- [ ] **Step 1: 写 README.md**（按上述 Produces 章节结构，内容从设计文档与实际代码提取，命令须与 docker-compose.yml 实际一致）

- [ ] **Step 2: 写 docs/面试问答准备.md**（PRD 第十二节 6 问：异步队列 why / Top-K 选择与检索失败处理 / 缓存 key 设计与失效 / 限流算法权衡 / 扩展方案 / 大模型降级，每问 200-400 字）

- [ ] **Step 3: 最终验收**

Run: `pytest -v && curl -s localhost:8000/health`
Expected: 测试全绿 + health ok。对照 PRD 第十一节 DoD 8 项逐条勾选确认。
