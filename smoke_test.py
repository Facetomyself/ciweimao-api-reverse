"""当前 App 2.9.362 协议的只读连通性检查。"""

import json
import sys
from pathlib import Path

from client import config
from client.api import Session


TOKEN_PATH = Path(__file__).with_name("tokens.json")


def main() -> bool:
    with open(TOKEN_PATH, "r", encoding="utf-8") as handle:
        tokens = json.load(handle)

    session = Session(
        login_token=tokens["login_token"],
        account=tokens["account"],
        device_token=tokens.get("device_token", "ciweimao_"),
        app_version=config.APP_VERSION,
    )

    print(f"[INFO] App protocol: {config.APP_VERSION}")
    try:
        session.get_my_info()
        print("[PASS] 游客/登录凭据有效")

        search = session.search_books("青春", page=0, count=10)
        search_books = search.get("data", {}).get("book_list", [])
        if len(search_books) != 10:
            raise RuntimeError(f"搜索第一页条数异常: {len(search_books)}")
        print("[PASS] 当前 App 搜索链返回 10 本")

        city_books = session.get_bookcity_books(
            page=0, count=100, order="uptime")
        if len(city_books) != 100:
            raise RuntimeError(f"书城第一页条数异常: {len(city_books)}")
        print("[PASS] 书城全站入口返回 100 本")

        print("[CONCLUSION] 当前签名、响应解密、搜索和书城分页均可用")
        return True
    except Exception as exc:
        print(f"[FAIL] {exc}")
        return False


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
