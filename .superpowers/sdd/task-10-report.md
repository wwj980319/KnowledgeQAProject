# Task 10 Report — README 与面试材料

## 交付物

- `README.md`（项目根）：项目简介 / ASCII 架构图 / 技术选型表（含"为什么"列）/ 快速开始（cp .env.example .env → 填 ANTHROPIC_API_KEY → docker compose up --build）/ API 一览表 / 4 条关键设计权衡（用户级缓存隔离、固定窗口限流、pgvector 单库、本地 embedding，每条含选择原因+局限+扩展方向）/ 项目结构 / 冒烟测试记录
- `docs/面试问答准备.md`：PRD 第十二节 6 问逐条作答，每问按"设计思路→权衡→踩坑/扩展"结构，含代码片段，字数 250–400 字/题

## 验证输出

```
pytest -q: 29 passed, 1 warning in 5.68s
curl -s localhost:8000/health: {"status":"ok","postgres":true,"redis":true}
```

## DoD 清单（PRD 第十一节，8/8）

- [x] 用户可完成注册、登录，获得有效 JWT
- [x] 用户可上传文档，文档经异步处理后状态变为 completed
- [x] 用户可针对已上传文档提问，获得基于文档内容的回答，并显示引用来源
- [x] 相同/相似问题的重复请求命中缓存，响应明显加快（冒烟实测 4.3s → 0.01s）
- [x] 超出限流阈值的请求返回 429 及明确提示
- [x] 服务可通过 docker-compose up 一键启动
- [x] /health 接口可正确反映数据库、Redis、向量存储的连通状态
- [x] README 中包含架构图、技术选型说明、本地运行方式

## 实现偏差（README 已体现实际现状）

1. 缓存按用户隔离（key 含 user_id），非原设计文档的全局缓存——跨用户泄漏冒烟发现后修复，README 权衡一节已改写，面试材料 Q3 收录"发现→修复"故事
2. get_db() commit-on-success 模式（面试材料 Q6 踩坑）
3. /health 直连 engine 绕过 DI（面试材料 Q6 踩坑）

## 关注点

无阻断性问题。passlib crypt 废弃警告为第三方库问题，Python 3.11 下无影响，29 个测试全绿。
