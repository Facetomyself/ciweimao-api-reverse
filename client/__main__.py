"""Ciweimao API 下载器 CLI。

用法:
  python -m client list             列出书架全部书籍
  python -m client search <关键词>   搜索书籍
  python -m client download <书ID>  下载指定书籍
  python -m client download-all     下载书架中尚未导出的书籍
  python -m client token            查看登录凭据状态
  python -m client token-extract    从模拟器自动提取 token
"""

import sys
import os
import json
import time
import subprocess
from pathlib import Path

# ADB 路径（支持多位置查找）
_ADB_PATHS = [
    r"D:\reverse_ENV\tools\adb\adb.exe",
    r"D:\leidian\LDPlayer9\adb.exe",
    "adb",  # fallback: 从 PATH 中查找
]


def _find_adb() -> str:
    """查找可用的 adb 可执行文件。"""
    for p in _ADB_PATHS:
        try:
            result = subprocess.run([p, "version"],
                                    capture_output=True, timeout=5)
            if result.returncode == 0:
                return p
        except Exception:
            continue
    raise FileNotFoundError("找不到 adb，请安装或设置 PATH")

from client import api, downloader, models

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "tokens.json"
OUTPUT_DIR = ROOT / "output"


def _load_tokens() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[ERR] 找不到 {CONFIG_PATH}")
        print("  请先运行: python -m client token-extract (从模拟器提取)")
        print("  或手动创建 tokens.json")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_session() -> api.Session:
    t = _load_tokens()
    return api.Session(
        login_token=t["login_token"],
        account=t["account"],
        device_token=t.get("device_token", "ciweimao_"),
        app_version=t.get("app_version", "2.9.312"),
    )


def _table(headers: list, rows: list, max_widths: list = None):
    """打印对齐表格。"""
    if not rows:
        print("  (空)")
        return
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    if max_widths:
        for i, mw in enumerate(max_widths):
            if mw > 0:
                widths[i] = min(widths[i], mw)
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    header_line = "|" + "|".join(f" {h:<{widths[i]}} " for i, h in enumerate(headers)) + "|"
    print(sep)
    print(header_line)
    print(sep)
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            s = str(cell)
            if len(s) > widths[i]:
                s = s[:widths[i] - 1] + "…"
            cells.append(f" {s:<{widths[i]}} ")
        print("|" + "|".join(cells) + "|")
    print(sep)


# ============================================================
# Commands
# ============================================================

def cmd_list():
    """列出书架全部书籍。"""
    s = _build_session()
    print("[INFO] 正在获取书架...")
    books = s.get_all_shelf_books()
    if not books:
        print("[WARN] 书架为空")
        return

    rows = []
    for b in books:
        rows.append([
            b.get("book_id", "?"),
            b.get("book_name", "?")[:30],
            b.get("author_name", "?")[:12],
            _fmt_words(b.get("total_word_count", "0")),
            b.get("_shelf_name", "?")[:8],
        ])
    _table(["Book ID", "书名", "作者", "字数", "书架"], rows,
           [10, 30, 12, 8, 8])


def cmd_search(keyword: str):
    """搜索书籍。"""
    s = _build_session()
    print(f'[INFO] 搜索: "{keyword}"...')
    data = s.search_books(keyword)
    book_list = data.get("data", {}).get("book_list", [])
    if not book_list:
        print("[WARN] 未找到结果")
        return

    rows = []
    for b in book_list:
        rows.append([
            b.get("book_id", "?"),
            b.get("book_name", "?")[:30],
            b.get("author_name", "?")[:12],
            _fmt_words(b.get("total_word_count", "0")),
        ])
    _table(["Book ID", "书名", "作者", "字数"], rows, [10, 30, 12, 8])


