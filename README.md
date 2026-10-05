# 个人知识库 AI 问答服务

基于 RAG（检索增强生成）的个人知识库问答系统。上传 TXT/PDF 文档后，用自然语言提问，系统检索相关文档片段并调用 Claude API 生成带引用编号的回答。

**项目定位**：后端求职实战项目，覆盖异步队列、向量检索、缓存、限流、JWT 认证等高频考点，每个模块均有完整的设计权衡可在面试中阐述。

---

## 系统架构

```
用户 ──▶ FastAPI (api 容器)
          ├── PostgreSQL + pgvector：users / documents / chunks(向量) / query_logs
          ├── Redis：问答缓存 + 限流计数 + RQ 队列
          └── RQ Worker (worker 容器)
                ├── 文本提取(txt/pdf) → 分块(500字/100重叠) → bge 本地向量化 → 写 pgvector
                └── 失败重试 3 次，状态回写 documents.status (processing/completed/failed)

问答链路：
  问题 → Redis 缓存查询(user_id + question hash) → 未命中 →
  bge 向量化问题 → pgvector Top-K 余弦检索(默认4, 可配) →
  拼接 Prompt → Claude API (claude-sonnet-5) → 回答 + 引用来源 → 写缓存(TTL 1h) → 落 query_logs
```

---

## 技术选型

| 类别 | 选型 | 为什么选它 |
|---|---|---|
| 语言/框架 | Python 3.11 + FastAPI | 类型注解 + 依赖注入 + 自动 OpenAPI；AI/ML 生态最完善 |
| 数据库 | PostgreSQL 16 + pgvector | 元数据与向量同库，减少一个中间件；pgvector 余弦检索满足万级 chunk 的个人知识库场景 |
| 缓存/队列 | Redis 7 | 同时充当问答缓存、限流计数器、RQ broker，三合一降低依赖数量 |
| 异步任务 | RQ（Redis Queue） | 比 Celery 轻量，配置仅需 broker URL；任务失败自动重试 3 次，状态可查 |
| 大模型 API | Claude API — `claude-sonnet-5` | 官方 `anthropic` Python SDK；1M 上下文；`output_config.effort=low` 显式控制延迟 |
| Embedding | 本地 `BAAI/bge-small-zh-v1.5` | Claude 无 embedding API；本地跑零成本、中文优化、约 130MB；512 维向量 |
| 认证 | PyJWT + passlib[bcrypt] | JWT 无状态、可配过期时间；bcrypt 加盐哈希，防彩虹表 |
| PDF 解析 | pypdf | 纯 Python、零系统依赖，轻量 |
| ORM | SQLAlchemy 2.x + pgvector-python | `select()` 语句式 API；pgvector-python 提供向量列类型与余弦距离运算符 |
| 配置 | pydantic-settings | 读 `.env`，类型校验，敏感信息不入代码 |
| 容器化 | Docker + docker-compose | 四容器（api/worker/postgres/redis）一键启动，本地与云端环境一致 |
| 测试 | pytest + httpx TestClient | Claude 调用全部 mock；sentence-transformers 测试使用真实本地模型 |

---

## 快速开始

**前置条件**：Docker Desktop 已安装并运行。

```bash
# 1. 复制环境变量模板
cp .env.example .env

# 2. 编辑 .env，填入真实的 ANTHROPIC_API_KEY
#    其余变量（DATABASE_URL、REDIS_URL）在 Docker 内已由 docker-compose.yml 覆盖，无需改动
vim .env

# 3. 构建并启动所有服务（首次拉取镜像 + 下载 bge 模型约需数分钟）
docker compose up --build

# 4. 验证服务健康状态
curl http://localhost:8000/health
# 预期：{"status":"ok","postgres":true,"redis":true}

# 5. 访问 Swagger UI
open http://localhost:8000/docs
```

---

## API 一览

| 方法 | 路径 | 说明 | 需鉴权 |
|---|---|---|---|
| POST | `/auth/register` | 用户注册（email + password） | 否 |
| POST | `/auth/login` | 登录，返回 JWT token | 否 |
| POST | `/documents` | 上传文档（multipart，≤10MB，txt/pdf） | 是 |
| GET | `/documents` | 获取当前用户文档列表 | 是 |
| GET | `/documents/{id}` | 查询单文档状态（processing/completed/failed） | 是 |
| DELETE | `/documents/{id}` | 删除文档及关联 chunks | 是 |
| POST | `/query` | 提交问题，返回回答 + 引用来源 | 是 |
| GET | `/query/history` | 查看历史问答（最近 20 条） | 是 |
| GET | `/health` | 服务健康检查（PG + Redis 连通性） | 否 |

鉴权方式：请求头 `Authorization: Bearer <token>`

---

## 关键设计权衡

### 1. 缓存按用户隔离（非全局缓存）

**选择原因**：缓存 key 设计为 `qa:cache:{user_id}:<sha256(question)>`，检索时联 `documents` 表过滤 `user_id`，确保用户只能命中自己上传内容生成的答案。

