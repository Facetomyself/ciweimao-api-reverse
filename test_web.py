"""网页章节链的不联网回归测试。"""

from __future__ import annotations

import asyncio
import base64
import threading
import time
import unittest
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor

from client.web import (
    AsyncWebChapterSession,
    WebChapterError,
    WebChapterSession,
    WebDecryptError,
    decrypt_chapter_payload,
)
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


def _encrypt_layer(plain: bytes, key_b64: str, iv: bytes) -> str:
    key = base64.b64decode(key_b64)
    encrypted = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(plain, 16))
    return base64.b64encode(iv + encrypted).decode("ascii")


def encrypted_fixture(access_key: str = "A中") -> tuple[str, list[str], str, str]:
    keys = [
        base64.b64encode(bytes([index]) * 32).decode("ascii")
        for index in range(7)
    ]
    first = keys[ord(access_key[-1]) % len(keys)]
    second = keys[ord(access_key[0]) % len(keys)]
    iv1 = b"0123456789abcdef"
    iv2 = b"fedcba9876543210"
    html = (
        "<div><p class='chapter'> 第一段 <span>watermark</span>。</p>"
        "<p>第二段<br>换行<span>noise</span></p></div>"
    )
    inner = _encrypt_layer(html.encode("utf-8"), second, iv2)
    outer = _encrypt_layer(inner.encode("ascii"), first, iv1)
    return outer, keys, access_key, html


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: Mapping[str, object] | None = None,
        text: str = "<html><body>chapter</body></html>",
        headers: Mapping[str, object] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = dict(payload) if payload is not None else None
        self.text = text
        self.headers = dict(headers or {})

    def json(self):
        if self._payload is None:
            raise ValueError("not JSON")
        return dict(self._payload)


class ScriptedSession:
    """同步 curl session 替身；记录请求并模拟 Cookie 轮换。"""

    def __init__(self, *, encrypted: str, keys: list[str], access_key: str, rotate: bool = False, delay: float = 0.0, **kwargs):
        self.encrypted = encrypted
        self.keys = keys
        self.access_key = access_key
        self.rotate = rotate
        self.delay = delay
        self.calls: list[tuple[str, str, dict]] = []
        self.cookies: dict[str, str] = {}
        self._guard = threading.Lock()
        self._active = 0
        self.max_active = 0
        self.factory_kwargs = kwargs

    def _record(self, method: str, url: str, kwargs: dict) -> None:
        with self._guard:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
            self.calls.append((method, url, kwargs))
        if self.delay:
            time.sleep(self.delay)
        with self._guard:
            self._active -= 1

    def get(self, url: str, **kwargs):
        self._record("GET", url, kwargs)
        headers = {"Set-Cookie": "ci_session=rotated; Path=/"} if self.rotate else {}
        return FakeResponse(headers=headers)

    def post(self, url: str, **kwargs):
        self._record("POST", url, kwargs)
        if url.endswith("ajax_get_session_code"):
            return FakeResponse(payload={"code": 100000, "chapter_access_key": self.access_key})
        return FakeResponse(payload={
            "code": 100000,
            "chapter_content": self.encrypted,
            "encryt_keys": self.keys,
        })

    def close(self):
        self.closed = True


class AsyncScriptedSession(ScriptedSession):
    async def get(self, url: str, **kwargs):
        self._record("GET", url, kwargs)
        await asyncio.sleep(0)
        headers = {"Set-Cookie": "ci_session=rotated; Path=/"} if self.rotate else {}
        return FakeResponse(headers=headers)

    async def post(self, url: str, **kwargs):
        self._record("POST", url, kwargs)
        await asyncio.sleep(0)
        if url.endswith("ajax_get_session_code"):
            return FakeResponse(payload={"code": 100000, "chapter_access_key": self.access_key})
        return FakeResponse(payload={
            "code": 100000,
            "chapter_content": self.encrypted,
            "encryt_keys": self.keys,
        })

    async def close(self):
        self.closed = True