def cmd_download(book_id: str, session=None, book_info=None,
                 skip_existing: bool = False):
    """下载一本书。"""
    s = session or _build_session()

    # 获取书名
    info = dict(book_info or {})
    name = info.get("book_name", book_id)
    if not info:
        try:
            data = s.get_book_info(book_id)
            info = data.get("data", {}).get("book_info", {})
            name = info.get("book_name", book_id)
        except api.ApiError as exc:
            if exc.code == "320001":
                for shelf_book in s.get_all_shelf_books():
                    if str(shelf_book.get("book_id")) == str(book_id):
                        info = shelf_book
                        name = info.get("book_name", book_id)
                        break
            else:
                raise

    output_path = OUTPUT_DIR / f"{models.safe_book_name(name)}.txt"
    if skip_existing and output_path.exists():
        print(f"[SKIP] 已存在: {output_path.name}")
        return "skipped"

    print(f'[INFO] 下载: {name} ({book_id})')
    start = time.time()

    def on_progress(current, total):
        elapsed = max(time.time() - start, 0.01)
        rate = current / elapsed
        pct = current * 100 // total if total else 0
        bar = "#" * (pct // 3) + "-" * (33 - pct // 3)
        eta = (total - current) / rate if rate > 0 else 0
        print(f"\r  [{bar}] {current}/{total} ({pct}%) "
              f"{rate:.1f}ch/s ETA:{eta:.0f}s", end="", flush=True)

    try:
        output_path = downloader.download_book(
            s, book_id, output_dir=str(OUTPUT_DIR),
            progress_callback=on_progress, book_info=info,
            skip_existing=skip_existing)
        elapsed = time.time() - start
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"\n[OK] {output_path} ({size_mb:.1f}MB, {elapsed:.0f}s)")
    except Exception as e:
        print(f"\n[ERR] 下载失败: {e}")
        return "failed"
    return "downloaded"


def cmd_download_all():
    """下载书架中尚未导出的书籍。"""
    s = _build_session()
    print("[INFO] 获取书架...")
    books = s.get_all_shelf_books()
    print(f"[INFO] 共 {len(books)} 本书")

    stats = {"downloaded": 0, "skipped": 0, "failed": 0}
    for i, b in enumerate(books):
        bid = b.get("book_id", "")
        name = b.get("book_name", bid)
        print(f"\n[{i + 1}/{len(books)}] {name} ({bid})")
        result = cmd_download(
            bid, session=s, book_info=b, skip_existing=True)
        stats[result] += 1
    print("\n[SUMMARY] "
          f"新增 {stats['downloaded']}，跳过 {stats['skipped']}，"
          f"失败 {stats['failed']}")


def cmd_token():
    """显示当前 token 信息。"""
    t = _load_tokens()
    print("当前凭据:")
    for k, v in t.items():
        if k in ("login_token",):
            print(f"  {k}: {v[:12]}... ({len(v)} chars)")
        else:
            print(f"  {k}: {v}")

    s = _build_session()
    try:
        data = s.get_my_info()
        reader = data.get("data", {}).get("reader_info", {})
        print(f"\nToken 状态: 有效")
        print(f"  昵称: {reader.get('reader_name', '?')}")
        print(f"  ID: {reader.get('reader_id', '?')}")
        print(f"  VIP Lv: {reader.get('vip_lv', '?')}")
        print(f"  Exp Lv: {reader.get('exp_lv', '?')}")
    except Exception as e:
        print(f"\nToken 状态: 无效 - {e}")


