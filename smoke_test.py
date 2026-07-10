"""Smoke test: 用从模拟器提取的 token 验证 Ciweimao API。

用法:
  python smoke_test.py
"""

import sys
import json
import requests
from client import crypto, config


# 从模拟器提取的凭据
TOKENS = {
    "login_token": "c7e4bb97595fbf1eb01ee7cdb3f2b2ee",
    "account": "书客75351748166",
    "device_token": "ciweimao_",
    "app_version": "2.9.312",
    "reader_id": "3507481",
}


def api_get(endpoint: str, extra_params: dict = None) -> dict:
    """发送带认证的 API 请求并解密响应。"""
    params = {
        "login_token": TOKENS["login_token"],
        "account": TOKENS["account"],
        "device_token": TOKENS["device_token"],
        "app_version": TOKENS["app_version"],
    }
    if extra_params:
        params.update(extra_params)

    url = f"{config.BASE_URL}{endpoint}"
    resp = requests.post(
        url,
        data=params,
        headers={
            "User-Agent": config.USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=15,
    )

    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}", "raw": resp.text[:200]}

    plaintext = crypto.decrypt_response(resp.text.strip())
    return json.loads(plaintext)


def main():
    print("=" * 60)
    print("Ciweimao API 连通性验证")
    print(f"reader_id: {TOKENS['reader_id']}")
    print(f"app_version: {TOKENS['app_version']}")
    print("=" * 60)

    # Test 1: 获取用户信息（验证 token 有效性）
    print("\n[Test 1] 验证 token 有效性 (/reader/get_my_info)...")
    data = api_get("/reader/get_my_info")
    code = data.get("code", "")
    if code == "100000":
        reader = data.get("data", {}).get("reader_info", {})
        print(f"  [PASS] Token 有效!")
        print(f"  reader_name: {reader.get('reader_name', 'N/A')}")
        print(f"  exp_lv: {reader.get('exp_lv', 'N/A')}")
        print(f"  vip_lv: {reader.get('vip_lv', 'N/A')}")
    elif code == "200100":
        print("  [FAIL] Token 已过期，需要重新登录")
        return False
    else:
        print(f"  [FAIL] code={code}, tip={data.get('tip', '')}")
        return False

    # Test 2: 获取书籍详情
    print("\n[Test 2] 获取书籍详情 (/book/get_info_by_id)...")
    data = api_get("/book/get_info_by_id", {"book_id": "100085206"})
    code = data.get("code", "")
    if code == "100000":
        book = data.get("data", {}).get("book_info", {})
        print(f"  [PASS] 书籍信息获取成功!")
        print(f"  book_name: {book.get('book_name', 'N/A')}")
        print(f"  author: {book.get('author_name', 'N/A')}")
        print(f"  total_word_count: {book.get('total_word_count', 'N/A')}")
        print(f"  category: {book.get('category_name', 'N/A')}")
    else:
        print(f"  [FAIL] code={code}, tip={data.get('tip', '')}")
        return False

    # Test 3: 获取分卷列表
    print("\n[Test 3] 获取分卷列表 (/book/get_division_list)...")
    data = api_get("/book/get_division_list", {"book_id": "100085206"})
    code = data.get("code", "")
    if code == "100000":
        divisions = data.get("data", {}).get("division_list", [])
        print(f"  [PASS] 分卷列表获取成功! ({len(divisions)} 卷)")
        for d in divisions[:3]:
            print(f"    - {d.get('division_name', 'N/A')} ({d.get('chapter_count', '?')}章)")
        if len(divisions) > 3:
            print(f"    ... 还有 {len(divisions)-3} 卷")
    else:
        print(f"  [FAIL] code={code}")
        return False

    # Test 4: 获取章节目录
    print("\n[Test 4] 获取章节目录 (/chapter/get_updated_chapter_by_division_id)...")
    first_div_id = divisions[0].get("division_id", "")
    data = api_get("/chapter/get_updated_chapter_by_division_id", {"division_id": first_div_id})
    code = data.get("code", "")
    if code == "100000":
        chapters = data.get("data", {}).get("chapter_list", [])
        print(f"  [PASS] 章节目录获取成功! ({len(chapters)} 章)")
        for c in chapters[:3]:
            print(f"    - [{c.get('chapter_index')}] {c.get('chapter_title', 'N/A')} ({c.get('word_count', '?')}字)")
        if len(chapters) > 3:
            print(f"    ... 还有 {len(chapters)-3} 章")
    else:
        print(f"  [FAIL] code={code}")
        return False

    # Test 5: 获取章节内容密钥
    print("\n[Test 5] 获取章节内容 (/chapter/get_chapter_cmd → /chapter/get_cpt_ifm)...")
    first_chapter_id = chapters[0].get("chapter_id", "")
    data = api_get("/chapter/get_chapter_cmd", {"chapter_id": first_chapter_id})
    code = data.get("code", "")
    if code == "100000":
        command = data.get("data", {}).get("command", "")
        print(f"  [PASS] 获取 command 成功: {command[:20]}...")

        # Test 6: 获取加密章节内容
        data = api_get("/chapter/get_cpt_ifm", {
            "chapter_id": first_chapter_id,
            "chapter_command": command,
        })
        code = data.get("code", "")
        if code == "100000":
            chapter_info = data.get("data", {}).get("chapter_info", {})
            txt_encrypted = chapter_info.get("txt_content", "")
            print(f"  [PASS] 章节内容获取成功! (加密长度: {len(txt_encrypted)})")

            # 解密章节内容
            try:
                content = crypto.decrypt_chapter(txt_encrypted, command)
                text = content.decode("utf-8")
                print(f"  [PASS] 章节解密成功! ({len(text)} 字符)")
                print(f"  内容预览: {text[:100]}...")
            except Exception as e:
                print(f"  [FAIL] 章节解密失败: {e}")
                return False
        else:
            print(f"  [FAIL] code={code}, tip={data.get('tip', '')}")
            return False
    else:
        print(f"  [FAIL] code={code}")
        return False

    # 总结
    print("\n" + "=" * 60)
    print("[CONCLUSION] 全部 6 个 API 测试通过!")
    print("  - Token 有效")
    print("  - 全局 API key 正确")
    print("  - 书籍/分卷/章节/内容 API 全部可用")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
