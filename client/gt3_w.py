"""GT3 fullpage bind：HTTP 三枪、``w`` 打包、Node 黑盒出参。

官方 App 是 ``GT3GeetestUtils`` WebView（``setPattern(1)``），不是滑块。
本模块把同一条 gettype → get → ajax 收到 Python。``w`` 的主路：

- 本机 Node 跑官方 ``gt.js`` / ``initGeetest``，读 ``getValidate()``（黑盒，不依赖 RuyiDOM）
- 可选 RuyiDOM（``prefer=ruyidom``）
- AES-CBC 字典 + RSA 包 key（公开 packing；fullpage 9.2.0 仍 ``error_03``）

默认 ``bind()`` 仍是 ``Gt3BindNotReady``。验收只认独立会话
``get_cpt_ifm=100000``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
import urllib.request

from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad

from . import gt3


GEETEST_RSA_N = (
    "00C1E3934D1614465B33053E7F48EE4EC87B14B95EF88947713D25EECBFF7E74C7"
    "977D02DC1D9451F79DD5D1C10C29ACB6A9B4D6FB7D0A0279B6719E1772565F09AF"
    "627715919221AEF91899CAE08C0D686D748B20A3603BE2318CA6BC2B59706592A9"
    "219D0BF05C9F65023A21D2330807252AE0066D59CEEFA5F2748EA80BAB81"
)
GEETEST_RSA_E = "010001"
GEETEST_B64_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789()"
)
DEFAULT_API_HOSTS = (
    "https://api.geetest.com",
    "https://api.geevisit.com",
)
DEFAULT_GT_JS = "https://static.geetest.com/static/tools/gt.js"
DEFAULT_CLIENT_TYPE = "native"
DEFAULT_LANG = "zh-cn"
NATIVE_UA = (
    "Mozilla/5.0 (Linux; Android 15; Pixel 6 Build/AP3A.241005.015) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/124.0.0.0 "
    "Mobile Safari/537.36"
)
AES_IV = b"0000000000000000"
_CLIENT_DIR = Path(__file__).resolve().parent
NODE_BIND_JS = _CLIENT_DIR / "gt3_node_bind.mjs"
NODE_EXE = Path(r"D:\reverse_ENV\tools\node\node.exe")
RUYIDOM_BIND_JS = _CLIENT_DIR / "gt3_ruyidom_bind.js"
RUYIDOM_PS1 = Path(r"D:\reverse_ENV\tools\ruyidom\run.ps1")
POWERSHELL = Path(
    os.environ.get("SystemRoot", r"C:\Windows")
) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
PROVIDER_NAMES = ("node", "ruyidom", "aes-rsa")


def provider_order(prefer: str) -> tuple[str, ...]:
    """Default stamp is Node-only. RuyiDOM is opt-in, not a fallback."""
    name = str(prefer or "node")
    if name == "node-then-ruyidom":
        return ("node", "ruyidom")
    if name in PROVIDER_NAMES:
        return (name,)
    raise Gt3WError(f"prefer-{name}")


class Gt3WError(gt3.Gt3Error):
    """gettype/get/ajax 或 ``w`` 出参失败。"""


@dataclass(frozen=True, repr=False)
class GeetestPlane:
    """一次 gettype/get/ajax 的脱敏形状。不含 gt/challenge/w/validate 原文。"""

    host: str
    path: str
    query_keys: tuple[str, ...]
    http_code: int
    ok: bool
    resp_len: int
    resp_class: str
    shape: dict = field(default_factory=dict)
    label: str = ""
    error: str = ""


def geetest_b64_encode(data: bytes) -> str:
    """GeeTest 6-bit 字母表，``+/`` 换成 ``()``，无 padding。"""
    alphabet = GEETEST_B64_ALPHABET
    out: list[str] = []
    n = len(data)
    i = 0
    while i < n:
        b1 = data[i]
        out.append(alphabet[b1 >> 2])
        if i + 1 < n:
            b2 = data[i + 1]
            out.append(alphabet[((b1 & 3) << 4) | (b2 >> 4)])
            if i + 2 < n:
                b3 = data[i + 2]
                out.append(alphabet[((b2 & 15) << 2) | (b3 >> 6)])
                out.append(alphabet[b3 & 63])
            else:
                out.append(alphabet[(b2 & 15) << 2])
        else:
            out.append(alphabet[(b1 & 3) << 4])
        i += 3
    return "".join(out)


def random_aes_key() -> str:
    return secrets.token_hex(8)


def rsa_encrypt_aes_key_bytes(aes_key: str) -> bytes:
    """PKCS#1 v1.5，1024-bit，密文 128 字节。"""
    key = RSA.construct((int(GEETEST_RSA_N, 16), int(GEETEST_RSA_E, 16)))
    cipher = PKCS1_v1_5.new(key)
    return cipher.encrypt(aes_key.encode("ascii"))


