# 刺猬猫 App 2.9.365 协议升级报告

## 基本信息

| 项目 | 值 |
|------|-----|
| 目标文件 | `analysis/app-version-2.9.365/input/ciweimao-2.9.365.apk` |
| SHA-256 | `C9B2DA202C32F883536C26C3EA77CB32863ECB9CC1EF7248602E7DA116F6CB6B` |
| 文件类型 | Android APK，Bangcle/SecNeo（SecShell），Native Android |
| 架构 | ARM64 主分析；APK 同时含 ARMv7 与 `libSecShell-x86.so` |
| App | `com.kuangxiangciweimao.novel` 2.9.365 (`290365`) |
| 分析时间 | 2026-08-23 至 2026-08-27；续推进 2026-09-01 / 2026-09-02 / 2026-09-03 |
| 分析深度 | L3-partial；Node 黑盒 GT3 bind 已过 `get_cpt_ifm=100000`（不依赖 RuyiDOM）；纯算 `w` 仍 `error_03` |

## 目标概述

确认 2.9.362 章节正文接口 `310017` 是否只是版本字符串过期，以及 2.9.365 是否更换了 HMAC/AES。当前结论：签名与响应密钥未换；正文接口被服务端单独拦住。

## 执行摘要

1. `libcwmhttps.so` 哈希变化（362 `75f488dd...` / 365 `428d5f64...`），但 AES 双 key、`CkMxWNB666` 后缀、业务基址字符串均仍在，只新增 `reader/get_vip_consume_record_list`。
2. `libcurlhttps.so` 与 `libJavaJni.so` 与 2.9.362 字节级相同。
3. 本地过期 token 解密后得到 `200100`，证明 2.9.365 HMAC 与 AES 解密可用。
4. 新游客下：搜索、目录、`get_chapter_cmd`、`get_chapter_download_cmd` 均为 `100000`；`get_cpt_ifm` / `download_cpt` / `check_download_cpt` 均为 `310017`，提示「请升级到最新版本客户端」。把 `app_version` 改成 `2.9.365` 并重算 HMAC **不能**过正文门。
5. Wandoujia 当前公开版仍是 2.9.365。因此 310017 不是“仓库里的 APK 过旧”。2026-09-03 对全新官方游客取证：第一次 `get_cpt_ifm` 仍是普通 8 键；官方接着 HTTP/2 GET 极验 API1，第二次 cpt 带 `geetest_*` 后身份放行。同日把 Python 自注册身份写入官方 App，官方进程打戳后独立客户端也变成 100000。当晚再注册一份全新游客，无 MITM 走同一 oracle，约 53s 后独立客户端也是 100000。网页章节链风控不同，不能代替这次 App 门。
6. Java 仍被 SecShell 加密（`assets/classes0.jar` 约 18.9MB，非 ZIP/DEX magic）。LDPlayer 上 x86 `libSecShell-x86.so` 在 maps/`fclose` SIGSEGV。**Pixel 6 原包 ARM64 冷启动进入 `WelcomeActivity`，panda 拉到 43 个结构有效 DEX（71,775,408 字节），含 `com.kuangxiangciweimao`。** wrapper 因 dump 后进程已死标 `partial`。已 dump DEX 字符串中无明文 `get_cpt_ifm`。debug 重签包仍不能当完整性单变量。
7. 外部源码与真实 canary 证明公开网页是可用的独立产品面：章节页 GET 后串行调用 `ajax_get_session_code` 与 `get_book_chapter_detail_info`，双层 AES-CBC 解密成功。客户端已将它接入 free-only fallback；App gate 仍单独记录为 310017。

## 关键发现

### F-044：Node 黑盒 bind 已过 App 门（不依赖 RuyiDOM）

- **位置**：`client/gt3_node_bind.mjs` / `client/gt3_w.py` / `static/tools/gt.js`
- **描述**：新游客 `310017` → 本机 Node `initGeetest` bind → 三元组 32/32/39 → `get_cpt_ifm=100000`。薄宿主 `w` len=704 会 `error_100` 并掉进 slide；补 Audio/WebGL/canvas 后 `w` len=1088 过 ajax。AES+RSA packing 仍 `error_03`。
- **证据**：`evidence/gt3-node-bind-canary.json`
- **置信度**：high

