# 2.9.365 协议升级进度

更新于 2026-09-02。状态：**App `get_cpt_ifm` 仍是主线。** Python 自注册游客固定 310017；官方出生游客在官方进程读章后，独立 App 客户端已 100000。官方读章序复放不能放行自注册游客。uid MITM 字段对照：官方与 Python 是同一 8 键集合与同一形状；头值/键序差不是门。Web 与 App 风控不同级，不能用网页链代替 App 门。

## 目标

恢复能通过章节正文接口的 App 协议，使采集服务不再把搜索成功当成协议完成。

## 暂停原因（已解除）

LDPlayer x86 SecShell `maps`/`fclose` SIGSEGV 已用 Pixel 6 ARM64 原包绕过，不再作为主阻塞。正文接口 `310017` 仍未过。

## 执行环境（恢复时核对）

| 项 | 值 |
|---|---|
| 设备 | Pixel 6 `oriole`，ADB `18251FDF6000N9` |
| 系统 | 定制 Android 15 `AP3A.241005.015`，内核 `5.10.209-android13-4*` |
| Root | APatch `su` `uid=0` |
| Frida | 宿主 17.15.3；设备用 `tools/frida-server-android-arm64`（不要推 x86_64 的 `tools/frida-server`） |
| KPM | 本轮 `kpatch list failed`；重启后需重 load。不要默认加载 stealth-hook |
| 包 | 原签 `com.kuangxiangciweimao.novel` 2.9.365 (`290365`)，`primaryCpuAbi=arm64-v8a`，`appId=10237` |
| 启动模拟器 | 本阶段不用 LDPlayer；不要碰 index 0 / `emulator-5554` |
| 凭据 | 不覆盖项目根 `tokens.json`；游客只在 `analysis/**/work/` |

## 已完成

- Native `libcwmhttps.so` 与 2.9.362 对照：HMAC/AES 同代
- 游客 `auto_reg_v2` 后真实 canary：搜索/目录/command 成功，正文 `310017`
- 客户端登记 `2.9.365` 协议档案；探针与 ready 门禁包含 `get_cpt_ifm`
- LDPlayer 上确认崩溃点：x86 `libSecShell-x86.so+0x7f580` → libc `fclose`
- 运行期 so dump 已落盘（与磁盘加密 so 不同）
- Pixel 6 原包冷启动：Splash → `WelcomeActivity`（3.3s），无 tombstone
- panda 真机 dump：43 个结构有效 DEX / 71,775,408 字节，含 `com.kuangxiangciweimao`

## 当前阶段

L3 运行时：官方进程内 `get_cpt_ifm` 已多次 `100000`。官方表单键与 oldcurl 一致，无 Cookie，每次新 easy。同日官方读章成功后，该官方出生游客在 Python / oldcurl 上也变成 `100000`；Python 自注册游客仍 `310017`。uid MITM 已解密冷启动与正文，并完成字段形状对照：同一 8 键，形状一致；官方 `Accept=*/*` + `charsets`，Python 默认短 UA、无 charsets、键序不同。同一默认 Python 包仍按身份分叉。不要再对齐头/键序指望自注册过门。不要再钩 `0x6ebc0`，不要再密采 slist，不要 `pm clear` 这份已放行游客。不要再 Frida attach，不要再 eCapture 本栈，不要长期开全局 `http_proxy`。

## 2026-09-02 HWBP

