# 310017 网页章节回退方案

更新：2026-09-02

## 结论

App `chapter/get_cpt_ifm` 对 Python 自注册游客仍返回 `310017`。2026-09-02
uid MITM 已证明官方线上没有隐藏头 / Cookie，键序与 TLS 栈也不是门；官方出生
游客在官方进程读章成功后，独立客户端可以 `100000`。公开站点使用另一套无签名
网页协议，免费章可以在同一出口通过下列链路读取：

```text
GET  /chapter/{chapter_id}                         # 建立/刷新 ci_session
POST /chapter/ajax_get_session_code                # chapter_id -> access key
POST /chapter/get_book_chapter_detail_info         # chapter_id + access key
     -> chapter_content + encryt_keys (双层 AES-CBC)
```

客户端已将该链路实现为 `client.web.WebChapterSession` /
`AsyncWebChapterSession`，仅在调用方明确处于 `free_only` 且 App 返回
`310017` 时回退。网页请求不携带 App 的 `account`、`login_token`、
`device_token`、`app_version`、`p` 或 `chapter_command`。

## 解密与清洗

`encryt_keys` 的索引是 access key 字符的 Unicode code point：

```text
first_key  = keys[ord(access_key[-1]) % len(keys)]
second_key = keys[ord(access_key[0])  % len(keys)]
```

每一层载荷为 `Base64(IV || AES-CBC(ciphertext))`，PKCS#7 去填充；第一层明文
仍是第二层 Base64，第二层得到 HTML。导出前删除水印 `<span>`，再按段落/`br`
归一化为 TXT。

## 会话与限速边界

- 每个 Web session 维护独立 Cookie jar，并接收响应 `Set-Cookie`（尤其是
  `ci_session` 轮换）；不复制其他浏览器会话的旧 Cookie。
- 一个 session 内完整的 GET → session → detail 序列加锁串行执行；默认章节间隔
  `3s`，避免站点的单活跃会话限制。生产并发由任务队列控制，不能把同一 Web
  session 当成无状态连接池。
- 当前实现只支持文本免费章。VIP/图片章仍需要网页登录或购买态，不能把网页
  预览当作 App 已购正文。
- 代理只从当前 `ProxyLease` 注入；Web fallback 不修改系统代理，也不读取或写入
  项目 `tokens.json`。

## 证据与复现

脱敏 canary：[`analysis/app-version-2.9.365/evidence/web-fallback-canary.json`](../analysis/app-version-2.9.365/evidence/web-fallback-canary.json)

```powershell
& "D:\reverse_ENV\.venv\Scripts\python.exe" `
  "D:\reverse_ENV\workspace\ciweimao-api-reverse\analysis\app-version-2.9.365\scripts\web_fallback_canary.py" `
  --chapter-id 112001971
```

canary 记录三次 HTTP 状态、字节数、正文长度/hash 与 Cookie 名称，不落盘访问
密钥、Cookie 值、密文或正文。该证据证明网页 detail 的业务码 `100000`；
`app_protocol_gate.known_code=310017` 保持独立，不能据此把 App gate 标为
`serverAccepted`。

## 外部方案交叉验证

本轮检索路径：先用 `search-layer` deep（Exa/Tavily/Grok）查询
`Ciweimao chapter ajax_get_session_code get_book_chapter_detail_info chapter_access_key AES`
与 `刺猬猫 chapter_access_key ajax_get_session_code`，再用 `gh repo view`、
`gh api` 读取候选仓库源码和 `saudadez21/novel-downloader#157` 的维护者评论；
最后用本机公开 canary 做真实请求核验。并行检索代理负责候选发现，控制器重新读取
源码、仓库元数据并独立复跑 canary，未把重复链接当成独立证据。

以下公开实现均采用同一 GET + 两次 POST 与双层 AES 思路，本地通过 `gh api`
直接读取源码/Issue 交叉核对：

| 来源 | 证据 | 适用性 |
|---|---|---|
| [guohuiyuan/go-novel-dl](https://github.com/guohuiyuan/go-novel-dl/blob/main/internal/site/ciweimao.go)（185★，AGPL-3） | 文本章节请求、access key、双层 AES、`span` 清理 | 直接对应当前网页链；仅借鉴协议，不复制 AGPL 代码 |
| [dteviot/WebToEpub](https://github.com/dteviot/WebToEpub/blob/ExperimentalTabMode/plugin/js/parsers/CiweimaoParser.js)（1437★） | 浏览器端 session/detail 请求与 free chapter 分支 | 证明请求头/顺序；浏览器扩展不作为本项目运行时依赖 |
| [404-novel-project/novel-downloader](https://github.com/404-novel-project/novel-downloader/blob/master/src/rules/special/original/ciweimao.ts)（1884★，AGPL-3） | `chapter_access_key` 与 `encryt_keys` 字段及水印清理 | 作为字段命名交叉证据 |
| [saudadez21/novel-downloader#157](https://github.com/saudadez21/novel-downloader/issues/157) | 维护者说明单活跃 session、`Set-Cookie` 轮换会使旧 Cookie 失效 | 支撑本实现的 Cookie jar、串行与限速约束 |

## 明确不采用的路径

- 继续盲改 App HMAC、UA、JA3、`save_reader_oaid` 或 HTTP 版本：已有
  `analysis/app-version-2.9.365` canary 证明这些变量不能改变 `310017`。
- 把 GT3 滑块当作官方游客必经步骤：它只属于被风控身份的恢复门，不能解释
  官方游客直接 `100000`；本项目不自动解题。
- 把网页 Cookie/响应密钥拼回 App API，或把网页成功写成 App 协议完成：两者
  是不同产品面，凭据与验收证据必须隔离。

## 运行配置

服务配置：

| 环境变量 | 默认 | 作用 |
|---|---:|---|
| `CIWEIMAO_WEB_FALLBACK_ENABLED` | `1` | 是否允许 free-only 下载在 App `310017` 时回退网页 |
| `CIWEIMAO_WEB_MIN_INTERVAL_SECONDS` | `3` | 同一网页 session 的请求最小间隔 |

关闭回退后，原有 App 语义不变：正文 `310017` 会进入协议失败分类，不会静默
返回网页预览。
