# 实验记录

## 2026-09-02 官方读章序复放到 Python 自注册游客

- 记录时间：2026-09-02（Asia/Shanghai）
- 分析思路：Web 与 App 风控不是同一套，不能用网页链代替 App `get_cpt_ifm`。pass6 的 `getC` 36/116 先对上路径，再按官方 `url===>` 原序复放。
- 本轮操作：`getAddr` 表确认 33=`book/get_bookmark_list`，36=`chapter/get_updated_chapter_by_division_new`，116=`chapter/get_tsukkomi_num`，264=`get_chapter_cmd`，259=`get_cpt_ifm`。从 pass10 logcat 抽出书详页/阅读序（只留字段名）。对仍 310017 的 Python 自注册游客复放：书签×2→目录→cmd→cpt；再补 `setting/get_version`/`get_check`/`thired_party_switch`；再补详情/间贴/评论。未写 `tokens.json`，未走 Web。
- 实验结果：三组 cpt 都是 `310017`。`get_version` 的 `android_version=2.9.293`，`is_force_update=0`，不是商店版本比 2.9.365 新。官方本地 SP 没有单独的「已放行」键。
- 下一步计划：不要再用 Web 回退冒充 App 门。继续查服务端对官方出生游客放行、对自注册游客仍拦的差异。不要 `pm clear` 已放行官方游客。

## 2026-09-02 官方读章后独立客户端对照

- 记录时间：2026-09-02（Asia/Shanghai）
- 分析思路：slist X0 读不到。静态看 `postHttpsRequest` 每次新 easy、SO 无 Cookie。logcat `post===>` 对字段名。再测 `CURLOPT_IPRESOLVE=V4`。
- 本轮操作：从 pass6/pass10 设备 logcat 抽 `get_cpt_ifm` 字段名（不落值）。重编 oldcurl 做 V4 / 默认 A/B。同一官方游客再打 Python curl_cffi；对照一份 Python 自注册游客。未写 `tokens.json`，未 `pm clear`。
- 实验结果：官方 `get_cpt_ifm` 键序与 oldcurl 一致，无 `refresh`。V4 与默认 oldcurl 都是 `100000`。官方游客 Python 双主机也是 `100000`（`chapter_info.txt_content` 为 CDN URL）。Python 自注册游客仍双主机 `310017`。上午同一官方游客移植还是 `310017`。
- 下一步计划：不要再钩 slist / `0x6ebc0`。不要 `pm clear` 这份已放行游客。310017 还卡 Python 自注册身份。

## 2026-09-02 HWBP pass10 读 slist 链

- 记录时间：2026-09-02（Asia/Shanghai）
- 分析思路：内核查询只留最后一次 hit。UA 入 slist 时 X0 应是已有链。挂钩后立刻走 `/proc/pid/mem`。
- 本轮操作：第一次在挂钩期间密采 hook log（121 节点），ADB 掉线、官方进程消失。冷启后改成点阅读等 3 秒再读一次 X0。未 `pm clear`。
- 实验结果：第二次 8 hit，ViseLog `259====>100000` 两次，末次仍是 oldcurl 同款 UA。X0 链读出来是空串或不可读——3 秒后 heap 上的 slist 已经没了。KPM count=0。密采会打死进程，不要再在 HWBP 期间狂打 adb。
- 下一步计划：不要再钩 `0x6ebc0`，不要再密采 slist。独立客户端 310017 不是 UA 不同；额外头即使有，oldcurl 已经发过仍 310017。

## 2026-09-02 HWBP pass9 未读书详页 slist_append

- 记录时间：2026-09-02（Asia/Shanghai）
- 分析思路：`after_getHead0` 全线程已证伪。改钩 `curl_slist_append` 函数入口，且必须先停在未读过的书详页 `立即阅读`。
- 本轮操作：免费区热书列表点未读过的书，确认 `立即阅读@540,2263`。只钩 `libcurl.so` `slist_append@0x3365c`（113 节点），再点阅读。跑完卸载。未 `pm clear`。
- 实验结果：阅读器打开。logcat 有 `get_cpt_ifm` / `get_chapter_cmd`，ViseLog `259====>100000` 两次。hook 打中 8 次，进程仍在，KPM count=0。8 个 dump 的最后一次都是 `User-Agent: Android  com.kuangxiangciweimao.novel.c  2.9.365, google, Pixel 6, 35, 15`，与 oldcurl `ua.txt` 一致。每个 tid 打印的 hit_count 都是 `#8`，更早的 slist 行（静态分析里的 Content-Type / charsets / Expect）这次没入镜。
- 下一步计划：310017 不是 UA 字符串不同。不要再钩 `0x6ebc0`。若还要证明 slist 是否只有 UA，需要能看到同 tid 的 1..7 次 append，或 dump slist 链；不要再 Frida attach / eCapture / px-proxy。

## 2026-09-02 HWBP pass8 书详页立即阅读再钩 after_getHead0 — 失败

- 记录时间：2026-09-02（Asia/Shanghai）
- 分析思路：按 pass6 UI，先停在 `立即阅读`，再只钩 `0x6ebc0`，避免 pass7 的 `am start` + 先挂钩。
- 本轮操作：免费大卡片进入已读过的书详页，确认 `立即阅读@540,2263`。只钩 `after_getHead0`（116 节点）再点阅读。未 `pm clear`。
- 实验结果：阅读器打开，但 logcat 无 `get_cpt_ifm`（缓存）。hook 0 hit。随后 ADB 再掉线，官方进程消失。KPM count=0。冷启回到 `MainFrameActivity`。
- 下一步计划：不要再对 `0x6ebc0` 做全线程 HWBP。未缓存章若还要明文头，只钩 `slist_append` 一处，且必须先停在未读过的书详页。不要 hook-first + `am start`。

## 2026-09-02 HWBP pass7 after_getHead0 先挂钩再点网格 — 失败

- 记录时间：2026-09-02（Asia/Shanghai）
- 分析思路：阅读器无目录控件，想换一本未缓存书再 dump `0x6ebc0` 的 UA。
- 本轮操作：6 次 BACK + `am start MainFrame`，再只钩 `after_getHead0@0x6ebc0`（119 节点），点网格书。未 `pm clear`。
- 实验结果：hook 已挂上（119 节点）但 0 hit。随后 ADB 掉线，官方进程消失。KPM 恢复后 count=0。冷启 Splash 回到 `MainFrameActivity`，游客数据还在。
- 下一步计划：不要再 hook-first + `am start` + 网格。按 pass6：先停在书详页 `立即阅读`，再只钩一处。

## 2026-09-02 HWBP pass6 书详页立即阅读只钩 track

- 记录时间：2026-09-02 20:08（Asia/Shanghai）
- 分析思路：无 hook 先停在书详页 `立即阅读`，再只钩 `track` 一处，避免全线程双断点把设备打掉。
- 本轮操作：免费大卡片进入《转生成为一只猫的我，决定摆烂了》书详页，确认 `立即阅读@540,2263`。load KPM 后只钩 `track@0x6d260`，再点阅读。跑完卸载。
- 操作目的：看 X3 是否为 259（get_cpt_ifm）。
- 所用工具：`official_inprocess_hwbp_pass6.py`
- 运行命令：`python analysis/app-version-2.9.365/work/official_inprocess_hwbp_pass6.py`
- 代码变更：work 脚本。
- 检测代码明细：只读 HWBP，1 个偏移，115 线程。
- 实验结果：点 `立即阅读` 后进入 `ReaderActivity4`。`track` 打中 16 次，X3 序列含 33/36/264/259/116。ViseLog `259====>` 两次均为 `code=100000`；`get_cpt_ifm` URL 两次打到 `app1.happybooker.cn`。`264` 与 `get_chapter_cmd` 对齐，也是 `100000`。JNI dump 仍是对象头，没有 HTTP 明文。KPM 已卸，进程仍在阅读器，代理 `null`。
- 下一步计划：只钩 `after_getHead0@0x6ebc0` 或 `curl_slist_append` 一处，抓 259 当次的 UA/头。不要再全线程双断点。