def rsa_encrypt_aes_key(aes_key: str) -> str:
    """PKCS#1 v1.5，输出 256 hex。padding 随机，同一明文每次不同。"""
    return rsa_encrypt_aes_key_bytes(aes_key).hex()


def aes_cbc_encrypt(plaintext: str, aes_key: str) -> bytes:
    if len(aes_key) != 16:
        raise Gt3WError("aes-key-len")
    cipher = AES.new(aes_key.encode("ascii"), AES.MODE_CBC, AES_IV)
    return cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))


PACK_MODES = ("b64-hex", "b64-b64", "b64-concat")


def pack_w(plaintext: str, *, aes_key: str | None = None,
           mode: str = "b64-hex") -> str:
    """打包 ``w``。9.2.0 官方外形是整串 GeeTest 字母表，末尾不是 hex。"""
    if mode not in PACK_MODES:
        raise Gt3WError(f"pack-mode-{mode}")
    key = aes_key or random_aes_key()
    aes_ct = aes_cbc_encrypt(plaintext, key)
    rsa_ct = rsa_encrypt_aes_key_bytes(key)
    if mode == "b64-hex":
        return geetest_b64_encode(aes_ct) + rsa_ct.hex()
    if mode == "b64-b64":
        return geetest_b64_encode(aes_ct) + geetest_b64_encode(rsa_ct)
    return geetest_b64_encode(aes_ct + rsa_ct)


def w_public_shape(value: str) -> dict:
    return {
        "len": len(value),
        "rsa_hex_len": 256 if len(value) >= 256 else 0,
        "body_len": max(0, len(value) - 256),
        "alphabet_ok": all(ch in GEETEST_B64_ALPHABET for ch in value[:-256])
        if len(value) >= 256 else False,
        "rsa_hex_ok": all(ch in "0123456789abcdef" for ch in value[-256:].lower())
        if len(value) >= 256 else False,
    }