### F-043：RuyiDOM 黑盒 bind 已过 App 门

- **位置**：`client/gt3_w.py` / `static/tools/gt.js`
- **描述**：新游客 `310017` → RuyiDOM `initGeetest` bind → 三元组 32/32/39 → `get_cpt_ifm=100000`。误加载 `geetest.6.0.9.js` 没有 `initGeetest`。AES+RSA packing ajax=`error_03`。fullpage JS=`fullpage.9.2.0-guwyxh.js`。
- **证据**：`evidence/gt3-fullpage-w-canary.json`
- **置信度**：high

### F-042：Python 已冻 fullpage gettype/get 键，未打 ajax

- **位置**：`https://api.geetest.com/gettype.php`、`/get.php`
- **描述**：新游客 API1 成功。`gettype` 的 `type=fullpage`。`get.php` 必须带 `challenge`，成功包含 `c`/`s`。官方 stamp 用过的 `103.143.17.166` 现在 404。未 POST `ajax.php`。
- **证据**：`evidence/gt3-bind-boundary-canary.json`
- **置信度**：high

### F-041：Python 已接 GT3 bind 合同，`w` 仍不能标纯算

- **位置**：`client/gt3.py`
- **描述**：`first_register` 复现官方 API1。`retry_chapter_params` 只追加三元组。`bind()` 默认 `Gt3BindNotReady`。过滤 jadx 没有 `com.geetest.sdk`。公开滑块解题器不接入。
- **证据**：`client/gt3.py`、`test_gt3.py`
- **置信度**：high

### F-040：新注册游客可重复走官方 App GT3 oracle

- **位置**：官方 `LoginedUser` 注入 + 免费区 `ReaderActivity4`
- **描述**：全新 `auto_reg_v2` 游客 `40fe19acfd04` 基线 `310017`。写入官方 prefs 后身份保住。清阅读缓存后免费列表直进阅读器。停留后独立客户端普通 8 键 `100000`。已放行游客 `41c934e820ac` 还原后仍 `100000`。无 MITM，无 `ajax.php` 解题器，未写 `tokens.json`。
- **证据**：`evidence/official-gt3-new-guest-oracle-canary.json`
- **置信度**：high

### F-039：官方进程 GT3 bind 能给 Python 自注册游客打戳

- **位置**：官方 `LoginedUser` 注入 + 免费区 `ReaderActivity4`
- **描述**：不 `pm clear`。自注册 `83ae0babe4e9` 写入官方 prefs 后身份能保住。清本地阅读缓存后官方进入阅读器。随后同一身份独立客户端 `get_cpt_ifm=100000`。已放行游客还原/仍在设备上，cpt `100000`。未走网页章节链。
- **证据**：`evidence/official-python-born-gt3-oracle-canary.json`
- **置信度**：high

### F-038：官方 GT3 是 bind 一键，约 1 秒无滑块资源

- **位置**：`103.143.17.166` `/gettype.php` → `/get.php` → `/ajax.php`
- **描述**：第一次 `get_cpt_ifm` 128b。API1 之后 1.1s 内打完三枪极验机，无 `pic.php` / 静态图。ajax 后第二次 cpt 变成 1.0k。自动化未点验证码。
- **证据**：`evidence/official-gt3-wire-canary.json`
- **置信度**：high

### F-037：API1 或假极验三元组不能给自注册游客打戳

- **位置**：`BaseTaskNew` 310017 → `initJiyan` `setPattern(1)` → `onDialogResult` 回写三元组
- **描述**：Python 自注册 API1 已是 `success=1`。空字段 / 只带 challenge 仍 `310017`。假 `validate` + `|jordan` 变成 `280002`。之后普通包回到 `310017`。
- **证据**：`evidence/official-geetest-retry-canary.json`
- **置信度**：high

### F-036：全新官方游客靠极验重试打放行戳

