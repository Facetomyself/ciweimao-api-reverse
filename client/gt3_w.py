"""GT3 fullpage bind：HTTP 三枪与纯算 ``w``。

官方 App 是 ``GT3GeetestUtils`` WebView（``setPattern(1)``），不是滑块。
本模块把同一条 gettype → get → ajax 收到 Python。盖章运行时只有
fullpage 9.2.0 纯算：``get.php`` 的 ``w`` 登记 AES key（自定义 base64 + RSA hex），
``ajax.php`` 的 ``w`` 只用同一把 key 的自定义 base64。

``prefer=node`` / ``ruyidom`` / ``node-then-ruyidom`` 抛 ``blackbox-removed``。
默认 ``bind()`` 仍是 ``Gt3BindNotReady``。验收只认独立会话
``get_cpt_ifm=100000``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import secrets
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
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
GEETEST_B64_PAD = "."
# $_HCB 从 24-bit 组里按这些掩码抽 6 bit，顺序不是标准 base64。
GEETEST_B64_MASKS = (7274496, 9483264, 19220, 235)
DEFAULT_API_HOSTS = (
    "https://api.geetest.com",
    "https://api.geevisit.com",
)
DEFAULT_GT_JS = "https://static.geetest.com/static/tools/gt.js"
DEFAULT_CLIENT_TYPE = "native"
DEFAULT_LANG = "zh-cn"
# NATIVE_UA 含 Mobi，fullpage 把 client_type 设成 web_mobile，pt 设成 3。
FULLPAGE_CLIENT_TYPE = "web_mobile"
FULLPAGE_PT = "3"
GEETEST_REFERER = "https://www.geetest.com/demo/bind-app.html"
NATIVE_UA = (
    "Mozilla/5.0 (Linux; Android 15; Pixel 6 Build/AP3A.241005.015) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/124.0.0.0 "
    "Mobile Safari/537.36"
)
AES_IV = b"0000000000000000"
# fullpage.9.2.0-guwyxh 成功 bind 的稳定环境字段。
# tt 基底在送出前按 get.php 的 c/s 插入；s/h/hh/hi 是该环境指纹的 MD5。
FULLPAGE_TT = "M(*((1((M(("
FULLPAGE_S = "c7c3e21112fe4f741921cb3e4ff9f7cb"
FULLPAGE_H = "321f9af1e098233dbd03f250fd2b5e21"
FULLPAGE_HH = "39bd9cad9e425c3a8f51610fd506e3b3"
FULLPAGE_HI = "09eb21b3ae9542a9bc1e8b63b3d9a467"
# djb2 of the 9.2.0-guwyxh inner o/n sources plus "bbOy".
FULLPAGE_CAPTCHA_TOKEN = "112439067"
FULLPAGE_I = ("-1!!" * 73) + "-1"
FULLPAGE_TM_DELTAS = (
    ("a", 0), ("f", 4), ("g", 6), ("h", 10), ("i", 10), ("j", 18),
    ("l", 20), ("m", 40), ("n", 55), ("o", 56), ("p", 120), ("q", 130),
    ("r", 132), ("s", 180), ("t", 181), ("u", 190),
)
_REMOVED_PREFERS = frozenset({"node", "ruyidom", "node-then-ruyidom"})


def provider_order(prefer: str) -> tuple[str, ...]:
    """Stamp runtime is pure Python fullpage 9.2.0 w."""
    name = str(prefer or "aes-rsa")
    if name in _REMOVED_PREFERS:
        raise Gt3WError(f"blackbox-removed-{name}")
    if name == "aes-rsa":
        return ("aes-rsa",)
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


def geetest_b64_body_ok(value: str) -> bool:
    """字母表校验。末尾 ``.`` 是 $_HCB 的余数填充，不在 64 字符表里。"""
    body = value.rstrip(GEETEST_B64_PAD)
    return bool(body) and all(ch in GEETEST_B64_ALPHABET for ch in body)


def _geetest_b64_index(word: int, mask: int) -> int:
    """$_HBZ：从高位到低位，掩码为 1 的位拼进下标。"""
    index = 0
    for bit in range(23, -1, -1):
        if (mask >> bit) & 1:
            index = (index << 1) | ((word >> bit) & 1)
    return index


def geetest_b64_encode(data: bytes) -> str:
    """fullpage 9.2.0 ``$_HEJ``。余数 2 补 ``.``，余数 1 补 ``..``。"""
    alphabet = GEETEST_B64_ALPHABET
    out: list[str] = []
    n = len(data)
    i = 0
    while i < n:
        left = n - i
        if left >= 3:
            word = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2]
            masks = GEETEST_B64_MASKS
            pad = ""
        elif left == 2:
            word = (data[i] << 16) | (data[i + 1] << 8)
            masks = GEETEST_B64_MASKS[:3]
            pad = GEETEST_B64_PAD
        else:
            word = data[i] << 16
            masks = GEETEST_B64_MASKS[:2]
            pad = GEETEST_B64_PAD * 2
        out.extend(alphabet[_geetest_b64_index(word, mask)] for mask in masks)
        if pad:
            out.append(pad)
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


def tt_insert(track: str, c: list | None, s: str | None) -> str:
    """fullpage 9.2.0 把 get.php 的 ``c``/``s`` 插进轨迹，不插进 ``w``。"""
    if not track or not c or not s:
        return track
    try:
        scale = int(c[0])
        bias = int(c[2])
        shift = int(c[4])
    except (IndexError, TypeError, ValueError):
        return track
    out = track
    offset = 0
    width = len(track)
    while offset + 2 <= len(s):
        pair = s[offset:offset + 2]
        offset += 2
        try:
            value = int(pair, 16)
        except ValueError:
            break
        pos = (scale * value * value + bias * value + shift) % width
        out = out[:pos] + chr(value) + out[pos:]
    return out


def pack_registered_w(plaintext: str, *, aes_key: str) -> str:
    """``get.php`` ``w``：自定义 base64(AES) + RSA hex，用来登记 AES key。"""
    aes_ct = aes_cbc_encrypt(plaintext, aes_key)
    return geetest_b64_encode(aes_ct) + rsa_encrypt_aes_key(aes_key)


def pack_ajax_w(plaintext: str, *, aes_key: str) -> str:
    """``ajax.php`` ``w``：同一把 key 的自定义 base64(AES)，没有 RSA 尾。"""
    return geetest_b64_encode(aes_cbc_encrypt(plaintext, aes_key))


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
        "alphabet_ok": geetest_b64_body_ok(value[:-256])
        if len(value) >= 256 else False,
        "rsa_hex_ok": all(ch in "0123456789abcdef" for ch in value[-256:].lower())
        if len(value) >= 256 else False,
    }


def _js_value(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def fullpage_get_plaintext(api1: gt3.Api1Result, *, api_server: str) -> str:
    """``get.php`` 加密 JSON。字段顺序跟 9.2.0-guwyxh ``JSON.stringify`` 一致。"""
    host = str(api_server or "").split("://", 1)[-1].strip("/") or "api.geetest.com"
    payload = {
        "gt": api1.gt,
        "challenge": api1.challenge,
        "offline": False,
        "new_captcha": True,
        "product": "bind",
        "https": True,
        "api_server": host,
        "lang": DEFAULT_LANG,
        "width": "300px",
        "protocol": "https://",
        "type": "fullpage",
        "static_servers": ["static.geetest.com/", "static.geevisit.com/"],
        "click": "/static/js/click.3.1.2.js",
        "beeline": "/static/js/beeline.1.0.1.js",
        "voice": "/static/js/voice.1.2.6.js",
        "fullpage": "/static/js/fullpage.9.2.0-guwyxh.js",
        "slide": "/static/js/slide.7.9.3.js",
        "geetest": "/static/js/geetest.6.0.9.js",
        "aspect_radio": {"slide": 103, "click": 128, "voice": 128, "beeline": 50},
        "cc": 8,
        "ww": True,
        "i": FULLPAGE_I,
    }
    return _js_value(payload)


def fullpage_ep(now_ms: int) -> dict:
    base = int(now_ms)
    return {
        "v": "9.2.0-guwyxh",
        "te": False,
        "$_BBn": False,
        "ven": -1,
        "ren": -1,
        "fp": None,
        "lp": None,
        "em": {
            "ph": 1, "cp": 1, "ek": "11", "wd": 1, "nt": 1, "si": 0, "sc": 0,
        },
        "tm": {key: base + delta for key, delta in FULLPAGE_TM_DELTAS},
        "dnf": "dnf",
        "by": 2,
    }


def fullpage_ajax_plaintext(
    api1: gt3.Api1Result,
    *,
    passtime: int = 2200,
    client_type: str = DEFAULT_CLIENT_TYPE,
    c: list | None = None,
    s: str | None = None,
    now_ms: int | None = None,
) -> str:
    """手写 fullpage ajax 明文。``captcha_token`` 和 ``tsfq`` 不走 ``JSON.stringify``。"""
    del client_type  # 9.2.0 把它放在 query，不放进 ajax 明文
    stamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    spent = int(passtime)
    rp = hashlib.md5(
        f"{api1.gt}{api1.challenge}{spent}".encode("utf-8")
    ).hexdigest()
    fields = (
        ("lang", DEFAULT_LANG),
        ("type", "fullpage"),
        ("tt", tt_insert(FULLPAGE_TT, c, s) or -1),
        ("light", -1),
        ("s", FULLPAGE_S),
        ("h", FULLPAGE_H),
        ("hh", FULLPAGE_HH),
        ("hi", FULLPAGE_HI),
        ("vip_order", -1),
        ("ct", -1),
        ("ep", fullpage_ep(stamp - 300)),
        ("passtime", spent),
        ("rp", rp),
    )
    body = "".join(f'"{key}":{_js_value(value)},' for key, value in fields)
    return (
        "{"
        + body
        + f'"captcha_token":"{FULLPAGE_CAPTCHA_TOKEN}","tsfq":"xovrayel"}}'
    )


def challenge_cs(parsed: Any) -> tuple[list, str]:
    data = parsed.get("data") if isinstance(parsed, dict) else None
    source = data if isinstance(data, dict) else parsed if isinstance(parsed, dict) else {}
    raw_c = source.get("c")
    raw_s = source.get("s")
    c_value = raw_c if isinstance(raw_c, list) else []
    s_value = raw_s if isinstance(raw_s, str) else ""
    return c_value, s_value


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
    headers = {
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "User-Agent": user_agent,
        "Referer": GEETEST_REFERER,
    }
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
        headers={
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": kwargs.get("user_agent", NATIVE_UA),
            "Referer": GEETEST_REFERER,
        },
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
    pt: str = "0",
    now_ms: int | None = None,
    w: str | None = None,
) -> dict:
    query = {
        "gt": api1.gt,
        "challenge": api1.challenge,
        "lang": DEFAULT_LANG,
        "pt": str(pt),
        "client_type": client_type,
        "w": w or "",
        "callback": callback_name(now_ms),
    }
    if not w:
        query.pop("w")
    return query


def ajax_query(
    api1: gt3.Api1Result,
    w_value: str,
    *,
    client_type: str = DEFAULT_CLIENT_TYPE,
    pt: str = "0",
    now_ms: int | None = None,
) -> dict:
    return {
        "gt": api1.gt,
        "challenge": api1.challenge,
        "lang": DEFAULT_LANG,
        "pt": str(pt),
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
    """fullpage 9.2.0 纯算。get.php 登记 AES key，ajax 只送 base64(AES)。"""

    def __init__(
        self,
        *,
        api_host: str | None = None,
        client_type: str = FULLPAGE_CLIENT_TYPE,
        pt: str = FULLPAGE_PT,
        user_agent: str = NATIVE_UA,
    ):
        self.api_host = api_host
        self.client_type = client_type
        self.pt = str(pt)
        self.user_agent = user_agent
        self.last_public: dict = {}

    def complete_bind(self, api1: gt3.Api1Result) -> gt3.Gt3Triple:
        if not api1.success:
            raise Gt3WError("api1-unsuccessful")
        host = self.api_host or DEFAULT_API_HOSTS[0]
        started = time.time()
        gettype_plane, gettype_data = fetch_jsonp(
            host, "/gettype.php", gettype_query(api1), user_agent=self.user_agent)
        if self.api_host is None:
            host = pick_api_host(gettype_data)
        aes_key = random_aes_key()
        get_plain = fullpage_get_plaintext(api1, api_server=host)
        w_get = pack_registered_w(get_plain, aes_key=aes_key)
        get_plane, get_data = fetch_jsonp(
            host, "/get.php",
            getphp_query(api1, client_type=self.client_type, pt=self.pt, w=w_get),
            user_agent=self.user_agent)
        if self.api_host is None:
            host = pick_api_host(get_data, gettype_data)
        c_value, s_value = challenge_cs(get_data)
        elapsed = time.time() - started
        if elapsed < 2.2:
            time.sleep(2.2 - elapsed)
        passtime = max(1, int((time.time() - started) * 1000))
        plaintext = fullpage_ajax_plaintext(
            api1,
            passtime=passtime,
            client_type=self.client_type,
            c=c_value,
            s=s_value,
            now_ms=int(time.time() * 1000),
        )
        w_value = pack_ajax_w(plaintext, aes_key=aes_key)
        ajax_plane, ajax_data = fetch_jsonp(
            host, "/ajax.php",
            ajax_query(api1, w_value, client_type=self.client_type, pt=self.pt),
            user_agent=self.user_agent)
        self.last_public = {
            "origin": "aes-rsa",
            "api_host": host.split("://", 1)[-1],
            "client_type": self.client_type,
            "gettype": plane_public(gettype_plane),
            "get": plane_public(get_plane),
            "ajax": plane_public(ajax_plane),
            "w_get": w_public_shape(w_get),
            "w": {
                "len": len(w_value),
                "alphabet_ok": geetest_b64_body_ok(w_value),
                "rsa_tail": False,
            },
            "tt_len": len(json.loads(plaintext).get("tt") or ""),
            "passtime": passtime,
            "cs": bool(c_value and s_value),
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


def _make_provider(name: str):
    if name == "aes-rsa":
        return AesRsaWProvider()
    raise Gt3WError(f"provider-{name}")


class FullpageWProvider:
    """fullpage 9.2.0 纯算 ``w``。``prefer`` 只接受 ``aes-rsa``。"""

    def __init__(self, *, prefer: str = "aes-rsa"):
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
