# 个人知识库 AI 问答服务 — 技术设计文档

- 日期：2026-07-16
- 状态：已评审通过（用户确认）
- 上游文档：`AI知识库问答服务_PRD.md`
- 硬约束：**任何外部模型 API 只能接入 Claude API**

## 一、技术选型

| 类别 | 选型 | 说明 |
|---|---|---|
| 语言/框架 | Python 3.11 + FastAPI | 现有 venv 为 3.11 |
| 数据库 | PostgreSQL 16 + pgvector | 元数据与向量同库，简化架构 |
| 缓存/队列 | Redis 7 | 问答缓存 + 限流计数 + RQ broker 三合一 |
| 异步任务 | RQ（Redis Queue） | 轻量，MVP 首选；失败重试 3 次 |
| 大模型 API | **Claude API — `claude-sonnet-5`** | 官方 `anthropic` Python SDK；2026-08-31 前优惠价 $2/$10 每 MTok；1M 上下文、128K 输出；adaptive thinking，effort 显式设 low/medium 控制延迟 |
| Embedding | 本地 sentence-transformers `BAAI/bge-small-zh-v1.5` | Claude 无 embedding API；本地模型零成本、中文优化、约 130MB；512 维向量 |
| 认证 | PyJWT + passlib[bcrypt] | JWT 过期时间可配置；密码 bcrypt 加盐哈希 |
| PDF 解析 | pypdf | 纯 Python、轻量 |
| ORM | SQLAlchemy 2.x + pgvector-python | |
| 配置 | pydantic-settings 读 `.env` | `ANTHROPIC_API_KEY` 等敏感信息不入代码 |
| 容器化 | Docker + docker-compose | 服务：api / worker / postgres / redis |
| 测试 | pytest + httpx TestClient | Claude 调用一律 mock |

## 二、系统架构

```
用户 ──▶ FastAPI (api 容器)
          ├── PostgreSQL + pgvector：users / documents / chunks(向量) / query_logs
          ├── Redis：问答缓存 + 限流计数 + RQ 队列
          └── RQ Worker (worker 容器)
                ├── 文本提取(txt/pdf) → 分块(500字/100重叠) → bge 本地向量化 → 写 pgvector
                └── 失败重试 3 次，状态回写 documents.status (processing/completed/failed)

问答链路：
  问题 → Redis 缓存查询(question hash) → 未命中 →
  bge 向量化问题 → pgvector Top-K 余弦检索(默认4, 可配) →
  拼接 Prompt → Claude API (claude-sonnet-5) → 回答 + 引用来源 → 写缓存(TTL 1h) → 落 query_logs
```

## 三、Claude API 集成设计

- SDK：`anthropic`，`client.messages.create(model="claude-sonnet-5", max_tokens=..., output_config={"effort": "low"}, ...)`
- API key：`.env` 中 `ANTHROPIC_API_KEY`，由 SDK 自动读取
- Prompt 结构：system prompt 固定（要求仅基于给定片段回答、检索不到时明确说"资料中没有相关内容"、输出引用编号）；检索 chunks + 用户问题放 user turn
- 降级处理（分级）：
  - `RateLimitError`（429）→ 读 `retry-after` header，返回"服务繁忙请稍后再试"
  - `APIStatusError` 5xx → SDK 自动重试 2 次后返回友好错误
  - `APIConnectionError` → 返回网络错误提示
  - 所有失败返回结构化错误 JSON，不抛 500
- 成本控制：全局问答缓存（MVP 简化，文档中说明权衡）+ 按用户限流

## 四、数据模型

| 表 | 关键字段 | 说明 |
|---|---|---|
| users | id, email, password_hash, created_at | |
| documents | id, user_id, filename, status, error_message, created_at | status: processing/completed/failed |
| chunks | id, document_id, content, embedding vector(512), chunk_index | bge-small-zh 输出 512 维 |
| query_logs | id, user_id, question, answer, referenced_chunks(JSONB), created_at | |

限流计数只放 Redis（固定窗口：`INCR` + `EXPIRE 60s`，默认每用户每分钟 10 次），不落库。

## 五、API 端点

与 PRD 第七节一致：`POST /auth/register`、`POST /auth/login`、`POST /documents`（≤10MB，txt/pdf）、`GET /documents`、`GET /documents/{id}`、`DELETE /documents/{id}`（级联删 chunks）、`POST /query`、`GET /query/history`、`GET /health`（检查 PG/Redis 连通）。

## 六、工程结构

```
app/
├── main.py          # FastAPI 入口 + 中间件（结构化日志）
├── config.py        # pydantic-settings
├── database.py      # SQLAlchemy engine/session
├── models.py        # ORM
├── schemas.py       # Pydantic
├── auth.py          # JWT 签发/校验依赖
├── routers/         # auth.py / documents.py / query.py / health.py
├── services/        # embedding.py / chunking.py / rag.py / cache.py / rate_limit.py
└── tasks.py         # RQ 文档处理任务
tests/
docker-compose.yml   # api / worker / postgres(pgvector/pgvector:pg16) / redis
Dockerfile
.env.example
README.md            # 架构图 + 选型说明 + 运行方式 + 面试问答准备
```

## 七、测试与验收

- pytest 覆盖：注册/登录 JWT 流程、分块逻辑（边界：短文本、恰好整除）、缓存命中、限流 429、文档上传状态流转、RAG 端到端（mock Claude）
- 验收对照 PRD 第十一节 DoD 清单

## 八、已确认的关键权衡

1. 缓存 key 用全局维度（question 归一化后 hash），不分用户 —— MVP 简化，README 说明多租户下应加 user_id 维度
2. Embedding 本地跑而非 API —— 符合"只接 Claude"约束，零成本；代价是 Docker 镜像变大（约 +500MB 含 torch），首次启动需下载模型（缓存到 volume）
3. 限流用固定窗口而非令牌桶 —— 实现简单（两条 Redis 命令），边界突刺问题在 README 讲清权衡即可
4. pgvector 而非独立向量库 —— 数据量小（个人知识库），一套 PG 降低运维复杂度