- **位置**：第一次 `/chapter/get_cpt_ifm`（8 键）→ GET `/signup/geetest_first_register`（HTTP/2）→ 第二次 `get_cpt_ifm`（多 `geetest_challenge` / `geetest_validate` / `geetest_seccode`）
- **描述**：`pm clear` 后新游客 Python 先打 `310017`。官方立即阅读后按上序走完，Python 复打变成 `100000`。本轮没有点验证码控件。已放行官方游客已还原。
- **证据**：`evidence/official-stamp-event-canary.json`
- **置信度**：high

### F-035：官方独有前置接口不能给自注册游客打戳

- **位置**：`get_startpage_url_list` / `add_specific_recommend_exposure` / `set_read_chapter_record` / `add_readbook` 之后再打 `get_cpt_ifm`
- **描述**：这些接口补参后自身都是 `100000`。自注册游客 cpt 前/后仍 `310017`。
- **证据**：`evidence/official-unique-replay-canary.json`
- **置信度**：high

### F-034：官方与 Python 默认包字段集合相同，头值/键序差不是门

- **位置**：`/chapter/get_cpt_ifm` HTTP/1.1
- **描述**：官方线上头值 `Accept=*/*`、`charsets=utf-8`、长 UA；无 Expect / Cookie / Accept-Encoding。Python 默认 session 只有短 UA + Content-Type，键序不同。两边都是 8 个同名字段，形状一致。同一默认 Python 包：官方出生 `100000`，自注册 `310017`。
- **证据**：`evidence/official-vs-python-field-compare.json`
- **置信度**：high

### F-033：uid MITM 已解密官方 get_cpt_ifm 明文

- **位置**：`/chapter/get_cpt_ifm` HTTP/1.1
- **描述**：未缓存阅读序 info → bookmark×2 → `division_new` → cmd → cpt（两次）。线上头名与冷启动相同，键序与 logcat `OFFICIAL_CPT_ORDER` 相同。无 Cookie / Expect / refresh。缓存书不出 cpt。
- **证据**：`evidence/official-uid-mitm-cpt.json`
- **置信度**：high

### F-032：uid 级 MITM 已解密官方冷启动 HTTPS

- **位置**：uid `10237` tcp/443 REDIRECT → 设备 CONNECT → PC mitmdump
- **描述**：不用全局 `http_proxy`。冷启动 9 条 HTTP/1.1 POST，头名只有 Host/Accept/Content-Type/charsets/User-Agent/Content-Length。slist 里的空 `Expect` 不上线。无 Cookie / Set-Cookie。路径集合与 logcat 冷启动相同。Python 默认不打这组前置请求；`prelude-canary` 已复放仍 310017。
- **证据**：`evidence/official-uid-mitm-startup.json`
- **置信度**：high

### F-031：官方读章序复放不能放行 Python 自注册游客

- **位置**：`getAddr(33/36/116/264/259)` → 书签/目录/间贴/cmd/cpt
- **描述**：按官方 `url===>` 原序复放，再补 `get_version`/`get_check`/详情，自注册游客仍 `310017`。商店最新 Android 版本字面是 `2.9.293`，不是客户端过旧。
- **证据**：`evidence/official-read-sequence-replay-canary.json`
- **置信度**：high

### F-030：官方读章成功后，同一官方游客在独立客户端也变成 100000

- **位置**：`/chapter/get_cpt_ifm`
- **描述**：今天上午官方出生游客移植到 Python / oldcurl 仍 310017。官方进程内 pass6/9/10 读章成功后，同一游客在 curl_cffi 与 APK libcurl 上均为 100000。Python 自注册游客仍 310017。`IPRESOLVE_V4` 不是原因。
- **证据**：`evidence/official-vs-python-cpt-now.json`、`evidence/official-ipresolve-ab-canary.json`
- **置信度**：high

### F-029：官方 get_cpt_ifm 没有额外表单键或 Cookie

- **位置**：`CenterDataAPI::postHttpsRequest@0x6eae4`
- **描述**：logcat `post===>` 键序与 oldcurl `OFFICIAL_CPT_ORDER` 一致。SO 无 Cookie。每次请求 `curl_easy_init` / `cleanup`。
- **证据**：pass6/pass10 logcat；`libcwmhttps.so` 反汇编
- **置信度**：high

### F-028：延迟读 slist X0 拿不到更早的头

