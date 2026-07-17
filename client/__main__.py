"""Ciweimao App API 免费章节抓取 CLI。"""

import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from client import api, config, downloader, models


_ADB_PATHS = [
    r"D:\reverse_ENV\tools\adb\adb.exe",
    r"D:\leidian\LDPlayer9\adb.exe",
    "adb",
]

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "tokens.json"
OUTPUT_DIR = ROOT / "output"


def _find_adb() -> str:
    for path in _ADB_PATHS:
        try:
            result = subprocess.run(
                [path, "version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return path
        except Exception:
            continue
    raise FileNotFoundError("找不到 adb，请安装或配置项目 ADB")


def _load_tokens() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[ERR] 找不到 {CONFIG_PATH}")
        print("  先打开官方 App 一次，再运行: python -m client token-extract")
        raise SystemExit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_session() -> api.Session:
    tokens = _load_tokens()
    return api.Session(
        login_token=tokens["login_token"],
        account=tokens["account"],
        device_token=tokens.get("device_token", "ciweimao_"),
        # app_version 属于协议，不属于凭据。CLI 始终复现当前 App 链路，
        # 避免旧 tokens.json 中的 2.9.312 把搜索降级成不完整结果。
        app_version=config.APP_VERSION,
    )


def _mask(value: str, prefix: int = 4, suffix: int = 2) -> str:
    text = str(value or "")
    if len(text) <= prefix + suffix:
        return "*" * len(text)
    return f"{text[:prefix]}...{text[-suffix:]}"


def _table(headers: list, rows: list, max_widths: list = None):
    if not rows:
        print("  (空)")
        return
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(str(cell)))
    if max_widths:
        for index, max_width in enumerate(max_widths):
            if max_width > 0:
                widths[index] = min(widths[index], max_width)
    separator = "+" + "+".join("-" * (width + 2)
                                   for width in widths) + "+"
    print(separator)
    print("|" + "|".join(
        f" {header:<{widths[index]}} "
        for index, header in enumerate(headers)) + "|")
    print(separator)
    for row in rows:
        cells = []
        for index, cell in enumerate(row):
            value = str(cell)
            if len(value) > widths[index]:
                value = value[:widths[index] - 1] + "…"
            cells.append(f" {value:<{widths[index]}} ")
        print("|" + "|".join(cells) + "|")
    print(separator)


def _fmt_words(value: str) -> str:
    try:
        number = int(value)
    except (ValueError, TypeError):
        return str(value)
    if number >= 10000:
        return f"{number / 10000:.1f}万"
    return str(number)


def _book_rows(books):
    return [[
        book.get("book_id", "?"),
        book.get("book_name", "?")[:30],
        book.get("author_name", "?")[:12],
        _fmt_words(book.get("total_word_count", "0")),
        "免费" if str(book.get("is_paid", "1")) == "0" else "付费书",
    ] for book in books]


def cmd_list():
    session = _build_session()
    print("[INFO] 正在获取书架...")
    books = session.get_all_shelf_books()
    rows = []
    for book in books:
        rows.append([
            book.get("book_id", "?"),
            book.get("book_name", "?")[:30],
            book.get("author_name", "?")[:12],
            _fmt_words(book.get("total_word_count", "0")),
            book.get("_shelf_name", "?")[:8],
        ])
    _table(["Book ID", "书名", "作者", "字数", "书架"], rows,
           [10, 30, 12, 8, 8])


def cmd_search(keyword: str, max_pages: int = 1):
    session = _build_session()
    page_limit = None if max_pages == 0 else max_pages
    print(f'[INFO] 搜索: "{keyword}"...')
    books = list(session.iter_search_books(
        keyword, max_pages=page_limit, count=10))
    _table(["Book ID", "书名", "作者", "字数", "类型"],
           _book_rows(books), [10, 30, 12, 8, 8])
    print(f"[SUMMARY] 去重后 {len(books)} 本")
    return books


def _resolve_book_info(session: api.Session, book_id: str,
                       book_info: dict = None) -> dict:
    info = dict(book_info or {})
    if info:
        return info
    try:
        data = session.get_book_info(book_id)
        return data.get("data", {}).get("book_info", {})
    except api.ApiError as exc:
        if exc.code != "320001":
            raise
        for shelf_book in session.get_all_shelf_books():
            if str(shelf_book.get("book_id")) == str(book_id):
                return shelf_book
        return {"book_id": book_id, "book_name": book_id}


def cmd_download(book_id: str, session=None, book_info=None,
                 skip_existing: bool = False, free_only: bool = False,
                 include_book_id: bool = False,
                 chapter_delay: float = 0.05):
    active_session = session or _build_session()
    info = _resolve_book_info(active_session, book_id, book_info)
    name = info.get("book_name", book_id)
    stem = models.safe_book_name(name)
    if include_book_id:
        stem = f"{book_id} - {stem}"
    candidate = OUTPUT_DIR / f"{stem}.txt"
    if skip_existing and candidate.exists():
        print(f"[SKIP] 已存在: {candidate.name}")
        return "skipped"

    mode = "免费章节" if free_only else "可读章节"
    print(f"[INFO] 下载{mode}: {name} ({book_id})")
    started = time.time()

    def on_progress(current, total):
        elapsed = max(time.time() - started, 0.01)
        rate = current / elapsed
        percent = current * 100 // total if total else 0
        bar = "#" * (percent // 3) + "-" * (33 - percent // 3)
        eta = (total - current) / rate if rate > 0 else 0
        print(f"\r  [{bar}] {current}/{total} ({percent}%) "
              f"{rate:.1f}ch/s ETA:{eta:.0f}s", end="", flush=True)

    try:
        output_path = downloader.download_book(
            active_session,
            book_id,
            output_dir=str(OUTPUT_DIR),
            progress_callback=on_progress,
            book_info=info,
            skip_existing=skip_existing,
            free_only=free_only,
            include_book_id=include_book_id,
            chapter_delay=chapter_delay,
        )
        elapsed = time.time() - started
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"\n[OK] {output_path} ({size_mb:.2f}MB, {elapsed:.0f}s)")
        return "downloaded"
    except downloader.NoDownloadableChapters as exc:
        print(f"\n[EMPTY] {exc}")
        return "no_free"
    except Exception as exc:
        print(f"\n[ERR] 下载失败: {exc}")
        return "failed"


def _crawl_books(session: api.Session, books, max_books: int = None,
                 chapter_delay: float = 0.05, free_only: bool = True,
                 include_book_id: bool = True):
    stats = {"downloaded": 0, "skipped": 0, "no_free": 0, "failed": 0}
    processed = 0
    for book in books:
        if max_books is not None and processed >= max_books:
            break
        processed += 1
        book_id = str(book.get("book_id", ""))
        if not book_id:
            continue
        print(f"\n[{processed}] {book.get('book_name', book_id)} ({book_id})")
        result = cmd_download(
            book_id,
            session=session,
            book_info=book,
            skip_existing=True,
            free_only=free_only,
            include_book_id=include_book_id,
            chapter_delay=chapter_delay,
        )
        stats[result] += 1
    print("\n[SUMMARY] "
          f"处理 {processed}，新增 {stats['downloaded']}，"
          f"跳过 {stats['skipped']}，无免费章 {stats['no_free']}，"
          f"失败 {stats['failed']}")
    return stats


def cmd_crawl_search(keyword: str, max_pages: int = 0,
                     max_books: int = None,
                     chapter_delay: float = 0.05):
    session = _build_session()
    page_limit = None if max_pages == 0 else max_pages
    books = session.iter_search_books(
        keyword, max_pages=page_limit, count=10)
    return _crawl_books(
        session, books, max_books=max_books, chapter_delay=chapter_delay)


def cmd_crawl_all(max_pages: int = 0, max_books: int = None,
                  order: str = "uptime", chapter_delay: float = 0.05):
    session = _build_session()
    page_limit = None if max_pages == 0 else max_pages
    books = session.iter_all_books(
        max_pages=page_limit, count=100, order=order)
    return _crawl_books(
        session, books, max_books=max_books, chapter_delay=chapter_delay)


def cmd_download_all():
    session = _build_session()
    books = session.get_all_shelf_books()
    return _crawl_books(
        session, books, free_only=False, include_book_id=False)


def cmd_token():
    tokens = _load_tokens()
    print("当前凭据:")
    print(f"  login_token: {_mask(tokens.get('login_token', ''), 8, 4)}")
    print(f"  account: {_mask(tokens.get('account', ''), 3, 2)}")
    print(f"  device_token: {_mask(tokens.get('device_token', ''), 8, 2)}")
    print(f"  app_version: {config.APP_VERSION} (当前协议)")
    session = _build_session()
    try:
        data = session.get_my_info()
        reader = data.get("data", {}).get("reader_info", {})
        print("\nToken 状态: 有效")
        print(f"  昵称: {reader.get('reader_name', '?')}")
        print(f"  是否绑定: {reader.get('is_bind', '?')}")
        print(f"  VIP Lv: {reader.get('vip_lv', '?')}")
    except Exception as exc:
        print(f"\nToken 状态: 无效 - {exc}")


def cmd_token_extract(device: str = None):
    """提取 App 自动生成的游客凭据或正式账号凭据。"""
    print("[INFO] 正在从 App 提取游客/登录凭据...")
    adb_exe = _find_adb()
    result = subprocess.run(
        [adb_exe, "devices"], capture_output=True, text=True, timeout=5)
    devices = [line.split("\t")[0]
               for line in result.stdout.strip().split("\n")[1:]
               if "\tdevice" in line]
    if device:
        if device not in devices:
            raise SystemExit(f"[ERR] 指定设备未连接: {device}")
        selected = device
    elif len(devices) == 1:
        selected = devices[0]
    elif not devices:
        raise SystemExit("[ERR] 未检测到 ADB 设备")
    else:
        raise SystemExit("[ERR] 检测到多个设备，请传 --device SERIAL")
    print(f"[INFO] 使用设备: {selected}")

    prefs_path = ("/data/data/com.kuangxiangciweimao.novel/"
                  "shared_prefs/com.kuangxiangciweimao.novel_preferences.xml")
    result = subprocess.run(
        [adb_exe, "-s", selected, "shell", "su", "-c",
         f"cat '{prefs_path}'"],
        capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise SystemExit("[ERR] 读取 App 私有配置失败，请确认 Root")
    match = re.search(r'LoginedUser">(\{.*?\})</string>', result.stdout)
    if not match:
        raise SystemExit("[ERR] 未找到游客身份；请先打开官方 App 一次")

    user_data = json.loads(html.unescape(match.group(1)))
    login_token = user_data.get("loginToken", "")
    reader_info = user_data.get("readerInfo", {})
    account = reader_info.get("account", "")
    if not login_token or not account:
        raise SystemExit("[ERR] App 凭据不完整")

    device_xml = ("/data/data/com.kuangxiangciweimao.novel/"
                  "shared_prefs/device.xml")
    result = subprocess.run(
        [adb_exe, "-s", selected, "shell", "su", "-c",
         f"cat '{device_xml}'"],
        capture_output=True, text=True, timeout=5)
    device_match = re.search(r'deviceID">(.*?)</string>', result.stdout)
    device_token = device_match.group(1) if device_match else "ciweimao_"

    tokens = {
        "login_token": login_token,
        "account": account,
        "device_token": device_token,
        "app_version": config.APP_VERSION,
    }
    with open(CONFIG_PATH, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(tokens, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"[OK] 凭据已保存到 {CONFIG_PATH}")
    print(f"  account: {_mask(account, 3, 2)}")
    print(f"  login_token: {_mask(login_token, 8, 4)}")
    print(f"  身份: {'已绑定账号' if reader_info.get('is_bind') == '1' else '游客'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="刺猬猫 App API 搜索与全站免费章节抓取")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("token", help="验证本地凭据")
    extract = sub.add_parser("token-extract", help="从 Root 设备提取游客/登录凭据")
    extract.add_argument("--device", help="ADB serial")
    sub.add_parser("list", help="列出账号书架（兼容命令）")

    search = sub.add_parser("search", help="分页搜索书籍")
    search.add_argument("keyword")
    search.add_argument("--max-pages", type=int, default=1,
                        help="最多页数，0 表示直到空页")

    download = sub.add_parser("download", help="下载指定书籍")
    download.add_argument("book_id")
    download.add_argument("--free-only", action="store_true",
                          help="只导出免费章节")
    download.add_argument("--include-book-id", action="store_true")
    download.add_argument("--chapter-delay", type=float, default=0.05)

    sub.add_parser("download-all", help="下载书架可读内容（兼容命令）")

    crawl_search = sub.add_parser("crawl-search", help="抓取搜索结果中的免费章节")
    crawl_search.add_argument("keyword")
    crawl_search.add_argument("--max-pages", type=int, default=0)
    crawl_search.add_argument("--max-books", type=int)
    crawl_search.add_argument("--chapter-delay", type=float, default=0.05)

    crawl_all = sub.add_parser("crawl-all", help="遍历书城并抓取免费章节")
    crawl_all.add_argument("--max-pages", type=int, default=0)
    crawl_all.add_argument("--max-books", type=int)
    crawl_all.add_argument("--order", choices=("uptime", "newtime"),
                           default="uptime")
    crawl_all.add_argument("--chapter-delay", type=float, default=0.05)
    crawl_all.add_argument("--yes", action="store_true",
                           help="确认执行不设上限的全站任务")
    return parser


def main():
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        cmd_download(sys.argv[1])
        return
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "token":
        cmd_token()
    elif args.command == "token-extract":
        cmd_token_extract(args.device)
    elif args.command == "list":
        cmd_list()
    elif args.command == "search":
        cmd_search(args.keyword, args.max_pages)
    elif args.command == "download":
        cmd_download(
            args.book_id,
            free_only=args.free_only,
            include_book_id=args.include_book_id,
            chapter_delay=args.chapter_delay,
        )
    elif args.command == "download-all":
        cmd_download_all()
    elif args.command == "crawl-search":
        cmd_crawl_search(
            args.keyword, args.max_pages, args.max_books,
            args.chapter_delay)
    elif args.command == "crawl-all":
        if (args.max_pages == 0 and args.max_books is None
                and not args.yes):
            parser.error("无限制全站抓取需显式传 --yes")
        cmd_crawl_all(
            args.max_pages, args.max_books, args.order,
            args.chapter_delay)


if __name__ == "__main__":
    main()