## 2026-09-02 HWBP pass5 等立即阅读再下断

- 记录时间：2026-09-02 19:58–20:04（Asia/Shanghai）
- 分析思路：上一轮 HWBP 通路已通，但 UI 没等到书详页 `立即阅读`，正文请求没出网。
- 本轮操作：先免费区点未读过的书并轮询 `立即阅读`（pass5）；失败后改成先挂 `track`+`0x6ebc0` 再点书（pass5b）。未 `pm clear`，未写 `tokens.json`。
- 操作目的：看官方打开正文时 `track` X3 是否为 259，以及 getHead0 返回 UA。
- 所用工具：`official_inprocess_hwbp_pass5.py` / `official_inprocess_hwbp_pass5b.py`
- 运行命令：`python analysis/app-version-2.9.365/work/official_inprocess_hwbp_pass5.py`；`python analysis/app-version-2.9.365/work/official_inprocess_hwbp_pass5b.py`
- 代码变更：work 脚本。
- 检测代码明细：只读 HWBP，两处断点。
- 实验结果：pass5 点网格封面会直接进 `ReaderActivity4`，书详页没有 `立即阅读`，断点还没下正文请求已过。pass5b 先挂上 214 个节点（2 offsets × 107 threads），随后点书仍停在 `MainFrame`，0 hit；全线程 HWBP 再次让 ADB 掉线，官方进程消失。证据 `official-inprocess-hwbp-pass5.json`。
- 下一步计划：不要再对官方进程挂全线程双断点。先无 hook 打开书详页并确认 `立即阅读`，再只钩 `track` 一处；或等人手点阅读。不要再 Frida attach，不要再 eCapture 本栈。

## 2026-09-02 HWBP 官方进程内 libcwmhttps 头

- 记录时间：2026-09-02 19:45–20:00（Asia/Shanghai）
- 分析思路：eCapture 钩不到 APK OpenSSL。Frida attach 已失败。改为内核 HWBP 读 `track` / `postHttpsRequest` / `getHead0`。`extractNativeLibs=false`，maps 只有 `base.apk`，不能 `--so libcwmhttps.so`。
- 本轮操作：`libcwmhttps` zip payload `0x4354000`，`--so 04354000`，pass_off = apk_off + func_off。KPM 用设备侧 env 脚本读 0600 keyfile，不把 superkey 打进 wrapper argv。随后用 libcurl `curl_slist_append` 和阅读器翻章补打，再对免费区新书 `立即阅读`。跑完确认 KPM count=0。未 `pm clear`，未写 `tokens.json`。
- 操作目的：对照官方进程内 HTTP 头/体与 oldcurl。
- 所用工具：`xiaojianbang_hook` / `kpm_loader`、`official_inprocess_hwbp.py` 及 pass2/3/4。
- 运行命令：`python analysis/app-version-2.9.365/work/official_inprocess_hwbp.py`
- 代码变更：work 脚本（gitignored）；账本增加 F-024。
- 检测代码明细：只读 HWBP，不 replace-ret / 不改 X0-X7。
- 实验结果：KPM hello/load/unload 成功。`track`/`postHttpsRequest`/`getHead0` 在书城 `get_index_list`（`track` X3=2）上打中 5 次，PC 与算出的绝对地址一致。`getHead0` listen-ret 落在 `postHttpsRequest` 返回点，X6/X7 小端 ASCII 为 `Expect: `，说明官方仍组这条空 Expect。本轮 UI 先误进阅读历史，后打开免费新书阅读器但翻章无出网（`slist_append` 0 hit，logcat 无 `get_cpt_ifm`）。全线程 HWBP 时 ADB 会短暂掉线。收尾后官方 App 在 `MainFrameActivity`，KPM count=0，代理 `null`。
- 下一步计划：等书详页出现 `立即阅读` 再下断；优先 `track` 看 X3=259，以及 `postHttpsRequest+0xdc`（`0x6ebc0`）dump getHead0 返回的 UA 串。不要再 Frida attach，不要再 eCapture 本栈。

## 2026-09-02 eCapture 官方进程内明文

- 记录时间：2026-09-02 19:35（Asia/Shanghai）
- 分析思路：身份移植已证伪。定制系统还没用的明文面是 eCapture。官方业务栈是 APK OpenSSL 1.1.0f，不是系统代理能看到的 OkHttp。
- 本轮操作：`px-status` ready，代理 `null`。官方 App 冷启动进 `MainFrameActivity`，未 `pm clear`。eCapture v2.3.0 text 模式对着官方 pid/uid。随后从「读书」打开阅读器。再试 Frida 17.15.3 attach。未写 `tokens.json`。
- 操作目的：拿到官方进程内 `get_cpt_ifm` 原始 HTTP，对照进程外 oldcurl。
- 所用工具：`ecapture_android.py` / 设备 eCapture、`official_inprocess_ecapture.py`、logcat `curl`/`ViseLog`、Frida CLI。
- 运行命令：`python analysis/app-version-2.9.365/work/official_inprocess_ecapture.py`；`frida -D 18251FDF6000N9 -p <pid> -l official_inprocess_header_hook.js`
- 代码变更：work 脚本（gitignored）；账本增加 F-023 / G-006。
- 检测代码明细：无用户态 patch。KPM 本轮未列出。
- 实验结果：eCapture 请求 `openssl 1.1.x` 仍加载 `boringssl_a_15_kern_noncore.o`。Connect 能看到官方 pid 的 443 元组，没有 HTTP 头。阅读器打开导流章 `106129841`，logcat 有 `get_bookmark_list` / `get_division_list` / `get_tsukkomi_num` / `set_read_chapter_record`=`100000`，没有 `get_cpt_ifm`（缓存章）。Frida 能枚举「刺猬猫阅读」，attach 报 process not found；无新 tombstone。官方 App 已重新冷启动回书城。
- 下一步计划：不要再 eCapture 本栈、不要再 Frida attach。HWBP `libcwmhttps` `track@0x6d260` / `postHttpsRequest@0x6eae4` / `getHead0@0x80cf0`，并打开未缓存章。

## 2026-09-02 官方出生身份移植

- 记录时间：2026-09-02 19:10（Asia/Shanghai）
- 分析思路：未闭合矛盾是「官方进程里注册的游客可读章，进程外注册的不可」。若服务端认的是出生身份，把官方 SharedPreferences 游客拿到独立客户端应过 `get_cpt_ifm`。
- 本轮操作：Pixel 身份门 ready，无残留代理。读取官方 `LoginedUser`（`is_bind=0`）写入 `work/official-born-guest-tokens.json`。未 `pm clear`，未写 `tokens.json`，不打印凭据。先 Python curl_cffi 打双主机；再同一凭据走 Pixel APK libcurl + getHead0 UA。
- 操作目的：单变量「官方出生身份 × 独立传输」。
- 所用工具：`official_born_identity_canary.py`、`official_born_oldcurl_canary.py`、panda `GetBookContentDetailTask.java`。
- 运行命令：`python analysis/app-version-2.9.365/work/official_born_identity_canary.py`；`python analysis/app-version-2.9.365/work/oldcurl/official_born_oldcurl_canary.py`
- 代码变更：两份 canary；账本/report/triage/findings 增加 F-022。
- 检测代码明细：无 hook。代理 `null`。
- 实验结果：官方游客 `get_my_info`/搜索/目录/cmd=`100000`。Python 双主机正文 `310017`。oldcurl `libcurl/7.56.1` + UA=`Android  com.kuangxiangciweimao.novel.c  2.9.365, google, Pixel 6, 35, 15` + `content-type,charsets,expect` 正文仍 `310017`。Java 任务只有 `chapter_id`/`chapter_command`/可选 `refresh`。
- 下一步计划：身份门证伪。对照官方进程内原始 HTTP，不要再移植身份。

