# Ciweimao API Reverse

刺猬猫（Ciweimao / Hbooker）官方 Android App 业务协议的研究仓库，同时维护一套游客态采集客户端。

本项目面向协议复现与可运行的采集链路，而不是 APK 脱壳全集。当前跟踪的 App 版本为 **2.9.365**（与 2.9.362 同代 HMAC / AES）。身份默认走 App 首次启动同款游客注册（`signup/auto_reg_v2`），不依赖绑定账号。

仓库：<https://github.com/Facetomyself/ciweimao-api-reverse>

## 项目状态（2026-09-04：RuyiDOM 黑盒 GT3 bind 已过 App 门；纯算 `w` 未完成）

| 能力 | 状态 |
|------|------|
| 请求签名 HMAC-SHA256 | 已复现，84/84 与官方 live `p` 一致 |
| 响应 AES-256-CBC | 已复现（2.9.352+ current key） |
| 游客注册 / 搜索 / 书城 / 目录 / `get_chapter_cmd` | 已复现，业务码 `100000` |
| 官方 App 游客读章 | 已复现，`get_cpt_ifm=100000` |
| 独立客户端读章 `get_cpt_ifm` | 未打戳 `310017`。下载/探测在该码上先 `stamp_gt3()`（RuyiDOM `gt.js` bind），失败且 `free_only` 才 Web fallback。纯算 `w` 仍 `error_03` |
| Native 注册通路（`getC(17)` → `libcwmhttps.so`） | 已静态闭合并完成传输三项 canary |
| 官方 HTTPS 明文（uid MITM） | 冷启动 9 条与未缓存 `get_cpt_ifm` 已解密；无隐藏头 / Cookie；字段集合与形状已和 Python 对齐 |

`get_cpt_ifm` 的 `310017` 跟着「这个身份有没有走过 GT3 bind 一键」走。官方线是 API1 → `gettype.php`/`get.php`/`ajax.php`（约 1s，无滑块图）→ 带三元组的第二次 cpt。只调 API1 或假 `validate|jordan` 不能打戳。Python 已用 RuyiDOM 跑官方 `static/tools/gt.js` 完成同一条 bind（`Session.stamp_gt3()`）；AES+RSA packing 对 fullpage 9.2.0 是 `error_03`，不得标纯算完成。网页章节链是另一条产品面。

闭合事实见 [docs/protocol.md](docs/protocol.md)。黑盒 bind：[gt3-fullpage-w-canary.json](analysis/app-version-2.9.365/evidence/gt3-fullpage-w-canary.json)。GT3 线：[official-gt3-wire-canary.json](analysis/app-version-2.9.365/evidence/official-gt3-wire-canary.json)。账本见 [analysis/app-version-2.9.365/analysis-progress.md](analysis/app-version-2.9.365/analysis-progress.md)。

## 仓库结构

```text
client/                         协议客户端（签名、解密、游客注册、同步/异步会话）
service/                        FastAPI 控制面、队列、调度、身份槽、归档
frontend/                       采集控制台（Vite + React）
docs/                           架构、部署、协议冻结说明
analysis/anonymous-reader/      游客身份与出口结论
analysis/app-workflow/          2.9.362 签名/AES 恢复
analysis/app-version-2.9.365/   2.9.365 正文门与 native 通路
analysis/auth-capability/       登录与匿名免费章边界
analysis/service-architecture/  服务分层
```

APK、DEX dump、IDA 数据库、pcap、游客 token、截图只留本机，不进 Git。

## 协议摘要

业务主机：

| 场景 | Host |
|------|------|
| 游客注册 | `https://app1.hbooker.com` |
| 登录后（`reader_id` 尾数 1–5） | `https://app1.happybooker.cn` |
| 其余 | `https://app1.hbooker.com` |

每个业务 POST 追加 16 hex `rand_str` 与签名 `p`：

```text
source = account=<percent-encoded>&app_version=2.9.365&rand_str=<16hex>&signatures=<certMD5>CkMxWNB666
p      = Base64(HMAC-SHA256(key=certMD5, msg=source))
```