- `extractNativeLibs=false`：`--so libcwmhttps.so` 无效；`--so 04354000`（APK zip payload）可算基址。
- KPM 用设备 env + 0600 keyfile 加载，不把 superkey 打进 wrapper argv；收尾 KPM count=0。
- 书城 `get_index_list`：`track`/`postHttpsRequest`/`getHead0` 打中；`getHead0` 返回点寄存器有 `Expect: `。
- 免费新书阅读器翻章无出网，本轮没有 `get_cpt_ifm`。
- pass5：网格封面直接进 `ReaderActivity4`，书详页没有 `立即阅读`。
- pass5b：先挂 `track`+`0x6ebc0`（214 节点）仍 0 hit，ADB 掉线，官方进程消失。
- pass6：书详页 `立即阅读` 后只钩 `track`。X3=259，ViseLog `259====>100000` 两次。
- pass7：`am start` + 先挂钩 `0x6ebc0`（119 节点）+ 网格，0 hit，进程消失。
- pass8：先停在 `立即阅读` 再钩 `0x6ebc0`（116 节点）。缓存阅读无出网，0 hit，随后进程再消失。
- pass9：未读书详页只钩 `slist_append`（113 节点）。`259====>100000`，末次头=oldcurl UA。
- pass10：密采打死进程一次。冷启后再钩 slist，3 秒后读 X0 链为空。正文仍 `100000`。
- 静态：`postHttpsRequest` 每次 `easy_init`/`cleanup`；slist 只有 CT/charsets/Expect/UA；SO 无 Cookie。
- logcat `post===>`：`get_cpt_ifm` 键序=oldcurl `OFFICIAL_CPT_ORDER`，无 `refresh`。
- 随后同一官方游客：Python 双主机与 oldcurl 默认/V4 均为 `100000`。对照 Python 自注册游客仍 `310017`。IPRESOLVE 不是原因。
- `getAddr`：33=书签，36=目录 new，116=间贴数，264=cmd，259=cpt。官方阅读前缀复放到自注册游客仍 310017。`get_version.android_version=2.9.293`。
- uid MITM：`http_proxy` 保持 null。冷启动 9 条 HTTP/1.1 POST，头名 Host/Accept/Content-Type/charsets/User-Agent/Content-Length；空 Expect 不上线；无 Cookie/Set-Cookie。路径集合与 `pixel6-startup-urls` 相同。prelude 复放早已 310017。
- uid MITM 阅读：未缓存封面直进阅读器，抓到两次 `get_cpt_ifm`。键序=OFFICIAL_CPT_ORDER，头名与冷启动相同。缓存书只打旧 `get_updated_chapter_by_division_id` + `set_read_chapter_record`，不出 cpt。
- 字段对照：官方线上头值 `Accept=*/*`、`charsets=utf-8`、长 UA；无 Expect / Cookie / Accept-Encoding。Python 默认 session 只有短 UA + Content-Type。两边 body 都是同一 8 键，形状一致。官方出生默认包 `100000`，自注册默认包 `310017`。见 `evidence/official-vs-python-field-compare.json`。

## 2026-09-02 身份移植

- Pixel 官方 App 现有游客 `is_bind=0`，未 `pm clear`，未写 `tokens.json`。
- 官方凭据 → Python curl_cffi：双主机 `get_my_info`/搜索/目录/cmd=`100000`，`get_cpt_ifm=310017`。
- 同一凭据 → Pixel APK libcurl + getHead0 UA：同样 cmd=`100000`、正文 `310017`。
- panda `GetBookContentDetailTask` 只传 `chapter_id` / `chapter_command` / 可选 `refresh=1`。
- 结论：上午移植时仍 310017。官方进程内读章成功后，同一官方游客在独立客户端也变成 100000。Python 自注册游客仍 310017。不是「出生在官方进程」本身，更像读章成功后的放行。

## 2026-09-01 续推进

- 外部源码与 Issue 交叉确认网页链：章节页 GET → `ajax_get_session_code` → `get_book_chapter_detail_info`，Cookie（尤其 `ci_session`）需接收轮换并串行限速。
- 新增 `client/web.py` 的同步/异步实现；仅在 `free_only=True` 且 App 返回 `310017` 时触发，不发送 App credentials。
- 新增脱敏 canary：公开章节 `112001971` 三次 HTTP 均 200，detail 业务码 `100000`，双层 AES-CBC 解密并输出非空正文。
- 服务 readiness 可选接受 Web probe，但 payload 明确保留 `app_gate_ok=false`，不把 Web 成功伪装成 App 协议完成。

## 关键路径

