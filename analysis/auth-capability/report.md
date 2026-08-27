# 刺猬猫登录与匿名免费章节能力分析

## 基本信息

| 项目 | 值 |
|------|-----|
| 目标 | `ciweimao-api-reverse` 认证与免费章节访问链 |
| 类型 | HTTP API + Web SSR |
| 分析时间 | 2026-07-12 |
| 分析深度 | L2（源码与最小在线请求） |

## 执行摘要

1. App API 不能通过省略或置空 `login_token/account` 匿名读取书籍详情、分卷和正文；实测详情与分卷均返回 `code=200001`、`缺少登录必需参数`。
2. 免费章节可以不登录抓取，但需要改走公开 Web 页面。该路线技术上成立，不过与本项目“备份书架内已购及下架内容”的目标重合度低，决定暂不实现。
3. App 账号密码登录接口仍在线：`POST /signup/login`，核心参数为 `login_name`、`passwd`、`device_token`、`app_version`。开源客户端源码与当前服务端参数校验共同证明该接口仍被识别。
4. 用户已使用真实账号密码验证：登录接口会要求验证码。账号密码登录不能作为稳定无人值守能力，本项目暂不继续恢复或接入验证码链。
5. 当前稳定认证路径保持不变：在官方 App 内完成人工登录，再通过 `token-extract` 提取 `login_token/account/device_token`。

## 证据

### F-001：App API 强制登录参数

- 本地代码：`client/api.py` 的所有 App 请求默认附加认证参数。
- 在线请求（2026-07-12）：使用空 `login_token/account` 请求：
  - `/book/get_info_by_id?book_id=100085206` -> HTTP 200，业务码 `200001`。
  - `/book/get_division_list?book_id=100085206` -> HTTP 200，业务码 `200001`。
- 结论：不能仅靠空 token 绕过 App API 登录。
- 置信度：high。

### F-002：公开 Web 链可匿名读取免费内容

- `https://www.ciweimao.com/`：匿名 HTTP 200，可提取当前书籍 ID。
- 当前样本书 `100450318` 的 `www` 书籍页：匿名 HTTP 200，可提取章节 ID。
- `https://wap.ciweimao.com/chapter/113781989`：匿名 HTTP 200。
- `https://mip.ciweimao.com/chapter/113781989`：匿名 HTTP 200，HTML 约 15 KB，页面纯文本约 2.5K，未出现登录拦截标记。
- 外部交叉证据：`404-novel-project/novel-downloader` 的刺猬猫站点说明标注“免费章节可直接阅读，VIP 章节需要有效 Cookie”。
- 结论：匿名免费章节 Provider 可行，但需要解析 Web 页面并识别免费/VIP 状态，不能复用 App 正文接口。
- 置信度：high（具体解析 selector 仍需 fixture 固化）。

### F-003：账号密码登录接口仍存在

- 本地实现：`client/auth.py::AuthManager.login()` 使用 `/signup/login`，参数 `login_name`、`passwd`、`device_token`、`app_version`。
- GitHub 源码：`NateScarlet/ciweimao/pkg/client/login.go` 使用同一 endpoint 和 `passwd` 参数。
- 当前在线探测：合法邮箱形态的虚构账号请求返回 `code=280001`、`登录失败,请稍后再试`，而非 endpoint 不存在或参数缺失。
- 注意：`zsakvo/Ciweimao-Raycast/src/api.ts` 使用 `password` 字段，与其 README 的 `passwd` 不一致，不应照抄。
- 结论：协议入口仍在线；能否成功登录取决于真实凭据和风控状态。
- 置信度：high（接口存在）/ medium（成功登录能力）。

### F-004：账号密码登录已确认受验证码保护

- `Cirno-go`、`pineapple-backups` 和 `HedgehogCatAppNovelDownload` 均记录：正确账号密码也可能因频次、IP 或风险状态触发 GEETEST，推荐从 App 获取 token。
- 用户随后使用真实账号密码手动验证，确认登录接口返回验证码要求。
- 本轮未继续采集 challenge 数据，不确认具体 GEETEST 版本、字段或验证协议。
- 结论：不把账号密码登录作为 token 刷新器，也不继续强化验证码处理能力。
- 置信度：high（需要验证码）；验证码协议细节未分析。

## 最终决策

```text
TokenApiProvider
  login_token/account -> 书架、已购章、下架书 fallback

CredentialBootstrap
  官方 App 人工登录并完成验证码
  token-extract -> tokens.json
```

### 暂不实施

- 不实现匿名 Web 免费章节 Provider：该能力只能覆盖公开免费内容，对书架备份、已购章和下架书帮助有限。
- 不新增账号密码登录 CLI，也不实现 GEETEST challenge 处理或自动解题链。
- `client/auth.py` 中现有密码登录代码保留为协议参考，不在 README 中宣传为可用登录方式。

## GitHub 证据

| 项目 | Stars | 证据价值 |
|------|------:|----------|
| `AlexiaAshford/pineapple-backups` | 100 | 记录 GEETEST、token 优先策略，MIT |
| `zsakvo/Cirno-go` | 64 | 旧登录能力被划掉，记录验证码阻塞 |
| `NateScarlet/ciweimao` | 6 | `/signup/login` 与 `passwd` 的直接源码证据 |
| `zsakvo/Ciweimao-Raycast` | 4 | 登录 curl 与章节 App API 调用示例；代码字段存在不一致 |

## 脱敏说明

在线登录探测仅使用虚构账号和无效密码。未记录或提交真实 token、账号、密码、Cookie、设备唯一标识及章节正文。