官方原签 APK 的证书 MD5（`PackageInfo.signatures[0].toCharsString` 再 MD5）为 `a90f3731745f1c30ee77cb13fc00005a`。游客注册时尚无 account，HMAC 占位 `cmw666`。响应为 Base64 + AES-256-CBC（SHA-256 派生 key，零 IV，PKCS#7）；2.9.352 起使用 current key。

Native 发送路径：`AutoRegTask.getC(17)` → `NetUtils.track` → `CenterDataAPI::post1` + `postHttpsRequest`。`getAddr(17)=signup/auto_reg_v2`。完整说明见 [docs/protocol.md](docs/protocol.md) 与 [evidence/native-autoreg-path.json](analysis/app-version-2.9.365/evidence/native-autoreg-path.json)。

### 已验证接口

| 能力 | Endpoint | 关键参数 |
|------|----------|----------|
| 游客注册 | `/signup/auto_reg_v2` | `uuid`、`channel`、`device_token`、`gender`、`oauth_*`、`p` |
| 搜索 | `/bookcity/get_filter_search_book_list` | `page=0..N`、`count=10` |
| 全站书城 | `/bookcity/get_filter_book_list` | `tab_type=200`、`order=uptime`、`count=100` |
| 排行 | `/bookcity/get_rank_book_list` | `order`、`time_type`、`page` |
| 详情 | `/book/get_info_by_id` | `book_id` |
| 评论 | `/book/get_review_list` | 热门 `type=2`；普通 `type=1` |
| 整本目录 | `/chapter/get_updated_chapter_by_division_new` | `division_id=0` |
| 章节 command | `/chapter/get_chapter_cmd` | `chapter_id` |
| 章节元数据 | `/chapter/get_cpt_ifm` | `chapter_id`、`chapter_command`；被拦时官方会再带 `geetest_*` 重试；打戳后普通 8 键即可 |
| 间贴计数 | `/chapter/get_tsukkomi_num` | `chapter_id` |

免费章过滤必须同时满足 `is_paid=0` 且 `auth_access=1`。正文 CDN 为 `gzip → zlib → UTF-8 HTML fragment`。业务 API 走 native libcurl；CDN 走 Java/OkHttp，服从系统代理。残留 `http_proxy=127.0.0.1:8085` 会让官方阅读器停在加载中，与协议门无关。

## TLS 指纹与采集入口

官方 App 业务栈是 APK 内 `libcurl/7.56.1` + `OpenSSL/1.1.0f`。ClientHello ALPN 只有 `http/1.1`（native 代码虽写 `CURLOPT_HTTP_VERSION=3`，该 so 未编 nghttp2，线上仍是 HTTP/1.1）。

| 栈 | JA3 MD5 | ALPN |
|----|---------|------|
| 官方 App / APK libcurl | `1aee0238942d453d679fc1e37a303387` | `http/1.1` |
| Python `curl_cffi` 默认 | `87e2668215f385b4ea50bcc9cbe4279d` | `h2,http/1.1` |

对照证据：[evidence/tls-hello-compare.json](analysis/app-version-2.9.365/evidence/tls-hello-compare.json)。Pixel 上 APK libcurl 注册仍 `310017`；官方出生游客用 `curl_cffi` 默认 JA3 也可 `100000`。因此 JA3 / 键序 / 短 UA 都不是当前门。线上明文见 [official-uid-mitm-cpt.json](analysis/app-version-2.9.365/evidence/official-uid-mitm-cpt.json)，字段对照见 [official-vs-python-field-compare.json](analysis/app-version-2.9.365/evidence/official-vs-python-field-compare.json)。

采集与核验入口（匿名、无需登录）：

