# App 2.9.365 协议冻结说明

冻结日期：2026-08-27。正文接口 `310017` 仍未过，本文件只记录已经闭合的事实，不再当作进行中的实验草稿。

详细 canary 与排除项见 [analysis/app-version-2.9.365/analysis-progress.md](../analysis/app-version-2.9.365/analysis-progress.md)、[report.md](../analysis/app-version-2.9.365/report.md)。

## 签名

官方原签 APK 的 HMAC key 来自 `GetInfo`：`PackageInfo.signatures[0].toCharsString()` 再 `Md5Encode`，不是 `.so` 字面量。运行时值为：

```text
a90f3731745f1c30ee77cb13fc00005a
```

suffix 以 live `p` 为准，字面 `CkMxWNB666`。游客注册 JSON 无 `account` 时，HMAC 占位 `cmw666`。

```text
source = account={urlenc}&app_version={ver}&rand_str={rand}&signatures={certMD5}CkMxWNB666
p      = Base64(HMAC-SHA256(key=certMD5, msg=source))
```

`test_client.py` fixture（`书客1234567` / `2.9.362` / `10072263a65a4345`）得到 `RTemA7/IKa4GppnByNkaz0tVeAk1Cn8LnSM5NZ993Qc=`。`HMAC(MD5(source))` 与 suffix=`MD5("CkMxWNB666")` 均不匹配该 fixture。

响应：Base64 → AES-256-CBC，key 先 SHA-256，IV 16 字节全零，PKCS#7。`mode=1` 走 2.9.352+ current key，否则 legacy。

## Native 注册通路

```text
AutoRegTask.doHttpRequest
  uuid = Installation.id = "android" + UUID（files/INSTALLATION）
  gender / channel / oauth_*
  → BaseTaskNew.getC(17, map)
       setCommonParams：未登录不加 account/login_token
                         加 app_version、device_token
                         URLEncoder.encode 每个值
       → NetUtils.track(ctx, 17, json, UrlConstants.getUserType())
            CenterDataAPI::GetInfo（一次）
            CenterDataAPI::post1          # 表单 + rand_str + p
            host(userType) + getAddr(17)
            CenterDataAPI::postHttpsRequest
```

`getAddr` 表 `dword_527DC[apiId-2]`（`libcwmhttps.so` SHA-256 `428d5f646236fe24ad2eef11b2ec2e54f5141bcf70af9e3bb6684644827036eb`）：

| apiId | 路径 |
|-------|------|
| 17 | `signup/auto_reg_v2` |
| 154 | `signup/save_reader_oaid` |
| 259 | `chapter/get_cpt_ifm` |

首次游客 `getUserType()=2` → `https://app1.hbooker.com/`。`userType=1` → `https://app1.happybooker.cn/`。

`getHead0` UA：

```text
Android  com.kuangxiangciweimao.novel.c  {versionName}, {brand}, {model}, {sdk}, {release}
```

Pixel 6 实测：`Android  com.kuangxiangciweimao.novel.c  2.9.365, google, Pixel 6, 35, 15`。

`postHttpsRequest` slist：`Content-Type: application/x-www-form-urlencoded`、`charsets: utf-8`、`Expect:`、上述 UA。`CURLOPT_HTTP_VERSION=3`；APK `libcurl/7.56.1` 无 nghttp2，setopt 返回 `CURLE_UNSUPPORTED_PROTOCOL`，协商 HTTP/1.1，与官方 pcap ALPN 一致。

注册成功后 `SendImeiTask.getC(154)` 上报 OAID / `am=MD5(ANDROID_ID)`。空 OAID 时接口可返回 `400000`，官方游客仍能读章。

## 310017 已排除

下列单项均不能把独立客户端的 `get_cpt_ifm` 从 `310017` 打成 `100000`：

- HMAC / AES 换代
- APK 版本字符串（Wandoujia 当前仍是 2.9.365）
- 缺 `send_client_info`、主机切换、冷启动 prelude
- 前缀 UA 或完整 `getHead0` UA
- `charsets` / `Expect`
- `CURLOPT_HTTP_VERSION=3`（实际未协商到 HTTP/2）
- 官方 JA3（Pixel 上 APK libcurl 注册 `100000`，正文仍 `310017`）
- `auto_reg_v2` 缺字段；补 `save_reader_oaid`
- 官方 extras + 导流章 `106129841`

官方游客完整链（`pm clear` 后）`get_cpt_ifm=100000`，不进极验。被拦身份的 310017 回包只有 `code`+`tip`；GT3 API1 可给出 `gt`/`challenge`。残留系统代理会造成「真机无法加载」，与该业务码无关。

证据索引：[evidence/](../analysis/app-version-2.9.365/evidence/)，传输三项 canary 为 `pixel-native-headers-canary.json`。
