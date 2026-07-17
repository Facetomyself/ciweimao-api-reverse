# 刺猬猫 App 搜索、全站枚举与免费章节协议报告

## 基本信息

| 项目 | 值 |
|------|-----|
| 目标文件 | `analysis/anonymous-reader/input/ciweimao-2.9.362.apk` |
| SHA-256 | `D74F25B282AC32B396948473341CD6145FDEB5DE923A2BC3D29C759D72B816F0` |
| 文件类型 | Android APK，360 Jiagu，Native Android / Kotlin |
| 架构 | ARM64 主分析，APK 同时含 ARMv7 |
| App | `com.kuangxiangciweimao.novel` 2.9.362 (`290362`) |
| 分析时间 | 2026-07-17 16:05–17:20 |
| 分析深度 | L3（运行时日志 + Flow + Native 静态 + 真实请求复验） |

## 目标概述

本轮只分析官方 Android App 的搜索、排行榜、书籍详情、整本目录与免费正文协议。TXT / EPUB、插图和本地缓存等既有下载格式能力不再重复逆向。

## 执行摘要

1. App 2.9.362 的业务 API 由 Native `curl` 发出，当前 mitmproxy Flow 未出现这些请求；App 自身 debug log 同时记录了加密响应和解密 JSON。封面及正文 CDN 则会进入 mitmproxy，证明两者是不同网络分支。
2. 84 个业务请求的 `p` 均可由 HMAC-SHA256 签名公式重算，结果 `84/84` 一致。
3. `libcwmhttps.so` 静态确认 2.9.362 使用新的 AES response key 分支：SHA-256 派生 256-bit key、零 IV、AES-CBC、PKCS#7。旧 2.9.312 key 仍作为另一个 mode 分支保留。
4. 使用恢复后的签名和解密链发起真实 2.9.362 搜索，请求返回 10 本，`book_id` 及顺序与 App 抓取页面完全一致；旧 2.9.312 链只返回少量结果，不能替代当前搜索。
5. 全站书城入口 `/bookcity/get_filter_book_list` 以 `tab_type=200&order=uptime&count=100` 从第 0 页分页；实测前三页各 100 本，共 300 个不同 `book_id`。
6. 免费章节不能只看 `is_paid=0`，必须同时要求 `auth_access=1`。433 章样本中有 5 章是“免费标记但无访问权”，直接按免费标记抓会踩坑。

## 关键发现

### F-001：业务 API 与 CDN 使用分离的网络路径

- **位置**：`captures/app_actions_20260717_160554.log`、`captures/app_actions_20260717_161359.flow`
- **描述**：logcat 中有 84 个 Native API 请求，但同一时段 Flow 中没有 `app1.happybooker.cn` 业务 POST；Flow 只包含封面、头像、上报和 7 个正文 CDN GET。
- **证据**：Native 日志 tag 为 `curl`；Flow 共 177 个请求，其中正文 CDN 7 个，全部 HTTP 200。
- **结论**：正文此前卡加载是代理感知的 CDN 分支断链，不是 Native API 或账号权限失败。
- **置信度**：`high`

### F-002：当前 App 请求签名已完整恢复

- **位置**：`libcwmhttps.so`、运行时 `signatures/ss/res/post` 日志
- **描述**：请求追加 `rand_str` 与 `p`，其中 `p=Base64(HMAC-SHA256(key, source))`。
- **证据**：84 个请求逐条重算，84 个全部一致；签名 source 仅由 percent-encoded account、App version、rand string 和固定 suffix 组成。
- **置信度**：`high`

### F-003：2.9.362 新响应 key 位于 Native mode=1 分支

- **位置**：`libcwmhttps.so` RVA `0x80D6C`
- **描述**：`CenterDataAPI::aes_256_cbc_decode` 比较 mode 与 `1`；命中时取 `.rodata` RVA `0x522A2` 的 current key，否则取 RVA `0x50A47` 的 legacy key。
- **证据**：RVA `0x80DF0` 调用 SHA-256；RVA `0x80DF4` 初始化 16 字节零 IV；底层调用 `AES_set_decrypt_key(...,256,...)` 和 `AES_cbc_encrypt(...,enc=0)`。
- **验证**：抓包中的章节 command 短响应可按该链还原；真实 2.9.362 搜索响应也能解密。
- **置信度**：`high`

### F-004：搜索分页从 0 开始，跨页必须去重

- **位置**：`/bookcity/get_filter_search_book_list`
- **描述**：固定 `count=10`；实测关键词“青春”第 0–5 页每页均为 10 条。
- **证据**：60 条结果中出现 1 个跨页重复，最终 59 个不同 `book_id`。
- **验证**：恢复后的客户端对第 0 页发起真实请求，10 个 `book_id` 与 App 抓取页面顺序完全一致。
- **置信度**：`high`