| 项 | 状态 |
|---|---|
| native `auto_reg` 通路 | 已静态闭合：`getC(17)` → `track` → `getAddr=signup/auto_reg_v2`；见 `evidence/native-autoreg-path.json`。不是 310017 已解 |
| HMAC 公式 | 可用；key=官方证书 MD5（GetInfo），suffix 以 live 字面 `CkMxWNB666` 为准 |
| AES 响应解密 | 可用 |
| 游客注册 | 可用 |
| 搜索/榜单/目录 | 可用 |
| `get_chapter_cmd` | 可用 |
| `get_cpt_ifm` / `download_cpt` / `check_download_cpt` | 官方进程内 100000。官方出生游客在今日进程内读章成功后，Python / oldcurl 也 100000；Python 自注册游客仍 310017。free-only 已有 Web fallback |
| `client.web` Web fallback | 已实现；文本免费章 Web detail=`100000`，VIP/图片章不覆盖 |
| SecShell 解密 DEX | Pixel 6 panda：43 DEX / 71MB，业务包名已在 `dex_0x72090ab000.dex` 等；wrapper 标 `partial`（dump 后 SIGCONT 时进程已死）。不是完整脱壳声明 |
| LDPlayer 原包启动 | x86 so 可映射，随后 maps/`fclose` SIGSEGV；停在 Splash 或直接崩。真机已替代 |
| Pixel 6 原包启动 | 过 Splash，进入 `WelcomeActivity` |
| ARM `libSecShell.so` + houdini | 不可行：加密动态段，Fatal `0x01101246`（此前 `libtcb` ns 为 `0x0190019f`） |
| Frida 17 Java | Python `create_script` 默认无 `Java`；agent 未 `import` 时不会发 `frida:load-bridge` |
| 运行期 so dump | `artifacts/dumps/libSecShell-x86.mem.so` |

## 证据与产物

| 路径 | 说明 |
|---|---|
| `input/ciweimao-2.9.365.apk` | SHA-256 `C9B2DA20…F6CB6B` |
| `evidence/protocol-canary.json` | 搜索/目录/cmd=`100000`，正文=`310017` |
| `evidence/download-cpt-canary.json` | `download_cpt` / `check_download_cpt`=`310017` |
| `artifacts/dumps/libSecShell-x86.mem.so` | 1,458,176 字节，x86_64 ELF，SHA-256 `66396047aa619f374069db2d35edce77924a4a1619543399dbaa24b309c52054` |
| `work/apk-static/apktool/lib/arm64-v8a/libSecShell-x86.so` | 磁盘包 1,367,853 字节，SHA-256 `e044a04b…0f21658`，动态段加密 |
| `artifacts/maps/tombstone_02.txt` | 无 hook 基线：`fclose` fault `0x9eb6b2b8`，pc `so+0x7f582` |
| `artifacts/maps/tombstone_05.txt` | Frida 后仍 `fclose`，fault `0x0` |
| `docs/experiment_record.md` | 逐轮实验 |
| `evidence/transport-canary.json` | 双主机 × TLS 伪装；`send_client_info=100000`，正文 `310017` |
| `evidence/prelude-canary.json` | 官方冷启动 prelude 复放后正文仍 `310017` |
| `evidence/pixel6-startup-urls.json` | 官方冷启动 URL 序；无 `send_client_info` |
| `evidence/identity-canary.json` | `tokens.json` 过期 200100；游客 is_bind=0，正文 310017 |
| `evidence/ua-canary.json` | Python UA 与 native 常量 UA 正文均为 310017 |
| `evidence/tls-hello-compare.json` | 官方 vs Python ClientHello/JA3 不一致 |
| `evidence/ja3-guest-canary.json` | 游客 HTTP/1.1 仍 310017；官方 JA3 因 0xccaa 无法直接套 |
| `evidence/tls-align-canary.json` | curl_cffi 最近 JA3：Invalid TLS extension order |
| `evidence/tls12-urllib3-canary.json` | OpenSSL 3 TLS1.2+HTTP/1.1 正文仍 310017 |
| `evidence/pixel6-guest-reset.json` | `pm clear` 冷启动；游客打了 `send_client_info` |
| `evidence/pixel6-guest-reset-read.json` | 残留代理清掉后官方游客 `get_cpt_ifm=100000` |
| `evidence/oldcurl-guest-canary.json` | APK libcurl 7.56.1 JA3 对齐后正文仍 310017 |
| `evidence/auto-reg-field-diff.json` | auto_reg_v2 键一致；Python 缺 save_reader_oaid |
| `evidence/save-oaid-canary.json` | 补 save_reader_oaid=400000，正文仍 310017 |
| `evidence/official-guest-chain.json` | 先 trace 再 pm-clear：官方 auto_reg/oaid/get_cpt 键 + 正文 UI |
| `evidence/pixel-oldcurl-autoreg-canary.json` | Pixel 官方 libcurl auto_reg=100000，正文仍 310017 |
| `evidence/pixel-official-chain-canary.json` | 官方 extras + 导流章 106129841 + 青春免费章，正文仍 310017 |
| `evidence/geetest-api1-canary.json` | 310017 回包仅 code/tip；API1 给出 GT3 v3 gt/challenge |
| `evidence/native-autoreg-path.json` | native 注册通路：host/UA/头/HMAC；HTTP/2 只是 setopt，APK libcurl 无 nghttp2 |
| `evidence/pixel-native-headers-canary.json` | 完整 getHead0 UA + charsets/Expect + HTTP_VERSION=3：注册 100000，正文仍 310017；协商 HTTP/1.1 |
| `evidence/web-fallback-canary.json` | 公开 Web 三步链真实 canary；仅记录状态/长度/hash/Cookie 名称 |
| `evidence/official-born-identity-canary.json` | 官方 SharedPreferences 游客 → Python：正文 310017 |
| `evidence/official-born-oldcurl-canary.json` | 上午同一官方游客 → Pixel 官方 libcurl：正文 310017 |
| `evidence/official-inprocess-hwbp-pass10.json` | slist 末次 UA；X0 链空；正文 100000 |
| `evidence/official-ipresolve-ab-canary.json` | 官方游客 oldcurl 默认/V4 均为 100000 |
| `evidence/official-vs-python-cpt-now.json` | 官方游客 Python 100000；Python 自注册仍 310017 |
| `evidence/official-uid-mitm-startup.json` | uid MITM 冷启动 9 条；只记路径/头名 |
| `evidence/official-uid-mitm-cpt.json` | uid MITM 官方 get_cpt_ifm 明文；只记路径/头名/键名 |
| `evidence/official-vs-python-field-compare.json` | 官方 MITM vs Python 默认/对齐包：头值白名单 + body 形状 |
| `evidence/official-inprocess-ecapture.json` | eCapture 强制 boringssl_a_15；无 get_cpt_ifm 明文；Frida attach 失败 |
| `scripts/spawn_secshell_arm.py` | Frida 17 spawn + `frida:load-bridge` 投递 |
| `scripts/secshell_arm_frida_agent.js` | 当前：过滤 maps 并 dump so 页；不要 `Interceptor.replace(fclose)` |