## 2026-08-27 native 三项传输 canary

- 记录时间：2026-08-27 14:43（Asia/Shanghai）
- 分析思路：静态通路多出来的完整 `getHead0` UA、`charsets`/`Expect`、`CURLOPT_HTTP_VERSION=3` 还没单变量打过。
- 本轮操作：`oldcurl_post.c` 对齐 native slist（Content-Type / charsets / Expect），setopt HTTP/2 并回读协商版本。`pixel_native_headers_canary.py` 用设备 `getprop` 拼 UA，同一栈 auto_reg + search/cmd/cpt。游客只写 `work/pixel-native-headers-guest-tokens.json`。未写 `tokens.json`。
- 操作目的：看这三项能不能让自签游客过正文。
- 所用工具：Pixel `oldcurl_post` + APK so；NDK 重编。
- 运行命令：`python work/oldcurl/pixel_native_headers_canary.py`
- 代码变更：`oldcurl_post.c` 头与 HTTP_VERSION；`oldcurl_guest_canary.py` 回传协商版本；新 canary 脚本。
- 检测代码明细：无 hook。代理 `null`。
- 实验结果：UA=`Android  com.kuangxiangciweimao.novel.c  2.9.365, google, Pixel 6, 35, 15`。`http_version_setopt=1`，`http_version=2`（HTTP/1.1）。`curl_version` 仍是 `libcurl/7.56.1 OpenSSL/1.1.0f zlib/1.3.0.1-motley`，无 nghttp2。auto_reg/search/cmd=`100000`，`get_cpt_ifm=310017`。
- 下一步计划：这三项排除。不要再补传输头。官方游客仍不走极验；人机 GT3 只验证被拦身份能否恢复。

## 2026-08-27 native 注册通路静态还原

- 记录时间：2026-08-27 15:30（Asia/Shanghai）
- 分析思路：用户要官方 native `auto_reg` 通路，对照 Python/oldcurl 究竟多了什么。
- 本轮操作：IDA headless `kq22` 解 `libcwmhttps.so`（SHA-256 `428d5f64…`）`track` / `getAddr` / `GetInfo` / `post1` / `getSha256` / `getHead0` / `postHttpsRequest`；rabin2/radare2 核字符串与表；panda `AutoRegTask` / `BaseTaskNew.getC` / `UrlConstants.getUserType`。未打 live 请求，未读 token。
- 操作目的：把 `getC(17)` 接到 `signup/auto_reg_v2` 的 host、头、HMAC、UA。
- 所用工具：ida-multi-mcp、radare2、jadx dump。
- 运行命令：MCP `analyze_function` / `decompile_to_file`；`rabin2 -zz`；表项 `dword_527DC[api-2]`。
- 代码变更：无业务代码。落 `evidence/native-autoreg-path.json` 与 `so/ida-decomp/`。
- 检测代码明细：无 hook。
- 实验结果：`getAddr(17)=signup/auto_reg_v2`，`getAddr(154)=signup/save_reader_oaid`，`getAddr(259)=chapter/get_cpt_ifm`。首次游客 `userType=2` → `https://app1.hbooker.com/`。UA 为 `User-Agent: Android  com.kuangxiangciweimao.novel.c  ` + versionName + `, ` + brand + `, ` + model + `, ` + sdk + `, ` + release。额外头 `charsets: utf-8`、`Expect: `。`CURLOPT_HTTP_VERSION=3`（HTTP/2）。HMAC key 是证书 `toCharsString` 的 MD5，不是 .so 常量；guest 占位 `cmw666`；live `p` 仍以 84/84 公式为准（字面 `CkMxWNB666`）。Hex-Rays 在 `post1` 末尾叠了 MD5，变体与 fixture `RTemA7/IKa4GppnByNkaz0tVeAk1Cn8LnSM5NZ993Qc=` 不符。
- 下一步计划：不要把这条写成 310017 已解。若做单变量，只补完整 `getHead0` UA + `charsets`/`Expect` + HTTP/2，不要抄 token。

## 2026-08-27 310017 极验 API1

- 记录时间：2026-08-27 08:56（Asia/Shanghai）
- 分析思路：用户认为 Python 游客没过验证、达不到风控标准。官方对 `310017` 走 GT3：API1 `signup/geetest_first_register`，过关后把 `geetest_challenge/seccode/validate` 写回同一枪 `get_cpt_ifm`。先取 API1，不解滑块。
- 本轮操作：`geetest_api1_canary.py`。沿用 `work/pixel-chain-guest-tokens.json`。未写 `tokens.json`。
- 操作目的：看 310017 回包有没有 gt，以及 API1 是否给出 GT3 v3 初始化。
- 所用工具：Pixel oldcurl 打正文；本机 urllib GET API1。
- 运行命令：`python work/oldcurl/geetest_api1_canary.py`
- 代码变更：canary；从 `dex_0x75490eb000.dex` 恢复 `AddressUtils`。
- 检测代码明细：无 hook。
- 实验结果：正文仍 `{code,tip}` 的 `310017`，回包没有 gt。API1 在 happybooker 与 hbooker 均为 `success=1`、`new_captcha=true`、gt/challenge 各 32。官方游客读章不进这条。滑块未做。
- 下一步计划：人机过 GT3 后再带三元组重试 `get_cpt_ifm`。不要自动解滑块，不要抄 token。

## 2026-08-27 官方游客 extras + 导流章

- 记录时间：2026-08-27 08:47（Asia/Shanghai）
- 分析思路：Python 自签身份过不了正文。按官方链在 Pixel libcurl 上补注册前 `ad_reader_check`、cookie jar、按 `reader_id` 选主机、`save_reader_oaid`、`send_client_info(push_type=2, reader_id)`，并打官方导流章 `106129841`。
- 本轮操作：`pixel_official_chain_canary.py`。游客只写 `work/pixel-chain-guest-tokens.json`。未写 `tokens.json`。oldcurl 增加 COOKIEFILE/COOKIEJAR。
- 操作目的：单组官方 extras + 官方章号，不再做 TLS/INSTALLATION。
- 所用工具：Pixel `oldcurl_post` + APK so。
- 运行命令：`python work/oldcurl/pixel_official_chain_canary.py`
- 代码变更：canary 脚本；`oldcurl_post.c` cookie 路径。
- 检测代码明细：无 hook。
- 实验结果：代理 null。`ad_reader_check=100000`。`auto_reg=100000`，`is_bind=0`，`reader_id` 尾数 4 → `app1.happybooker.cn`。`save_reader_oaid=400000`。`send_client_info=100000`。导流章与搜索免费章 `get_chapter_cmd=100000`，`get_cpt_ifm=310017`。设备上未写出 `cookies.txt`（本轮 cookie 引擎可能未落盘；官方 viselog 也无 Cookie 头）。
- 下一步计划：不要再补 extras/章号。看 native `track()` 是否加了 POST 看不到的头。不要先极验。

## 2026-08-27 Pixel 官方 libcurl 上 auto_reg_v2

