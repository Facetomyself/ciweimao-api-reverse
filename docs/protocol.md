# App 2.9.365 协议冻结说明

更新：2026-09-04。正文接口跟着「这个身份有没有走过 GT3 bind」走。RuyiDOM 黑盒 `stamp_gt3()` 已把新游客独立会话打成 `100000`。纯算 `w` 仍是 `error_03`，不能标 algorithmic。本文件只记录已经闭合的事实。

详细 canary 与排除项见 [analysis/app-version-2.9.365/analysis-progress.md](../analysis/app-version-2.9.365/analysis-progress.md)、[report.md](../analysis/app-version-2.9.365/report.md)。

## 签名

官方原签 APK 的 HMAC key 来自 `GetInfo`：`PackageInfo.signatures[0].toCharsString()` 再 `Md5Encode`，不是 `.so` 字面量。运行时值为：

```text
a90f3731745f1c30ee77cb13fc00005a
```

suffix 以 live `p` 为准，字面 `CkMxWNB666`。游客注册 JSON 无 `account` 时，HMAC 占位 `cmw666`。

```text
source = account={urlenc}&app_version={ver}&rand_str={rand}&signatures={certMD5}CkMxWNB666
p      = Base64(HMAC-SHA256(key=certMD5, msg=source))
```

`test_client.py` fixture（`书客1234567` / `2.9.362` / `10072263a65a4345`）得到 `RTemA7/IKa4GppnByNkaz0tVeAk1Cn8LnSM5NZ993Qc=`。`HMAC(MD5(source))` 与 suffix=`MD5("CkMxWNB666")` 均不匹配该 fixture。

响应：Base64 → AES-256-CBC，key 先 SHA-256，IV 16 字节全零，PKCS#7。`mode=1` 走 2.9.352+ current key，否则 legacy。

## Native 注册通路

```text
AutoRegTask.doHttpRequest
  uuid = Installation.id = "android" + UUID（files/INSTALLATION）
  gender / channel / oauth_*
  → BaseTaskNew.getC(17, map)
       setCommonParams：未登录不加 account/login_token
                         加 app_version、device_token
                         URLEncoder.encode 每个值
       → NetUtils.track(ctx, 17, json, UrlConstants.getUserType())
            CenterDataAPI::GetInfo（一次）
            CenterDataAPI::post1          # 表单 + rand_str + p
            host(userType) + getAddr(17)
            CenterDataAPI::postHttpsRequest
```

`getAddr` 表 `dword_527DC[apiId-2]`（`libcwmhttps.so` SHA-256 `428d5f646236fe24ad2eef11b2ec2e54f5141bcf70af9e3bb6684644827036eb`）：

| apiId | 路径 |
|-------|------|
| 17 | `signup/auto_reg_v2` |
| 154 | `signup/save_reader_oaid` |
| 259 | `chapter/get_cpt_ifm` |

首次游客 `getUserType()=2` → `https://app1.hbooker.com/`。`userType=1` → `https://app1.happybooker.cn/`。

`getHead0` UA：

```text
Android  com.kuangxiangciweimao.novel.c  {versionName}, {brand}, {model}, {sdk}, {release}
```

Pixel 6 实测：`Android  com.kuangxiangciweimao.novel.c  2.9.365, google, Pixel 6, 35, 15`。

`postHttpsRequest` slist：`Content-Type: application/x-www-form-urlencoded`、`charsets: utf-8`、`Expect:`、上述 UA。uid MITM 证实空 `Expect` 不上线；线上头名是 Host / Accept / Content-Type / charsets / User-Agent / Content-Length。`CURLOPT_HTTP_VERSION=3`；APK `libcurl/7.56.1` 无 nghttp2，setopt 返回 `CURLE_UNSUPPORTED_PROTOCOL`，协商 HTTP/1.1，与官方 pcap / MITM 一致。`get_cpt_ifm` 表单键序：

```text
account, app_version, chapter_command, chapter_id, device_token, login_token, rand_str, p
```

注册成功后 `SendImeiTask.getC(154)` 上报 OAID / `am=MD5(ANDROID_ID)`。空 OAID 时接口可返回 `400000`，官方游客仍能读章。

## 310017 已排除

下列单项均不能把独立客户端的 `get_cpt_ifm` 从 `310017` 打成 `100000`：