## 已排除（有证据）

- 正文 `310017` 不是 HMAC 换代：2.9.365 重算后搜索仍 `100000`。
- 正文 `310017` 不是 APK 过旧：Wandoujia 当前仍是 2.9.365。
- 业务码 `code` 不是接口生成的 token：客户端只读解密 JSON 的 `code`；`100000`/`200100`/`310001`/`310002`/`310017` 在 `BaseTaskNew` 硬编码分支。真正由接口生成的是 `chapter_command`（`get_chapter_cmd`）和极验三元组（`310017` 之后）。
- 正文 `310017` 不是缺 `send_client_info`、不是主机 `hbooker.com` vs `happybooker.cn`、不是 `chrome99_android` impersonate、不是缺官方冷启动 prelude。Python 空参 `send_client_info` 已 `100000`。官方启动未打该接口。uid MITM 确认 prelude 线上也没有隐藏头/Cookie。
- 正文 `310017` 不是 Python UA 写成版本号：换成 native 常量 `Android  com.kuangxiangciweimao.novel.c  ` 仍 `310017`。完整 `getHead0` UA（`2.9.365, google, Pixel 6, 35, 15`）加上 `charsets: utf-8` / `Expect:` 仍 `310017`。
- 正文 `310017` **不是**「身份必须在官方进程里注册」：上午官方 SharedPreferences 游客移植到 Python / oldcurl 仍 `310017`。同日官方进程读章成功后，该游客在独立客户端也变成 `100000`；Python 自注册游客仍 `310017`。
- 正文 `310017` **不是** Cookie / 连接复用 / 额外 POST 键 / `CURLOPT_IPRESOLVE=V4`：官方每次新 easy，SO 无 Cookie，`post===>` 键序与 oldcurl 一致；默认与 V4 都已 100000。
- 正文 `310017` **不是**「Python 默认包字段集合或形状不对」：官方 MITM 与 Python 默认是同一 8 键、同一形状。头值/键序差真实存在（官方有 `Accept=*/*` 与 `charsets`），但官方出生游客用未对齐的 Python 默认包仍 `100000`。
- eCapture **不能**作为本栈官方进程内明文面：Android 15 构建强制 BoringSSL a15，钩不到 APK OpenSSL 1.1.0f。官方阅读器打开缓存导流章时甚至不会再打 `get_cpt_ifm`。
- 正文 `310017` **不是** native `CURLOPT_HTTP_VERSION=3`：APK `libcurl/7.56.1` 版本串无 nghttp2，setopt 返回 1（`CURLE_UNSUPPORTED_PROTOCOL`），协商 `http_version=2`（HTTP/1.1），与官方 pcap ALPN 仅 `http/1.1` 一致。
- 正文 `310017` 不是「游客不能读」：官方匿名可打开正文；`pm clear` 后 viselog `get_cpt_ifm=100000`。
- 正文 `310017` **不是**「只要换成官方 libcurl/OpenSSL Hello」：Pixel 上 APK `libcurl/7.56.1 OpenSSL/1.1.0f` 的 JA3 与官方 pcap 同为 `1aee0238…`，search/cmd=`100000`，正文仍 `310017`。官方 UA、官方 POST 键序、先打空参 `send_client_info` 都不改码。TLS Hello 不是充分条件。
- 正文 `310017` **不是** `auto_reg_v2` 缺字段或 uuid/device_token/gender/oauth 形状不对：键与 2.9.362 官方 live、2.9.365 `AutoRegTask` 一致。
- 补 `/signup/save_reader_oaid` **不能**过正文：接口 `400000`，随后 `get_cpt_ifm` 仍 `310017`。
- 在 Pixel 用 APK libcurl 打 `auto_reg_v2`（官方 UA/键序，新 uuid）**不能**过正文：注册 `100000`，`get_cpt_ifm=310017`。不是「没同步真机 INSTALLATION」。
- 官方游客 extras **不能**过正文：`ad_reader_check=100000` → Pixel libcurl `auto_reg=100000`（`reader_id` 尾数 4 → `app1.happybooker.cn`）→ `save_reader_oaid=400000` → `send_client_info(push_type=2)=100000` → 官方导流章 `106129841` 与搜索免费章 `get_chapter_cmd=100000`、`get_cpt_ifm=310017`。设备上未写出 cookie 文件；官方 viselog 的 `post===>` 也没有 Cookie 头。
- `310017` 回包没有 gt/challenge，只有 `code`+`tip`。GT3 API1 `/signup/geetest_first_register` 对当前 Python 游客 `success=1`。这是被拦身份的恢复门，不是官方游客读章的必经步骤。
- 用户真机「也无法加载」不是服务端改拦官方游客：残留全局代理 `127.0.0.1:8085`（mitmdump/`adb reverse` 已停）。WebView `ERR_PROXY_CONNECTION_FAILED`。清掉后官方游客正文接口 100000。
- curl_cffi ja3 对齐官方 Hello 不可行：`Invalid TLS extension order`，且不支持 `0xccaa`/`0xff`/`0-1-2`。CPython OpenSSL 3.0.18 TLS1.2-only 仍 310017。
- 不能把 x86 so 改写成 ARM 再交给 houdini：ARM ELF 动态段加密。
- `extractNativeLibs=true` 的 debug 重签包不能当单变量：会和壳完整性混在一起。
- 仅过滤 `/proc/self/maps` 中的 Frida 行不够：同一 `fclose` 仍崩。

## 下一步

1. App 门继续走 `/chapter/get_cpt_ifm`，不要用 Web fallback 当完成条件。
2. 不要再钩 `after_getHead0`，不要再密采 slist，不要再复放已对齐的书签/目录/版本检查/冷启动 prelude，不要再对齐 Accept/charsets/键序指望自注册游客过门。
3. 不要 `pm clear` 已放行的官方游客。下一步对比两类身份在服务端/官方进程里的差，而不是再改报文。
4. 人机 GT3 只验证被拦身份恢复。不要覆盖 `tokens.json`。抓原生 HTTPS 用 uid REDIRECT，不要长期开 `px-proxy` 全局代理。不要再 Frida attach / eCapture 本栈。

不要：再试 houdini ARM 改写、再 `replace(fclose)`、再盲改 `app_version`、覆盖 `tokens.json`、碰 LDPlayer index 0、把死代理留在 Pixel 上。