class WebDecryptTests(unittest.TestCase):
    def test_double_layer_decrypt_uses_unicode_codepoint_and_normalizes_html(self):
        encrypted, keys, access_key, _ = encrypted_fixture()
        plaintext = decrypt_chapter_payload(encrypted, keys, access_key)
        self.assertIn("<span>watermark</span>", plaintext)

        session = WebChapterSession(
            session_factory=lambda **kwargs: ScriptedSession(
                encrypted=encrypted, keys=keys, access_key=access_key, **kwargs
            ),
            min_interval=0,
        )
        result = session.fetch_chapter("123")
        self.assertEqual("123", result.chapter_id)
        self.assertNotIn("watermark", result.html)
        self.assertNotIn("noise", result.text)
        self.assertEqual("第一段 。\n第二段\n换行", result.text)
        session.close()

    def test_malformed_payload_is_rejected(self):
        with self.assertRaises(WebDecryptError):
            decrypt_chapter_payload("not-base64", ["AA=="], "A")


class WebSyncSessionTests(unittest.TestCase):
    def setUp(self):
        self.encrypted, self.keys, self.access_key, _ = encrypted_fixture()
        self.fake: ScriptedSession | None = None

        def factory(**kwargs):
            self.fake = ScriptedSession(
                encrypted=self.encrypted,
                keys=self.keys,
                access_key=self.access_key,
                **kwargs,
            )
            return self.fake

        self.factory = factory

    def test_request_order_headers_and_app_credentials_are_absent(self):
        session = WebChapterSession(
            base_url="https://web.example",
            proxy="socks5h://127.0.0.1:1080",
            impersonate="chrome136",
            session_factory=self.factory,
            min_interval=0,
        )
        result = session.fetch_chapter("123")
        self.assertEqual("第一段 。\n第二段\n换行", result.text)
        assert self.fake is not None
        self.assertEqual(["GET", "POST", "POST"], [item[0] for item in self.fake.calls])
        self.assertEqual(
            [
                "https://web.example/chapter/123",
                "https://web.example/chapter/ajax_get_session_code",
                "https://web.example/chapter/get_book_chapter_detail_info",
            ],
            [item[1] for item in self.fake.calls],
        )
        page_headers = self.fake.calls[0][2]["headers"]
        ajax_headers = self.fake.calls[1][2]["headers"]
        self.assertEqual("https://web.example/", page_headers["Referer"])
        self.assertEqual("https://web.example", ajax_headers["Origin"])
        self.assertEqual("https://web.example/chapter/123", ajax_headers["Referer"])
        self.assertEqual("XMLHttpRequest", ajax_headers["X-Requested-With"])
        self.assertEqual(
            {"chapter_id"},
            set(self.fake.calls[1][2]["data"]),
        )
        self.assertEqual(
            {"chapter_id", "chapter_access_key"},
            set(self.fake.calls[2][2]["data"]),
        )
        forbidden = {"account", "login_token", "device_token", "app_version", "rand_str", "p", "chapter_command"}
        for _, _, kwargs in self.fake.calls:
            self.assertTrue(forbidden.isdisjoint(kwargs["headers"]))
            if "data" in kwargs:
                self.assertTrue(forbidden.isdisjoint(kwargs["data"]))
        self.assertEqual("socks5h://127.0.0.1:1080", self.fake.factory_kwargs["proxy"])
        self.assertEqual("chrome136", self.fake.factory_kwargs["impersonate"])
        session.close()

    def test_cookie_rotation_is_used_by_following_requests(self):
        def factory(**kwargs):
            self.fake = ScriptedSession(
                encrypted=self.encrypted,
                keys=self.keys,
                access_key=self.access_key,
                rotate=True,
                **kwargs,
            )
            return self.fake

        session = WebChapterSession(session_factory=factory, min_interval=0)
        session.fetch_chapter("123")
        assert self.fake is not None
        self.assertEqual("rotated", session.cookies["ci_session"])
        self.assertEqual(
            "ci_session=rotated",
            self.fake.calls[1][2]["headers"]["Cookie"],
        )
        self.assertEqual(
            "ci_session=rotated",
            self.fake.calls[2][2]["headers"]["Cookie"],
        )
        self.assertTrue(session.cookie_changes)
        session.close()

    def test_business_error_stops_before_detail(self):
        class ErrorSession(ScriptedSession):
            def post(self, url: str, **kwargs):
                self._record("POST", url, kwargs)
                return FakeResponse(payload={"code": 310017, "tip": "请升级到最新版本客户端"})

        def factory(**kwargs):
            self.fake = ErrorSession(
                encrypted=self.encrypted, keys=self.keys,
                access_key=self.access_key, **kwargs,
            )
            return self.fake

        session = WebChapterSession(session_factory=factory, min_interval=0)
        with self.assertRaises(WebChapterError) as caught:
            session.fetch_chapter("123")
        self.assertEqual("session", caught.exception.stage)
        self.assertEqual("310017", caught.exception.code)
        self.assertIn("升级", caught.exception.tip)
        assert self.fake is not None
        self.assertEqual(2, len(self.fake.calls))
        session.close()

    def test_image_chapter_is_rejected_before_ajax(self):
        class ImageSession(ScriptedSession):
            def get(self, url: str, **kwargs):
                self._record("GET", url, kwargs)
                return FakeResponse(text="<div id='J_ImgRead'></div>")

        session = WebChapterSession(
            session_factory=lambda **kwargs: ImageSession(
                encrypted=self.encrypted, keys=self.keys,
                access_key=self.access_key, **kwargs,
            ),
            min_interval=0,
        )
        with self.assertRaises(WebChapterError) as caught:
            session.fetch_chapter("123")
        self.assertEqual("image-chapter", caught.exception.code)
        self.assertEqual(1, len(session.client.calls))
        session.close()

    def test_lock_serializes_complete_three_request_sequences(self):
        session = WebChapterSession(
            session_factory=lambda **kwargs: ScriptedSession(
                encrypted=self.encrypted, keys=self.keys,
                access_key=self.access_key, delay=0.005, **kwargs,
            ),
            min_interval=0,
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: session.get_chapter_content("123"), range(2)))
        self.assertEqual(["第一段 。\n第二段\n换行"] * 2, results)
        fake = session.client
        self.assertIsNotNone(fake)
        self.assertEqual(6, len(fake.calls))
        self.assertEqual(
            ["GET", "POST", "POST", "GET", "POST", "POST"],
            [item[0] for item in fake.calls],
        )
        self.assertEqual(1, fake.max_active)
        session.close()

    def test_app_credential_headers_are_rejected(self):
        with self.assertRaises(ValueError):
            WebChapterSession(headers={"account": "must-not-be-used"})


class WebAsyncSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_sequence_cookie_rotation_and_lock(self):
        encrypted, keys, access_key, _ = encrypted_fixture()
        fake: AsyncScriptedSession | None = None

        def factory(**kwargs):
            nonlocal fake
            fake = AsyncScriptedSession(
                encrypted=encrypted, keys=keys,
                access_key=access_key, rotate=True, **kwargs,
            )
            return fake

        session = AsyncWebChapterSession(
            session_factory=factory,
            min_interval=0,
        )
        results = await asyncio.gather(
            session.get_chapter_content("123"),
            session.get_chapter_content("123"),
        )
        self.assertEqual(["第一段 。\n第二段\n换行"] * 2, results)
        assert fake is not None
        self.assertEqual(6, len(fake.calls))
        self.assertEqual(
            ["GET", "POST", "POST", "GET", "POST", "POST"],
            [item[0] for item in fake.calls],
        )
        self.assertEqual("rotated", session.cookies["ci_session"])
        self.assertEqual(1, fake.max_active)
        await session.close()

    async def test_async_business_error(self):
        class ErrorSession(AsyncScriptedSession):
            async def post(self, url: str, **kwargs):
                self._record("POST", url, kwargs)
                await asyncio.sleep(0)
                return FakeResponse(payload={"code": "310017", "tip": "请升级到最新版本客户端"})

        encrypted, keys, access_key, _ = encrypted_fixture()
        session = AsyncWebChapterSession(
            session_factory=lambda **kwargs: ErrorSession(
                encrypted=encrypted, keys=keys,
                access_key=access_key, **kwargs,
            ),
            min_interval=0,
        )
        with self.assertRaises(WebChapterError) as caught:
            await session.fetch_chapter("123")
        self.assertEqual("session", caught.exception.stage)
        self.assertEqual("310017", caught.exception.code)
        await session.close()


if __name__ == "__main__":
    unittest.main()
