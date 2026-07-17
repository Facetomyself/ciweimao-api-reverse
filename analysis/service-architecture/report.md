# FastAPI 异步抓取服务实施报告

## 基本信息

| 项目 | 值 |
|---|---|
| 目标 | `ciweimao-api-reverse` Python collector |
| 类型 | App API 协议复现与服务化 |
| 分析时间 | 2026-07-17 |
| 分析深度 | L1 便携复现 + 服务编排 |

## 目标概述

在已确认的 App 2.9.362 协议基础上，将网络层迁移到 `curl_cffi`，增加异步免费章节下载、SQLite 持久化任务队列、APScheduler 定时榜单/新书同步和 FastAPI API。

## 关键发现

### F-001：同步与异步请求可共享同一协议层

- 位置：`client/api.py`
- 描述：签名参数、响应 AES 解密、分页参数和 CDN 解码不依赖同步 HTTP 库，可由 `Session` 与 `AsyncSession` 共用。
- 证据：`test_client.py`、`test_async_client.py`；同步和异步 mock 均通过相同签名/解码链。
- 置信度：high

### F-002：持久化队列必须以数据库状态为事实源

- 位置：`service/database.py`、`service/queue.py`
- 描述：`asyncio.Queue` 仅作进程内唤醒；`tasks` 保存 payload、状态和结果。启动时将 `running` 恢复为 `queued`，并重新投递。
- 证据：`test_service_storage.py::test_active_dedupe_and_restart_recovery`。
- 置信度：high

### F-003：榜单与新书需要保留历史快照

- 位置：`service/database.py`
- 描述：只 upsert `books` 会覆盖历史位置，因此拆分 `snapshots` 与 `observations`，同时保留当前书籍索引和每次观察顺序。
- 证据：`test_service_storage.py::test_snapshot_round_trip`、`test_service_core.py`。
- 置信度：high

### F-004：Scheduler 应只投递任务

- 位置：`service/scheduler.py`
- 描述：手动和定时入口共用 handler、payload 校验及去重键，避免产生独立失败处理链。
- 证据：`test_service_app.py` 验证 FastAPI lifespan 中存在两个 scheduler job，并由 durable queue 执行 HTTP 创建的任务。
- 置信度：high

### F-005：App 列表接口需要短生命周期 session

- 位置：`service/core.py`
- 描述：同一 `curl_cffi.AsyncSession` 连续混跑搜索、榜单和新书时，服务端可返回临时码 `320002`；将搜索按页、榜单按规格、新书按页拆成独立 session 后真实门禁稳定通过。
- 证据：`analysis/service-architecture/real-gate.json`。
- 置信度：high

## 架构概览

```text
FastAPI / APScheduler
  -> PersistentTaskQueue
  -> CiweimaoService
  -> curl_cffi AsyncSession
  -> SQLite WAL + TXT artifacts
```

完整数据模型、状态机、并发和 PostgreSQL 迁移边界见 `docs/architecture.md`。

## 脱敏说明

- 测试只使用 synthetic credentials；
- 真实 `account`、`login_token`、`device_token` 不写入数据库、测试、报告或响应；
- 服务每个任务惰性读取 env 或忽略的 `tokens.json`。

## 验证

- `python -m compileall -q .`：通过；
- `python -m unittest -v`：29 tests / OK；
- 覆盖同步/异步协议、CDN 解码、免费章过滤、原子写入、队列恢复、任务去重、快照、FastAPI lifespan 和 scheduler。
- 真实只读门禁：搜索 `10`、`fans_value:week` 榜单 `10`、新书 `100`；SQLite 快照分别为 `10/100`，WAL 生效。凭据仅从忽略的本地 capture 内存提取，未回显、未保存。

## Triage 遗留项

见 `triage.md`。当前无阻塞项，保留多进程 scheduler 与 SQLite 扩容边界。
