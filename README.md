# ciweimao-api-reverse

刺猬猫（Ciweimao / Hbooker）官方 Android App API 的搜索、书城枚举与免费章节抓取客户端。

本仓当前只负责：

- 复现 App 2.9.362 的请求签名与响应解密；
- 使用 `curl_cffi` 提供同步 CLI 与异步服务两套会话；
- 按关键词从第 0 页开始搜索并按 `book_id` 去重；
- 从书城入口按更新时间连续遍历书籍；
- 一次请求获取整本分卷与章节目录；
- 仅处理 `is_paid=0` 且 `auth_access=1` 的免费可读章节；
- 通过 FastAPI、SQLite durable queue 和 APScheduler 主动同步榜单与新书；
- 在 ali-cloud 上按需提取快代理 20 分钟 DPS，不启动任务就不消耗 IP。

TXT / EPUB、插图和 App 本地缓存等既有下载格式能力不在本轮重复逆向；本仓的抓取命令只复用现有 TXT 落盘链。

## App 端结论

2026-07-17 对官方 App 2.9.362 的运行时取证确认，所谓“未登录可看”并非完全空身份：App 首次启动会自动创建未绑定游客账号，后续请求仍携带游客 `account` 与 `login_token`。

正文曾卡在“加载中”的直接原因是残留代理，而不是 App 禁止游客阅读：

```text
Native curl 业务 API
  -> command / 章节元数据成功

Java/OkHttp CDN 请求
  -> 服从 Android 代理 127.0.0.1:8083
  -> 当时无 adb reverse / mitmproxy 监听
  -> ECONNREFUSED
```

业务 API 与正文 CDN 使用不同网络分支，因此会出现“目录、评论、章节授权全正常，正文却一直转圈”的现象。补齐代理链后正文 CDN 返回 HTTP 200；关闭代理时必须同时清理 host、port、PAC 与 exclusion 等 global setting。

## 2.9.362 协议

当前 App 的业务 API 基址为：

```text
https://app1.happybooker.cn
```

每个业务请求追加 16 位 `rand_str` 与 HMAC-SHA256 签名 `p`。签名输入为：

```text
account=<percent-encoded>&app_version=2.9.362&rand_str=<16hex>&signatures=<key><suffix>
```

抓到的 84 个请求已全部逐个重算，`84/84` 一致。Native 静态分析同时确认：

- `libcwmhttps.so` 的 `CenterDataAPI::aes_256_cbc_decode` 位于 RVA `0x80D6C`；
- mode 为 `1` 时使用 2.9.352+ response key，否则使用 legacy key；
- key 先经过 SHA-256，再以零 IV 执行 AES-256-CBC；
- 当前抓包中的短响应可直接解密，真实签名请求的搜索结果与 App 抓取结果顺序完全一致。

旧版 2.9.312 兼容链仍保留，但 CLI 默认使用 2.9.362。旧链搜索结果明显不完整，不能代替当前 App 搜索。

## 已验证接口

| 能力 | Endpoint | 关键参数 |
|---|---|---|
| 搜索 | `/bookcity/get_filter_search_book_list` | `page=0..N`、`count=10` |
| 全站书城 | `/bookcity/get_filter_book_list` | `tab_type=200`、`order=uptime`、`count=100` |
| 排行 | `/bookcity/get_rank_book_list` | `order`、`time_type`、`page` |
| 详情 | `/book/get_info_by_id` | `book_id` |
| 评论 | `/book/get_review_list` | 热门 `type=2`；普通 `type=1` |
| 整本目录 | `/chapter/get_updated_chapter_by_division_new` | `division_id=0` |
| 章节 command | `/chapter/get_chapter_cmd` | `chapter_id` |
| 章节元数据 | `/chapter/get_cpt_ifm` | `chapter_id`、`chapter_command` |
| 间贴计数 | `/chapter/get_tsukkomi_num` | `chapter_id` |

运行时样本：

- 搜索“青春”第 0–5 页均返回 10 本，60 条中有 1 个跨页重复，必须去重；
- 当前协议实测书城第 0–2 页各 100 本，合计 300 个不同 `book_id`；
- 一份 433 章目录中，50 章满足免费可读，5 章虽 `is_paid=0` 但 `auth_access=0`，另有 378 个付费未授权章；
- 正文 CDN 的 7 个样本均为 `HTTP gzip -> zlib -> UTF-8 HTML fragment`。

## 环境

只使用 `D:\reverse_ENV` 项目环境：

```powershell
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m pip install -r "D:\reverse_ENV\workspace\ciweimao-api-reverse\requirements.txt"
```

## 凭据

可使用 App 自动创建的游客身份，无需绑定正式账号。`tokens.json` 只保存在本机并已排除 Git。

