# APK libcurl canary

用官方 APK 的 `libcurl.so` / `libssl.so` / `libcrypto.so` 在 Android 设备上 POST，对齐 native `postHttpsRequest` 的头与 HTTP 版本。so 本体不进 Git，从本机 apktool 输出或设备 `/data/app/.../lib/arm64` 取得。

```powershell
$clang = "D:\reverse_ENV\tools\android-ndk\toolchains\llvm\prebuilt\windows-x86_64\bin\aarch64-linux-android33-clang.cmd"
& $clang -O2 -fPIE -pie -o oldcurl_post oldcurl_post.c -ldl
python pixel_native_headers_canary.py
```

`oldcurl_post.c` 发送 `Content-Type`、`charsets: utf-8`、`Expect:`，并 `CURLOPT_HTTP_VERSION=3`。APK libcurl 7.56.1 无 nghttp2 时 setopt 失败，协商 HTTP/1.1。
