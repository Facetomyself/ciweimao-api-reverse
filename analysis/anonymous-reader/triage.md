# Triage — App 游客正文加载

## 状态速览

| 深度等级 | 已完成 | 部分完成 | 阻滞 | 未开始 |
|----------|--------|----------|------|--------|
| L1（便携） | APK 指纹 | 壳后业务代码未导出 | 0 | 定向静态分析 |
| L2（上下文） | 游客身份、章节权限、代理 A/B、搜索与全站链 | 0 | 0 | 0 |
| L3（运行时） | 抓包归档、Native crypto 定向静态 | 0 | 0 | Frida / whole-DEX 按需取证 |
| L4（triage） | 360 加固路由确认 | 0 | 0 | 0 |

## 已解决

### R-001：正文永久加载

- **原因**：App 进程使用 `127.0.0.1:8083` 代理，但实例没有对应 `adb reverse` 和 mitmproxy 监听。
- **验证**：章节 API 成功、CDN 请求 `ECONNREFUSED`；补齐代理链后 CDN HTTP 200 且正文渲染。
- **当前状态**：已恢复并完成抓包；监听、`adb reverse` 和项目实例 proxy 分项均已清理。

## 环境风险

### G-001：proxy-off 清理不完整

- **缺陷**：`tools/ldplayer/ldplayer.ps1` 当前只删除 `http_proxy`。
- **影响**：模板或项目实例仍可能保留 `global_http_proxy_host/port`，新进程继续走死代理。
- **建议**：同步删除 host、port、exclusion list、PAC URL，并增加关闭后断言；随后清理模板状态。

## 待验证假设

### H-001：游客注册与正式账号使用不同加密/签名分支

- **依据**：公开项目记录游客注册存在特殊加密；当前 App 已自动创建游客身份。
- **验证方法**：后续 whole-DEX dump 或运行时 Hook，对比游客 bootstrap 与正式登录请求构造。
- **影响**：决定客户端是否能独立复现游客身份初始化，而不依赖 App 预生成 token。

## 后续深挖

1. 搜索、全站枚举、免费边界与当前响应解密已转入 `analysis/app-workflow/` 并完成。
2. 只有需要恢复游客 bootstrap、正式登录或把 Native API 纳入 mitmproxy 时，再做 whole-DEX / Frida 定向取证。
3. TXT、EPUB 与本地缓存格式不再列为本轮待办。
