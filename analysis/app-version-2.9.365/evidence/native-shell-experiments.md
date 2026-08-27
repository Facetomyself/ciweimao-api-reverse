# App 2.9.365 Native 壳实验记录

## 2026-07-18 14:35

- **记录时间**：2026-07-18 14:35（Asia/Shanghai）。
- **分析思路**：服务端对 App 2.9.362 的章节正文接口返回 `310017`，仅替换 `app_version=2.9.365` 并沿用旧签名又返回 `320002`。先确认新版 APK 的保护层和运行边界，再恢复新版签名及章节协议；不把游客权限、代理出口与客户端协议升级混为一谈。
- **本轮操作**：校验 2.9.362/2.9.365 APK 哈希与签名证书；运行 fingerprint 和 controlled decode；在项目 LDPlayer 实例中原位升级到 2.9.365 并采集 logcat/tombstone；检索 SecNeo/Bangcle 现成兼容与脱壳证据；暂停线上自动下载并备份 SQLite。
- **操作目的**：确定旧下载链失效是权限、代理、版本签名还是新壳导致，并阻止错误章节占位文件继续被记录为成功下载。
- **所用工具**：`apk-reverse` fingerprint/decode、apktool 3.0.2、jadx、Android build-tools 35 `apksigner`、LDPlayer 9 `emulator-5574`、adb/logcat/tombstone、search-layer、GitHub CLI、ali-cloud SSH、Docker Compose、SQLite backup API。
- **运行命令**：关键入口为 `fingerprint.sh <apk>`、`decode.ps1 -ApkPath <2.9.365.apk> -OutRoot <analysis/work> -Clean`、`adb -s emulator-5574 install -r <2.9.365.apk>`、`adb logcat`、读取 `/data/tombstones/tombstone_01`；线上只操作 Compose project `ciweimao-api-reverse`。
- **代码变更**：尚未修改业务协议；服务器当前 release 临时设置 `CIWEIMAO_AUTO_DOWNLOAD_ENABLED=0`。本地新增本实验记录，并忽略 `artifacts/` 原始运行时 dump。
- **检测代码明细**：2.9.365 Manifest Application 为 `com.SecShell.SecShell.AW`，`appComponentFactory` 为 `com.SecShell.SecShell.AP`，`extractNativeLibs=false`。APK 同时包含 x86-64 `libSecShell-x86.so` 和 AArch64 `libSecShell.so`。LDPlayer 启动时加载 x86-64 变体，随后在 `libSecShell-x86.so+0x7F582` 的上游路径调用 libc `fclose/close`，因坏指针 `0x9eb6b2b8` 触发 `SIGSEGV`；栈顶为 libc `close+9 -> fclose+220 -> libSecShell-x86.so+0x7F582`。tombstone 内同时出现 `/proc/self/maps` 文本，说明该路径正在解析进程映射。是否存在自身 CRC、签名校验、匿名 RX 或运行时重建尚待 syscall-filter、maps 与 IDA 确认。
- **实验结果**：两版 APK 使用相同发布证书。旧版 fingerprint 命中 360 Jiagu，新版命中 Bangcle/SecNeo；新版静态 DEX 仅得到 372 个壳/依赖 Java 文件，业务代码未暴露。2.9.365 在 LDPlayer 中于壳初始化阶段崩溃，尚未进入游客注册、业务 API 或章节逻辑。GitHub 同类 `/proc/self/maps` 路径缺失案例报告 `android:extractNativeLibs=true` 可修复，但对本样本仍为待验证候选，不能直接当结论或 patch。
- **下一步计划**：先验证 LDPlayer 是否具备 `xiaojianbang-syscall-filter` 所需 KernelPatch/KPM；采集或明确记录环境缺口。随后落盘启动期 maps，确认 pc/lr 与匿名可执行段归属；判断磁盘 `libSecShell-x86.so` 是否自解密/运行时重建；按 `.init -> .init_array -> JNI_OnLoad -> 匿名映射 -> CRC/完整性 -> 崩溃函数上下游` 顺序用 IDA 分析。满足门禁后再验证 `extractNativeLibs=true` 或单点 Native patch。

## 2026-08-23 22:30

- **记录时间**：2026-08-23 22:30（Asia/Shanghai）。
- **分析思路**：先静态对照 `libcwmhttps.so`，再以游客身份做真实请求 canary。不把 2026-07-18 的「改版本号得 320002」直接当成 HMAC 已变。
- **本轮操作**：SO 哈希/字符串 diff；`auto_reg_v2` 新游客；搜索/目录/command/正文/download_cpt canary；协议档案加入 2.9.365；探针覆盖 `get_cpt_ifm`；apktool 重打包去掉 `unknown/res` 重复项后 debug 签名（未安装，避免和壳完整性混为一谈）。
- **操作目的**：判断 310017 是签名换代、版本字符串，还是正文接口额外证明。
- **所用工具**：项目 venv Python、radare2 `radiff2`/`rabin2`、wandoujia search、search-layer、GitHub CLI。
- **运行命令**：`compare_native_crypto.py`、`protocol_canary.py`、`download_cpt_canary.py`。
- **代码变更**：`client/config.py` 默认 `2.9.365`；`service/core.py` 与 `service/app.py` 的探针/ready 门禁。
- **检测代码明细**：无新壳崩溃抓取。LDPlayer Android 9 无 KernelPatch，syscall-filter 未跑。
- **实验结果**：HMAC/AES 同代；搜索 `100000`；正文三接口 `310017`。先前「2.9.365 + 旧签名 -> 320002」与本次「2.9.365 重算 HMAC -> 搜索成功」不一致，320002 不能再当成公式已变的证据。
- **下一步计划**：真机或能启动的 2.9.365 进程抓 `get_cpt_ifm` POST 键；不要继续盲改 `app_version`。

## 2026-08-24 00:10（暂停）

- **记录时间**：2026-08-24 00:10（Asia/Shanghai）。
- **分析思路**：用户要求暂停并落文档。把 08-23 夜至 08-24 凌晨的 LDPlayer 脱壳结论收束到三件套与进度账本，不再叠加 Frida 变量。
- **本轮操作**：只写文档，不 spawn、不改客户端协议。
- **操作目的**：换会话可从 `analysis-progress.md` 恢复。
- **所用工具**：无新运行。
- **运行命令**：无。
- **代码变更**：更新 `analysis-progress.md`、`report.md`、`findings.json`、`triage.md`、`workspace.json`、本文件与 `docs/experiment_record.md`。
- **检测代码明细**：同 2026-08-24 00:05 实验记录。崩溃函数在运行期 dump `+0x7f540`：`mov rdi,r14` / `call [rbp+0x10]` / `call [rbp+8]`（fclose）。
- **实验结果**：暂停时 B-001（正文 310017）与 B-002（maps/`fclose`）均未解除。mem dump SHA-256 `66396047aa619f374069db2d35edce77924a4a1619543399dbaa24b309c52054`。
- **下一步计划**：IDA `artifacts/dumps/libSecShell-x86.mem.so`；禁止再试 houdini ARM 改写与 `replace(fclose)`。