| 用途 | 链接 |
|------|------|
| ClientHello / JA3 / JA4 / Akamai 指纹 JSON | https://tls.peet.ws/api/all |
| TLS 与 HTTP/2 指纹页 | https://tls.browserleaks.com/ |
| TLS 指纹 JSON | https://tls.browserleaks.com/json |
| 浏览器 TLS 说明页 | https://browserleaks.com/tls |
| 本仓库官方 vs Python Hello 对照 | [analysis/app-version-2.9.365/evidence/tls-hello-compare.json](analysis/app-version-2.9.365/evidence/tls-hello-compare.json) |
| 游客强制 HTTP/1.1 canary | [analysis/app-version-2.9.365/evidence/ja3-guest-canary.json](analysis/app-version-2.9.365/evidence/ja3-guest-canary.json) |
| APK 静态指纹（2.9.362） | [analysis/anonymous-reader/evidence/fingerprint.txt](analysis/anonymous-reader/evidence/fingerprint.txt) |

本地复放官方 Hello 时使用 `analysis/app-version-2.9.365/scripts/oldcurl/` 中的 `oldcurl_post.c`（`dlopen` APK `libcurl.so`）。pcap 与 so 本体不进 Git。

## 文档

| 文档 | 内容 |
|------|------|
| [docs/protocol.md](docs/protocol.md) | 签名、Native 注册通路、310017 排除项（含 uid MITM 与字段对照） |
| [docs/architecture.md](docs/architecture.md) | 采集服务分层、队列与调度 |
| [docs/deployment-ali-cloud.md](docs/deployment-ali-cloud.md) | Compose / 出口 / 密钥挂载 |
| [analysis/app-workflow/report.md](analysis/app-workflow/report.md) | 2.9.362 HMAC/AES 恢复 |
| [analysis/app-version-2.9.365/report.md](analysis/app-version-2.9.365/report.md) | 2.9.365 正文门与真机结论 |
| [analysis/app-version-2.9.365/analysis-progress.md](analysis/app-version-2.9.365/analysis-progress.md) | 进度账本 |
| [analysis/anonymous-reader/report.md](analysis/anonymous-reader/report.md) | 游客身份必须从同一出口注册 |
| [analysis/auth-capability/report.md](analysis/auth-capability/report.md) | 空 token 不可用；账号密码登录会出验证码 |

## 环境

Python 3.13+，依赖见 `requirements.txt`。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m compileall -q .
.\.venv\Scripts\python.exe -m unittest -v
```

控制台：

```powershell
cd frontend
npm install
npm test
npm run dev
```

作者本机把解释器放在 `D:\reverse_ENV\.venv`；克隆本仓不要求该路径。

## 凭据

默认使用 App 自动创建的未绑定游客。`tokens.json` 只保存在本机，已写入 `.gitignore`。

FastAPI / Docker 可设置 `CIWEIMAO_GUEST_BOOTSTRAP_ENABLED=1`。静态代理可在启动时校验；动态租约会延迟到第一次真实搜索、同步或下载：先提取出口，再经同一出口调用 `auto_reg_v2`。新游客以 `0600` 权限原子写入 `CIWEIMAO_TOKEN_PATH`。

从已登录设备提取身份（会写入 `tokens.json`，已有正式账号时不要覆盖）：

```powershell
python -m client token-extract --device <adb-serial>
python -m client token
```

## 命令行

```powershell
python -m client search "青春"
python -m client search "青春" --max-pages 0
python -m client crawl-search "方舟" --max-books 20
python -m client crawl-all --max-pages 1 --max-books 5
python -m client crawl-all --yes
python -m client download 100448715 --free-only --include-book-id
python -m client list
```

全站模式默认 `order=uptime`、每页 100 本。遇到空页、重复页或整页没有新 `book_id` 时停止。`--free-only` 下载遇到 App `310017` 时，会使用独立网页 session（章节页 → 两次 AJAX → 双层 AES-CBC）；默认请求间隔为 3 秒，不发送 App 凭据。该 fallback 只覆盖公开文本免费章，VIP/图片章仍需网页登录态。详见 [docs/web-fallback.md](docs/web-fallback.md)。

## FastAPI 服务

单 worker：

```powershell
python -m service
```

Swagger：`http://127.0.0.1:8000/docs`。控制台开发代理见 `frontend/vite.config.ts`。