FastAPI / Docker 部署可设置 `CIWEIMAO_GUEST_BOOTSTRAP_ENABLED=1`。静态代理模式可
在 lifespan 校验凭据；快代理动态租约模式会延迟到第一次真实搜索、同步或下载，先
按需提取 IP，再通过同一出口校验或调用 `auto_reg_v2`。新游客以 `0600` 权限原子写入
`CIWEIMAO_TOKEN_PATH`，服务启动和 healthcheck 不会提前消耗代理。

从 Root 设备提取当前 App 身份：

```powershell
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m client token-extract --device emulator-5574
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m client token
```

`token-extract` 会写入 `tokens.json`；已有正式账号凭据时不要随手覆盖。

## 使用

### 搜索

```powershell
# 第一页
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m client search "青春"

# 一直翻到空页，并按 book_id 去重
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m client search "青春" --max-pages 0
```

### 抓取搜索结果中的免费章节

```powershell
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m client crawl-search "方舟" --max-books 20
```

### 全站抓取免费章节

```powershell
# 小范围验证
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m client crawl-all --max-pages 1 --max-books 5

# 不限制页数和书籍数时必须显式确认
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m client crawl-all --yes
```

全站模式默认 `order=uptime`、每页 100 本。分页遇到空页、重复页或整页没有新 `book_id` 时停止。

### 兼容命令

```powershell
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m client download 100448715 --free-only --include-book-id
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m client list
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m client download-all
```

## FastAPI 服务

启动入口固定为单 worker：

```powershell
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m service

# 等价方式；不要把 workers 改成大于 1
& "D:\reverse_ENV\.venv\Scripts\uvicorn.exe" service.app:app --host 127.0.0.1 --port 8000 --workers 1
```

Swagger UI：`http://127.0.0.1:8000/docs`。

常用接口：

| Method | Path | 用途 |
|---|---|---|
| `GET` | `/health` | 数据库、队列、调度器与凭据配置状态 |
| `GET` | `/api/books/search?q=书名` | 直接异步搜索并更新书籍索引 |
| `POST` | `/api/downloads/by-name` | 按书名投递免费章节 TXT 下载任务 |
| `POST` | `/api/sync/all` | 手动投递榜单 + 新书合并同步任务 |
| `POST` | `/api/sync/rankings` | 手动投递榜单同步任务 |
| `POST` | `/api/sync/new-books` | 手动投递新书同步任务 |
| `GET` | `/api/tasks` | 查询任务列表 |
| `GET` | `/api/tasks/{task_id}` | 查询任务状态与结果 |
| `GET` | `/api/rankings/latest` | 获取各榜单最新快照 |
| `GET` | `/api/new-books/latest` | 获取最新新书快照 |
| `GET` | `/api/scheduler/jobs` | 查看下次调度时间 |

按书名下载示例：

```powershell
$body = @{
  book_name = "目标书名"
  author_name = "作者名"
  exact_match = $true
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/downloads/by-name" `
  -ContentType "application/json" -Body $body
