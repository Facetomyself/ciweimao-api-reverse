# Triage — 登录与匿名免费章节

## 状态速览

| 能力 | 状态 |
|------|------|
| App API 匿名读取 | 已否定 |
| Web 匿名免费章 | 技术路线已确认，决定不实施 |
| 账号密码 endpoint | 已确认存在 |
| 真实账号密码登录 | 已确认要求验证码 |
| GEETEST challenge 协议 | 决定不继续分析 |
| App 登录后提取 token | 当前稳定主路径 |

## 决策性遗留

### D-001：不接入账号密码登录

- 状态：`won't implement`
- 依据：真实账号密码登录已确认触发验证码；自动登录会引入动态 challenge、风控状态和额外维护成本。
- 当前方案：用户在官方 App 内完成人工登录，再运行 `python -m client token-extract`。
- 重启条件：只有在 token 提取路径失效，且用户明确要求恢复验证码登录协议时重新评估。

### D-002：不实现匿名 Web 免费章 Provider

- 状态：`won't implement`
- 依据：公开 Web 路线只能补充免费内容，无法替代书架、已购章和下架书的 Token API 能力，收益不足。
- 当前方案：项目继续聚焦账号书架内容备份。
- 重启条件：只有在项目目标扩展为匿名公开内容下载时重新评估。

## 当前认证流程

```text
官方 App 人工登录并完成验证码
  -> ADB/root 读取 App 私有 shared_prefs
  -> token-extract 写入本地 tokens.json
  -> Token API 下载书架、已购章节和仍有权限的下架书
```

## 未解决但不阻塞

- `login_token` 仍会过期，需要重新执行 App 登录和 token 提取。
- 当前未恢复 GEETEST 版本、challenge 字段和验证协议；这是明确的范围外事项，不是待办。