- HMAC / AES 换代
- APK 版本字符串（Wandoujia 当前仍是 2.9.365）
- 缺 `send_client_info`、主机切换、冷启动 prelude
- 前缀 UA 或完整 `getHead0` UA
- `charsets` / `Expect`
- `CURLOPT_HTTP_VERSION=3`（实际未协商到 HTTP/2）
- 官方 JA3（Pixel 上 APK libcurl 注册 `100000`，正文仍 `310017`）
- `auto_reg_v2` 缺字段；补 `save_reader_oaid`
- 官方 extras + 导流章 `106129841`
- 官方出生身份本身：2026-09-02 11:09Z SharedPreferences 游客移植到 Python 或进程外官方 libcurl，正文仍 `310017`
- Cookie / 连接复用 / 额外 POST 键 / `CURLOPT_IPRESOLVE=V4`：官方 `post===>` 与 uid MITM 键序一致，SO 无 Cookie，每次新 easy；默认与 V4 在已放行身份上均为 100000
- Python 默认键序、短 UA、缺 `charsets`、`curl_cffi` JA3，以及字段集合/形状：官方 MITM 与 Python 默认是同一 8 键、同一形状，官方线上 `Accept=*/*`；同一套默认 Python 请求下，已放行官方出生游客 `100000`，自注册游客 `310017`（`official-vs-python-field-compare.json`）
- 官方读章序 / 冷启动 prelude 复放
- 官方独有前置接口：`get_startpage_url_list(height=2400,width=1080)`、`get_index_list`、`get_prop_info`、`add_specific_recommend_exposure`、`set_read_chapter_record`、`add_readbook` 在自注册游客上都是 `100000`，随后 cpt 仍 `310017`（`official-unique-replay-canary.json`）
- uid MITM 才能看见的隐藏头或 Set-Cookie：冷启动 9 条与未缓存 `get_cpt_ifm` 均无
- 全新官方游客的**第一次** `get_cpt_ifm` 另有隐藏字段：第一次仍是上面那 8 键。打戳发生在随后的极验重试（`official-stamp-event-canary.json`）
- 只调 API1，或回填空/`challenge` only / 假 `validate|jordan`：空与 only 仍 `310017`，假三元组是 `280002`，随后普通包回到 `310017`（`official-geetest-retry-canary.json`）
- 「没点验证码」不是漏字段：官方 GT3 是 bind 一键，`gettype.php` → `get.php` → `ajax.php` 约 1s，无滑块资源；第一次 cpt 128b，ajax 后 1.0k（`official-gt3-wire-canary.json`）

2026-09-03 对 `pm clear` 后的全新官方游客：Python 先打 `310017`。官方立即阅读时第一次 `get_cpt_ifm` 仍是 8 键；接着 OkHttp HTTP/2 GET `/signup/geetest_first_register`；第二次 `get_cpt_ifm` 增加 `geetest_challenge` / `geetest_validate` / `geetest_seccode`。之后同一游客在 Python 上变成 `100000`。已放行身份再用普通 8 键也能 `100000`。

同日把仍 `310017` 的 Python 自注册身份写入官方 SharedPreferences：官方进程能保住该身份。清掉本地阅读缓存后进入 `ReaderActivity4`，随后同一自注册身份在独立客户端变成 `100000`。已放行官方游客还原后仍 `100000`。当晚再注册一份全新游客（`40fe19acfd04`），无 MITM 走同一 oracle，约 53s 后独立客户端也是 `100000`。网页章节链是另一条产品面。uid `10237` REDIRECT 才能看见 native 业务 HTTPS；全局 `http_proxy` 看不到这条面。

被拦身份的 310017 回包只有 `code`+`tip`。官方 `BaseTaskNew` 对 310017 走 GT3 bind（`setPattern(1)` + `startCustomFlow`），`onDialogResult` 把三元组写回同一 `getC`。API1 本身不够；假三元组是 `280002`。官方 SDK 自己走完 bind 一键。残留系统代理会造成「真机无法加载」，与该业务码无关。

Python 目标是同一条 bind，而不是官方进程 oracle。`Session.stamp_gt3()` 用 RuyiDOM 跑官方 `static/tools/gt.js` 的 `initGeetest` bind，出三元组后独立会话 `get_cpt_ifm=100000`（`gt3-fullpage-w-canary.json`）。下载与协议探测在 `310017` 时默认 `allow_gt3_stamp=True`，失败且 `free_only` 才 Web fallback。`bind()` 默认仍 `Gt3BindNotReady`。AES+RSA packing 对 fullpage 9.2.0 是 `error_03 param decrypt error`，不得标 `algorithmic`。

证据索引：[evidence/](../analysis/app-version-2.9.365/evidence/)。黑盒 bind：`gt3-fullpage-w-canary.json`。新游客 oracle：`official-gt3-new-guest-oracle-canary.json`。自注册官方打戳：`official-python-born-gt3-oracle-canary.json`。stamp-event：`official-stamp-event-canary.json`。假重试：`official-geetest-retry-canary.json`。GT3 线：`official-gt3-wire-canary.json`。线上明文：`official-uid-mitm-startup.json`、`official-uid-mitm-cpt.json`。字段对照：`official-vs-python-field-compare.json`。官方独有接口复放：`official-unique-replay-canary.json`。身份对照：`official-vs-python-cpt-now.json`。

## 独立客户端的免费章回退

App `get_cpt_ifm` 的 310017 仍作为独立协议门记录，不再继续盲猜字段。为让
采集服务继续产出公开免费章，`client.web` 提供隔离的网页链：

```text
GET  www.ciweimao.com/chapter/{chapter_id}
POST www.ciweimao.com/chapter/ajax_get_session_code
POST www.ciweimao.com/chapter/get_book_chapter_detail_info
```

该链使用站点 Cookie 与 `chapter_access_key`，响应 `chapter_content` / `encryt_keys`
按双层 AES-CBC 解密，再去除水印 span。只有 `free_only=True` 且 App 返回 310017
时才允许回退；VIP/图片章不会被伪装成已购内容。网页 session 自己维护 Cookie
轮换并串行限速，绝不把 App `account`、`login_token`、`p` 等参数带入网页请求。

实现、运行配置与脱敏 canary 见 [web-fallback.md](web-fallback.md)。