```

接口返回 `202` 和任务 ID。实际搜索、目录抓取、免费章下载、文件校验与数据库登记均由 worker 异步完成。

### 定时任务

- 每 30 分钟只投递一个 `sync_all`，顺序同步榜单和新书；
- 两段同步共享同一个 `ProxyLease`，正常情况下整轮只提取一个快代理 IP；
- `coalesce=True`、`max_instances=1`；
- Scheduler 不直接访问 App API，只向持久化队列投递任务；
- 相同 payload 的 `queued/running` 任务通过 `dedupe_key` 合并。

默认同步 13 个 App 榜单组合，包括 `fans_value` 周/月/总榜，以及点击、月票、字数、追读、完本、刀片、新书月票、推荐、间贴和收藏榜。榜单请求按顺序执行，不会一次性高并发打向同一 host。按默认周期且无失败刷新时，定时任务约消耗 2 个 IP/小时。

### 数据存储

默认数据库：`data/ciweimao.sqlite3`，运行时启用 SQLite WAL。默认下载目录：`output_api/`。

| 表 | 内容 |
|---|---|
| `tasks` | durable queue、payload、去重键、状态、尝试次数、结果和错误 |
| `books` | 书籍当前索引及原始 App JSON |
| `snapshots` | 榜单或新书的一次抓取批次 |
| `observations` | 快照内书籍位置和当次原始数据 |
| `downloads` | 下载任务、文件路径、大小和 SHA-256 |

正文文件放文件系统，SQLite 只存元数据与校验值，避免把大段文本塞进单库。仓储操作封装在 `service/database.py`，后续切 PostgreSQL 时业务 handler 和 API 路由无需改写。

完整架构与扩容边界见 `docs/architecture.md`。

### 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `CIWEIMAO_DB_PATH` | `data/ciweimao.sqlite3` | SQLite 路径 |
| `CIWEIMAO_OUTPUT_DIR` | `output_api/` | TXT 输出目录 |
| `CIWEIMAO_TOKEN_PATH` | `tokens.json` | App 游客/登录凭据文件 |
| `CIWEIMAO_GUEST_BOOTSTRAP_ENABLED` | `0` | 静态出口启动校验；动态出口首次使用时按需创建游客 |
| `CIWEIMAO_SCHEDULER_ENABLED` | `1` | 是否在当前进程启动 scheduler |
| `CIWEIMAO_SYNC_INTERVAL_MINUTES` | `30` | 榜单 + 新书合并同步周期 |
| `CIWEIMAO_QUEUE_WORKERS` | `1` | 任务 worker 数；默认串行避免同 host 任务互相干扰 |
| `CIWEIMAO_HTTP_MAX_CLIENTS` | `5` | 单个 `curl_cffi.AsyncSession` 连接上限 |
| `CIWEIMAO_HTTP_MAX_RETRIES` | `2` | 连接断开/超时后的有限重试次数 |
| `CIWEIMAO_HTTP_RETRY_BACKOFF` | `0.25` | 指数退避基数（秒） |
| `CIWEIMAO_HTTP_TRANSIENT_API_RETRIES` | `1` | App 临时业务码 `320002` 重试次数 |
| `CIWEIMAO_PROXY_PROVIDER` | `auto` | `direct`、`static` 或 `kuaidaili_dps` |
| `CIWEIMAO_PROXY_URL` | 空 | `static` 模式的 HTTP/SOCKS5 代理 URL |
| `CIWEIMAO_PROXY_LEASE_SECONDS` | `1200` | 动态代理租约时长 |
| `CIWEIMAO_PROXY_EXPIRY_SAFETY_SECONDS` | `30` | 到期前安全窗口 |
| `KDL_SECRET_ID(_FILE)` | 空 | 快代理订单级 SecretId 或 Docker secret 路径 |
| `KDL_SECRET_KEY(_FILE)` | 空 | 快代理订单级 SecretKey 或 Docker secret 路径 |
| `CIWEIMAO_KDL_AUTH_MODE` | `auto` | `auto`、`required` 或 `whitelist` |
| `CIWEIMAO_LIST_REQUEST_DELAY` | `0.25` | 列表页/榜单规格之间的间隔（秒） |
| `CIWEIMAO_CHAPTER_CONCURRENCY` | `3` | 单本书章节有界并发数 |

也可通过 `CIWEIMAO_LOGIN_TOKEN`、`CIWEIMAO_ACCOUNT` 和 `CIWEIMAO_DEVICE_TOKEN` 注入凭据；这些值不会写入数据库或接口响应。

同一进程内 Scheduler 与 API 共存时必须使用 `--workers 1`。如果部署多个 API replica，只允许一个实例设置 `CIWEIMAO_SCHEDULER_ENABLED=1`，其余设为 `0`；再往上扩容时应拆独立 scheduler/worker 进程并将 SQLite repository 替换为 PostgreSQL。

## Docker Compose

仓库提供 `Dockerfile` 与 `compose.yaml`。默认以独立 project `ciweimao-api-reverse` 运行，只绑定宿主 `127.0.0.1:18086`，数据与下载文件分别持久化到 `runtime/data/` 和 `runtime/output/`。

```bash
mkdir -p runtime/data runtime/output runtime/secrets
# 将订单级 SecretId / SecretKey 分别写入下列 0600 文件
install -m 600 /dev/null runtime/secrets/kdl_secret_id
install -m 600 /dev/null runtime/secrets/kdl_secret_key
chown 10001:10001 runtime/secrets/kdl_secret_id runtime/secrets/kdl_secret_key
docker-compose -p ciweimao-api-reverse up -d --build
```

Compose 将游客凭据持久化为 `runtime/data/guest-tokens.json`，快代理 API 密钥通过
Compose secrets 只读挂载。部署只有一个 API 容器，不再包含 NAS SSH egress sidecar。
合并同步任务每轮开始提取一个新 IP，并让榜单和新书共享该租约；指定书下载与搜索复用
仍有效租约，到期或出口失败才换。所有代理只作用于本项目的 App API/CDN 请求，不改变
宿主或其他容器路由。
完整边界见 `docs/deployment-ali-cloud.md`。

## 验证

```powershell
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m compileall -q .
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m unittest -v
```

动态证据与三件套位于：

- `analysis/anonymous-reader/`
- `analysis/app-workflow/`
- `analysis/service-architecture/`
