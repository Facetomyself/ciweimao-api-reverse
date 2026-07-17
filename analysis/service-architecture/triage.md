# Triage — FastAPI 异步抓取服务

## 状态速览

| 深度等级 | 已完成 | 部分完成 | 阻滞 | 未开始 |
|---|---:|---:|---:|---:|
| L1 便携复现 | 6 | 0 | 0 | 0 |
| L2 上下文 | 1 | 0 | 0 | 0 |
| L3 运行时 | 1 | 0 | 0 | 0 |
| L4 triage | 0 | 0 | 0 | 0 |

## 已知边界

### T-001：多进程 scheduler

- 严重程度：medium
- 原因：每个 Uvicorn worker 都会执行 FastAPI lifespan，APScheduler 3.x 没有跨进程 leader election。
- 当前处理：启动命令固定 `workers=1`；多 API replica 时只允许一个实例启用 `CIWEIMAO_SCHEDULER_ENABLED=1`。
- 后续条件：需要多机 worker 时切 PostgreSQL claim 或独立消息队列。

### T-002：SQLite 扩容上限

- 严重程度：low
- 原因：WAL 适合当前单服务和少量 worker，但不面向多机高写并发。
- 当前处理：短连接、短事务、`busy_timeout=5000`，repository 边界已隔离。
- 后续条件：真实任务吞吐证明出现锁等待或需要多个 worker 节点时迁移 PostgreSQL。

## 运行时验证

- 搜索“方舟”第 0 页：10 本；
- `fans_value:week` 第 0 页：10 本；
- `newtime` 第 0 页：100 本；
- 榜单/新书 SQLite 快照：10/100；
- 证据：`real-gate.json`；
- 凭据处理：仅内存提取，未回显、未保存。

当前无待验证假设或 blocker。