- 记录时间：2026-08-27 08:37（Asia/Shanghai）
- 分析思路：Python 游客 310017 可能是注册时 TLS 被打标。用 APK libcurl 在 Pixel 上打 `auto_reg_v2`（官方 UA、官方键序），uuid 新生成 `android+uuid4`，不读官方 App 的 INSTALLATION。
- 本轮操作：`pixel_autoreg_canary.py`。游客只写 `work/pixel-oldcurl-guest-tokens.json`。未写 `tokens.json`。
- 操作目的：单变量「注册也走官方 Hello」。
- 所用工具：Pixel `oldcurl_post` + APK so。
- 运行命令：`python work/oldcurl/pixel_autoreg_canary.py`
- 代码变更：canary 脚本。
- 检测代码明细：无 hook。
- 实验结果：`auto_reg=100000`，`is_bind=0`。同栈搜索/cmd=`100000`，`get_cpt_ifm=310017`。真机官方 Hello 上注册仍不能过正文。
- 下一步计划：不是 Pixel INSTALLATION 指纹同步。不要再为「注册 TLS」加实验。官方游客链已通。

## 2026-08-26 官方游客完整链路（先 trace 再 pm clear）

- 记录时间：2026-08-26 23:28（Asia/Shanghai）
- 分析思路：先起 curl/ViseLog，再 `pm clear` 重新注册官方游客，走到正文。
- 本轮操作：锁屏导致第一次空跑；解锁后 `pm clear` + 同意隐私 + 选标签/书 + 阅读器。未写 `tokens.json`，原始 logcat 解析后删除。
- 操作目的：确认 2.9.365 官方游客完整注册/读章链，核对 auto_reg 与 save_reader_oaid 字段。
- 所用工具：adb logcat `-s curl:D ViseLog:D`、uiautomator。
- 运行命令：`python work/official_guest_chain.py`
- 代码变更：抓取脚本。
- 检测代码明细：无 hook。
- 实验结果：链路出现 `auto_reg_v2`（hbooker，channel=TX，gender=1，oauth 空，uuid android+UUID）→ `save_reader_oaid`（happybooker，oaid 空，am 32 位）→ `send_client_info`（多 `push_type=2`、`reader_id`）→ `get_chapter_cmd` / `get_cpt_ifm`。阅读器正文已渲染。ViseLog code 本轮未配对成功，以 UI 渲染为官方读章成功证据。
- 下一步计划：官方完整链已复现。Python 同字段 save_oaid 仍 400000，正文 310017。不要先极验。

## 2026-08-26 补 save_reader_oaid

- 记录时间：2026-08-26 23:07（Asia/Shanghai）
- 分析思路：官方注册后打 `/signup/save_reader_oaid`。Python 补这一枪，正文仍走 APK libcurl。
- 本轮操作：`guest.save_reader_oaid`；存量游客、新 `auto_reg_v2` 游客、唯一 `am` 各打一次。未写 `tokens.json`。
- 操作目的：单变量看该接口能否改正文 310017。
- 所用工具：Pixel oldcurl、项目 venv。
- 运行命令：`python work/oldcurl/save_oaid_canary.py`
- 代码变更：`client/guest.py` 增加参数构造与调用，不自动挂到 `register_guest`。
- 检测代码明细：无 hook。
- 实验结果：`save_reader_oaid` 在 hbooker/happybooker、Pixel `am` 与唯一 `am` 下均为 `400000`（空 tip）。随后搜索/cmd=`100000`，`get_cpt_ifm=310017`。补枪未改变正文码。
- 下一步计划：不要把 400000 当成功绑定。310017 仍在。不要先极验，不要抄 token。

## 2026-08-26 Python auto_reg_v2 与官方游客注册字段

- 记录时间：2026-08-26 22:55（Asia/Shanghai）
- 分析思路：JA3 对齐后正文仍 310017，对照注册字段，不碰 `tokens.json`、不从 logcat 抄 token。
- 本轮操作：读 `guest.py`、`AutoRegTask`/`setCommonParams`/`Installation`/`SendImeiTask`；脱敏解析 2.9.362 官方 `guest-auto-reg-splash.log` 的 `post===>` 键。
- 操作目的：看 Python 注册请求是否缺字段或 channel/uuid/device_token 形状不对。
- 所用工具：jadx 产物、既有官方 logcat。
- 运行命令：无新网络请求。
- 代码变更：无客户端。
- 检测代码明细：无 hook。
- 实验结果：`/signup/auto_reg_v2` 键集合一致：`app_version, channel, device_token, gender, oauth_*, uuid, rand_str, p`。uuid=`android`+UUID；device_token=`ciweimao_`；gender=`1`；oauth 空；HMAC 占位 `cmw666` 不进 POST body。2.9.362 官方 live channel=`TX` 与 Python 相同。2.9.365 APK `UMENG_CHANNEL=Common`，安装包无 `META-INF/cztchannel`。Python **没有** 注册后的 `/signup/save_reader_oaid`（官方 `SendImeiTask`，oaid 可空，`am`=MD5(android_id)）。
- 下一步计划：`auto_reg_v2` 字段不是缺口。可单变量补 `save_reader_oaid` 看正文码；不要抄 token。

## 2026-08-26 官方 libcurl/OpenSSL 栈打游客正文

- 记录时间：2026-08-26 22:48（Asia/Shanghai）
- 分析思路：用 APK 里的 `libcurl.so` 7.56.1 + `libssl.so` OpenSSL 1.1.0f 在 Pixel 6 上 POST。Python 只签名和解密。
- 本轮操作：NDK 编 `oldcurl_post`，`dlopen` APK so；游客 search/catalog/cmd/get_cpt_ifm。对照官方 UA、官方 POST 键序、先打 `send_client_info`。tcpdump 核 JA3。未写 `tokens.json`。
- 操作目的：单变量换成官方 TLS 栈。
- 所用工具：NDK `aarch64-linux-android33-clang`、设备 APK so、adb tcpdump。
- 运行命令：`python work/oldcurl/oldcurl_guest_canary.py`
- 代码变更：`work/oldcurl/oldcurl_post.c`、`oldcurl_guest_canary.py`
- 检测代码明细：无 Frida。
- 实验结果：`curl_version=libcurl/7.56.1 OpenSSL/1.1.0f`。JA3 md5 `1aee0238…` 与官方 pcap **相同**。search/catalog/cmd/`send_client_info`=`100000`。`get_cpt_ifm` 在默认 UA、官方 UA+键序、prelude 之后均为 `310017`。官方 Hello 对齐仍不够。
- 下一步计划：TLS 不再当充分条件。对照 Python `auto_reg_v2` 与官方游客注册/设备信息字段，不要再调 curl_cffi ja3，不要先做极验。

## 2026-08-26 重置游客并关掉残留代理

- 记录时间：2026-08-26 22:11（Asia/Shanghai）
- 分析思路：用户真机官方 App 也无法加载正文。先 `pm clear` 走游客，再对照主线新能力。不要登录态、不要覆盖 `tokens.json`。
- 本轮操作：`pm clear` + 同意隐私 + 选书进书架；读章时卡住。查出 `global_http_proxy_host=127.0.0.1` `port=8085`，mitmdump 与 `adb reverse` 都不在。`px-proxy.ps1 -Action off` 并补删 host/port。再开 `ReaderActivity4`。
- 操作目的：区分「服务端现在也拦官方游客」和「本机抓包残留」。
- 所用工具：adb、uiautomator、logcat `curl`/`ViseLog`（只留 code/path）。
- 运行命令：`pm clear com.kuangxiangciweimao.novel`；`px-proxy.ps1 -Project ciweimao-api-reverse -Action off -DeviceSerial 18251FDF6000N9`。
- 代码变更：`px-proxy.ps1` 的 `off` 同时删 `http_proxy`/`global_http_proxy_host`/`global_http_proxy_port`。未改 `client/`，未写 `tokens.json`。
- 检测代码明细：无 hook。
- 实验结果：代理残留时官方停在「加载中」，WebView `net::ERR_PROXY_CONNECTION_FAILED`。只删 settings 键不够：ConnectivityService 活代理仍是 `127.0.0.1:8085`，Wi-Fi `validation failed`，OkHttp 连不上，native curl 的 `get_cpt_ifm` 仍 `100000`。`:0` 哨兵 + 重开 Wi-Fi 后网络 `IS_VALIDATED`，阅读器正文 UI 出来。无极验。
- 下一步计划：Python 正文 310017 仍对官方旧 TLS 栈。不要再开死代理。对照正文明文优先 eCapture，不要长期留 `px-proxy`。`dump-device-dex` 对本包已是 whole-fill，帮不了 310017。

