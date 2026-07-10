"""AES-256-CBC 解密模块。

API 响应解密：
  Base64 → AES-256-CBC(SHA256(api_key), IV=0x00*16) → plaintext

章节内容解密（双层）：
  Layer 1: 全局 API key 解密响应 → 提取 command + txt_content
  Layer 2: command 解密 txt_content → 最终明文
"""

import base64
import hashlib
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad


# 全局 API 密钥（硬编码在 App 中，来自开源参考项目）
DEFAULT_API_KEY = "zG2nSeEfSHfvTCHy5LCcqtBbQehKNLXn"


def aes_decrypt(ciphertext_bytes: bytes, key_str: str) -> bytes:
    """AES-256-CBC 解密，key=SHA256(key_str)，IV=16 字节零。"""
    key = hashlib.sha256(key_str.encode("utf-8")).digest()
    iv = bytes([0] * 16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    plaintext = unpad(cipher.decrypt(ciphertext_bytes), AES.block_size)
    return plaintext


def decrypt_response(response_b64: str, key_str: str = DEFAULT_API_KEY) -> bytes:
    """解密 API 响应：Base64 解码 → AES-256-CBC 解密。"""
    ciphertext = base64.b64decode(response_b64)
    return aes_decrypt(ciphertext, key_str)


def decrypt_chapter(content_b64: str, command_key: str) -> bytes:
    """解密章节内容（第二层加密）：Base64 → AES-256-CBC(command_key)。"""
    ciphertext = base64.b64decode(content_b64)
    return aes_decrypt(ciphertext, command_key)