def cmd_token_extract():
    """从模拟器自动提取 token。"""
    print("[INFO] 正在从模拟器提取登录凭据...")

    # 检测 ADB 设备
    try:
        adb_exe = _find_adb()
        result = subprocess.run(
            [adb_exe, "devices"], capture_output=True, text=True, timeout=5)
        lines = result.stdout.strip().split("\n")[1:]
        devices = [l.split("\t")[0] for l in lines if "\tdevice" in l]
    except Exception:
        print("[ERR] 找不到 adb 命令，请确保 ADB 在 PATH 中")
        sys.exit(1)

    if not devices:
        print("[ERR] 未检测到 ADB 设备，请确保模拟器已开启并连接")
        sys.exit(1)

    device = devices[0]
    print(f"[INFO] 使用设备: {device}")

    # 提取 token
    prefs_path = ("/data/data/com.kuangxiangciweimao.novel/"
                  "shared_prefs/com.kuangxiangciweimao.novel_preferences.xml")

    try:
        result = subprocess.run(
            [adb_exe, "-s", device, "shell",
             "su", "-c", f"cat '{prefs_path}'"],
            capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            print(f"[ERR] 读取失败: {result.stderr}")
            print("[HINT] 需要 root 权限，请确认模拟器已 root")
            sys.exit(1)
    except Exception as e:
        print(f"[ERR] ADB 错误: {e}")
        sys.exit(1)

    # 解析 LoginedUser JSON
    import re
    import html
    match = re.search(r'LoginedUser">(\{.*?\})</string>', result.stdout)
    if not match:
        print("[ERR] 未找到登录信息，请确认 App 已登录")
        sys.exit(1)

    user_data = json.loads(html.unescape(match.group(1)))
    login_token = user_data.get("loginToken", "")
    reader_info = user_data.get("readerInfo", {})
    account = reader_info.get("account", "")
    internal_ver = user_data.get("internal_version", "2.9.312")

    if not login_token or not account:
        print("[ERR] 凭据不完整")
        sys.exit(1)

    # 获取 device_token
    device_xml = ("/data/data/com.kuangxiangciweimao.novel/"
                  "shared_prefs/device.xml")
    try:
        result = subprocess.run(
            [adb_exe, "-s", device, "shell",
             "su", "-c", f"cat '{device_xml}'"],
            capture_output=True, text=True, timeout=5)
        dev_match = re.search(r'deviceID">(.*?)</string>', result.stdout)
        device_token = dev_match.group(1) if dev_match else "ciweimao_"
    except Exception:
        device_token = "ciweimao_"

    # 写入配置
    tokens = {
        "login_token": login_token,
        "account": account,
        "device_token": device_token,
        "app_version": internal_ver,
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(tokens, f, ensure_ascii=False, indent=2)

    print(f"[OK] 凭据已保存到 {CONFIG_PATH}")
    print(f"  login_token: {login_token[:12]}...")
    print(f"  account: {account}")
    print(f"  device_token: {device_token}")
    print(f"  app_version: {internal_ver}")
    print(f"  昵称: {reader_info.get('reader_name', '?')}")
    print(f"\n现在可以运行: python -m client list")


# ============================================================
# Helpers
# ============================================================

def _fmt_words(n: str) -> str:
    """格式化字数。"""
    try:
        n = int(n)
    except (ValueError, TypeError):
        return str(n)
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return str(n)


def _usage():
    print(__doc__)
    print("命令:")
    print("  list              列出书架全部书籍")
    print("  search <关键词>    搜索书籍")
    print("  download <书ID>    下载指定书籍")
    print("  download-all       下载书架中尚未导出的书籍")
    print("  token              查看当前凭据状态")
    print("  token-extract      从模拟器自动提取 token")


# ============================================================
# Main
# ============================================================

def main():
    if len(sys.argv) < 2:
        _usage()
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "list":
        cmd_list()
    elif cmd == "search":
        if len(sys.argv) < 3:
            print("Usage: python -m client search <关键词>")
            sys.exit(1)
        cmd_search(sys.argv[2])
    elif cmd == "download":
        if len(sys.argv) < 3:
            print("Usage: python -m client download <书ID>")
            sys.exit(1)
        cmd_download(sys.argv[2])
    elif cmd == "download-all":
        cmd_download_all()
    elif cmd == "token":
        cmd_token()
    elif cmd == "token-extract":
        cmd_token_extract()
    elif cmd in ("-h", "--help", "help"):
        _usage()
    else:
        # 兼容旧用法：直接传书 ID
        cmd_download(cmd)


if __name__ == "__main__":
    main()
