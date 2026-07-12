# ciweimao-api-reverse

刺猬猫（Ciweimao / Hbooker）HTTP API TXT 导出工具。适合已有登录凭据的账号批量备份书架内可读内容。

## 能力

- 读取并搜索账号书架
- 下载免费章节和账号已购买章节
- `download-all` 自动跳过 `output/` 中同名 TXT
- 详情接口对下架书返回 `320001` 时，使用书架元数据继续走分卷、章节和正文接口
- 从已 root 的 Android 设备或模拟器提取现有登录凭据

下架不等于一定可下载：能否导出最终由账号对章节的 `auth_access` 和正文接口权限决定。本工具不会绕过未购买章节。

## 安装

```bash
pip install requests pycryptodome pydantic
git clone https://github.com/Facetomyself/ciweimao-api-reverse.git
cd ciweimao-api-reverse
```

## 获取凭据

### 从已登录设备提取

```bash
python -m client token-extract
```

该命令通过 ADB 读取 App 私有目录，设备必须已连接、App 已登录，并提供 root 权限。提取完成后，日常 API 下载不需要保持模拟器运行。

也可手动创建本地 `tokens.json`：

```json
{
  "login_token": "...",
  "account": "...",
  "device_token": "ciweimao_",
  "app_version": "2.9.312"
}
```

`tokens.json` 已加入 `.gitignore`，不要提交或分享该文件。

## 使用

```bash
python -m client token             # 验证当前凭据
python -m client list              # 列出书架全部书籍
python -m client search 关键词      # 搜索书籍
python -m client download 书ID     # 下载指定书籍
python -m client download-all      # 仅下载 output/ 中缺少的书籍
```

输出目录为 `output/`。单本 `download` 会重新导出并覆盖同名文件；批量 `download-all` 默认跳过已有同名 TXT。

## 下载链路

```text
/reader/get_my_info                         验证 token
/bookshelf/get_shelf_list                   获取书架
/bookshelf/get_shelf_book_list              获取书架元数据
/book/get_info_by_id                        获取详情（下架时允许失败）
/book/get_division_list                     获取分卷
/chapter/get_updated_chapter_by_division_id 获取章节
/chapter/get_chapter_cmd                    获取章节 command
/chapter/get_cpt_ifm                        获取加密正文
AES-256-CBC                                 解密并导出 TXT
```

## 限制

- `login_token` 会失效，届时需重新登录并提取。
- token 提取依赖 ADB + root；“纯 HTTP”仅指凭据准备完成后的下载阶段。
- 服务端可能对书架分页返回重复页，客户端会按页签名停止并按 `book_id` 去重。
- 当前仅导出 TXT，不包含上游项目的 EPUB、插图和 App 缓存导出能力。

## 验证

```bash
python smoke_test.py
```

Smoke test 从本地 `tokens.json` 读取凭据，不在源码中保存 token。

## 参考项目

- [NateScarlet/ciweimao](https://github.com/NateScarlet/ciweimao)
- [zsakvo/Cirno-go](https://github.com/zsakvo/Cirno-go)
- [AlexiaVeronica/pineapple-backups](https://github.com/AlexiaVeronica/pineapple-backups)
- [NovelDownloader/CiweimaoDownloader](https://github.com/NovelDownloader/CiweimaoDownloader)
