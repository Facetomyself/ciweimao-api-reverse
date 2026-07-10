# ciweimao-api-reverse

刺猬猫（Ciweimao / Hbooker）纯 API 下载器 — **零人工、零模拟器**的 TXT 小说导出工具。

## 特性

- **纯 HTTP API**：不依赖 Android 模拟器、ADB 或 root 权限
- **零人工操作**：书架读取 + 批量下载全自动
- **已购章节导出**：仅导出已购买/免费的章节，不破解付费内容
- **书架管理**：支持多书架浏览、搜索
- **一键 token 提取**：从模拟器自动提取登录凭据，无需密码

## 快速开始

### 1. 安装

```bash
pip install requests pycryptodome pydantic
git clone https://github.com/Facetomyself/ciweimao-api-reverse.git
cd ciweimao-api-reverse
```

### 2. 获取登录凭据

**方式 A — 从模拟器自动提取（推荐）：**
```bash
python -m client token-extract
```

**方式 B — 手动配置：**
创建 `tokens.json`：
```json
{
  "login_token": "从模拟器提取的32位hex",
  "account": "书客...",
  "device_token": "ciweimao_",
  "app_version": "2.9.312"
}
```

### 3. 使用

```bash
python -m client list              # 列出书架全部书籍
python -m client search 关键词      # 搜索书籍
python -m client download 书ID     # 下载指定书籍
python -m client download-all      # 下载书架全部书籍
python -m client token             # 查看凭据状态
```

输出在 `output/` 目录。

## 工作原理

```
刺猬猫 Android API (app.hbooker.com)
    │
    ├── POST /signup/login          → login_token + account
    ├── GET  /bookshelf/get_shelf_list → 书架列表
    ├── GET  /book/get_info_by_id   → 书籍详情
    ├── GET  /chapter/get_chapter_cmd → 章节解密密钥
    └── GET  /chapter/get_cpt_ifm   → 加密章节内容
              │
              ▼
    AES-256-CBC 解密 → TXT 输出
```

所有 API 响应均使用 AES-256-CBC 加密（全局密钥硬编码在 App 中）。

## 项目结构

```
client/
  ├── config.py       # API 配置
  ├── crypto.py       # AES-256-CBC 解密
  ├── auth.py         # 登录 / Token 管理
  ├── api.py          # API 端点 + 书架 + 搜索
  ├── models.py       # Book / Division / Chapter 数据模型
  ├── downloader.py   # 批量下载编排器
  └── __main__.py     # CLI 入口
smoke_test.py         # API 连通性验证脚本
```

## 限制

- 仅能下载已购买/免费的章节（受 `auth_access` 字段控制）
- `login_token` 会过期，过期后需重新提取（`token-extract`）
- 账号密码登录可能触发 GEETEST 验证码，推荐 token 方式

## 致谢

API 协议分析参考了以下开源项目：
- [NateScarlet/ciweimao](https://github.com/NateScarlet/ciweimao) — Go API 客户端库
- [zsakvo/Cirno-go](https://github.com/zsakvo/Cirno-go) — Go 下载器
- [AlexiaVeronica/pineapple-backups](https://github.com/AlexiaVeronica/pineapple-backups) — Go 多平台备份工具
- [NovelDownloader/CiweimaoDownloader](https://github.com/NovelDownloader/CiweimaoDownloader) — 原始 ADB 缓存解密工具

## 声明

- 仅供个人学习与技术研究
- 禁止任何形式的商业用途
- 所有内容版权归原作者及刺猬猫平台所有
- 请在 24 小时内删除下载的文件