- **位置**：`curl_slist_append` X0 / `/proc/pid/mem`
- **描述**：挂钩期间密采会打死进程。等 3 秒再读 X0，链已空。末次仍是 oldcurl UA，正文仍 `100000`。
- **证据**：`evidence/official-inprocess-hwbp-pass10.json`
- **置信度**：high

### F-027：官方 get_cpt_ifm 的 slist 末次头就是 oldcurl UA

- **位置**：`curl_slist_append@0x3365c`
- **描述**：未读书详页只钩 slist 入口。正文仍 `100000`。8 次最后 dump 都是
  `User-Agent: Android  com.kuangxiangciweimao.novel.c  2.9.365, google, Pixel 6, 35, 15`，
  与 oldcurl 一致。打印全是 `#8`，更早的 slist 行未入镜。
- **证据**：`evidence/official-inprocess-hwbp-pass9.json`
- **置信度**：high

### F-026：after_getHead0 全线程 HWBP 会打死进程，缓存阅读也不出网

- **位置**：`postHttpsRequest+0xdc` / `0x6ebc0`
- **描述**：pass7 先挂钩再进书城：0 hit，ADB/进程掉线。pass8 先停在 `立即阅读` 再钩：阅读器打开但无 `get_cpt_ifm`，仍 0 hit，随后进程再消失。`track` 入口可以活；这个返回点全线程不要再挂。
- **证据**：`evidence/official-inprocess-hwbp-pass7.json`、`evidence/official-inprocess-hwbp-pass8.json`
- **置信度**：high

### F-025：官方立即阅读走 track(259)，进程内正文仍 100000

- **位置**：`NetUtils.track` / `getC(259)` → `/chapter/get_cpt_ifm`
- **描述**：书详页出现 `立即阅读` 后再只钩 `track`。X3=259 出现四次。
  logcat 两次打到 `get_cpt_ifm`，ViseLog `259====> code=100000`。
  同一次打开还有 `get_chapter_cmd`（X3=264）等 100000。JNI dump 仍不是 HTTP 明文。
- **证据**：`evidence/official-inprocess-hwbp-pass6.json`
- **置信度**：high

### F-024：zip 映射 libcwmhttps 可 HWBP，本轮未抓到 get_cpt_ifm

- **位置**：`libcwmhttps.so` 从 `base.apk` `0x4354000` 映射；`track@0x6d260` /
  `postHttpsRequest@0x6eae4` / `getHead0@0x80cf0`
- **描述**：`--so libcwmhttps.so` 对不上 maps。用文件偏移 `04354000` 作 so_token
  后，书城 `get_index_list` 上三个函数都打中。`getHead0` 返回点寄存器仍有
  `Expect: `。免费新书阅读器翻章没有出网，`curl_slist_append` 0 hit。
- **证据**：`evidence/official-inprocess-hwbp.json`、
  `evidence/official-inprocess-hwbp-pass3.json`
- **置信度**：high

### F-023：eCapture 看不了官方进程内 APK OpenSSL 明文

- **位置**：APK `libssl.so`（`base.apk` 偏移 `0x3020000`）；eCapture v2.3.0
- **描述**：官方业务 TLS 是 OpenSSL 1.1.0f，不是 conscrypt。eCapture 在 Android 15
  上忽略 `--ssl_version`，固定加载 `boringssl_a_15`。官方阅读器打开导流章时
  logcat 有 native curl `100000`，但没有 `get_cpt_ifm`（缓存章）。Connect 元组有，
  HTTP 头没有。Frida 能枚举进程，attach 失败。
- **证据**：`evidence/official-inprocess-ecapture.json`
- **置信度**：high

### F-022：官方出生身份移植后仍 310017

- **位置**：官方 SharedPreferences `LoginedUser` → Python / Pixel `oldcurl_post`
- **描述**：服务端认的不是「这个游客是不是在官方进程里注册的」。
  Pixel 当前官方游客 `is_bind=0`，`get_my_info`/搜索/目录/`get_chapter_cmd` 均为 `100000`。
  同一套凭据打 `get_cpt_ifm`：Python curl_cffi 双主机 `310017`；
  APK libcurl 7.56.1 + 完整 getHead0 UA + `charsets`/`Expect` 仍 `310017`。
  `GetBookContentDetailTask` 只传 `chapter_id`、`chapter_command`、可选 `refresh=1`。