def fullpage_ajax_plaintext(
    api1: gt3.Api1Result,
    *,
    passtime: int = 520,
    client_type: str = DEFAULT_CLIENT_TYPE,
) -> str:
    """fullpage ajax 字典。字段名公开；这不是已对齐的官方 fixture。"""
    rp = hashlib.md5(
        f"{api1.gt}{api1.challenge[:32]}{passtime}".encode("utf-8")
    ).hexdigest()
    payload = {
        "lang": DEFAULT_LANG,
        "type": "fullpage",
        "offline": False,
        "new_captcha": True,
        "product": "bind",
        "https": True,
        "protocol": "https://",
        "gt": api1.gt,
        "challenge": api1.challenge,
        "client_type": client_type,
        "passtime": int(passtime),
        "ep": {"v": "3.3.0", "te": False, "me": True},
        "rp": rp,
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _resp_class(raw: str) -> str:
    stripped = raw.strip()
    if stripped.startswith("geetest_"):
        return "jsonp"
    if stripped.startswith("{"):
        return "json"
    return "other"


def geetest_request(
    host: str,
    path: str,
    query: dict,
    *,
    method: str = "GET",
    body: dict | None = None,
    user_agent: str = NATIVE_UA,
    timeout: float = 12,
) -> GeetestPlane:
    query_keys = tuple(sorted(query))
    rec = {
        "host": host.split("://", 1)[-1],
        "path": path,
        "query_keys": query_keys,
        "http_code": 0,
        "ok": False,
        "resp_len": 0,
        "resp_class": "empty",
        "shape": {},
        "label": "",
        "error": "",
    }
    url = f"{host.rstrip('/')}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    headers = {"Accept": "*/*", "User-Agent": user_agent}
    data = None
    if method.upper() == "POST":
        payload = body if body is not None else {}
        data = urlencode(payload).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    raw = ""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            rec["http_code"] = int(resp.status)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        rec["http_code"] = int(exc.code)
        rec["error"] = "http-error"
    except URLError as exc:
        rec["error"] = type(exc.reason).__name__ if exc.reason else "URLError"
        return GeetestPlane(**rec)
    except Exception as exc:
        rec["error"] = type(exc).__name__
        return GeetestPlane(**rec)
    rec["ok"] = rec["http_code"] == 200
    rec["resp_len"] = len(raw)
    rec["resp_class"] = _resp_class(raw)
    try:
        parsed = gt3.parse_geetest_jsonp(raw)
        rec["shape"] = gt3.public_json_shape(parsed)
        rec["label"] = gt3.ajax_result_label(parsed) if path.endswith("ajax.php") else (
            str((parsed.get("data") or {}).get("type") or parsed.get("status") or "")
            if isinstance(parsed, dict) else ""
        )
        rec["_parsed"] = parsed
    except Exception as exc:
        rec["error"] = rec["error"] or type(exc).__name__
    return GeetestPlane(
        host=rec["host"],
        path=rec["path"],
        query_keys=query_keys,
        http_code=rec["http_code"],
        ok=rec["ok"],
        resp_len=rec["resp_len"],
        resp_class=rec["resp_class"],
        shape=rec["shape"],
        label=rec["label"],
        error=rec["error"],
    )


def _plane_parsed(plane: GeetestPlane) -> Any:
    return getattr(plane, "_parsed", None)


def attach_parsed(plane: GeetestPlane, parsed: Any) -> GeetestPlane:
    object.__setattr__(plane, "_parsed", parsed)
    return plane


def geetest_get(host: str, path: str, query: dict, **kwargs) -> GeetestPlane:
    plane = geetest_request(host, path, query, method="GET", **kwargs)
    if plane.ok:
        try:
            raw_host = host
            url = f"{raw_host.rstrip('/')}{path}?{urlencode(query)}"
            req = urllib.request.Request(
                url,
                headers={"Accept": "*/*", "User-Agent": kwargs.get("user_agent", NATIVE_UA)},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=kwargs.get("timeout", 12)) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            attach_parsed(plane, gt3.parse_geetest_jsonp(raw))
        except Exception:
            pass
    return plane


def fetch_jsonp(host: str, path: str, query: dict, **kwargs) -> tuple[GeetestPlane, Any]:
    query_keys = tuple(sorted(query))
    url = f"{host.rstrip('/')}{path}?{urlencode(query)}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "*/*", "User-Agent": kwargs.get("user_agent", NATIVE_UA)},
        method="GET",
    )
    rec: dict[str, Any] = {
        "host": host.split("://", 1)[-1],
        "path": path,
        "query_keys": query_keys,
        "http_code": 0,
        "ok": False,
        "resp_len": 0,
        "resp_class": "empty",
        "shape": {},
        "label": "",
        "error": "",
    }
    raw = ""
    parsed: Any = None
    try:
        with urllib.request.urlopen(req, timeout=kwargs.get("timeout", 12)) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            rec["http_code"] = int(resp.status)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        rec["http_code"] = int(exc.code)
        rec["error"] = "http-error"
    except URLError as exc:
        rec["error"] = type(exc.reason).__name__ if exc.reason else "URLError"
        return GeetestPlane(**rec), None
    except Exception as exc:
        rec["error"] = type(exc).__name__
        return GeetestPlane(**rec), None
    rec["ok"] = rec["http_code"] == 200
    rec["resp_len"] = len(raw)
    rec["resp_class"] = _resp_class(raw)
    try:
        parsed = gt3.parse_geetest_jsonp(raw)
        rec["shape"] = gt3.public_json_shape(parsed)
        if path.endswith("ajax.php"):
            rec["label"] = gt3.ajax_result_label(parsed)
        elif isinstance(parsed, dict):
            nested = parsed.get("data") if isinstance(parsed.get("data"), dict) else {}
            rec["label"] = str(nested.get("type") or parsed.get("status") or "")
    except Exception as exc:
        rec["error"] = rec["error"] or type(exc).__name__
    plane = GeetestPlane(**rec)
    attach_parsed(plane, parsed)
    return plane, parsed


def callback_name(now_ms: int | None = None) -> str:
    stamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    return f"geetest_{stamp}"


def gettype_query(api1: gt3.Api1Result, *, now_ms: int | None = None) -> dict:
    return {"gt": api1.gt, "callback": callback_name(now_ms)}


def getphp_query(
    api1: gt3.Api1Result,
    *,
    client_type: str = DEFAULT_CLIENT_TYPE,
    now_ms: int | None = None,
) -> dict:
    return {
        "gt": api1.gt,
        "challenge": api1.challenge,
        "lang": DEFAULT_LANG,
        "pt": "0",
        "client_type": client_type,
        "callback": callback_name(now_ms),
    }


def ajax_query(
    api1: gt3.Api1Result,
    w_value: str,
    *,
    client_type: str = DEFAULT_CLIENT_TYPE,
    now_ms: int | None = None,
) -> dict:
    return {
        "gt": api1.gt,
        "challenge": api1.challenge,
        "lang": DEFAULT_LANG,
        "pt": "0",
        "client_type": client_type,
        "w": w_value,
        "callback": callback_name(now_ms),
    }


def pick_api_host(*datas: dict | None) -> str:
    for data in datas:
        if not isinstance(data, dict):
            continue
        nested = data.get("data") if isinstance(data.get("data"), dict) else data
        server = str(nested.get("api_server") or "")
        if server:
            if server.startswith("http"):
                return server.rstrip("/")
            return f"https://{server.rstrip('/')}"
    return DEFAULT_API_HOSTS[0]


def static_host(gettype_data: dict | None) -> str:
    host = "https://static.geetest.com"
    if not isinstance(gettype_data, dict):
        return host
    nested = gettype_data.get("data")
    if not isinstance(nested, dict):
        return host
    servers = nested.get("static_servers")
    if isinstance(servers, list) and servers:
        first = str(servers[0])
        host = first if first.startswith("http") else f"https://{first.rstrip('/')}"
    return host.rstrip("/")


def static_asset_url(gettype_data: dict | None, name: str, default: str) -> str:
    if not isinstance(gettype_data, dict):
        return default
    nested = gettype_data.get("data")
    if not isinstance(nested, dict):
        return default
    path = str(nested.get(name) or "")
    if path:
        return f"{static_host(gettype_data)}/{path.lstrip('/')}"
    return default


def gt_loader_url(gettype_data: dict | None = None) -> str:
    """``data.geetest`` 是核心库，没有 ``initGeetest``。loader 固定 ``static/tools/gt.js``。"""
    return DEFAULT_GT_JS


def plane_public(plane: GeetestPlane) -> dict:
    return {
        "host": plane.host,
        "path": plane.path,
        "query_keys": list(plane.query_keys),
        "http_code": plane.http_code,
        "ok": plane.ok,
        "resp_len": plane.resp_len,
        "resp_class": plane.resp_class,
        "label": plane.label,
        "error": plane.error or None,
        "shape": plane.shape,
    }


class AesRsaWProvider:
    """用公开 packing 打 ajax。字典未 sampleParity 时 ajax 可以失败。"""

    def __init__(
        self,
        *,
        api_host: str | None = None,
        client_type: str = DEFAULT_CLIENT_TYPE,
        user_agent: str = NATIVE_UA,
    ):
        self.api_host = api_host
        self.client_type = client_type
        self.user_agent = user_agent
        self.last_public: dict = {}

    def complete_bind(self, api1: gt3.Api1Result) -> gt3.Gt3Triple:
        if not api1.success:
            raise Gt3WError("api1-unsuccessful")
        host = self.api_host or DEFAULT_API_HOSTS[0]
        gettype_plane, gettype_data = fetch_jsonp(
            host, "/gettype.php", gettype_query(api1), user_agent=self.user_agent)
        get_plane, get_data = fetch_jsonp(
            host, "/get.php", getphp_query(api1, client_type=self.client_type),
            user_agent=self.user_agent)
        if self.api_host is None:
            host = pick_api_host(get_data, gettype_data)
        plaintext = fullpage_ajax_plaintext(api1, client_type=self.client_type)
        w_value = pack_w(plaintext)
        ajax_plane, ajax_data = fetch_jsonp(
            host, "/ajax.php", ajax_query(api1, w_value, client_type=self.client_type),
            user_agent=self.user_agent)
        self.last_public = {
            "origin": "aes-rsa",
            "api_host": host.split("://", 1)[-1],
            "client_type": self.client_type,
            "gettype": plane_public(gettype_plane),
            "get": plane_public(get_plane),
            "ajax": plane_public(ajax_plane),
            "w": w_public_shape(w_value),
            "plaintext_keys": sorted(json.loads(plaintext).keys()),
        }
        if not ajax_plane.ok:
            raise Gt3WError(f"ajax-http-{ajax_plane.http_code}")
        try:
            return gt3.triple_from_dialog(
                ajax_data if isinstance(ajax_data, dict) else {},
                fallback_challenge=api1.challenge,
            )
        except gt3.Gt3Error as exc:
            raise Gt3WError(
                f"ajax-no-validate:{ajax_plane.label or ajax_plane.error or 'empty'}"
            ) from exc


def _extract_json_line(stdout: str, *, label: str = "bind-no-json") -> dict:
    last = None
    for line in str(stdout or "").splitlines():
        text = line.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                last = json.loads(text)
            except json.JSONDecodeError:
                continue
    if not isinstance(last, dict):
        raise Gt3WError(label)
    return last


class RuyiDomWProvider:
    """官方 gt.js 黑盒：``initGeetest`` + ``verify`` + ``getValidate()``。"""

    def __init__(
        self,
        *,
        script: Path | None = None,
        timeout_seconds: int = 90,
        api_host: str | None = None,
        user_agent: str = NATIVE_UA,
    ):
        self.script = Path(script) if script else RUYIDOM_BIND_JS
        self.timeout_seconds = int(timeout_seconds)
        self.api_host = api_host
        self.user_agent = user_agent
        self.last_public: dict = {}

    def complete_bind(self, api1: gt3.Api1Result) -> gt3.Gt3Triple:
        if not api1.success:
            raise Gt3WError("api1-unsuccessful")
        if not self.script.is_file():
            raise Gt3WError("ruyidom-script-missing")
        if not RUYIDOM_PS1.is_file():
            raise Gt3WError("ruyidom-cli-missing")
        host = self.api_host or DEFAULT_API_HOSTS[0]
        gettype_plane, gettype_data = fetch_jsonp(
            host, "/gettype.php", gettype_query(api1), user_agent=self.user_agent)
        if gettype_plane.ok and self.api_host is None:
            host = pick_api_host(gettype_data)
        gt_js = gt_loader_url(gettype_data)
        payload = {
            "gt": api1.gt,
            "challenge": api1.challenge,
            "new_captcha": bool(api1.new_captcha),
            "api_server": host.split("://", 1)[-1],
            "gt_js_url": gt_js,
            "product": "bind",
            "lang": DEFAULT_LANG,
        }
        with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            input_path = handle.name
        cmd = [
            str(POWERSHELL),
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", str(RUYIDOM_PS1),
            "-Script", str(self.script),
            "-InputFile", input_path,
            "-AllowNetwork",
            "-TimeoutSeconds", str(self.timeout_seconds),
        ]
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds + 30,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise Gt3WError("ruyidom-timeout") from exc
        finally:
            try:
                os.unlink(input_path)
            except OSError:
                pass
        stdout = completed.stdout or ""
        try:
            result = _extract_json_line(stdout, label="ruyidom-no-json")
        except Gt3WError:
            self.last_public = {
                "origin": "ruyidom",
                "ok": False,
                "exit_code": completed.returncode,
                "error": "ruyidom-no-json",
                "gettype": plane_public(gettype_plane),
                "gt_js_host": urlparse(gt_js).netloc,
            }
            raise
        public = {
            "origin": "ruyidom",
            "ok": bool(result.get("ok")),
            "exit_code": completed.returncode,
            "script_loaded": bool(result.get("script_loaded")),
            "ready": bool(result.get("ready")),
            "success": bool(result.get("success")),
            "error": result.get("error"),
            "gettype": plane_public(gettype_plane),
            "gt_js_path": "/".join(gt_js.split("/")[-2:]),
            "validate_len": result.get("validate_len") or 0,
            "challenge_len": result.get("challenge_len") or 0,
            "seccode_len": result.get("seccode_len") or 0,
            "w_shape": result.get("w_shape"),
        }
        self.last_public = public
        if not result.get("ok"):
            raise Gt3WError(f"ruyidom-fail:{result.get('error') or 'unknown'}")
        dialog = {
            "geetest_challenge": result.get("challenge") or api1.challenge,
            "geetest_validate": result.get("validate") or "",
            "geetest_seccode": result.get("seccode") or "",
        }
        return gt3.triple_from_dialog(dialog, fallback_challenge=api1.challenge)


def _js_bind_payload(api1: gt3.Api1Result, *, api_host: str | None,
                     user_agent: str) -> tuple[dict, GeetestPlane, str]:
    host = api_host or DEFAULT_API_HOSTS[0]
    gettype_plane, gettype_data = fetch_jsonp(
        host, "/gettype.php", gettype_query(api1), user_agent=user_agent)
    if gettype_plane.ok and api_host is None:
        host = pick_api_host(gettype_data)
    gt_js = gt_loader_url(gettype_data)
    payload = {
        "gt": api1.gt,
        "challenge": api1.challenge,
        "new_captcha": bool(api1.new_captcha),
        "api_server": host.split("://", 1)[-1],
        "gt_js_url": gt_js,
        "product": "bind",
        "lang": DEFAULT_LANG,
    }
    return payload, gettype_plane, gt_js


class NodeWProvider:
    """官方 gt.js 黑盒：本机 Node ``vm`` + JSONP 宿主，不依赖 RuyiDOM。"""

    def __init__(
        self,
        *,
        script: Path | None = None,
        node: Path | None = None,
        timeout_seconds: int = 90,
        api_host: str | None = None,
        user_agent: str = NATIVE_UA,
    ):
        self.script = Path(script) if script else NODE_BIND_JS
        self.node = Path(node) if node else NODE_EXE
        self.timeout_seconds = int(timeout_seconds)
        self.api_host = api_host
        self.user_agent = user_agent
        self.last_public: dict = {}

    def complete_bind(self, api1: gt3.Api1Result) -> gt3.Gt3Triple:
        if not api1.success:
            raise Gt3WError("api1-unsuccessful")
        if not self.script.is_file():
            raise Gt3WError("node-script-missing")
        if not self.node.is_file():
            raise Gt3WError("node-missing")
        payload, gettype_plane, gt_js = _js_bind_payload(
            api1, api_host=self.api_host, user_agent=self.user_agent)
        with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            input_path = handle.name
        env = os.environ.copy()
        env.pop("RUYIDOM_INPUT_JSON", None)
        env.pop("RUYIDOM_INPUT_FILE", None)
        cmd = [str(self.node), str(self.script), input_path]
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds + 30,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            stderr = str(exc.stderr or "")[-1500:]
            self.last_public = {
                "origin": "node",
                "ok": False,
                "error": "node-timeout",
                "stderr_tail": [
                    line for line in stderr.splitlines()
                    if line.startswith("[gt3-node]")
                ][-20:],
            }
            raise Gt3WError("node-timeout") from exc
        finally:
            try:
                os.unlink(input_path)
            except OSError:
                pass
        stdout = completed.stdout or ""
        try:
            result = _extract_json_line(stdout, label="node-no-json")
        except Gt3WError:
            self.last_public = {
                "origin": "node",
                "ok": False,
                "exit_code": completed.returncode,
                "error": "node-no-json",
                "gettype": plane_public(gettype_plane),
                "gt_js_host": urlparse(gt_js).netloc,
                "stderr_len": len(completed.stderr or ""),
            }
            raise
        public = {
            "origin": "node",
            "ok": bool(result.get("ok")),
            "exit_code": completed.returncode,
            "script_loaded": bool(result.get("script_loaded")),
            "ready": bool(result.get("ready")),
            "success": bool(result.get("success")),
            "error": result.get("error"),
            "gettype": plane_public(gettype_plane),
            "gt_js_path": "/".join(gt_js.split("/")[-2:]),
            "validate_len": result.get("validate_len") or 0,
            "challenge_len": result.get("challenge_len") or 0,
            "seccode_len": result.get("seccode_len") or 0,
            "w_shape": result.get("w_shape"),
            "loaded": result.get("loaded") or [],
            "ajax_seen": bool(result.get("ajax_seen")),
            "miss": result.get("miss") or [],
        }
        self.last_public = public
        if not result.get("ok"):
            raise Gt3WError(f"node-fail:{result.get('error') or 'unknown'}")
        dialog = {
            "geetest_challenge": result.get("challenge") or api1.challenge,
            "geetest_validate": result.get("validate") or "",
            "geetest_seccode": result.get("seccode") or "",
        }
        return gt3.triple_from_dialog(dialog, fallback_challenge=api1.challenge)


def _make_provider(name: str):
    if name == "node":
        return NodeWProvider()
    if name == "ruyidom":
        return RuyiDomWProvider()
    if name == "aes-rsa":
        return AesRsaWProvider()
    raise Gt3WError(f"provider-{name}")


class FullpageWProvider:
    """默认本机 Node 黑盒。RuyiDOM / AES+RSA 只在显式 ``prefer`` 时走。"""

    def __init__(self, *, prefer: str = "node"):
        self.prefer = prefer
        self.last_public: dict = {}
        self.origin = ""

    def complete_bind(self, api1: gt3.Api1Result) -> gt3.Gt3Triple:
        errors: list[str] = []
        attempts: list[dict] = []
        order = provider_order(self.prefer)
        for name in order:
            provider = _make_provider(name)
            try:
                triple = provider.complete_bind(api1)
                self.origin = name
                public = dict(provider.last_public)
                public["tried"] = list(order)
                public["attempts"] = attempts
                self.last_public = public
                return triple
            except gt3.Gt3Error as exc:
                errors.append(f"{name}:{exc}")
                attempts.append({
                    "origin": name,
                    "ok": False,
                    "error": str(exc)[:160],
                    "nested": getattr(provider, "last_public", {}),
                })
                self.last_public = {
                    "origin": name,
                    "ok": False,
                    "error": str(exc)[:160],
                    "tried": list(order),
                    "attempts": attempts,
                }
        raise Gt3WError(";".join(errors)[:240])
