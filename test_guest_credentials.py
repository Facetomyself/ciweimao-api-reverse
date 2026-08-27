"""游客注册与 FastAPI 启动凭据自举回归测试。"""

import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import AsyncMock

from client import config, protocol
from client.guest import GuestCredentials, register_guest
from service.config import Credentials, Settings
from service.credentials import GuestCredentialBootstrapper


class FakeResponse:
    status_code = 200
    text = json.dumps({
        "code": "100000",
        "data": {
            "login_token": "fixture-token",
            "reader_info": {
                "account": "fixture-account",
                "reader_id": "42",
                "is_bind": "0",
            },
        },
    })


class FakeRegistrationSession:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.post_call = None
        self.__class__.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def post(self, url, **kwargs):
        self.post_call = (url, kwargs)
        return FakeResponse()


class FakeValidationSession:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.__class__.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def search_books(self, keyword, page=0, count=1):
        del keyword, page, count
        return {"code": "100000", "data": {"book_list": []}}


class GuestRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_guest_matches_runtime_request_shape(self):
        FakeRegistrationSession.instances.clear()
        credentials = await register_guest(
            uuid_value="android00000000-0000-0000-0000-000000000000",
            rand_str="10072263a65a4345",
            proxy="socks5://egress:1080",
            session_factory=FakeRegistrationSession,
        )

        self.assertEqual("fixture-token", credentials.login_token)
        self.assertNotIn("fixture-token", repr(credentials))
        instance = FakeRegistrationSession.instances[-1]
        self.assertEqual(
            "socks5://egress:1080", instance.kwargs["proxy"])
        url, request = instance.post_call
        self.assertEqual(
            "https://app1.hbooker.com/signup/auto_reg_v2", url)
        data = request["data"]
        self.assertEqual(config.DEVICE_TOKEN_PREFIX, data["device_token"])
        self.assertEqual(config.GUEST_REGISTRATION_CHANNEL, data["channel"])
        self.assertEqual(
            protocol.sign_request(
                config.GUEST_REGISTRATION_ACCOUNT,
                config.APP_VERSION,
                "10072263a65a4345",
            )["p"],
            data["p"],
        )


    def test_save_reader_oaid_params_match_official_keys(self):
        from client.guest import android_id_to_am, build_save_reader_oaid_params
        am = android_id_to_am("0123456789abcdef")
        self.assertEqual(32, len(am))
        params = build_save_reader_oaid_params(
            reader_id="1", am=am, oaid="")
        self.assertEqual(
            {"reader_id", "channel", "oaid", "am"}, set(params))
        self.assertEqual(config.GUEST_REGISTRATION_CHANNEL, params["channel"])
        self.assertEqual("", params["oaid"])


class CredentialBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_credentials_are_registered_and_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
                database_path=root / "data.sqlite3",
                output_dir=root / "output",
                token_path=root / "guest-tokens.json",
                guest_bootstrap_enabled=True,
                scheduler_enabled=False,
                http_proxy_url="socks5://egress:1080",
            )
            registrar = AsyncMock(return_value=GuestCredentials(
                login_token="fixture-token",
                account="fixture-account",
                device_token="ciweimao_",
                reader_id="42",
            ))
            FakeValidationSession.instances.clear()
            bootstrapper = GuestCredentialBootstrapper(
                settings,
                session_factory=FakeValidationSession,
                registrar=registrar,
            )

            first = await bootstrapper.ensure()
            second = await bootstrapper.ensure()

            self.assertTrue(first.created)
            self.assertFalse(second.created)
            self.assertEqual("token-file", second.source)
            self.assertEqual(1, registrar.await_count)
            payload = json.loads(
                settings.token_path.read_text(encoding="utf-8"))
            self.assertEqual("fixture-token", payload["login_token"])
            self.assertEqual("42", payload["reader_id"])
            if os.name != "nt":
                self.assertEqual(
                    0o600,
                    stat.S_IMODE(settings.token_path.stat().st_mode),
                )
            self.assertFalse(list(root.glob(".*.tmp")))

    async def test_runtime_refresh_registers_once_for_stale_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
                database_path=root / "data.sqlite3",
                output_dir=root / "output",
                token_path=root / "guest-tokens.json",
                guest_bootstrap_enabled=True,
                scheduler_enabled=False,
            )
            stale = Credentials(
                login_token="stale-token",
                account="stale-account",
                device_token="ciweimao_",
            )
            settings.save_credentials(stale)
            registrar = AsyncMock(return_value=GuestCredentials(
                login_token="fresh-token",
                account="fresh-account",
                device_token="ciweimao_",
            ))
            bootstrapper = GuestCredentialBootstrapper(
                settings,
                session_factory=FakeValidationSession,
                registrar=registrar,
            )

            first = await bootstrapper.refresh(stale)
            second = await bootstrapper.refresh(stale)

            self.assertTrue(first.created)
            self.assertFalse(second.created)
            self.assertEqual("token-file-refreshed", second.source)
            self.assertEqual(1, registrar.await_count)
            current = settings.load_credentials()
            self.assertEqual("fresh-token", current.login_token)


if __name__ == "__main__":
    unittest.main()