- **证据**：`evidence/official-born-identity-canary.json`、
  `evidence/official-born-oldcurl-canary.json`、panda
  `GetBookContentDetailTask.java`
- **置信度**：high

### F-021：公开 Web free-only fallback 已闭合

- **位置**：`client/web.py`、`client/api.py`、`client/async_downloader.py`
- **描述**：当 App `get_cpt_ifm` 返回 310017 且下载任务明确为 `free_only` 时，
  先 GET `www.ciweimao.com/chapter/{id}` 获取/刷新 `ci_session`，再 POST 两个
  AJAX 接口。`chapter_content` 按 access key 字符索引选择两层 AES key，解出 HTML
  后删除水印 span 并归一化 TXT。
- **证据**：`evidence/web-fallback-canary.json`（公开章节三步均 HTTP 200、detail
  `100000`、非空正文）、`test_web.py`（10 tests）、`test_web_fallback_integration.py`。
- **会话边界**：Web session 与 App credentials 完全隔离；Cookie jar 接收 Set-Cookie
  轮换，完整三请求序列加锁，默认间隔 3 秒。VIP/图片章不在本结论内。
- **置信度**：high
- **重建状态**：extracted（Web 协议）/ partial（App 购买态正文）

### F-020：完整 getHead0 UA / charsets / HTTP_VERSION=3 仍 310017

- **位置**：`CenterDataAPI::getHead0`、`postHttpsRequest`；Pixel APK libcurl
- **描述**：三项传输层差异已 canary。setopt HTTP/2 不被该 so 支持，协商 HTTP/1.1。注册成功，正文仍 310017。
- **证据**：`evidence/pixel-native-headers-canary.json`、`evidence/native-autoreg-path.json`
- **置信度**：`high`

### F-019：310017 是 GT3 恢复门，API1 已通

- **位置**：`/signup/geetest_first_register`；`BaseTaskNew.initJiyan`
- **描述**：正文 310017 回包只有 code/tip。官方恢复是 GET API1 再带极验三元组重试同一枪。API1 `success=1`。官方游客不走这条。滑块未做。
- **证据**：`evidence/geetest-api1-canary.json`
- **置信度**：`high`

### F-018：官方 extras 与导流章仍 310017

- **位置**：`/setting/ad_reader_check`、`/reader/send_client_info`、`/chapter/get_cpt_ifm`
- **描述**：Pixel 官方 libcurl 上按官方顺序补 extras，并打官方导流章 `106129841`，正文仍 `310017`。
- **证据**：`evidence/pixel-official-chain-canary.json`
- **置信度**：`high`

### F-017：Pixel 官方 libcurl 注册仍 310017

- **位置**：`/signup/auto_reg_v2`
- **描述**：官方 Hello 上 `auto_reg_v2=100000` 后正文仍 `310017`。不是 INSTALLATION 指纹。
- **证据**：`evidence/pixel-oldcurl-autoreg-canary.json`
- **置信度**：`high`

### F-001：请求签名与响应密钥未换代

- **位置**：`lib/arm64-v8a/libcwmhttps.so`
- **描述**：current/legacy AES key 与 HMAC suffix 仍在 `.rodata`，偏移只平移约 `0x2B`。
- **证据**：`analysis/app-version-2.9.365/work/compare_native_crypto.py` 输出；真实搜索 `100000`。
- **置信度**：`high`

### F-002：正文接口被独立版本门拦住

- **位置**：`/chapter/get_cpt_ifm`、`/chapter/download_cpt`、`/chapter/check_download_cpt`
- **描述**：2.9.362 与 2.9.365 游客身份下，命令接口成功、正文接口统一 `310017`。官方真机会话同键返回 `100000`。
- **证据**：`evidence/protocol-canary.json`、`evidence/download-cpt-canary.json`、`evidence/pixel6-get-cpt-ifm-post.json`。
- **置信度**：`high`

### F-016：官方游客完整链已复现

