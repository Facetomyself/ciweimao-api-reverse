"""GT3 bind 面离线回归。不访问网络，不写入真实 gt/validate。"""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from client import gt3
from client.api import ApiError, Session
from client.gt3 import (
    Api1Result,
    Gt3BindNotReady,
    Gt3Error,
    Gt3Triple,
    NotReadyWProvider,
    official_seccode,
)


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


class Gt3ParseTests(unittest.TestCase):
    def test_parse_api1_nested_data(self):
        result = gt3.parse_api1_payload({
            "code": "100000",
            "data": {
                "gt": "a" * 32,
                "challenge": "b" * 32,
                "success": 1,
                "new_captcha": True,
            },
        })
        self.assertTrue(result.success)
        self.assertEqual(32, result.gt_len)
        self.assertEqual(32, result.challenge_len)
        self.assertTrue(result.new_captcha)
        public = gt3.public_shape(result)
        dumped = json.dumps(public)
        self.assertNotIn("a" * 32, dumped)
        self.assertNotIn("b" * 32, dumped)
        self.assertTrue(public["gt"]["present"])

    def test_parse_api1_top_level(self):
        result = gt3.parse_api1_payload({
            "gt": "c" * 32,
            "challenge": "d" * 32,
            "success": "1",
            "new_captcha": 1,
        })
        self.assertTrue(result.success)
        self.assertEqual(("challenge", "gt", "new_captcha", "success"),
                         result.top_keys)

    def test_parse_api1_missing_fields_is_not_success(self):
        result = gt3.parse_api1_payload({"success": 1, "code": "100000"})
        self.assertFalse(result.success)
        self.assertEqual(0, result.gt_len)

    def test_api1_url_uses_t_and_user_id(self):
        url = gt3.api1_url("https://app1.happybooker.cn/", "acct", 1700000000000)
        self.assertTrue(url.startswith(
            "https://app1.happybooker.cn/signup/geetest_first_register?"))
        self.assertIn("t=1700000000000", url)
        self.assertIn("user_id=acct", url)

    def test_retry_params_append_official_keys(self):
        triple = Gt3Triple(
            challenge_len=32,
            validate_len=32,
            seccode_len=39,
            _challenge="ch",
            _validate="va",
            _seccode=official_seccode("va"),
        )
        params = gt3.retry_chapter_params(
            {"chapter_id": "1", "chapter_command": "cmd"},
            triple,
        )
        self.assertEqual(
            {
                "chapter_command",
                "chapter_id",
                *gt3.RETRY_KEYS,
            },
            set(params),
        )
        self.assertEqual("va|jordan", params["geetest_seccode"])
        self.assertEqual(gt3.RETRY_KEYS, (
            "geetest_challenge",
            "geetest_validate",
            "geetest_seccode",
        ))

    def test_triple_repr_omits_values(self):
        triple = Gt3Triple(
            challenge_len=2,
            validate_len=2,
            seccode_len=9,
            _challenge="xx",
            _validate="yy",
            _seccode="yy|jordan",
        )
        text = repr(triple)
        self.assertNotIn("xx", text)
        self.assertNotIn("yy", text)

    def test_jsonp_shape_redacts_secrets(self):
        data = gt3.parse_geetest_jsonp(
            'geetest_1({"gt":"zzzz","status":"success","data":{"result":"fullpage"}})')
        shape = gt3.public_json_shape(data)
        dumped = json.dumps(shape)
        self.assertNotIn("zzzz", dumped)
        self.assertIn("gt", dumped)
        self.assertEqual("success", next(
            item["value"] for item in shape["fields"] if item["name"] == "status"
        ))

    def test_parse_wrapped_object_without_geetest_prefix(self):
        data = gt3.parse_geetest_jsonp(
            '/*x*/{"status":"success","data":{"type":"fullpage"}}')
        self.assertEqual("success", data["status"])
        self.assertEqual("fullpage", data["data"]["type"])

    def test_first_register_uses_get(self):
        session = Mock()
        session.base_url = "https://app1.hbooker.com"
        session.account = "guest-account"
        session.app_version = "2.9.365"
        session.headers = {"User-Agent": "Android com.kuangxiangciweimao.novel 2.9.365"}
        session._request_with_retry.return_value = FakeResponse(json.dumps({
            "success": 1,
            "gt": "e" * 32,
            "challenge": "f" * 32,
            "new_captcha": True,
        }))
        result = gt3.first_register(session, now_ms=42)
        self.assertTrue(result.success)
        args, kwargs = session._request_with_retry.call_args
        self.assertEqual("get", args[0])
        self.assertIn("/signup/geetest_first_register?", args[1])
        self.assertIn("t=42", args[1])
        self.assertIn("user_id=guest-account", args[1])
        self.assertEqual("*/*", kwargs["headers"]["Accept"])

    def test_bind_stops_before_fake_ajax(self):
        session = Mock()
        session.base_url = "https://app1.hbooker.com"
        session.account = "guest-account"
        session.app_version = "2.9.365"
        session.headers = {}
        session._request_with_retry.return_value = FakeResponse(json.dumps({
            "success": 1,
            "gt": "g" * 32,
            "challenge": "h" * 32,
        }))
        with self.assertRaises(Gt3BindNotReady):
            gt3.bind(session)
        self.assertEqual(1, session._request_with_retry.call_count)

    def test_not_ready_provider_mentions_w(self):
        api1 = Api1Result(
            success=True,
            new_captcha=True,
            gt_len=32,
            challenge_len=32,
            top_keys=("gt",),
            _gt="i" * 32,
            _challenge="j" * 32,
        )
        with self.assertRaises(Gt3BindNotReady) as ctx:
            NotReadyWProvider().complete_bind(api1)
        self.assertIn("ajax w", str(ctx.exception))
        self.assertNotIn("i" * 32, str(ctx.exception))

    def test_triple_from_dialog_fills_seccode(self):
        triple = gt3.triple_from_dialog({
            "geetest_challenge": "ch",
            "geetest_validate": "va",
        })
        self.assertEqual("va|jordan", triple.seccode)
        self.assertEqual(2, triple.validate_len)

    def test_ajax_result_label_hides_validate(self):
        label = gt3.ajax_result_label({
            "status": "success",
            "data": {"result": "success", "validate": "z" * 32},
        })
        self.assertEqual("validate", label)
        self.assertNotIn("z", label)

    def test_public_json_shape_keeps_fullpage_path(self):
        shape = gt3.public_json_shape({
            "status": "success",
            "data": {
                "type": "fullpage",
                "fullpage": "/static/js/fullpage.9.2.0-test.js",
                "gt": "secret",
            },
        })
        dumped = json.dumps(shape)
        self.assertNotIn("secret", dumped)
        nested = next(item for item in shape["fields"] if item["name"] == "data")
        names = {item["name"]: item for item in nested.get("fields", [])}
        self.assertEqual("fullpage", names["type"]["value"])
        self.assertIn("fullpage.9.2.0-test.js", names["fullpage"]["value"])

    def test_probe_variants_do_not_include_ajax(self):
        api1 = Api1Result(
            success=True,
            new_captcha=True,
            gt_len=32,
            challenge_len=32,
            top_keys=("gt",),
            _gt="k" * 32,
            _challenge="l" * 32,
        )
        variants = gt3.probe_query_variants(api1, now_ms=1)
        paths = {item["path"] for item in variants if item.get("path")}
        self.assertEqual({"/gettype.php", "/get.php"}, paths)
        self.assertTrue(all("w" not in item.get("keys", []) for item in variants))


