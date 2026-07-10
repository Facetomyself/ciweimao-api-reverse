"""API 端点封装。

每个方法自动附加认证参数（login_token, account, device_token, app_version），
自动解密响应，返回解析后的 JSON dict。
"""

import json
import requests
from . import crypto, config


class Session:
    """无状态的 API 会话。每次调用自动附加认证参数。"""

    def __init__(self, login_token: str, account: str,
                 device_token: str = "ciweimao_",
                 app_version: str = config.APP_VERSION,
                 base_url: str = config.BASE_URL):
        self.login_token = login_token
        self.account = account
        self.device_token = device_token
        self.app_version = app_version
        self.base_url = base_url
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": f"Android com.kuangxiangciweimao.novel {app_version}",
            "Content-Type": "application/x-www-form-urlencoded",
        })

    def _auth_params(self) -> dict:
        return {
            "login_token": self.login_token,
            "account": self.account,
            "device_token": self.device_token,
            "app_version": self.app_version,
        }

    def _call(self, endpoint: str, extra_params: dict = None) -> dict:
        """发送 API 请求，自动解密响应，返回 JSON dict。

        Raises:
            RuntimeError: 当 token 过期或请求失败时。
        """
        params = self._auth_params()
        if extra_params:
            params.update(extra_params)

        url = f"{self.base_url}{endpoint}"
        resp = self._session.post(url, data=params, timeout=30)

        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        # 解密 + 解析
        try:
            plaintext = crypto.decrypt_response(resp.text.strip())
            data = json.loads(plaintext)
        except Exception as e:
            raise RuntimeError(f"解密/解析失败: {e}")

        code = data.get("code", "")
        if code != "100000":
            tip = data.get("tip", "")
            if code == "200100":
                raise RuntimeError("login_token 已过期，请重新提取")
            raise RuntimeError(f"API 错误 code={code}: {tip}")

        return data

    # ---- Reader ----

    def get_my_info(self) -> dict:
        """验证 token 有效性，返回用户信息。"""
        return self._call("/reader/get_my_info")

    # ---- Book ----

    def get_book_info(self, book_id: str) -> dict:
        """获取书籍详情。"""
        return self._call("/book/get_info_by_id", {"book_id": book_id})

    def get_division_list(self, book_id: str) -> dict:
        """获取分卷列表。"""
        return self._call("/book/get_division_list", {"book_id": book_id})

    # ---- Chapter ----

    def get_chapter_list(self, division_id: str) -> dict:
        """获取某卷的章节列表。"""
        return self._call(
            "/chapter/get_updated_chapter_by_division_id",
            {"division_id": division_id},
        )

    def get_chapter_command(self, chapter_id: str) -> str:
        """获取章节内容解密密钥（command）。"""
        data = self._call("/chapter/get_chapter_cmd",
                          {"chapter_id": chapter_id})
        return data.get("data", {}).get("command", "")

    def get_chapter_content(self, chapter_id: str, command: str) -> str:
        """获取并解密章节正文。返回纯文本。"""
        data = self._call("/chapter/get_cpt_ifm", {
            "chapter_id": chapter_id,
            "chapter_command": command,
        })
        chapter_info = data.get("data", {}).get("chapter_info", {})
        txt_encrypted = chapter_info.get("txt_content", "")
        if not txt_encrypted:
            return ""
        plaintext = crypto.decrypt_chapter(txt_encrypted, command)
        return plaintext.decode("utf-8", errors="replace")

    # ---- Bookshelf ----

    def get_shelf_list(self) -> list[dict]:
        """获取所有书架。"""
        data = self._call("/bookshelf/get_shelf_list")
        return data.get("data", {}).get("shelf_list", [])

    def get_shelf_books(self, shelf_id: str,
                        page: int = 1, count: int = 50) -> list[dict]:
        """获取某个书架上的书籍列表。"""
        data = self._call("/bookshelf/get_shelf_book_list", {
            "shelf_id": shelf_id,
            "page": str(page),
            "count": str(count),
        })
        return data.get("data", {}).get("book_list", [])

    def get_all_shelf_books(self, shelf_id: str = None) -> list[dict]:
        """获取全部书架上的所有书籍。

        Args:
            shelf_id: 指定书架 ID。为 None 时获取所有书架的全部书籍。
        """
        all_books = []
        if shelf_id:
            shelves = [{"shelf_id": shelf_id}]
        else:
            shelves = self.get_shelf_list()

        for shelf in shelves:
            sid = shelf.get("shelf_id", "")
            sname = shelf.get("shelf_name", sid)
            page = 1
            while True:
                books = self.get_shelf_books(sid, page=page, count=50)
                if not books:
                    break
                for b in books:
                    info = b.get("book_info", {})
                    info["_shelf_name"] = sname
                    all_books.append(info)
                if len(books) < 50:
                    break
                page += 1
        return all_books

    # ---- Search ----

    def search_books(self, keyword: str, page: int = 1,
                     count: int = 20) -> dict:
        """搜索书籍。"""
        return self._call("/bookcity/get_filter_search_book_list", {
            "key": keyword,
            "page": str(page),
            "count": str(count),
        })
