# Triage — App 2.9.365 协议升级

更新于 2026-08-27。Pixel 6 真机原包已过 Splash 并 dump 业务 DEX。官方游客正文接口 100000；Python 正文 310017 仍阻。用户「真机无法加载」已归因残留代理并清掉。

## 状态速览

| 深度等级 | 已完成 | 部分完成 | 阻滞 | 未开始 |
|----------|--------|----------|------|--------|
| L1（便携） | HMAC/AES 常量对照、真实搜索 canary | 0 | 正文接口 310017 | 0 |
| L2（上下文） | 游客注册、命令/目录可用；官方 POST 键对齐 | 0 | Python 正文 310017 | 0 |
| L3（运行时） | Pixel 6 原包过 Splash；panda 43 DEX；官方 `get_cpt_ifm` POST 已抓 | dump 后进程被 panda 暂停致死；`get_cpt_ifm` 明文未入 DEX | Python 正文 310017 | 极验路径（仅当被打到该码） |
| L4（triage） | SecShell 路由确认 | 0 | 0 | 0 |

## 阻滞项

### B-001：章节正文接口 310017

- **位置**：`/chapter/get_cpt_ifm`、`/chapter/download_cpt`、`/chapter/check_download_cpt`
- **严重程度**：`blocker`
- **原因**：服务端对 Python canary 返回枚举 `310017`，`tip` 文案是「请升级到最新版本客户端」。官方 App 同键会话返回 `100000`。DEX 里该码走极验，不是另算一个业务码。
- **已尝试的手段**：2.9.362/2.9.365 对照、新游客、`get_chapter_download_cmd` 替代 command、`download_cpt`/`check_download_cpt`、官方 POST 键对照。
- **证据**：`evidence/protocol-canary.json`、`evidence/download-cpt-canary.json`、`evidence/pixel6-get-cpt-ifm-post.json`、`BaseTaskNew.getC`
- **建议下一步**：人机过 GT3，把 `geetest_*` 写回 `get_cpt_ifm`。官方游客不走极验。不要自动解，不要登录态。

### B-002：SecShell maps/`fclose` SIGSEGV（LDPlayer）— 真机已绕过

- **位置**：`libSecShell-x86.so+0x7f580`（仅 LDPlayer x86_64）
- **严重程度**：`resolved-on-pixel6`（模拟器仍崩，不再挡主线）
- **原因**：模拟器 ABI 走 x86 so。Pixel 6 `primaryCpuAbi=arm64-v8a` 原包冷启动进入 `WelcomeActivity`，无 tombstone。
- **证据**：`docs/experiment_record.md` 2026-08-26 19:10；`artifacts/dex-dump/20260826_190632/metadata.json`
- **建议下一步**：不要再为这条做 houdini/IDA fclose。x86 mem dump 仅归档。

## 环境缺口

### G-001：syscall-filter / KernelPatch

- **缺失项**：已在 Pixel 6 加载 `xiaojianbang-syscall-filter`（uid 10237）。重启后需重 load。
- **来源位置**：此前 LDPlayer 无 KPM
- **影响范围**：真机闪退可走 syscall-filter
- **获取建议**：重启后 `kpm_loader load scfilter.kpm` + `uidadd=<appId>`

### G-002：保持原签名的 APK 修改

- **缺失项**：不破坏 SecShell `rsa.sig` 的情况下改 `extractNativeLibs` 或抽掉错放的 x86 so
- **来源位置**：debug 重签包
- **影响范围**：重打包会把完整性失败和 maps 崩溃混在一起。`extractNativeLibs` 对本崩溃不再是首选假设。
- **获取建议**：CorePatch/原签，或真机原包。暂停期间不要装 debug 签包。

### G-004：stealth-hook 挡住 Frida attach

- **缺失项**：对 `com.kuangxiangciweimao.novel` 的 Frida attach / process 枚举
- **来源位置**：`adb pidof` 有 pid；`frida enumerate_processes` 无对应名；attach 报 process not found
- **影响范围**：live User-Agent / header hook 当前做不成
- **获取建议**：需要 live hook 时先卸 `xiaojianbang-stealth-hook`，或改用非 Frida 路径

### G-005：px-proxy 残留全局代理 — 已清

- **缺失项**：`px-proxy off` 未删 `global_http_proxy_host/port`
- **来源位置**：设备 `127.0.0.1:8085`；mitmdump/`adb reverse` 不在
- **影响范围**：官方 App 停在「加载中」；WebView `ERR_PROXY_CONNECTION_FAILED`
- **获取建议**：已 `off` 并补删 host/port。脚本已改。不要长期开 px-proxy；正文明文对照走 eCapture

### G-003：Frida 17 Python 默认无 Java bridge

- **缺失项**：spawn 脚本里 `Java` 全局
- **来源位置**：`scripts/spawn_secshell_arm.py`；agent 未 `import Java from 'frida-java-bridge'`
- **影响范围**：不能 hook `H.is_x86_byso` / `System.loadLibrary`；只能 native。`frida-tools` CLI 会自动加载 bridge；Python 必须编译或投递 `frida:load-bridge`。
- **获取建议**：需要 Java hook 时用 CLI，或给 agent 显式 import 并 `frida-compile`。不要降级 Frida。

## 待验证假设

### H-001：正文接口新增了 Java 层字段或第二段证明

- **假设**：已证伪（POST 键）。2.9.365 官方 App POST 键与 Python 相同，官方返回 100000。
- **依据**：`evidence/pixel6-get-cpt-ifm-post.json`
- **验证方法**：已完成 logcat `curl` `post===>`
- **若假设错误的影响**：310017 更可能是身份或 native TLS，不是新 POST 字段

### H-004：缺 send_client_info / 冷启动 prelude / 错主机导致 310017

- **假设**：已证伪。官方冷启动未调用 `send_client_info`；Python 空参调用 100000 后正文仍 310017；双主机与 chrome99_android 无效。
- **依据**：`evidence/transport-canary.json`、`evidence/prelude-canary.json`、`evidence/pixel6-startup-urls.json`
- **验证方法**：已完成四格 canary + 官方 URL 序复放
- **若假设错误的影响**：会继续空打 prelude，耽误身份/native TLS 对照

### H-003：业务码由某接口现算

- **假设**：已证伪。`code` 是每条业务响应 JSON 的服务端枚举；客户端不生成、也没有取码接口。
- **依据**：`BaseTaskNew.getC` 对解密后的 `code` 做固定整数分支；`chapter_command` 才由 `get_chapter_cmd` 生成。
- **验证方法**：已完成 jadx 对照 + viselog `code=100000` + canary `code=310017`
- **若假设错误的影响**：会把极验三元组或 `chapter_command` 误当成业务码

### H-002：maps 解析按 32 位地址截断 x86_64 maps 行

- **假设**：`0x9eb6b2b8` 来自 64 位 maps 地址截断，与是否隐藏 Frida 行无关
- **依据**：过滤 maps 后仍 `fclose` SIGSEGV，fault 变为 `0x0`
- **验证方法**：IDA 看 `+0x7f540` 如何 scanf/解析 maps 行
- **若假设错误的影响**：仍可能是 FILE* 损坏或匿名段代码，需对照 mem dump 与 tombstone

## 未来可探索方向

- 真机原包（非 houdini）抓 `get_cpt_ifm`，可绕过本模拟器壳崩溃
- 真机 Ruyi/Frida 观察 `decrypt_jar_128K` 仅在 App 能启动后才有意义
- 不要把搜索成功当成协议完成；探针必须包含 `get_cpt_ifm`
