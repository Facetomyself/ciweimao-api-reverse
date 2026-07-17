# FastAPI 抓取服务架构

## 目标与边界

本服务只编排已经恢复的刺猬猫 App API：搜索、榜单、新书、目录、章节 command、章节元数据与正文 CDN。网络请求统一使用 `curl_cffi`，不引入浏览器或 Web 端协议。

服务当前输出免费章节 TXT，筛选条件固定为：

```text
is_paid = 0 AND auth_access = 1
```

格式转换不是调度层职责。后续增加其他导出格式时，应在 `client` 下增加 exporter，并保持任务、仓储和 API 不感知正文协议细节。

## 分层

```text
FastAPI routes
  -> PersistentTaskQueue
       -> SQLite tasks (durable truth)
       -> asyncio.Queue (process-local wakeup)
       -> CiweimaoService handlers
            -> client.api.AsyncSession (curl_cffi)
            -> client.async_downloader
            -> Database repository

APScheduler
  -> only enqueue sync_rankings / sync_new_books
```

### `client`

- `api.Session`：同步 `curl_cffi` 会话，兼容原 CLI；
- `api.AsyncSession`：FastAPI、worker 和 scheduler 任务使用的异步会话；
- `guest.py`：复现 App `auto_reg_v2`，创建与当前网络出口绑定的游客身份；
- `ssh_exec_socks.py`：Compose 私网 SOCKS5；通过普通 SSH exec channel 在 NAS 远端内存执行 TCP relay，只允许 80/443；
- `async_downloader`：章节有界并发、免费章过滤、TXT 原子落盘；
- 签名、AES response 解密、章节解密与 CDN 解码继续复用现有协议模块。

### `service`

- `config.py`：无密钥配置与凭据惰性加载；
- `credentials.py`：lifespan 前置凭据校验、游客自举和 `0600` 原子落盘；
- `database.py`：SQLite schema 和 repository；
- `queue.py`：任务恢复、claim、执行和状态迁移；
- `core.py`：搜索、按书名下载、榜单、新书业务 handler；
- `scheduler.py`：APScheduler 定时投递；
- `app.py`：FastAPI lifespan 与路由。

## 队列语义

任务状态机：

```text
queued -> running -> succeeded
                  -> failed
queued -> cancelled
running --process restart--> queued
```

`tasks` 是可靠性事实源。`asyncio.Queue` 丢失不会丢任务：服务启动时先把遗留 `running` 重置为 `queued`，再按创建时间重新投递全部 `queued` 任务。

任务 claim 使用条件更新：

```sql
UPDATE tasks
SET status = 'running', attempts = attempts + 1
WHERE id = ? AND status = 'queued';
```

只有影响一行的 worker 获得执行权。`dedupe_key` 上的 partial unique index只约束 `queued/running`，完成或失败后允许再次创建相同任务。

## 调度语义

APScheduler 3.11 使用 `AsyncIOScheduler`：

- `sync-rankings`：30 分钟；
- `sync-new-books`：10 分钟；
- `coalesce=True`；
- `max_instances=1`；
- 定时函数只调用 `queue.submit()`。

手动 API 和定时任务对 canonical JSON 计算 SHA-256 摘要，生成相同的 payload 去重键。因此同规格任务不会因两个入口重复执行。

## 网络并发

列表请求采用短生命周期 `curl_cffi.requests.AsyncSession`，避免同一连接池连续混跑不同 App 列表时出现服务端断链或临时码。下载阶段使用单独 session，默认 `max_clients=5`。

所有 Session 可通过 `CIWEIMAO_PROXY_URL` 注入统一 HTTP/SOCKS5 代理。该配置只作用于 App API 与正文 CDN 请求，不修改进程外的系统代理或宿主路由。`ali-cloud` 部署使用 `socks5h://egress:1080`：域名由 NAS 解析，SOCKS sidecar 只在 Compose network 内监听。NAS SSH 禁用了 `direct-tcpip`，因此 sidecar 复用一个密码认证、host-key pinned 的 Paramiko transport，并为每个目标创建普通 session channel，在 NAS 内存执行 Python TCP relay；NAS 不落脚本、不开放新端口、不修改 sshd。