- **位置**：`pm clear` 后 Splash → auto_reg_v2 → save_reader_oaid → 阅读器
- **描述**：2.9.365 官方游客能走完整注册并打开正文。auto_reg 字段与 Python 一致。
- **证据**：`evidence/official-guest-chain.json`
- **置信度**：`high`

### F-015：补 save_reader_oaid 仍不能过正文

- **位置**：`/signup/save_reader_oaid`
- **描述**：返回 `400000`，随后 `get_cpt_ifm=310017`。未自动挂到 `register_guest`。
- **证据**：`evidence/save-oaid-canary.json`
- **置信度**：`high`

### F-014：auto_reg_v2 字段与官方一致，缺 save_reader_oaid

- **位置**：`/signup/auto_reg_v2`、`/signup/save_reader_oaid`
- **描述**：注册键、uuid 形状、`ciweimao_`、gender=1、oauth 空均对齐。Python 不发注册后的 oaid/`am`。未证明这就是 310017。
- **证据**：`evidence/auto-reg-field-diff.json`
- **置信度**：`high`

### F-013：官方 libcurl Hello 对齐后正文仍 310017

- **位置**：Pixel 上 APK `libcurl.so` 7.56.1 + `libssl.so` 1.1.0f
- **描述**：JA3 与官方 pcap 相同。search/cmd=`100000`，`get_cpt_ifm=310017`。官方 UA、键序、`send_client_info` 都不改码。
- **证据**：`evidence/oldcurl-guest-canary.json`
- **置信度**：`high`

### F-012：官方真机无法加载是残留抓包代理

- **位置**：`global_http_proxy_host=127.0.0.1` `port=8085`
- **描述**：mitmdump 与 `adb reverse` 已停。WebView `ERR_PROXY_CONNECTION_FAILED`。清掉后 `pm clear` 游客 `get_cpt_ifm=100000`。Python 310017 未变。
- **证据**：`evidence/pixel6-guest-reset-read.json`
- **置信度**：`high`

### F-011：curl_cffi 套不出官方 Hello；禁 TLS1.3 也不够

- **位置**：curl_cffi `set_ja3_options`；`evidence/tls12-urllib3-canary.json`
- **描述**：官方扩展序被判非法；`0xccaa`/`0xff`/`0-1-2` 不受支持。OpenSSL 3 TLS1.2+HTTP/1.1 正文仍 310017。
- **证据**：`evidence/tls-align-canary.json`、`evidence/tls12-urllib3-canary.json`
- **置信度**：`high`

### F-010：游客 310017 对上的是 TLS 指纹，不是身份

- **位置**：官方 `curl/7.56.1` + `OpenSSL 1.1.0f` vs Python curl_cffi 0.16
- **描述**：用户确认官方匿名可打开正文。Python 游客搜索/cmd 成功、正文 310017。JA3 不一致；强制 HTTP/1.1 不够。
- **证据**：`evidence/tls-hello-compare.json`、`evidence/ja3-guest-canary.json`
- **置信度**：`high`

### F-009：UA 常量与过期 tokens.json 都不能解释正文门

- **位置**：`libcwmhttps.so` UA 常量；`evidence/identity-canary.json`
- **描述**：native UA 是完整常量，不是 `...novel {version}`。三种 UA 正文均 `310017`。`tokens.json` 已 `200100`。游客 `is_bind=0`。
- **证据**：`evidence/ua-canary.json`、`evidence/identity-canary.json`
- **置信度**：`high`

### F-008：主机 / TLS 伪装 / send_client_info / prelude 都不是 310017 原因

- **位置**：`/chapter/get_cpt_ifm`、`/reader/send_client_info`
- **描述**：Python 游客在 `app1.hbooker.com` 与 `app1.happybooker.cn`、`impersonate=none|chrome99_android`、先打空参 `send_client_info`、复放官方冷启动 prelude 后，正文仍 `310017`。官方冷启动未调用 `send_client_info`。
- **证据**：`evidence/transport-canary.json`、`evidence/prelude-canary.json`、`evidence/pixel6-startup-urls.json`。
- **置信度**：`high`

### F-007：业务码是服务端枚举，不是接口现算

