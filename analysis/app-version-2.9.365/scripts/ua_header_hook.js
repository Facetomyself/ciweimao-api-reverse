// Native-only. Logs User-Agent and request path, never POST bodies.
const CURLOPT_URL = 10002;
const CURLOPT_USERAGENT = 10018;

function hookCurl(mod) {
    const setopt = mod.findExportByName("curl_easy_setopt");
    if (!setopt) {
        send({ type: "error", message: "curl_easy_setopt missing in " + mod.name });
        return;
    }
    Interceptor.attach(setopt, {
        onEnter(args) {
            const option = args[1].toInt32();
            if (option === CURLOPT_USERAGENT && !args[2].isNull()) {
                send({ type: "ua", value: args[2].readCString() });
            }
            if (option === CURLOPT_URL && !args[2].isNull()) {
                const url = args[2].readCString() || "";
                const path = url.replace(/^https?:\/\/[^/]+/i, "");
                send({ type: "url", path: path.split("?")[0] });
            }
        }
    });
    send({ type: "ready", module: mod.name, base: mod.base.toString() });
}

function hookNowOrOnLoad(moduleName) {
    const existing = Process.findModuleByName(moduleName);
    if (existing) {
        hookCurl(existing);
        return;
    }
    const dlopen = Module.findGlobalExportByName("android_dlopen_ext")
        || Module.findGlobalExportByName("dlopen");
    if (dlopen === null) {
        send({ type: "error", message: "dlopen export not found" });
        return;
    }
    Interceptor.attach(dlopen, {
        onEnter(args) {
            this.path = args[0].readCString();
            this.shouldHook = this.path && this.path.indexOf(moduleName) !== -1;
        },
        onLeave(retval) {
            if (!this.shouldHook || retval.isNull()) return;
            const mod = Process.findModuleByName(moduleName);
            if (mod) hookCurl(mod);
        }
    });
}

hookNowOrOnLoad("libcurl.so");
hookNowOrOnLoad("libcurl.so.4");
hookNowOrOnLoad("libcwmhttps.so");
