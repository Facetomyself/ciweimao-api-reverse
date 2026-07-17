"""App API 协议配置。"""

import random


LEGACY_BASE_URL = "https://app.hbooker.com"
CURRENT_BASE_URL = "https://app1.happybooker.cn"
GUEST_REGISTRATION_BASE_URL = "https://app1.hbooker.com"

# 2.9.362 的 Native 实现仍保留旧 key，同时新增 current key。
LEGACY_API_KEY = "zG2nSeEfSHfvTCHy5LCcqtBbQehKNLXn"
CURRENT_API_KEY = "sD6doAOcW7hm7iaeK6UlcdtAIWlZGlBr"

# 请求签名常量，来自 2.9.362 Native 运行时日志并经 84/84 请求复核。
REQUEST_SIGNATURE_KEY = "a90f3731745f1c30ee77cb13fc00005a"
REQUEST_SIGNATURE_SUFFIX = "CkMxWNB666"

# App 2.9.362 在游客注册前使用的固定签名占位符。该值由两次干净安装
# 的独立 auto_reg_v2 请求复核，不是注册后的游客账号或用户凭据。
GUEST_REGISTRATION_ACCOUNT = "cmw666"
GUEST_REGISTRATION_CHANNEL = "TX"

LEGACY_APP_VERSION = "2.9.312"
APP_VERSION = "2.9.362"

# 2.9.328 开始要求请求签名；2.9.352 开始切换响应 AES key。
SIGNED_TRANSPORT_MIN_VERSION = (2, 9, 328)
CURRENT_RESPONSE_MIN_VERSION = (2, 9, 352)

BASE_URL = CURRENT_BASE_URL
API_KEY = CURRENT_API_KEY
USER_AGENT = f"Android com.kuangxiangciweimao.novel {APP_VERSION}"

# 设备 Token 前缀
DEVICE_TOKEN_PREFIX = "ciweimao_"


def version_tuple(version: str) -> tuple[int, ...]:
    """把点分版本转换为可比较的整数元组。"""
    try:
        return tuple(int(part) for part in str(version).split("."))
    except (TypeError, ValueError):
        return (0,)


def uses_signed_transport(version: str) -> bool:
    return version_tuple(version) >= SIGNED_TRANSPORT_MIN_VERSION


def uses_current_response_key(version: str) -> bool:
    return version_tuple(version) >= CURRENT_RESPONSE_MIN_VERSION


def base_url_for_version(version: str) -> str:
    return (CURRENT_BASE_URL if uses_signed_transport(version)
            else LEGACY_BASE_URL)


def response_key_for_version(version: str) -> str:
    return (CURRENT_API_KEY if uses_current_response_key(version)
            else LEGACY_API_KEY)


def generate_device_token() -> str:
    """生成随机 device_token（持久化后复用）。"""
    return f"{DEVICE_TOKEN_PREFIX}{random.randint(0, 299999999999999):015d}"
