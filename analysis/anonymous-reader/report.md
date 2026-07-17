# 刺猬猫 App 游客正文加载排查报告

## 基本信息

| 项目 | 值 |
|------|-----|
| 目标文件 | `analysis/anonymous-reader/input/ciweimao-2.9.362.apk` |
| SHA-256 | `D74F25B282AC32B396948473341CD6145FDEB5DE923A2BC3D29C759D72B816F0` |
| 文件类型 | Android APK，360 加固，Native Android / Kotlin |
| ABI | `arm64-v8a`、`armeabi-v7a` |
| App | `com.kuangxiangciweimao.novel` 2.9.362 (`290362`) |
| 分析时间 | 2026-07-17 15:35-15:45 |
| 分析深度 | L2（运行时网络与身份上下文） |

## 执行摘要

1. 本次正文卡在“加载中，请稍候”是代理链故障，不是免费章节的服务端权限拒绝。
2. 章节 command 和章节元数据接口均返回 `code=100000`；目标章节为免费章，服务端明确返回 `is_paid=0`、`auth_access=1` 和正文 CDN URL。
3. App 随后的 CDN GET 被导向 `127.0.0.1:8083`，但当时没有 `adb reverse` 和 mitmproxy 监听，最终 `ECONNREFUSED`。
4. 补齐同端口的 mitmproxy 与 `adb reverse` 后，CDN 连续返回 HTTP 200，ReaderActivity4 正常渲染正文。
5. “未登录”并非完全匿名：App 首次启动会自动创建未绑定的游客账号，并在请求中携带游客 `account/login_token`。游客可读免费章，付费章仍由 `auth_access=0` 拒绝。
6. 两次干净安装的 `auto_reg_v2` 独立样本使用同一固定预注册签名占位符，UUID 与最终游客账号均不同；现有 HMAC 和 AES 实现可直接完成注册、解密及随后搜索。
7. ali-cloud 直连及两个 self-server SSH 端口均能注册游客，但业务接口统一返回 `320002`；NAS 住宅出口经 SSH exec relay 注册与搜索均成功，说明限制落在出口策略，而不是注册算法或 token 文件格式。

## 关键发现

### F-001：正文空白由残留代理配置触发

- **位置**：Android global settings、`ReaderActivity4` 运行时日志
- **证据**：`global_http_proxy_host=127.0.0.1`、`global_http_proxy_port=8083`；无 `adb reverse`、无 mitmdump；正文 CDN 请求报 `Failed to connect to /127.0.0.1:8083`。
- **结论**：高置信度确认代理链断裂是本次无限加载的直接原因。
- **置信度**：`high`

### F-002：章节业务接口和免费章权限均正常

- **位置**：`/chapter/get_chapter_cmd`、`/chapter/get_cpt_ifm`
- **证据**：两个接口均返回 `code=100000`；章节元数据为 `is_paid=0`、`auth_access=1`、`use_cdn=1`。
- **结论**：服务端已授权游客读取该免费章，问题发生在后续 CDN 下载阶段。
- **置信度**：`high`

### F-003：App 使用自动游客账号，不是空身份访问

- **位置**：App 启动后的读者信息响应及后续请求参数
- **证据**：运行时产生未绑定、无手机号/邮箱的读者身份；业务请求携带游客账号和 token。原始凭据已省略。
- **结论**：排行榜、评论、免费正文复用游客身份；登录正式账号主要扩展书架、同步、已购章等权限。
- **置信度**：`high`

### F-004：接通代理后正文链恢复

- **位置**：`mitmproxy_traffic.flow`、ReaderActivity4 页面
- **证据**：建立 `tcp:8083` reverse 并启动 mitmdump 后，3 个正文 CDN GET 均返回 HTTP 200；页面由加载态切换为正文渲染态。
- **结论**：完成同进程、同章节链路的 A/B 验证。
- **置信度**：`high`

### F-005：游客身份可脱离 App 自动创建

- **位置**：`/signup/auto_reg_v2`、`client/guest.py`
- **证据**：两次干净安装的预注册占位符长度/hash 一致，UUID 与最终游客账号不同；`2/2` 请求签名重算一致。纯 `curl_cffi` 请求返回 HTTP 200，完整响应经当前 AES key 解密为 `code=100000`，随后搜索返回 10 本。
- **结论**：服务器必须从自己的 egress 创建游客，不能复制其他出口产生的 token；FastAPI 可在 lifespan 阶段自动完成该 bootstrap。
- **置信度**：`high`

### F-006：数据中心/专线出口被业务接口拒绝，NAS 住宅出口可用

- **位置**：ali-cloud Compose egress A/B、`client/ssh_exec_socks.py`
- **证据**：ali-cloud 直连、self-server 44001/44005 的 `auto_reg_v2` 均为 `100000`，但后续搜索/个人信息为 `320002`；同一协议经 NAS SSH exec relay 注册为 `100000`，搜索返回 10 本。
- **结论**：部署不能仅追求“国内 IP”或“同出口注册”，还需要目标接受的住宅出口。NAS 无需开启 `direct-tcpip`；普通 session channel 内存 relay 已完成真实验证。
- **置信度**：`high`

## 数据流

```text
App 首次启动
  -> /signup/auto_reg_v2 创建游客 reader identity
  -> 榜单 / 评论 / 搜索类业务 API

进入免费章节
  -> /chapter/get_chapter_cmd
  -> /chapter/get_cpt_ifm
  -> 返回 use_cdn=1 + txt_content URL
  -> OkHttp GET CDN TXT
  -> ReaderActivity4 渲染
```

本次故障点位于最后一个 CDN GET，而不是前面的章节授权接口。

## 根因与环境风险

新实例从 `re-xposed` 模板复制后保留了 `127.0.0.1:8083` 的代理分项。端口 `8083` 与模板实例 index 3 的默认代理端口一致，说明残留高度疑似来自模板历史代理状态。当前 `proxy-off` 实现只删除 `http_proxy`，未同步清理 `global_http_proxy_host`、`global_http_proxy_port`、排除列表和 PAC 键；部分网络栈或已启动进程仍可能继续使用残留值。

## 当前处置

- 本轮操作抓包已完成，Flow 和 logcat 已归档到本地 `captures/`。
- mitmproxy、logcat 监听与 `adb reverse` 已停止；项目实例的全部 global proxy 分项已手工清理。
- 后续若再次启用代理，关闭时仍需完整删除 host、port、exclusion list 与 PAC，并重启 App 进程，不能只删除 `http_proxy`。
- 已将游客注册复现为 `client/guest.py`，Docker 部署由 FastAPI lifespan 经项目专属 egress 校验或创建游客，凭据原子写入私有 token 文件。
- ali-cloud 部署的 egress 已从无效的 self-server 动态 SOCKS 路径改为 NAS SSH exec relay；sidecar 仅在 Compose 私网监听并只允许 80/443。

## 脱敏说明

- 报告、结构化 findings 和摘要证据均未保存游客账号、token、设备标识及正文内容。
- 原始 `mitmproxy_traffic.flow` 位于项目工作区并通过本地 Git exclude 排除；其中可能包含游客凭据，只用于本机复验，不进入 Git。

## 下一步

1. 修正 LDPlayer `proxy-off` 的完整清理逻辑，并清理模板残留代理状态。
2. 搜索、全站书目分页、免费章边界和 2.9.362 新响应解密结论见 `analysis/app-workflow/`。
3. 游客 bootstrap 已恢复；后续只有新 App 版本改变注册字段、签名或响应 key 时再定向复核。
4. 下载格式能力不再作为本轮逆向目标。