### F-005：书城可作为全站枚举入口

- **位置**：`/bookcity/get_filter_book_list`
- **描述**：`tab_type=200`、`order=uptime`、`count=100` 可连续分页，页码从 0 开始。
- **证据**：真实 2.9.362 请求第 0–2 页分别返回 100 本，相邻页无 `book_id` 重复，共 300 本。
- **边界**：未跑到全站末页，因此不声称当前站点总书量。
- **置信度**：`high`

### F-006：一次请求返回整本分卷与完整章节目录

- **位置**：`/chapter/get_updated_chapter_by_division_new`
- **描述**：传 `book_id` 与 `division_id=0`，响应 `data.chapter_list` 是分卷数组，每卷内嵌完整 `chapter_list`。
- **证据**：两个 App 样本分别返回 2 卷 / 433 章和 1 卷 / 78 章。
- **置信度**：`high`

### F-007：免费抓取边界是双条件，不是单看付费标记

- **位置**：目录章节项和 `/chapter/get_cpt_ifm` 的 `chapter_info`
- **描述**：可抓取章节必须同时满足 `is_paid=0` 与 `auth_access=1`。
- **证据**：433 章样本为：50 个免费可读、5 个免费但不可访问、378 个付费不可访问；另一本 78 章样本全部免费可读。
- **置信度**：`high`

### F-008：当前正文 CDN 是 gzip + zlib 双层压缩

- **位置**：`e6.kuangxiangit.com/*.txt`
- **描述**：HTTP wire body 使用 gzip，外层解压后以 zlib `78 9c` 开头，最终是 UTF-8 HTML fragment。
- **证据**：本轮 7 个 CDN 样本全部满足同一格式并返回 HTTP 200。
- **置信度**：`high`

## 架构概览

```text
官方 App 2.9.362
  -> 游客/正式账号 identity
  -> Native CenterDataAPI
       -> rand_str + HMAC-SHA256 request signature
       -> libcurl business POST
       -> Base64 + AES-256-CBC response
  -> Java/Kotlin reader layer
       -> /chapter/get_chapter_cmd
       -> /chapter/get_cpt_ifm
       -> HTTP CDN GET
       -> gzip -> zlib -> HTML -> reader render
```

## 客户端改造

- 默认协议切换到 App 2.9.362，不再用 2.9.312 搜索结果冒充当前 App。
- 新增 `client/protocol.py`，封装当前请求 HMAC 签名。
- `Session` 根据版本选择 base URL、签名门槛和 response key，同时保留 2.9.312 legacy 分支。
- 搜索与全站分页均按 `book_id` 去重；整页没有新增 ID 时停止。
- 免费章节过滤同时校验 `is_paid` 和 `auth_access`。
- CDN 解码兼容 requests 已解 gzip和仍保留 gzip 外层两种输入。

## 敏感点清单

| 类别 | 位置 | 描述 | 状态 |
|------|------|------|------|
| 请求签名 | `client/protocol.py` / Native `CenterDataAPI` | HMAC-SHA256 | 已确认 |
| 响应加密 | `client/crypto.py` / RVA `0x80D6C` | 双 key AES-256-CBC | 已确认 |
| 网络请求 | Native curl + CDN GET | 双网络路径 | 已确认 |
| 章节授权 | 目录 / cpt_ifm | `is_paid` + `auth_access` | 已确认 |
| 证书校验 | Native curl | 未作为本轮阻塞点展开 | 待专项分析 |
| Root/调试检测 | 360 Jiagu | 本轮未触发阻滞 | 不适用 |

## 脱敏说明

- 原始 logcat 和 Flow 含本机游客凭据，只保留在 Git exclude 的 `captures/`，不进入报告或提交。
- 报告、evidence JSON 与测试 fixture 均不保存真实 account、token、device ID 或正文全文。
- Native 静态 key 与签名常量属于客户端协议常量，不是用户凭据。

## Triage 遗留项

- 未执行真正不设上限的全站遍历，因此当前站点总书量与末页行为仍是运行时任务，不在报告中虚构。
- `tools/ldplayer/ldplayer.ps1` 的 `proxy-off` 清理不完整属于环境仓问题，当前项目实例已手工清理，但上游脚本尚未修改。
- 现有 `tokens.json` 可能是其他账号凭据且已过期；本轮真实复验临时使用抓包中的游客身份，未写回文件。

## 复现产出

- `client/protocol.py`：当前 App 请求签名。
- `client/config.py` / `client/crypto.py` / `client/api.py`：版本化 transport 与 response crypto。
- `analysis/app-workflow/evidence/runtime-summary.json`：脱敏运行时证据摘要。
- `analysis/app-workflow/evidence/native-response-crypto.txt`：Native 函数与 RVA 证据。
- `test_client.py`：签名、current/legacy decrypt、分页、免费边界及 gzip+zlib 回归。