**来源**：这是在冒烟测试中发现并修复的跨用户数据泄漏问题。初始设计使用全局缓存维度（不含 user_id），测试时发现用户 A 的问题缓存会被用户 B 命中，返回基于用户 A 文档内容的答案——这是严重的多租户安全问题。修复方案：retrieve_chunks 联表过滤 user_id；缓存 key 加入 user_id 维度。

**局限**：同一问题不同用户各自调用一次 Claude，无法共享缓存，成本略高于全局缓存。

**扩展方向**：可在用户级缓存之上增加全局语义缓存层（embedding 相似度匹配），但需对 answer 做脱敏审计（确保不含用户私有信息），复杂度较高，适合 v2 阶段。

---

### 2. 限流：固定窗口（非令牌桶/滑动窗口）

**选择原因**：实现仅需两条 Redis 命令——`INCR` 计数 + `EXPIRE 60s` 设窗口，无需 Lua 脚本或额外数据结构，代码简单、延迟极低。对个人知识库场景（默认 10 次/分钟）而言，窗口边界突刺问题（最坏情况 2N 次/分钟）不影响成本控制目标。

**局限**：窗口边界处用户可在前一秒发 N 次、后一秒再发 N 次，实际 2 秒内消耗 2N 次配额，存在突刺风险。

**扩展方向**：滑动窗口（sorted set 记录时间戳）可消除突刺，适合高价值 API 场景；令牌桶支持短时突发后平滑限速，可用 Lua 脚本在 Redis 原子实现。

---

### 3. 向量存储：pgvector（非独立向量数据库）

**选择原因**：个人知识库场景数据量小（千级 chunk），pgvector 余弦检索性能完全满足需求；元数据与向量同库，JOIN 查询（检索时按 user_id 过滤）无跨库开销；减少一个中间件降低运维复杂度。

**局限**：pgvector 在百万级向量时性能劣于 Pinecone/Milvus 等专用向量库；缺少 ANN 索引（HNSW 需手动建）在大数据量下查询慢。

**扩展方向**：数据量增长后可迁移至 Qdrant/Milvus；也可保留 PG 做元数据、向量单独存向量库，通过 chunk_id 关联。

---

### 4. Embedding：本地模型（非 API）

**选择原因**：Claude API 无 embedding 能力；`BAAI/bge-small-zh-v1.5` 中文优化、512 维向量、约 130MB，本地推理零成本、无网络延迟、无速率限制，适合文档处理 worker 批量向量化场景。

**局限**：Docker 镜像体积增加约 500MB（含 torch）；首次启动需从 HuggingFace 下载模型（已挂载 `hf_cache` volume 缓存）；CPU 推理速度慢于 GPU，大文档批量处理耗时较长。

**扩展方向**：生产环境可接入 Cohere/Voyage embedding API 替换本地模型，去掉 torch 依赖缩减镜像体积；也可加 GPU worker 节点加速本地推理。

---

## 项目结构

```
app/
├── main.py          # FastAPI 入口 + 结构化日志中间件
├── config.py        # pydantic-settings（读 .env）
├── database.py      # SQLAlchemy engine/session，commit-on-success 模式
├── models.py        # ORM（users/documents/chunks/query_logs）
├── schemas.py       # Pydantic 请求/响应 schema
├── auth.py          # JWT 签发/校验依赖
├── routers/
│   ├── auth.py      # 注册/登录
│   ├── documents.py # 文档 CRUD + 上传触发 RQ 任务
│   ├── query.py     # 问答 + 历史记录
│   └── health.py    # 健康检查（直连 engine，绕过 DI 保证 degraded-仍-200）
├── services/
│   ├── embedding.py # bge-small-zh 本地向量化
│   ├── chunking.py  # 固定长度 + 重叠窗口分块
│   ├── rag.py       # 检索 + Claude 调用 + 降级处理
│   ├── cache.py     # Redis 问答缓存（用户级隔离）
│   └── rate_limit.py# 固定窗口限流
└── tasks.py         # RQ 文档处理任务（提取→分块→向量化→写库）
tests/               # pytest 单元/集成测试（29 个用例）
docker-compose.yml   # api / worker / postgres / redis
Dockerfile
.env.example
```

---

## 测试

```bash
# 在项目根目录运行（需激活 venv 或 Docker 内）
.venv/bin/pytest -q
# 预期：29 passed
```

测试覆盖：JWT 注册/登录流程、分块边界（短文本/整除）、缓存命中/未命中、限流 429、文档上传状态流转、RAG 端到端（mock Claude）、健康检查降级。

---

## 冒烟测试记录（真实 API 调用）

| 步骤 | 结果 |
|---|---|
| 上传文档 | 立即返回 processing，worker 约 2s 后完成向量化，状态变 completed |
| 首次提问 | claude-sonnet-5 真实调用，回答含 [1] 引用编号，约 4.3s |
| 重复提问（同问题） | 缓存命中，0.01s 返回，cached: true |
| 跨用户隔离验证 | 用户 B 无法命中用户 A 的缓存，检索结果仅含自己的 chunks |