- 榜单：按规格顺序请求，每个规格独立 session；
- 新书与搜索：按页顺序请求，每页独立 session；
- 单本下载：章节使用 `asyncio.Semaphore(3)`，每章内部按 `command -> metadata/CDN` 顺序执行；
- App API/CDN 遇连接断开或 timeout 时默认最多重试 2 次，并按 0.25 秒基数指数退避；App `320002` 先在当前会话额外重试 1 次，仍失败或遇 `200100` 时由 credential bootstrap 单锁注册新游客，整个业务操作再重试 1 次；其他业务错误和解密错误不重试；
- 文件写入：通过 `asyncio.to_thread` 执行，不阻塞 event loop；
- 落盘：先写 `.txt.part`，完成后 `os.replace`。

这样避开同 host 无界并发，同时保留下载吞吐。

## 数据模型

### `tasks`

保存任务类型、payload、去重键、状态、执行次数、结果、错误与生命周期时间。服务重启只依赖该表恢复任务。

### `books`

以 `book_id` 为主键保存当前书名、作者、封面、付费标记、字数和最新原始 JSON。`first_seen_at` 不更新，`last_seen_at` 随每次观察推进。

### `snapshots` / `observations`

榜单和新书采用 append-only 快照：

- `snapshots` 描述一次抓取及参数；
- `observations` 保存书在该次快照中的位置和原始字段；
- `books` 保存当前索引。

该结构既能快速读取最新榜单，也能保留排名历史，不会因为 upsert 丢失过去的位置。

### `downloads`

保存任务、查询书名、实际 `book_id`、输出路径、文件大小与 SHA-256。正文保留在文件系统，数据库不存完整章节文本。

## SQLite 运行参数

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

repository 使用短连接和短事务。连接关闭及 shutdown 回写经过 cancellation-safe 处理，避免 Windows 重启时遗留锁文件。

## 部署拓扑

当前支持的默认拓扑：

```text
1 private NAS SSH exec SOCKS sidecar
  + 1 pinned SSH transport
  + per-target session-channel relay (80/443 only)
1 FastAPI process
  + 1 APScheduler
  + 1 queue worker
  + 1 SQLite database
```

必须使用单 Uvicorn worker。多个 Uvicorn worker 会各自启动 scheduler 和内存队列，即使任务去重能挡住一部分重复，仍不属于正确部署。

需要多个 API replica 时：

1. 只有一个实例启用 scheduler；
2. 当前 SQLite 阶段仍建议只启一个实际 worker 进程；
3. 扩到多进程 worker 前，将 `Database` repository 替换为 PostgreSQL，并使用 `SELECT ... FOR UPDATE SKIP LOCKED` 或专用消息队列；
4. FastAPI 路由和 `CiweimaoService` handler 保持不变。

## 故障恢复

| 故障 | 行为 |
|---|---|
| API 请求失败 | 任务标记 `failed`，错误摘要写入 `tasks.error` |
| 进程在运行中退出 | 下次启动把 `running` 重置为 `queued` |
| 同任务重复触发 | active partial unique index 返回已有任务 |
| TXT 写入中断 | 仅遗留 `.part`，不会覆盖成功文件；finally 清理临时文件 |
| Scheduler 暂停多周期 | `coalesce=True` 合并错过的执行 |
| 凭据缺失/跨出口失效 | lifespan 经当前 proxy 校验，按需注册游客后才启动队列与 scheduler |
| 运行中 `200100` / 持久 `320002` | 单锁刷新 token 文件；并发请求复用已刷新的游客，原业务操作重试 1 次 |
| 凭据文件更新 | 下个任务重新读取 `tokens.json`，无需重启服务 |

## 迁移 PostgreSQL 的边界

需要替换的只有 `service/database.py` 及初始化配置，业务侧依赖的方法契约保持：

- 任务：`create/get/list/claim/complete/fail/requeue/cancel`；
- 书籍：`upsert_books`；
- 快照：`create_snapshot/get_latest_snapshot(s)`；
- 下载：`record_download`。

不建议在当前规模提前引入 Redis、Celery 或独立 broker。先用真实负载证明 SQLite 的写竞争、队列吞吐或多机部署确实成为瓶颈，再迁移。
