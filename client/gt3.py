"""App ``get_cpt_ifm`` 的 GT3 bind 面。

官方 2.9.365 线（``BaseTaskNew.initJiyan`` ``setPattern(1)``）：

1. GET ``/signup/geetest_first_register?t=&user_id=``
2. SDK ``getGeetest``：``gettype.php`` → ``get.php`` → ``ajax.php``（约 1s，无滑块图）
3. ``onDialogResult`` 回写 ``geetest_challenge`` / ``geetest_validate`` / ``geetest_seccode``
4. 同一 ``get_cpt_ifm`` 再打一次

``bind()`` 默认 ``Gt3BindNotReady``。黑盒出参走 ``gt3_w.FullpageWProvider``
（本机 Node 跑官方 ``static/tools/gt.js``，不依赖 RuyiDOM）。AES+RSA packing 对 fullpage
9.2.0 是 ``error_03 param decrypt error``，不能标 ``algorithmic``。
公开滑块轨迹解题器不是这条线。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import time
from typing import Any, Protocol
from urllib.parse import urlencode

from . import config, crypto


API1_PATH = "/signup/geetest_first_register"
RETRY_KEYS = (
    "geetest_challenge",
    "geetest_validate",
    "geetest_seccode",
)
GT3_PATHS = ("/gettype.php", "/get.php", "/ajax.php")
OBSERVED_GT3_HOSTS = (
    "http://103.143.17.166",
    "https://api.geetest.com",
    "https://api.geevisit.com",
)
SECRET_FIELD_NAMES = {
    "gt",
    "challenge",
    "validate",
    "seccode",
    "w",
    "user_id",
    "token",
    "geetest_challenge",
    "geetest_validate",
    "geetest_seccode",
}


class Gt3Error(RuntimeError):
    """API1 / bind 平面失败。"""


class Gt3BindNotReady(Gt3Error):
    """``w`` 尚未 sampleParity，禁止假装 bind 已完成。"""


@dataclass(frozen=True, repr=False)
class Api1Result:
    """API1 解析结果。repr / ``public_shape`` 不带 gt/challenge 原文。"""

    success: bool
    new_captcha: bool | None
    gt_len: int
    challenge_len: int
    top_keys: tuple[str, ...]
    _gt: str = field(default="", repr=False, compare=False)
    _challenge: str = field(default="", repr=False, compare=False)

    @property
    def gt(self) -> str:
        return self._gt

    @property
    def challenge(self) -> str:
        return self._challenge

    def __repr__(self) -> str:
        return (
            "Api1Result("
            f"success={self.success!r}, new_captcha={self.new_captcha!r}, "
            f"gt_len={self.gt_len}, challenge_len={self.challenge_len})"
        )


@dataclass(frozen=True, repr=False)
class Gt3Triple:
    """官方 ``onDialogResult`` 三元组。repr 不带原文。"""

    challenge_len: int
    validate_len: int
    seccode_len: int
    _challenge: str = field(default="", repr=False, compare=False)
    _validate: str = field(default="", repr=False, compare=False)
    _seccode: str = field(default="", repr=False, compare=False)

    @property
    def challenge(self) -> str:
        return self._challenge

    @property
    def validate(self) -> str:
        return self._validate

    @property
    def seccode(self) -> str:
        return self._seccode

    def as_retry_fields(self) -> dict[str, str]:
        return {
            "geetest_challenge": self._challenge,
            "geetest_validate": self._validate,
            "geetest_seccode": self._seccode,
        }

    def __repr__(self) -> str:
        return (
            "Gt3Triple("
            f"challenge_len={self.challenge_len}, "
            f"validate_len={self.validate_len}, "
            f"seccode_len={self.seccode_len})"
        )


class WProvider(Protocol):
    """把 API1 收成官方三元组。默认实现必须拒绝，直到 ``w`` 对齐。"""

    def complete_bind(self, api1: Api1Result) -> Gt3Triple:
        ...


class NotReadyWProvider:
    def complete_bind(self, api1: Api1Result) -> Gt3Triple:
        raise Gt3BindNotReady(
            "ajax w is not algorithmic yet; "
            f"api1_ok={api1.success} gt_len={api1.gt_len} "
            f"challenge_len={api1.challenge_len}"
        )


def official_seccode(validate: str) -> str:
    """GeeTest 惯例 ``validate|jordan``。假 validate 仍是 280002。"""
    return f"{validate}|jordan"


def api1_url(base_url: str, account: str, now_ms: int) -> str:
    query = urlencode({
        "t": str(int(now_ms)),
        "user_id": str(account),
    })
    return f"{str(base_url).rstrip('/')}{API1_PATH}?{query}"


def api1_headers(user_agent: str | None = None) -> dict[str, str]:
    return {
        "Accept": "*/*",
        "User-Agent": user_agent or config.USER_AGENT,
    }


def _truthy(value: Any) -> bool:
    return value in (1, "1", True, "true", "True")


def parse_api1_payload(data: dict) -> Api1Result:
    if not isinstance(data, dict):
        raise Gt3Error("api1-not-object")
    payload = data.get("data")
    source = payload if isinstance(payload, dict) else data
    gt = str(source.get("gt") or data.get("gt") or "")
    challenge = str(source.get("challenge") or data.get("challenge") or "")
    success = _truthy(source.get("success", data.get("success")))
    if str(data.get("code", "")) == "100000" and gt and challenge:
        success = True
    new_raw = source.get("new_captcha", data.get("new_captcha"))
    new_captcha = None if new_raw is None else _truthy(new_raw)
    return Api1Result(
        success=bool(success and gt and challenge),
        new_captcha=new_captcha,
        gt_len=len(gt),
        challenge_len=len(challenge),
        top_keys=tuple(sorted(data.keys())),
        _gt=gt,
        _challenge=challenge,
    )


def decode_gt3_http_body(response, app_version: str) -> dict:
    raw = str(getattr(response, "text", "") or "").strip()
    if not raw:
        raise Gt3Error("empty-response")
    try:
        if raw.startswith("{"):
            data = json.loads(raw)
        else:
            plaintext = crypto.decrypt_response_for_version(raw, app_version)
            data = json.loads(plaintext.decode("utf-8"))
    except Gt3Error:
        raise
    except Exception as exc:
        raise Gt3Error("decode-failed") from exc
    if not isinstance(data, dict):
        raise Gt3Error("response-not-object")
    return data


def public_shape(result: Api1Result) -> dict:
    return {
        "success": result.success,
        "new_captcha": result.new_captcha,
        "gt": {"present": bool(result.gt), "len": result.gt_len},
        "challenge": {
            "present": bool(result.challenge),
            "len": result.challenge_len,
        },
        "top_keys": list(result.top_keys),
    }


SAFE_SHORT_NAMES = {
    "status",
    "type",
    "result",
    "error",
    "error_code",
    "user_error",
    "message",
    "api_server",
}
SAFE_PATH_NAMES = {
    "fullpage",
    "slide",
    "geetest",
    "beeline",
    "click",
    "voice",
    "api_server",
}


def public_json_shape(data: Any, *, depth: int = 0) -> dict:
    """只记 JSON 键名与值长度，不写密钥原文。"""
    if isinstance(data, dict):
        fields = []
        for name, value in data.items():
            item = {"name": str(name), "type": type(value).__name__}
            if isinstance(value, str):
                item["len"] = len(value)
                name_s = str(name)
                if name_s not in SECRET_FIELD_NAMES:
                    if name_s in SAFE_PATH_NAMES and len(value) <= 96:
                        item["value"] = value
                    elif (
                        (name_s in SAFE_SHORT_NAMES or len(value) <= 24)
                        and len(value) <= 32
                    ):
                        item["value"] = value
            elif isinstance(value, (int, bool)) and str(name) not in SECRET_FIELD_NAMES:
                item["value"] = value
            elif isinstance(value, dict):
                item["keys"] = sorted(value.keys())
                if depth < 1:
                    nested = public_json_shape(value, depth=depth + 1)
                    item["fields"] = [
                        field for field in nested.get("fields", [])
                        if field.get("name") in SAFE_SHORT_NAMES
                        or field.get("name") in SAFE_PATH_NAMES
                    ][:12]
            fields.append(item)
        return {"kind": "object", "keys": sorted(data.keys()), "fields": fields}
    if isinstance(data, list):
        return {"kind": "array", "len": len(data)}
    return {"kind": type(data).__name__}


def retry_chapter_params(base: dict, triple: Gt3Triple) -> dict:
    extra = {key: value for key, value in dict(base or {}).items()}
    extra.update(triple.as_retry_fields())
    return extra


def first_register(session, *, now_ms: int | None = None) -> Api1Result:
    """官方 ``RequestAPI1``：GET API1，解析 ``gt`` / ``challenge``。"""
    stamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    url = api1_url(session.base_url, session.account, stamp)
    user_agent = None
    headers = getattr(session, "headers", None)
    if isinstance(headers, dict):
        user_agent = headers.get("User-Agent")
    response = session._request_with_retry(
        "get", url, headers=api1_headers(user_agent))
    status = getattr(response, "status_code", None)
    if status not in (None, 200):
        raise Gt3Error(f"api1-http-{status}")
    return parse_api1_payload(
        decode_gt3_http_body(response, session.app_version))


async def first_register_async(session, *, now_ms: int | None = None) -> Api1Result:
    stamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    url = api1_url(session.base_url, session.account, stamp)
    user_agent = None
    headers = getattr(session, "headers", None)
    if isinstance(headers, dict):
        user_agent = headers.get("User-Agent")
    response = await session._request_with_retry(
        "get", url, headers=api1_headers(user_agent))
    status = getattr(response, "status_code", None)
    if status not in (None, 200):
        raise Gt3Error(f"api1-http-{status}")
    return parse_api1_payload(
        decode_gt3_http_body(response, session.app_version))


def bind(session, *, w_provider: WProvider | None = None,
         now_ms: int | None = None) -> Gt3Triple:
    """完整 bind。默认在 ``w`` 缺口处失败，避免假三元组。"""
    api1 = first_register(session, now_ms=now_ms)
    if not api1.success:
        raise Gt3Error("api1-unsuccessful")
    provider = w_provider or NotReadyWProvider()
    return provider.complete_bind(api1)


async def bind_async(session, *, w_provider: WProvider | None = None,
                     now_ms: int | None = None) -> Gt3Triple:
    api1 = await first_register_async(session, now_ms=now_ms)
    if not api1.success:
        raise Gt3Error("api1-unsuccessful")
    provider = w_provider or NotReadyWProvider()
    return provider.complete_bind(api1)


def parse_geetest_jsonp(raw: str) -> Any:
    text = str(raw or "").strip()
    if not text:
        raise Gt3Error("empty-jsonp")
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    brace = text.find("{")
    close = text.rfind("}")
    if brace >= 0 and close > brace:
        try:
            return json.loads(text[brace:close + 1])
        except json.JSONDecodeError:
            pass
    start = text.find("(")
    end = text.rfind(")")
    if start >= 0 and end > start:
        return json.loads(text[start + 1:end])
    raise Gt3Error("jsonp-decode-failed")


def probe_query_variants(api1: Api1Result, *, now_ms: int | None = None) -> list[dict]:
    """官方 access log 只看到 ``gt``；公开 web 还有 challenge/callback。只列键。"""
    if api1.gt_len <= 0:
        raise Gt3Error("api1-missing-gt")
    stamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    callback = f"geetest_{stamp}"
    return [
        {"label": "gettype-gt", "path": "/gettype.php", "keys": ["gt"]},
        {
            "label": "gettype-gt-callback",
            "path": "/gettype.php",
            "keys": ["gt", "callback"],
        },
        {"label": "get-gt", "path": "/get.php", "keys": ["gt"]},
        {
            "label": "get-gt-challenge",
            "path": "/get.php",
            "keys": ["gt", "challenge"],
        },
        {
            "label": "get-native-shape",
            "path": "/get.php",
            "keys": [
                "gt", "challenge", "lang", "pt", "client_type", "callback",
            ],
        },
        {
            "label": "callback",
            "path": "",
            "keys": ["callback"],
            "callback_class": "geetest_<epoch_ms>",
            "callback_len": len(callback),
        },
    ]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def triple_from_dialog(data: dict, *, fallback_challenge: str = "") -> Gt3Triple:
    """把 ``onDialogResult`` / ``getValidate()`` / ajax data 收成三元组。"""
    if not isinstance(data, dict):
        raise Gt3Error("dialog-not-object")
    nested = data.get("data")
    source = nested if isinstance(nested, dict) else data
    challenge = str(
        source.get("geetest_challenge")
        or source.get("challenge")
        or data.get("geetest_challenge")
        or data.get("challenge")
        or fallback_challenge
        or ""
    )
    validate = str(
        source.get("geetest_validate")
        or source.get("validate")
        or data.get("geetest_validate")
        or data.get("validate")
        or ""
    )
    seccode = str(
        source.get("geetest_seccode")
        or source.get("seccode")
        or data.get("geetest_seccode")
        or data.get("seccode")
        or ""
    )
    if validate and not seccode:
        seccode = official_seccode(validate)
    if not (challenge and validate):
        raise Gt3Error("dialog-missing-triple")
    return Gt3Triple(
        challenge_len=len(challenge),
        validate_len=len(validate),
        seccode_len=len(seccode),
        _challenge=challenge,
        _validate=validate,
        _seccode=seccode,
    )


def ajax_result_label(data: Any) -> str:
    """ajax 成败只返回短标签，不含 validate 原文。"""
    if not isinstance(data, dict):
        return type(data).__name__
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    status = str(data.get("status") or "")
    result = str(nested.get("result") or data.get("result") or "")
    error = str(data.get("error") or data.get("error_code") or nested.get("error") or "")
    if str(nested.get("validate") or data.get("validate") or ""):
        return "validate"
    if result:
        return result
    if error:
        return error
    if status:
        return status
    return "unknown"
