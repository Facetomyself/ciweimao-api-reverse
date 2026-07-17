"""认证模块：登录 / Token 管理。

登录流程：
  1. 生成 device_token（首次）或复用已保存的
  2. POST /signup/login → 获取加密响应
  3. 解密响应 → 提取 login_token, account, reader_id
  4. 保存 login_token 供后续请求使用

Token 刷新：
  login_token 会过期（错误码 200100），需自动重新登录
"""

import json
import requests
from . import crypto
from . import config


class AuthManager:
    """管理 Ciweimao 登录状态。"""

    def __init__(self):
        self.login_token: str = ""
        self.account: str = ""
        self.device_token: str = config.generate_device_token()
        self.reader_id: str = ""
        self.reader_name: str = ""

    def login(self, username: str, password: str) -> bool:
        """密码登录，获取 login_token 和 account。

        Returns:
            True 如果登录成功，False 如果失败。
        """
        params = {
            "login_name": username,
            "passwd": password,
            "device_token": self.device_token,
            "app_version": config.LEGACY_APP_VERSION,
        }

        url = f"{config.LEGACY_BASE_URL}/signup/login"
        resp = requests.post(
            url,
            data=params,
            headers={
                "User-Agent": (
                    "Android com.kuangxiangciweimao.novel "
                    f"{config.LEGACY_APP_VERSION}"
                ),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=15,
        )

        if resp.status_code != 200:
            print(f"[ERR] 登录 HTTP {resp.status_code}: {resp.text[:200]}")
            return False

        # 解密响应
        try:
            plaintext = crypto.decrypt_response(
                resp.text.strip(), key_str=config.LEGACY_API_KEY)
            data = json.loads(plaintext)
        except Exception as e:
            print(f"[ERR] 解密登录响应失败: {e}")
            print(f"[DEBUG] 原始响应: {resp.text[:100]}")
            return False

        code = data.get("code", "")
        if code != "100000":
            print(f"[ERR] 登录失败, code={code}")
            tip = data.get("tip", "")
            if tip:
                print(f"[ERR] 提示: {tip}")
            return False

        # 提取认证信息
        inner = data.get("data", {})
        self.login_token = inner.get("login_token", "")
        reader_info = inner.get("reader_info", {})
        self.account = reader_info.get("account", "")
        self.reader_id = reader_info.get("reader_id", "")
        self.reader_name = reader_info.get("reader_name", "")

        print(f"[OK] 登录成功: {self.reader_name} (reader_id={self.reader_id})")
        print("[OK] 凭据已载入内存，不回显 account/login_token")

        return True

    def is_logged_in(self) -> bool:
        return bool(self.login_token and self.account)

    def get_auth_params(self) -> dict:
        """获取所有 API 请求都需要附加的认证参数。"""
        return {
            "login_token": self.login_token,
            "account": self.account,
            "device_token": self.device_token,
            "app_version": config.LEGACY_APP_VERSION,
        }
