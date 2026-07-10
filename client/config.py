"""API 客户端配置。"""

import random

# API 基础 URL（来自 APK metadata 和参考项目）
BASE_URL = "https://app.hbooker.com"

# 全局 API 解密密钥（硬编码在 App 中）
API_KEY = "zG2nSeEfSHfvTCHy5LCcqtBbQehKNLXn"

# App 版本（从模拟器 App 提取验证：2.9.312）
APP_VERSION = "2.9.312"

# User-Agent
USER_AGENT = f"Android com.kuangxiangciweimao.novel {APP_VERSION}"

# 设备 Token 前缀
DEVICE_TOKEN_PREFIX = "ciweimao_"


def generate_device_token() -> str:
    """生成随机 device_token（持久化后复用）。"""
    return f"{DEVICE_TOKEN_PREFIX}{random.randint(0, 299999999999999):015d}"
