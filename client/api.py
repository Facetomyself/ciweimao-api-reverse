"""API 端点封装。

每个方法自动附加认证参数（login_token, account, device_token, app_version），
自动解密响应，返回解析后的 JSON dict。
"""

import json
import requests
from . import content, crypto, config, protocol


class ApiError(RuntimeError):
    """刺猬猫 API 返回的业务错误。"""

    def __init__(self, code: str, tip: str = ""):
        self.code = str(code)
        self.tip = tip
        super().__init__(f"API 错误 code={self.code}: {tip}")


class Session:
    """无状态的 API 会话。每次调用自动附加认证参数。"""

    def __init__(self, login_token: str, account: str,
                 device_token: str = "ciweimao_",
                 app_version: str = config.APP_VERSION,
                 base_url: str = None,
                 rand_factory=None):
        self.login_token = login_token
        self.account = account
        self.device_token = device_token
        self.app_version = app_version
        self.base_url = base_url or config.base_url_for_version(app_version)
        self._rand_factory = rand_factory
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": f"Android com.kuangxiangciweimao.novel {app_version}",
            "Content-Type": "application/x-www-form-urlencoded",
        })

    def _auth_params(self) -> dict:
        params = {
            "login_token": self.login_token,
            "account": self.account,
            "device_token": self.device_token,
            "app_version": self.app_version,
        }
        if config.uses_signed_transport(self.app_version):
            rand_str = self._rand_factory() if self._rand_factory else None
            params.update(protocol.sign_request(
                self.account,
                self.app_version,
                rand_str=rand_str,
            ))
        return params

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

        # 新旧 App 都返回 Base64 + AES-CBC；少数网关错误可能直接返回 JSON。
        try:
            raw = resp.text.strip()
            if raw.startswith("{"):
                data = json.loads(raw)
            else:
                plaintext = crypto.decrypt_response_for_version(
                    raw, self.app_version)
                data = json.loads(plaintext)
        except Exception as e:
            raise RuntimeError(f"解密/解析失败: {e}")

        code = data.get("code", "")
        if code != "100000":
            tip = data.get("tip", "")
            if code == "200100":
                raise RuntimeError("login_token 已过期，请重新提取")
            raise ApiError(code, tip)

        return data

    # ---- Reader ----

    def get_my_info(self) -> dict:
        """验证 token 有效性，返回用户信息。"""
        return self._call("/reader/get_my_info")

    # ---- Book ----

    def get_book_info(self, book_id: str) -> dict:
        """获取书籍详情。"""
        return self._call("/book/get_info_by_id", {
            "book_id": book_id,
            "use_daguan": "0",
        })

    def get_division_list(self, book_id: str) -> dict:
        """获取分卷列表。"""
        return self._call("/book/get_division_list", {"book_id": book_id})

    def get_book_catalog(self, book_id: str) -> dict:
        """一次获取整本书的分卷与章节目录。"""
        return self._call(
            "/chapter/get_updated_chapter_by_division_new",
            {"book_id": book_id, "division_id": "0"},
        )

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
        """获取章节正文，兼容内联 AES 与新版 CDN/zlib 两条路径。"""
        data = self._call("/chapter/get_cpt_ifm", {
            "chapter_id": chapter_id,
            "chapter_command": command,
        })
        chapter_info = data.get("data", {}).get("chapter_info", {})
        txt_content = chapter_info.get("txt_content", "")
        if not txt_content:
            return ""
        if str(txt_content).startswith(("http://", "https://")):
            resp = self._session.get(
                txt_content,
                headers={"Accept-Encoding": "gzip"},
                timeout=30,
            )
            resp.raise_for_status()
            return content.decode_cdn_payload(resp.content)
        plaintext = crypto.decrypt_chapter(txt_content, command)
        return content.normalize_chapter_text(
            plaintext.decode("utf-8", errors="replace"))

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
        seen_book_ids = set()
        if shelf_id:
            shelves = [{"shelf_id": shelf_id}]
        else:
            shelves = self.get_shelf_list()

        for shelf in shelves:
            sid = shelf.get("shelf_id", "")
            sname = shelf.get("shelf_name", sid)
            page = 1
            seen_pages = set()
            while True:
                books = self.get_shelf_books(sid, page=page, count=50)
                if not books:
                    break
                page_signature = tuple(
                    str(item.get("book_info", {}).get("book_id", ""))
                    for item in books
                )
                if page_signature in seen_pages:
                    break
                seen_pages.add(page_signature)
                for b in books:
                    info = dict(b.get("book_info", {}))
                    book_id = str(info.get("book_id", ""))
                    if not book_id or book_id in seen_book_ids:
                        continue
                    seen_book_ids.add(book_id)
                    info["_shelf_name"] = sname
                    all_books.append(info)
                if len(books) < 50:
                    break
                page += 1
        return all_books

    # ---- Search ----

    def search_books(self, keyword: str, page: int = 0,
                     count: int = 10) -> dict:
        """搜索书籍。App 搜索页使用从 0 开始的页码。"""
        count = max(1, min(int(count), 10))
        return self._call("/bookcity/get_filter_search_book_list", {
            "key": keyword,
            "page": str(page),
            "count": str(count),
            "category_index": "0",
            "filter_uptime": "",
            "filter_word": "",
            "is_paid": "",
            "order": "",
            "tags": "[]",
            "up_status": "",
            "use_daguan": "0",
        })

    def iter_search_books(self, keyword: str, max_pages: int = None,
                          count: int = 10):
        """分页搜索并按 book_id 去重。"""
        yield from self._iter_book_pages(
            lambda page: self.search_books(keyword, page=page, count=count)
            .get("data", {}).get("book_list", []),
            max_pages=max_pages,
        )

    # ---- Book city / whole site ----

    def get_bookcity_books(self, page: int = 0, count: int = 100,
                           order: str = "uptime") -> list[dict]:
        """获取书城全量列表的一页。

        `order=uptime` 实测可稳定连续分页；`newtime` 只覆盖较小的新书窗口。
        """
        count = max(1, min(int(count), 100))
        data = self._call("/bookcity/get_filter_book_list", {
            "tab_type": "200",
            "count": str(count),
            "page": str(page),
            "order": order,
        })
        return data.get("data", {}).get("book_list", [])

    def iter_all_books(self, max_pages: int = None, count: int = 100,
                       order: str = "uptime"):
        """遍历书城列表，遇空页或整页重复时停止。"""
        yield from self._iter_book_pages(
            lambda page: self.get_bookcity_books(
                page=page, count=count, order=order),
            max_pages=max_pages,
        )

    @staticmethod
    def _iter_book_pages(fetch_page, max_pages: int = None):
        seen_ids = set()
        seen_pages = set()
        page = 0
        while max_pages is None or page < max_pages:
            books = list(fetch_page(page) or [])
            if not books:
                break
            signature = tuple(str(item.get("book_id", "")) for item in books)
            if signature in seen_pages:
                break
            seen_pages.add(signature)
            added = 0
            for book in books:
                book_id = str(book.get("book_id", ""))
                if not book_id or book_id in seen_ids:
                    continue
                seen_ids.add(book_id)
                added += 1
                yield book
            if added == 0:
                break
            page += 1