## 2026-08-26 对齐官方 JA3

- 记录时间：2026-08-26 21:39（Asia/Shanghai）
- 分析思路：curl_cffi 不能原样套官方 JA3（缺 `0xccaa`）。按库限制去掉 SCSV/`0xccaa`、curve_formats 只能 `0`，再打游客正文。另用 CPython OpenSSL 3 锁 TLS1.2+HTTP/1.1 作对照。
- 本轮操作：`tls_align_canary.py`、`tls12_urllib3_canary.py`。未改默认客户端，未碰 `tokens.json`。
- 操作目的：看 curl_cffi 能表达的最近指纹、以及「只是禁 TLS1.3/h2」够不够。
- 所用工具：项目 venv curl_cffi 0.16.0、urllib3 2.7.0、OpenSSL 3.0.18。
- 运行命令：`python work/tls_align_canary.py`；`python work/tls12_urllib3_canary.py`。
- 代码变更：canary 脚本。
- 检测代码明细：`set_ja3_options` 断言 `curve_formats==0`、cipher 必须在 BoringSSL 名表、`TLS_EXTENSION_ORDER` 拒绝官方序 `0-11-10-13-16-22-23`。
- 实验结果：最近 JA3 在构造 ClientHello 阶段 `curl: (35) Invalid TLS extension order`。OpenSSL 3 TLS1.2+HTTP/1.1 搜索/cmd=`100000`，正文仍 `310017`。curl-impersonate 表达不了 OpenSSL 1.1.0f 的扩展序、NPN、SCSV、`0xccaa`、curve formats `0-1-2`。
- 下一步计划：不要再调 curl_cffi ja3。要过正文需真正旧栈（curl 7.56.1/OpenSSL 1.1.0f）或走官方极验。仓库 `tools/` 无该旧 curl。

## 2026-08-26 游客对照改 TLS

- 记录时间：2026-08-26 21:27（Asia/Shanghai）
- 分析思路：用户确认官方匿名游客能打开正文；2.9.362 游客 `get_cpt_ifm` 也曾 `100000`。不再等 `tokens.json`。同一出口上比对官方 native TLS 与 Python curl_cffi。
- 本轮操作：Pixel `tcpdump port 443`；解析 ClientHello JA3；`ja3_guest_canary.py` 游客正文。未读未写 `tokens.json`。
- 操作目的：确认 310017 是客户端传输栈，不是游客身份。
- 所用工具：adb tcpdump、项目 venv Python、curl_cffi 0.16.0。
- 运行命令：设备 `tcpdump -i any -c 40 -w ... port 443`；`python work/tls_hello_compare.py`；`python work/ja3_guest_canary.py`。
- 代码变更：canary 脚本；未改默认客户端。
- 检测代码明细：APK `libcurl.so` `curl/7.56.1`；`libssl.so` `OpenSSL 1.1.0f  25 May 2017`。
- 实验结果：官方 JA3 md5 `1aee0238942d453d679fc1e37a303387`（无 TLS1.3 cipher `13xx`，ALPN 仅 `http/1.1`，含 NPN 13172 与 SCSV `00ff`）。Python 默认 JA3 md5 `87e2668215f385b4ea50bcc9cbe4279d`（TLS1.3 `1301/1302/1303`，ALPN `h2,http/1.1`）。游客默认与强制 HTTP/1.1 正文均为 `310017`。按官方 JA3 复放因 curl_cffi 缺 cipher `0xccaa` 失败。pcap 本次 SNI 为 `da.kuangxiangit.com`，与业务 native curl 同一套 so。
- 下一步计划：不要再要登录态。要过正文需贴近 curl 7.56.1/OpenSSL 1.1.0f 指纹（自建 JA3 去掉 0xccaa 再试，或直用旧 libcurl）。不要 Chrome impersonate。

## 2026-08-26 tokens.json 登录态复跑

- 记录时间：2026-08-26 21:20（Asia/Shanghai）
- 分析思路：用户要求用现有 `tokens.json` 再做 Python 登录态对照。只读该文件，不覆盖，不从 logcat 抄 token。
- 本轮操作：`identity_canary.py`（`app1.hbooker.com`，`app_version=2.9.365`，无 impersonate）。
- 操作目的：同一 Python 栈上对比本地登录态与游客的 `get_cpt_ifm`。
- 所用工具：项目 venv Python。
- 运行命令：`python work/identity_canary.py`。
- 代码变更：无客户端代码；未写 `tokens.json`。
- 检测代码明细：无 hook。
- 实验结果：`tokens.json` 的 `get_my_info`/`search` 均为 `200100`（login_token 过期），正文对照未做成。游客仍是 `is_bind=0`，搜索/cmd=`100000`，正文=`310017`。文件元数据 `app_version=2.9.312`，mtime 早于本会话。
- 下一步计划：需要未过期的 `login_token` 写入 `tokens.json` 后再跑同一脚本。不要从 logcat 抄。

## 2026-08-26 身份与 UA

- 记录时间：2026-08-26 21:07（Asia/Shanghai）
- 分析思路：账本下一步是游客 vs 已登录、以及 live UA。同一 Python 栈对照 `tokens.json` 与游客；native `libcwmhttps.so` 的 UA 是完整常量。
- 本轮操作：`identity_canary.py` 只读 `tokens.json`；`ua_canary.py` 换 UA；Frida attach 被 stealth-hook 挡住（`pidof` 有 pid，Frida enumerate 看不到）。未把 logcat token 写入客户端。删除本轮含 token 的 viselog 落盘。
- 操作目的：判断 310017 是否只打游客、是否只因 UA 字符串。
- 所用工具：项目 venv Python；adb pidof；Frida 17.15.3 attach 失败。
- 运行命令：`python work/identity_canary.py`；`python work/ua_canary.py`。
- 代码变更：canary 脚本；未改 `client/` 默认 UA；未写 `tokens.json`。
- 检测代码明细：guest `get_my_info` `is_bind=0`、无手机邮箱。native UA 常量 `Android  com.kuangxiangciweimao.novel.c  `（双空格、以 `.c` 结尾，不是版本格式串）。
- 实验结果：`tokens.json` 为 `200100` 过期，Python 已登录对照未做成。游客正文仍 `310017`。Python 默认 UA、native 常量 UA、strip 后 UA 三格正文均为 `310017`。Frida live UA 因 stealth-hook 未抓到。
- 下一步计划：要用 Python 证明「已登录就能过」，需要有效登录态（用户自己更新 `tokens.json`，不要从 logcat 抄）。否则转向 native libcurl/OpenSSL 指纹或官方极验路径。

## 2026-08-26 传输面对照

