# 刺猬猫 App 2.9.365 协议升级报告

## 基本信息

| 项目 | 值 |
|------|-----|
| 目标文件 | `analysis/app-version-2.9.365/input/ciweimao-2.9.365.apk` |
| SHA-256 | `C9B2DA202C32F883536C26C3EA77CB32863ECB9CC1EF7248602E7DA116F6CB6B` |
| 文件类型 | Android APK，Bangcle/SecNeo（SecShell），Native Android |
| 架构 | ARM64 主分析；APK 同时含 ARMv7 与 `libSecShell-x86.so` |
| App | `com.kuangxiangciweimao.novel` 2.9.365 (`290365`) |
| 分析时间 | 2026-08-23 至 2026-08-27 |
| 分析深度 | L3-partial；2026-08-27 文档冻结。官方游客 `get_cpt_ifm=100000`；独立客户端正文 310017 未解 |

## 目标概述

确认 2.9.362 章节正文接口 `310017` 是否只是版本字符串过期，以及 2.9.365 是否更换了 HMAC/AES。当前结论：签名与响应密钥未换；正文接口被服务端单独拦住。

## 执行摘要

1. `libcwmhttps.so` 哈希变化（362 `75f488dd...` / 365 `428d5f64...`），但 AES 双 key、`CkMxWNB666` 后缀、业务基址字符串均仍在，只新增 `reader/get_vip_consume_record_list`。
2. `libcurlhttps.so` 与 `libJavaJni.so` 与 2.9.362 字节级相同。
3. 本地过期 token 解密后得到 `200100`，证明 2.9.365 HMAC 与 AES 解密可用。
4. 新游客下：搜索、目录、`get_chapter_cmd`、`get_chapter_download_cmd` 均为 `100000`；`get_cpt_ifm` / `download_cpt` / `check_download_cpt` 均为 `310017`，提示「请升级到最新版本客户端」。把 `app_version` 改成 `2.9.365` 并重算 HMAC **不能**过正文门。
5. Wandoujia 当前公开版仍是 2.9.365。因此 310017 不是“仓库里的 APK 过旧”，而是正文接口另有客户端证明，静态 Native 常量对不上。
6. Java 仍被 SecShell 加密（`assets/classes0.jar` 约 18.9MB，非 ZIP/DEX magic）。LDPlayer 上 x86 `libSecShell-x86.so` 在 maps/`fclose` SIGSEGV。**Pixel 6 原包 ARM64 冷启动进入 `WelcomeActivity`，panda 拉到 43 个结构有效 DEX（71,775,408 字节），含 `com.kuangxiangciweimao`。** wrapper 因 dump 后进程已死标 `partial`。已 dump DEX 字符串中无明文 `get_cpt_ifm`。debug 重签包仍不能当完整性单变量。

## 关键发现

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
  -> 本地 Python 不可：章节正文（310017）

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

## 脱敏说明

游客 token 只写在 gitignore 的 `analysis/**/work/`。报告与 evidence JSON 只保留业务码、计数和字段名。

## Triage 遗留项

见 `triage.md` 与 `analysis-progress.md`。当前双 blocker：正文接口客户端证明（B-001）和 LDPlayer maps/`fclose`（B-002）。不是 HMAC 公式。2026-08-24 已暂停；恢复先读 `analysis-progress.md`。