class Gt3WPackingTests(unittest.TestCase):
    def test_geetest_b64_matches_standard_for_man(self):
        from client import gt3_w
        self.assertEqual("TWFu", gt3_w.geetest_b64_encode(b"Man"))

    def test_pack_w_shape_hides_plaintext(self):
        from client import gt3_w
        packed = gt3_w.pack_w('{"type":"fullpage"}', aes_key="0123456789abcdef")
        shape = gt3_w.w_public_shape(packed)
        self.assertGreaterEqual(shape["len"], 256)
        self.assertEqual(256, shape["rsa_hex_len"])
        self.assertTrue(shape["alphabet_ok"])
        self.assertTrue(shape["rsa_hex_ok"])
        self.assertNotIn("fullpage", packed)

    def test_gt_loader_url_is_tools_gt_js(self):
        from client import gt3_w
        self.assertTrue(gt3_w.gt_loader_url(None).endswith("/static/tools/gt.js"))

    def test_pack_w_rsa_is_not_deterministic(self):
        from client import gt3_w
        first = gt3_w.pack_w('{"a":1}', aes_key="0123456789abcdef")
        second = gt3_w.pack_w('{"a":1}', aes_key="0123456789abcdef")
        self.assertEqual(first[:-256], second[:-256])
        self.assertNotEqual(first[-256:], second[-256:])


