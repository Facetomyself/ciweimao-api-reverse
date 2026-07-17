# ciweimao-api-reverse

刺猬猫（Ciweimao / Hbooker）官方 Android App API 的搜索、书城枚举与免费章节抓取客户端。

本仓当前只负责：

- 复现 App 2.9.362 的请求签名与响应解密；
- 按关键词从第 0 页开始搜索并按 `book_id` 去重；
- 从书城入口按更新时间连续遍历书籍；
- 一次请求获取整本分卷与章节目录；
- 仅处理 `is_paid=0` 且 `auth_access=1` 的免费可读章节。

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
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m pip install requests pycryptodome
```

## 凭据

可使用 App 自动创建的游客身份，无需绑定正式账号。`tokens.json` 只保存在本机并已排除 Git。

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

## 验证

```powershell
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m compileall -q client test_client.py smoke_test.py
& "D:\reverse_ENV\.venv\Scripts\python.exe" -m unittest -v
```

动态证据与三件套位于：

- `analysis/anonymous-reader/`
- `analysis/app-workflow/`
