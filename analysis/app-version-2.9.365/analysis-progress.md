# 2.9.365 协议升级进度

更新于 2026-08-27。状态：**文档冻结，暂停推进。** Pixel 6 真机原包已过 Splash，panda 已拉到业务 DEX。native `auto_reg` 通路已静态闭合。不要再走 LDPlayer x86 SecShell。

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
| KPM | syscall-filter + stealth-hook 已加载（重启后需重 load） |
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

**已冻结。** L3 运行时：官方游客完整链已通（不进极验）。Python 自签身份正文 `310017`；完整 `getHead0` UA + `charsets`/`Expect` + `HTTP_VERSION=3` 仍 `310017`。GT3 API1 已 `success=1`，人机滑块未做。恢复时先读本文件与 `docs/protocol.md`。

## 关键路径

| 项 | 状态 |
|---|---|
| native `auto_reg` 通路 | 已静态闭合：`getC(17)` → `track` → `getAddr=signup/auto_reg_v2`；见 `evidence/native-autoreg-path.json`。不是 310017 已解 |
| HMAC 公式 | 可用；key=官方证书 MD5（GetInfo），suffix 以 live 字面 `CkMxWNB666` 为准 |
| AES 响应解密 | 可用 |
| 游客注册 | 可用 |
| 搜索/榜单/目录 | 可用 |
| `get_chapter_cmd` | 可用 |
| `get_cpt_ifm` / `download_cpt` / `check_download_cpt` | 官方游客 100000；Python 自签游客在官方 JA3 libcurl 上，官方 extras + 导流章仍 310017 |
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
| `scripts/spawn_secshell_arm.py` | Frida 17 spawn + `frida:load-bridge` 投递 |
| `scripts/secshell_arm_frida_agent.js` | 当前：过滤 maps 并 dump so 页；不要 `Interceptor.replace(fclose)` |

## 已排除（有证据）

- 正文 `310017` 不是 HMAC 换代：2.9.365 重算后搜索仍 `100000`。
- 正文 `310017` 不是 APK 过旧：Wandoujia 当前仍是 2.9.365。
- 业务码 `code` 不是接口生成的 token：客户端只读解密 JSON 的 `code`；`100000`/`200100`/`310001`/`310002`/`310017` 在 `BaseTaskNew` 硬编码分支。真正由接口生成的是 `chapter_command`（`get_chapter_cmd`）和极验三元组（`310017` 之后）。
- 正文 `310017` 不是缺 `send_client_info`、不是主机 `hbooker.com` vs `happybooker.cn`、不是 `chrome99_android` impersonate、不是缺官方冷启动 prelude。Python 空参 `send_client_info` 已 `100000`。官方启动未打该接口。
- 正文 `310017` 不是 Python UA 写成版本号：换成 native 常量 `Android  com.kuangxiangciweimao.novel.c  ` 仍 `310017`。完整 `getHead0` UA（`2.9.365, google, Pixel 6, 35, 15`）加上 `charsets: utf-8` / `Expect:` 仍 `310017`。
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

1. 人机完成 GT3 滑块，把 `geetest_challenge/seccode/validate` 写回同一枪 `get_cpt_ifm`。脚本：`work/oldcurl/geetest_human_retry.py`。不要自动解。
2. 官方游客本来就不走极验。过滑块只能证明「被打到 310017 的身份能否靠 GT3 恢复」，不能解释官方匿名为何直接 100000。
3. native 注册通路三项（完整 UA / `charsets`+`Expect` / HTTP_VERSION=3）已 canary，不能过正文。不要再补 POST 键或传输头。
4. 不要 `tokens.json`，不要从 logcat 抄 token。不要长期开 `px-proxy`。

不要：再试 houdini ARM 改写、再 `replace(fclose)`、再盲改 `app_version`、覆盖 `tokens.json`、碰 LDPlayer index 0、把死代理留在 Pixel 上。