| Method | Path | 用途 |
|--------|------|------|
| `GET` | `/health` | 数据库、队列、调度器与凭据配置 |
| `GET` | `/api/books/search?q=书名` | 异步搜索并更新索引 |
| `POST` | `/api/downloads/by-name` | 按书名投递免费章 TXT 任务 |
| `GET` | `/api/downloads/stats` | 索引、下载与自动下载统计 |
| `POST` | `/api/sync/all` | 榜单 + 新书合并同步 |
| `GET` | `/api/tasks` | 任务列表 |
| `GET` | `/api/rankings/latest` | 各榜单最新快照 |
| `GET` | `/api/identity` | 游客身份槽（不回显 token） |
| `POST` | `/api/egress/probe` | 探测当前出口 |

按书名下载返回 `202` 与任务 ID，实际抓取由 worker 完成。

调度默认每 30 分钟一个 `sync_all`，两段同步共享同一个代理租约；完成后最多投递 100 本未下载书。`coalesce=True`、`max_instances=1`。SQLite 默认 `data/ciweimao.sqlite3`（WAL），正文文件在 `output_api/`。完整边界见 `docs/architecture.md`。

### 配置

| 环境变量 | 默认 | 说明 |
|----------|------|------|
| `CIWEIMAO_DB_PATH` | `data/ciweimao.sqlite3` | SQLite 路径 |
| `CIWEIMAO_OUTPUT_DIR` | `output_api/` | TXT 输出目录 |
| `CIWEIMAO_TOKEN_PATH` | `tokens.json` | 游客/登录凭据 |
| `CIWEIMAO_GUEST_BOOTSTRAP_ENABLED` | `0` | 启动或首次使用时创建游客 |
| `CIWEIMAO_SCHEDULER_ENABLED` | `1` | 是否在本进程启动调度器 |
| `CIWEIMAO_SYNC_INTERVAL_MINUTES` | `30` | 合并同步周期 |
| `CIWEIMAO_AUTO_DOWNLOAD_ENABLED` | `1` | 同步后自动投递免费章 |
| `CIWEIMAO_WEB_FALLBACK_ENABLED` | `1` | App `310017` 后是否回退公开 Web 免费章链 |
| `CIWEIMAO_WEB_MIN_INTERVAL_SECONDS` | `3` | 同一 Web session 的最小请求间隔 |
| `CIWEIMAO_READINESS_ALLOW_WEB_FALLBACK` | `0` | 是否允许 Web canary 作为服务就绪依据（App gate 仍单独展示） |
| `CIWEIMAO_QUEUE_WORKERS` | `1` | 任务 worker 数 |
| `CIWEIMAO_PROXY_PROVIDER` | `auto` | `direct` / `static` / `kuaidaili_dps` |
| `CIWEIMAO_PROXY_URL` | 空 | 静态代理 URL |
| `KDL_SECRET_ID(_FILE)` | 空 | 快代理 SecretId |
| `KDL_SECRET_KEY(_FILE)` | 空 | 快代理 SecretKey |

也可用 `CIWEIMAO_LOGIN_TOKEN`、`CIWEIMAO_ACCOUNT`、`CIWEIMAO_DEVICE_TOKEN` 注入凭据；这些值不会写入数据库或接口响应。同一进程内 Scheduler 与 API 共存时必须 `--workers 1`。

## Docker Compose

`Dockerfile` 与 `compose.yaml` 使用独立 project 名 `ciweimao-api-reverse`，默认绑定 `127.0.0.1:18086`。数据与下载分别持久化到 `runtime/data/` 与 `runtime/output/`。快代理密钥走 Compose secrets；游客凭据为 `runtime/data/guest-tokens.json`。部署说明见 [docs/deployment-ali-cloud.md](docs/deployment-ali-cloud.md)。

## License

[MIT](LICENSE)