- 记录时间：2026-08-26 20:09（Asia/Shanghai）
- 分析思路：同键 POST 官方 `100000`、Python `310017`。对照 UA、TLS impersonate、主机、Cookie、先发 `send_client_info` 与官方冷启动 prelude。
- 本轮操作：`strings libcwmhttps.so`；Pixel 冷启动 logcat `url===>`；Python `transport_canary.py` 与 `prelude_canary.py`。不读、不写项目根 `tokens.json`。
- 操作目的：单变量排除主机/TLS 伪装/Cookie/空参 `send_client_info`/官方先发接口。
- 所用工具：adb、项目 venv Python、curl_cffi 0.16.0。
- 运行命令：`python work/transport_canary.py`；`am start -W SplashActivity`；`python work/prelude_canary.py`。
- 代码变更：canary 脚本；未改 `client/` 默认行为。
- 检测代码明细：官方 native UA 片段 `User-Agent: Android  com.kuangxiangciweimao.novel.c`；Python UA `Android com.kuangxiangciweimao.novel 2.9.365`。无 Cookie 头。
- 实验结果：
  - native 确有 `reader/send_client_info`。官方冷启动未调用。Python 空参调用返回 `100000`，随后正文仍 `310017`。
  - `app1.happybooker.cn` 与 `app1.hbooker.com` × `impersonate=none|chrome99_android` 四格正文均为 `310017`。
  - 官方冷启动顺序：`get_meta_data` / `get_check` / `get_startpage_url_list` / `get_version` / `get_my_info` / `thired_party_switch` / `get_index_list`。Python 复放后正文仍 `310017`。`get_startpage_url_list` 空参为 `200001` 缺少参数，不在正文链上。
  - 官方读章节会话 URL 只有 bookmark/cmd/`get_cpt_ifm`/division/tsukkomi，无 `send_client_info`。
- 下一步计划：310017 更可能是游客身份 vs 官方已登录、或 native libcurl/OpenSSL 指纹，不是缺 prelude 接口。不要用 logcat 里的登录 token 做 Python 复放。

## 2026-08-26 业务码来源

- 记录时间：2026-08-26（Asia/Shanghai）
- 分析思路：用户问 `100000`/`310017` 是否不是固定值、有没有接口现算。对照 Python `_decode_response`、Pixel viselog、panda DEX 的 `BaseTaskNew.getC`。
- 本轮操作：只读 jadx `BaseTaskNew.java`、`Result.java`、`GetServerDataTask.java`、protocol-canary、pixel6 POST 证据。未发新请求。
- 操作目的：区分响应 `code`、`chapter_command`、极验三元组。
- 所用工具：jadx 产物、项目 evidence JSON。
- 运行命令：无。
- 代码变更：分析账本；未改 `client/`，未覆盖 `tokens.json`。
- 检测代码明细：`getC` 解密后 `JSONObject.getInt("code")`；`100000` 成功；`310017` 调 `initJiyan` + `GT3GeetestUtils.startCustomFlow()`，过关后把 `geetest_challenge/seccode/validate` 写回同一 POST 再 `getC`。`chapter_command` 另走 `/chapter/get_chapter_cmd`。
- 实验结果：业务码是服务端枚举，不是客户端生成、也没有「取码」接口。Python canary 的 tip「请升级到最新版本客户端」只是 `tip` 文案；官方 App 对 `310017` 忽略 tip、弹极验。真机会话同键返回 `100000`，说明服务端按客户端特征从目录里选码。
- 下一步计划：解释 Python 为何被打到 `310017`（TLS/UA/会话/风控），不要找生成 `code` 的接口。需要过 `310017` 时才复现极验重试，不默认改 POST 键。

## 2026-08-26 19:34

- 记录时间：2026-08-26 19:34（Asia/Shanghai）
- 分析思路：`get_cpt_ifm` 明文不在 dump DEX 里，但 `UrlConstants.isShowLog` 且历史抓包用 logcat `curl` 的 `url===>`/`post===>`。真机官方进程打开章节即可拿到 POST 键，不走 mitm、不 panda。
- 本轮操作：冷启动原包；同意隐私；书详情「立即阅读」；`logcat -s curl:D`。
- 操作目的：核对 2.9.365 官方 POST 键是否比 Python 客户端多字段。
- 所用工具：adb、uiautomator、logcat tag `curl`。
- 运行命令：`am start SplashActivity`；`input tap` 同意/立即阅读；`logcat -d -s curl:D ViseLog:D`。
- 代码变更：无客户端代码。证据 `evidence/pixel6-get-cpt-ifm-post.json`（无 token）。
- 检测代码明细：无 hook。
- 实验结果：两次 `/chapter/get_cpt_ifm` POST 键均为 `account, app_version, chapter_command, chapter_id, device_token, login_token, rand_str, p`，与 2.9.362 抓包和当前 Python `_call` 一致。ViseLog 邻近 JSON `code=100000`。先发 `/chapter/get_chapter_cmd`（无 `chapter_command`），再用返回 command 打 `get_cpt_ifm`。
- 下一步计划：310017 改查 TLS/UA/`send_client_info`/会话，不再加 POST 字段。


## 2026-08-26 19:10

- 记录时间：2026-08-26 19:10（Asia/Shanghai）
- 分析思路：用户要求用 Pixel 6 真机继续。模拟器阻塞是 x86 SecShell 解析 `/proc/self/maps` 后 `fclose` SIGSEGV。真机 `primaryCpuAbi=arm64-v8a`，应走 `libSecShell.so`，不再 houdini/x86。先无 Frida 原包基线，活过 Splash 再 panda。
- 本轮操作：`px-status` ready；停 frida-server；安装原签 `ciweimao-2.9.365.apk`；syscall-filter `uidadd=10237`；`am start -W` Splash。
- 操作目的：验证真机能否过壳，并 dump 业务 DEX。
- 所用工具：pixel6-control、apk-reverse `dump-dex.ps1`、panda、jadx（关 checksum）。
- 运行命令：`adb -s 18251FDF6000N9 install -r` 原包；`am start -W ...SplashActivity`；`dump-dex.ps1 -Project ciweimao-api-reverse -Package com.kuangxiangciweimao.novel -DeviceSerial 18251FDF6000N9`。
- 代码变更：无业务代码；更新本分析账本。未覆盖 `tokens.json`。
- 检测代码明细：未再 hook。壳 Application 仍是 `com.SecShell.SecShell.AW`。
- 实验结果：冷启动 TotalTime 3278ms，Activity=`WelcomeActivity`，pid=8813，tombstone 无。`dumpsys`：`versionName=2.9.365` `versionCode=290365` `primaryCpuAbi=arm64-v8a` `appId=10237`。panda 输出 43 个结构有效 DEX / 71775408 字节，目录 `artifacts/dex-dump/20260826_190632`。wrapper `status=partial`（dump 后 `kill -CONT 8813` 时进程已不在）。字符串命中：`dex_0x72090ab000.dex` 含 `com.kuangxiangciweimao` 与 `chapter/get_cpt`；jadx 该 DEX 得到 `UrlConstants` 的 `chapter/get_cpt_audio`，**43 个 DEX 均无明文 `get_cpt_ifm`**。
- 下一步计划：进程保活下抓 `get_cpt_ifm` POST；jadx 另外两个含包名 DEX。不要再对真机走 x86 fclose IDA。


## 2026-08-23 23:10

