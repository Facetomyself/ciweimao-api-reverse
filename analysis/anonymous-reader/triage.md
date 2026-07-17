# Triage — App 游客正文加载

## 状态速览

| 深度等级 | 已完成 | 部分完成 | 阻滞 | 未开始 |
|----------|--------|----------|------|--------|
| L1（便携） | APK 指纹 | 壳后业务代码未导出 | 0 | 定向静态分析 |
| L2（上下文） | 游客身份/bootstrap、章节权限、代理 A/B、搜索与全站链 | 0 | 0 | 0 |
| L3（运行时） | 抓包归档、Native crypto 定向静态 | 0 | 0 | Frida / whole-DEX 按需取证 |
| L4（triage） | 360 加固路由确认 | 0 | 0 | 0 |

## 已解决

### R-001：正文永久加载

- **原因**：App 进程使用 `127.0.0.1:8083` 代理，但实例没有对应 `adb reverse` 和 mitmproxy 监听。
- **验证**：章节 API 成功、CDN 请求 `ECONNREFUSED`；补齐代理链后 CDN HTTP 200 且正文渲染。
- **当前状态**：已恢复并完成抓包；监听、`adb reverse` 和项目实例 proxy 分项均已清理。

### R-002：游客 bootstrap 无法脱离 App

- **原因**：此前只持有 App 自动生成的游客 token，跨网络出口复制后返回 `320002`。
- **验证**：两次干净安装确认固定预注册签名占位符；纯 `curl_cffi` 注册、AES 解密和搜索均成功。
- **当前状态**：已恢复为服务启动前的自动校验/注册流程，凭据跟随 Compose egress 创建。

## 环境风险

### G-001：proxy-off 清理不完整

- **缺陷**：`tools/ldplayer/ldplayer.ps1` 当前只删除 `http_proxy`。
- **影响**：模板或项目实例仍可能保留 `global_http_proxy_host/port`，新进程继续走死代理。
- **建议**：同步删除 host、port、exclusion list、PAC URL，并增加关闭后断言；随后清理模板状态。

## 待验证假设

无。

## 后续深挖

1. 搜索、全站枚举、免费边界与当前响应解密已转入 `analysis/app-workflow/` 并完成。
2. 只有正式登录或新版本改变游客注册协议时，再做 whole-DEX / Frida 定向取证。
3. TXT、EPUB 与本地缓存格式不再列为本轮待办。
