"""快代理按需租约与并发复用测试。"""

import asyncio
import unittest

from service.proxy import KuaidailiDpsProvider, ProxyLeaseManager


class FakeClock:
    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value


class FakeProvider:
    name = "fake"
    dynamic = True
    lease_seconds = 1200

    def __init__(self, delay=0):
        self.calls = 0
        self.delay = delay

    async def acquire(self):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return f"http://user:secret@proxy-{self.calls}.test:8000"


class FakeKdlClient:
    def __init__(self):
        self.auth_calls = 0
        self.dps_calls = 0

    def get_proxy_authorization(self, plain_text=0):
        self.auth_calls += 1
        self.assert_plain_text = plain_text
        return {"username": "u name", "password": "p@ss"}

    def get_dps(self, **kwargs):
        self.dps_calls += 1
        self.kwargs = kwargs
        return ["1.2.3.4:5678"]


class ProxyLeaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_lazy_reuse_force_refresh_and_expiry(self):
        clock = FakeClock()
        provider = FakeProvider()
        manager = ProxyLeaseManager(
            provider, expiry_safety_seconds=30, clock=clock)

        self.assertEqual(0, provider.calls)
        self.assertFalse(manager.snapshot()["acquired"])

        first = await manager.context(reason="download")
        reused = await manager.context(reason="download")
        self.assertEqual(1, provider.calls)
        self.assertEqual(first.lease.generation, reused.lease.generation)

        forced = await manager.context(
            force_new=True, reason="sync_rankings")
        self.assertEqual(2, provider.calls)
        self.assertNotEqual(first.lease.generation, forced.lease.generation)

        clock.value += 1171
        expired = await manager.context(reason="download")
        self.assertEqual(3, provider.calls)
        self.assertNotEqual(forced.lease.generation, expired.lease.generation)

        snapshot = manager.snapshot()
        self.assertNotIn("proxy_url", snapshot)
        self.assertNotIn("secret", repr(snapshot))

    async def test_concurrent_first_use_extracts_only_once(self):
        provider = FakeProvider(delay=0.01)
        manager = ProxyLeaseManager(provider, expiry_safety_seconds=0)

        contexts = await asyncio.gather(*(
            manager.context(reason=f"request-{index}")
            for index in range(5)
        ))

        self.assertEqual(1, provider.calls)
        self.assertEqual(1, len({
            context.lease.generation for context in contexts
        }))

    async def test_kdl_provider_does_not_call_api_before_acquire(self):
        client = FakeKdlClient()
        provider = KuaidailiDpsProvider(
            secret_id="fixture-id",
            secret_key="fixture-key",
            client_factory=lambda secret_id, secret_key: client,
        )

        self.assertEqual(0, client.auth_calls)
        self.assertEqual(0, client.dps_calls)

        proxy_url = await provider.acquire()

        self.assertEqual("http://u%20name:p%40ss@1.2.3.4:5678", proxy_url)
        self.assertEqual(1, client.auth_calls)
        self.assertEqual(1, client.dps_calls)
        self.assertEqual(1, client.kwargs["num"])
        self.assertEqual(1, client.kwargs["pt"])


if __name__ == "__main__":
    unittest.main()