- 记录时间：2026-08-23 23:10（Asia/Shanghai）
- 分析思路：用户要求在模拟器继续脱壳和反 Frida hook，再补章节正文。先恢复 `ciweimao-api-reverse` 实例并确认 Root/Frida/KPM，再对原包做无 hook 基线。壳初始化 SIGSEGV 仍按 native-reverse 闪退门禁处理，不先盲 spawn Frida。
- 本轮操作：启动实例 index 10；初始化 artifacts 目录；准备 `init-ldplayer-re`。
- 操作目的：拿到可复现的设备基线，再决定 extractNativeLibs / Frida / syscall-filter。
- 所用工具：ldplayer-control、apk-reverse `init-ldplayer-re.ps1`、项目 adb `D:\reverse_ENV\tools\adb\adb.exe`。
- 运行命令：`re-init.ps1 -Project ciweimao-api-reverse`；`ldconsole launch --index 10`；`init-ldplayer-re.ps1 -DeviceSerial emulator-5574`。
- 代码变更：无。
- 检测代码明细：待运行期确认。
- 实验结果：实例 ADB 为 `emulator-5574`，项目 adb 与 LDPlayer adb 均可见。先前 `adb kill-server` 会把刚启动的实例打成无设备，后续禁止为了“对齐两个 adb”而 kill-server。
- 下一步计划：确认 Root、Frida、kpatch、已装包版本，然后原包无 hook 启动基线。

## 2026-08-23 23:02

- 记录时间：2026-08-23 23:02
- 分析思路：原包 `primaryCpuAbi=arm64-v8a`，但 `lib/arm64` 里同时抽出了 `libSecShell-x86.so`。假设崩溃来自 Java `H.is_x86_byso()` 选了 x86 so，且 `extractNativeLibs=false` 时还会从 `base.apk` mmap 同一文件。
- 本轮操作：无 hook 启动抓 `tombstone_02`；把抽出的 `libSecShell-x86.so` 改名为 `.bak` 后再启动抓 `tombstone_03`。
- 操作目的：单变量验证 x86 so 是否为 SIGSEGV 来源。
- 所用工具：adb、tombstone。
- 运行命令：`monkey -p com.kuangxiangciweimao.novel`；`mv libSecShell-x86.so libSecShell-x86.so.bak`。
- 代码变更：无。
- 检测代码明细：`com.SecShell.SecShell.AW` 在 `attachBaseContext` 调用 `H.is_x86_byso()`，true 则 `System.loadLibrary("SecShell-x86")`。崩溃 `#00 close+9 / #01 fclose+220 / #02 pc 0x7f582`。隐藏抽出文件后同一 pc 变成 `base.apk (offset 0x82df000)`，说明 zip mmap 仍加载 x86 so。fault addr 仍是 `0x9eb6b2b8`。
- 实验结果：x86 so + `/proc/self/maps` `fclose` 是崩溃点。仅改抽出目录不够，必须拦截 `loadLibrary`/`dlopen` 或改 APK 内容。无 kpatch，syscall-filter 未跑。
- 下一步计划：Frida spawn 重定向 `libSecShell-x86.so` -> `libSecShell.so`。

## 2026-08-23 23:16

- 记录时间：2026-08-23 23:16
- 分析思路：过检测任务允许 Frida 做主路径。在 constructor 前 hook `android_dlopen_ext`/`dlopen` 改路径，避免加载 x86 so。
- 本轮操作：frida-server 17.15.3 与宿主一致（禁止换版本；`init-ldplayer-re` 误报 mismatch）。`spawn_secshell_arm.py` spawn；进程保活。panda dump。尝试 Java 枚举。
- 操作目的：让 App 活过壳初始化，再 dump DEX / 抓正文请求。
- 所用工具：Frida 17.15.3、panda-dex-dumper、项目 adb。
- 运行命令：`python spawn_secshell_arm.py --device emulator-5574`；`panda-dex-dumper -p <pid>`。
- 代码变更：`scripts/secshell_arm_frida_agent.js`、`spawn_secshell_arm.py`。
- 检测代码明细：Frida 17 的 Python `create_script` 在 spawn/attach 时 `typeof Java === 'undefined'`（Java bridge 不再默认注入）。native dlopen hook 足够让进程活过 `0x7f582`。panda 只扫到 1.5MB / 662 class 的壳 DEX（`androidx`/`SecShell`/`alibaba`），未见 `com.kuangxiangciweimao`。进程停在 `SplashActivity`。
- 实验结果：脱壳未完成，但壳初始化崩溃已绕过。正文接口尚未抓到。LDPlayer 若从命令 Job 里启动 `dnplayer.exe` 会把 index 0 MAA 一起拉起，且部分命令结束后模拟器会掉线；后续只 `ldconsole launch --index 10`，不碰 emulator-5554。
- 下一步计划：进程保活后继续 Memory.scan DEX、过 Splash、抓 `get_cpt_ifm` POST 键；Java hook 需单独解决 Frida 17 java-bridge。

## 2026-08-23 23:40

- 记录时间：2026-08-23 23:40（Asia/Shanghai）
- 分析思路：上一轮把 `base.apk!/lib/arm64-v8a/libSecShell-x86.so` 改写成相对路径 `lib/arm64/libSecShell.so`，houdini 随后报 `libtcb.so` 不在 anonymous namespace。真正该改的是文件名而不是路径；同时 Python `create_script` 未处理 `frida:load-bridge`，所以 `Java` 一直 undefined。`H.is_x86_byso()` 读 `/system/lib/libc.so` 的 e_machine（3/6/7 当 x86），true 才 `loadLibrary("SecShell-x86")`。过检测主路径改为 Java 强制 false + 保留绝对/zip 路径的 native 改名。
- 本轮操作：WMI 在 Job 外 `ldconsole launch --index 10`（避免命令结束杀 VM）；确认 Root/`libnb.so`/无 KPM；启动已有 `frida-server` 17.15.3；补 bridge 投递与路径改写。
- 操作目的：让 ARM `libSecShell.so` 走和其他 ARM 业务 so 相同的 NativeBridge 加载路径，活过壳初始化后再 dump DEX。
- 所用工具：ldconsole、项目 adb、Frida 17.15.3、frida_tools/bridges/java.js。
- 运行命令：WMI `ldconsole launch --index 10`；`su 0 /data/local/tmp/frida-server -D`；`python spawn_secshell_arm.py --device emulator-5574`。
- 代码变更：`scripts/secshell_arm_frida_agent.js`、`scripts/spawn_secshell_arm.py`。
- 检测代码明细：`H.is_x86_byso` 读 `/system/lib/libc.so` ELF `e_machine`；`AW.attachBaseContext` 据此 `System.loadLibrary("SecShell-x86"|"SecShell")`。`libtcb.so` 实际在 `/system/lib64/arm64/nb/libtcb.so`。syscall-filter 仍不可用（无 kpatch）。
- 实验结果：见同日 00:05 续记。
- 下一步计划：spawn 后看 `System.loadLibrary(SecShell)` 与 `libSecShell.so` 是否进 maps；成功则 panda/`OpenCommon` dump，失败则只补 search path，不再叠加无关 hook。

## 2026-08-24 00:05