- **位置**：`BaseTaskNew.getC`（`dex_0x72090ab000.dex`）
- **描述**：`code` 来自解密后的响应 JSON。客户端硬编码 `100000`/`200100`/`310001`/`310002`/`310017`。`310017` 在官方 App 启动极验，过关后带 `geetest_*` 重试原接口。`chapter_command` 才由 `/chapter/get_chapter_cmd` 生成。
- **证据**：jadx `BaseTaskNew.java` 401–451 行；Python `_decode_response` 只读 `data["code"]`。
- **置信度**：`high`

### F-003：2.9.365 业务 Java 仍不可静态读取

- **位置**：`com.SecShell.SecShell.AW`、`assets/classes0.jar`、`assets/meta-data/`
- **描述**：jadx 仅 372 个壳/依赖文件。正文门需要的额外字段只可能在解密后的 DEX 或运行时请求里。
- **证据**：`work/apk-static/decode-summary.json`；`classes0.jar` magic 非 `PK`/`dex`。
- **置信度**：`high`

### F-004：LDPlayer 上 x86 SecShell 能加载，随后 maps/`fclose` SIGSEGV

- **位置**：`libSecShell-x86.so+0x7f580`（`call qword ptr [rbp+8]` → libc `fclose`）
- **描述**：进程 ABI 为 x86_64，`H.is_x86_byso()` 加载 x86 so。改走 ARM `libSecShell.so` 时 houdini 无法加载加密动态段（Fatal `0x01101246`）。x86 so 可映射；`fopen("/proc/self/maps")` 后 fclose SIGSEGV（fault 曾为 `0x9eb6b2b8` 或 `0x0`）。过滤 maps 不够。`Interceptor.replace(fclose)` 会打崩 Frida 自身。无 KPM，syscall-filter 未跑。运行期 dump 已落盘。
- **证据**：`docs/experiment_record.md` 2026-08-24 00:05；`artifacts/dumps/libSecShell-x86.mem.so`（SHA-256 `66396047…c52054`）；`artifacts/maps/tombstone_02.txt` / `tombstone_05.txt`
- **置信度**：`high`

## 架构概览

```text
2.9.365 APK
  -> SecShell stub Application
  -> 加密 classes0.jar（业务 Java）
  -> 明文 libcwmhttps.so（HMAC + AES，与 2.9.362 同代）
  -> 本地 Python 可：搜索/目录/章节 command
  -> 本地 Python App 路径不可：章节正文（310017）
  -> free-only Web fallback：章节页 GET → session/detail AJAX → 双层 AES → TXT

LDPlayer x86_64 + libnb
  -> H.is_x86_byso() 选 libSecShell-x86.so
  -> so 映射成功
  -> fopen(/proc/self/maps) -> fclose SIGSEGV @ +0x7f580
  -> Splash 或进程退出；业务 DEX 未进内存
```

## 复现产出

- `client/config.py`：登记并默认 `2.9.365` 协议档案。
- `service/core.py`：协议探针覆盖搜索、目录、`get_chapter_cmd`、`get_cpt_ifm`。
- `service/app.py`：ready 门禁要求章节探针通过，不再把搜索成功当成协议活着。
- `evidence/protocol-canary.json`、`evidence/download-cpt-canary.json`。
- `artifacts/dumps/libSecShell-x86.mem.so`：运行期 x86 SecShell（1,458,176 字节）。
- `scripts/spawn_secshell_arm.py`、`scripts/secshell_arm_frida_agent.js`：Frida 17 spawn；禁止 `replace(fclose)`。
- `client/web.py`、`scripts/web_fallback_canary.py`：公开 Web free-only 回退与脱敏 canary。
- `docs/web-fallback.md`：外部源码交叉验证、Cookie/限速边界与运行配置。

## 脱敏说明

游客 token 只写在 gitignore 的 `analysis/**/work/`。报告与 evidence JSON 只保留业务码、计数和字段名。

## Triage 遗留项

见 `triage.md` 与 `analysis-progress.md`。当前 App 侧 blocker 为客户端尚未接上官方 GT3 oracle（B-001）；新游客打戳流程已复验。LDPlayer maps/`fclose`（B-002）已在 Pixel 6 侧旁路。free-only 采集已由公开 Web fallback 继续推进，但不冒充 App 协议完成。