class Gt3StampRecoveryTests(unittest.TestCase):
    def _session(self):
        session = object.__new__(Session)
        session.web_fallback_enabled = True
        session.web_fallback_used = False
        session.gt3_stamped = False
        session.gt3_stamp_origin = None
        session._gt3_stamp_lock = __import__("threading").Lock()
        return session

    def test_default_does_not_stamp(self):
        session = self._session()
        session._call = Mock(side_effect=ApiError("310017", "blocked"))
        session.stamp_gt3 = Mock()
        with self.assertRaises(ApiError):
            session.get_chapter_content("1", "cmd")
        session.stamp_gt3.assert_not_called()

    def test_310017_stamps_then_retries(self):
        session = self._session()
        ok = {"data": {"chapter_info": {"txt_content": ""}}}
        session._call = Mock(side_effect=ApiError("310017", "blocked"))
        triple = Gt3Triple(
            32, 32, 39,
            _challenge="c" * 32,
            _validate="v" * 32,
            _seccode="v" * 32 + "|jordan",
        )
        def fake_stamp():
            session.gt3_stamped = True
            session.gt3_stamp_origin = "ruyidom"
            return triple
        session.stamp_gt3 = Mock(side_effect=fake_stamp)
        session.retry_chapter_after_gt3 = Mock(return_value=ok)
        text = session.get_chapter_content("1", "cmd", allow_gt3_stamp=True)
        self.assertEqual("", text)
        session.stamp_gt3.assert_called_once()
        session.retry_chapter_after_gt3.assert_called_once()
        self.assertTrue(session.gt3_stamped)

    def test_stamp_failure_falls_back_to_web(self):
        session = self._session()
        session._call = Mock(side_effect=ApiError("310017", "blocked"))
        session.stamp_gt3 = Mock(side_effect=Gt3Error("offline"))
        web = Mock()
        web.get_chapter_content.return_value = "网页正文"
        session._web_session = web
        text = session.get_chapter_content(
            "1", "cmd", allow_gt3_stamp=True, allow_web_fallback=True)
        self.assertEqual("网页正文", text)
        self.assertTrue(session.web_fallback_used)
        web.get_chapter_content.assert_called_once_with("1")

    def test_already_stamped_retries_without_second_bind(self):
        session = self._session()
        session.gt3_stamped = True
        ok = {"data": {"chapter_info": {"txt_content": ""}}}
        session._call = Mock(side_effect=[
            ApiError("310017", "blocked"),
            ok,
        ])
        session.stamp_gt3 = Mock()
        text = session.get_chapter_content("1", "cmd", allow_gt3_stamp=True)
        self.assertEqual("", text)
        session.stamp_gt3.assert_not_called()
        self.assertEqual(2, session._call.call_count)


if __name__ == "__main__":
    unittest.main()