- 记录时间：2026-08-24 00:05（Asia/Shanghai）
- 分析思路：LDPlayer 进程 ABI 是 x86_64，`H.is_x86_byso()` 读 `/system/lib/libc.so` 的 `e_machine` 后加载 `libSecShell-x86.so`（x86_64 ELF，放在 `lib/arm64-v8a`）。把它改成 ARM `libSecShell.so` 会走 houdini，而该 ARM ELF 动态段加密，houdini Fatal `0x01101246`。正确路径是让 NativeBridge 加载 x86 so，再过 `/proc/self/maps` 解析里的 `fclose` SIGSEGV。
- 本轮操作：WMI 拉起 index 10（避免 Job 杀 VM）；`frida-server` 17.15.3 已有进程；Frida spawn native hook。Python `create_script` 仍无 Java（agent 未 `import Java`，不会发 `frida:load-bridge`）。syscall-filter 仍不可用。
- 操作目的：活过壳初始化，dump 运行期 so / DEX，再抓 `get_cpt_ifm`。
- 所用工具：Frida 17.15.3、项目 adb、llvm-readelf。
- 运行命令：`python spawn_secshell_arm.py --device emulator-5574`。
- 代码变更：`scripts/secshell_arm_frida_agent.js`、`scripts/spawn_secshell_arm.py`。
- 检测代码明细：
  - `AW.attachBaseContext` → `H.is_x86_byso()` → `System.loadLibrary("SecShell-x86")`。
  - `libtcb.so` 是 x86_64，路径 `/system/lib64/arm64/nb/libtcb.so`；ARM rewrite 时 anonymous ns 空路径导致 `0x0190019f`，preload 后变为 houdini `0x01101246`。
  - x86 so 可映射（`base=0x7638…` size=1458176）。随后 `fopen("/proc/self/maps")`，在 `libSecShell-x86.so+0x7f580` 处 `call qword ptr [rbp+8]`（fclose）SIGSEGV，fault 曾为 `0x9eb6b2b8`（截断地址）或 `0x0`。
  - 过滤 maps 并重定向 fopen 后仍在同一 fclose 崩溃。`Interceptor.replace(fclose)` 会在 `script.load` 时把 Frida 自身打崩，禁止再用。
- 实验结果：未过壳、无业务 DEX、无 `get_cpt_ifm` 抓包。已落地运行期 so：`artifacts/dumps/libSecShell-x86.mem.so`（1,458,176 字节，ELF x86_64，与磁盘 1,367,853 字节不同）。磁盘 so 动态段仍加密。动态试错已超过三次上限，下一轮必须 IDA 分析 dump 里 `+0x7f540` 的 maps 解析函数后再 patch。
- 下一步计划：IDA 打开 mem dump，搞清 `rbp+8` 函数表和 fclose 参数来源；只 patch 该函数。不要继续叠加 fopen/fclose/houdini 变量。正文接口仍等解密 DEX 或真机抓包。

## 2026-08-24 00:10

- 记录时间：2026-08-24 00:10（Asia/Shanghai）
- 分析思路：用户要求暂停。本轮只落进度与三件套，不继续动态实验。
- 本轮操作：重写 `analysis-progress.md` 为恢复入口；同步 `report.md` / `findings.json` / `triage.md` / `workspace.json` / `evidence/native-shell-experiments.md`。
- 操作目的：交接时可只读进度文件恢复。
- 所用工具：无。
- 运行命令：无。
- 代码变更：分析文档；未改 `client/`、未覆盖 `tokens.json`、未再 spawn。
- 检测代码明细：无新增。
- 实验结果：文档与 dump 路径已对齐。工作暂停。
- 下一步计划：见 `analysis-progress.md`「恢复后只做这些」。

## 2026-09-01 Web fallback 续推进

- 记录时间：2026-09-01（Asia/Shanghai；canary UTC 时间为 2026-08-31 16:16）。
- 分析思路：App `get_cpt_ifm` 的 310017 已由多轮 HMAC/UA/TLS/native canary
  证明不是单项传输缺口；转查公开网页产品面，要求与 App credentials、身份槽和
  购买态严格隔离。
- 外部取证：`search-layer` deep 查询网页章节接口；`gh api` 交叉读取
  `guohuiyuan/go-novel-dl`、`dteviot/WebToEpub`、`404-novel-project/novel-downloader`
  以及 `saudadez21/novel-downloader#157`。一致证据为章节页 GET → session key
  POST → detail POST，Cookie（`ci_session`）会轮换，单活跃 session 需串行/限速。
- 本轮操作：新增 `client/web.py`（同步/异步 `WebChapterSession`）、App `310017`
  后仅 free-only 回退、Web 业务错误分类、readiness 的同槽 Web probe 分流；新增
  脱敏 canary 脚本与离线 fixture。
- 操作目的：让现有搜索/目录链在正文 App 门被拦时仍能下载公开文本免费章，同时
  不把网页成功伪装成 App 协议恢复。
- 运行命令：
  `D:\reverse_ENV\.venv\Scripts\python.exe analysis/app-version-2.9.365/scripts/web_fallback_canary.py --chapter-id 112001971 --min-interval 0`
  以及项目 `python -m unittest discover -s . -p 'test*.py' -q`。
- 检测/协议细节：`chapter_access_key` 首/末字符按 `ord(...) % len(keys)` 选两层
  AES-CBC key；每层是 `Base64(IV || ciphertext)` + PKCS#7；解密后删除水印 span。
  Web 请求不含 `account/login_token/device_token/app_version/p/chapter_command`。
- 实验结果：公开章节页面/session/detail 均 HTTP 200，detail `code=100000`，
  解密后非空正文；证据写入 `evidence/web-fallback-canary.json`，只保留状态、
  字节数、长度、hash 与 Cookie 名称。离线 Web 单测 10 个，项目单测 82 个，均通过。
- 下一步计划：生产保持每个 Web session 的 Cookie jar、单活跃序列和默认 3 秒间隔；
  若目标是 VIP/购买态或必须恢复 App gate，再单独安排人工 GT3 取证，不自动解题，
  也不覆盖 `tokens.json`。

## 2026-09-02 uid MITM 冷启动

- 记录时间：2026-09-02 22:44（Asia/Shanghai）
- 分析思路：系统 `http_proxy` 只覆盖 OkHttp，官方 `libcurl` 不读它。官方
  `SSL_VERIFYPEER/HOST=0`，缺的是 uid 级 443 透明转发，不是证书钉扎。
- 本轮操作：设备 `redir_connect` 听 18085，iptables owner 10237 REDIRECT 443，
  `route_localnet=1`，`adb reverse` 到 PC mitmdump；addon 只记路径/头名/键名。
  `force-stop` 后冷启动 Splash。收尾删除 CWM_MITM、杀掉转发、`http_proxy` 仍 null，
  `route_localnet` 恢复 0。
- 操作目的：补上原生 HTTPS MITM，核对前置链路是否比 Python 多隐藏头或 Cookie。
- 实验结果：9 条 HTTP/1.1 POST，路径集合与 `pixel6-startup-urls` 相同。线上头名
  Host/Accept/Content-Type/charsets/User-Agent/Content-Length；空 Expect 不上线；
  无 Cookie/Set-Cookie。本窗没有 `get_cpt_ifm`。prelude-canary 早已复放仍 310017。
- 证据：`evidence/official-uid-mitm-startup.json`
- 下一步计划：不要再用全局 `http_proxy` 抓 native。不要把冷启动序当充分条件。
  继续查官方出生游客与 Python 自注册游客的服务端放行差。

## 2026-09-02 uid MITM get_cpt_ifm

- 记录时间：2026-09-02 22:50（Asia/Shanghai）
- 分析思路：冷启动 MITM 已证明无隐藏头。需要同一平面解密正文请求。
- 本轮操作：解锁后复用 uid REDIRECT。第一本免费书走本地缓存，只打旧 catalog
  与 `set_read_chapter_record`。第二本封面直进阅读器，抓到 cmd/cpt 各两次。
- 实验结果：`get_cpt_ifm` HTTP 200，HTTP/1.1。头名与冷启动相同；键序
  account/app_version/chapter_command/chapter_id/device_token/login_token/rand_str/p。
  无 Cookie/Expect/refresh。与 logcat/HWBP 一致，不是新的协议缺口。
- 证据：`evidence/official-uid-mitm-cpt.json`
- 下一步计划：不要再为「缺隐藏头」开 MITM。下一步仍是两类游客的服务端放行差。
