# ali-cloud Docker Compose 部署

## 部署边界

| 项目 | 值 |
|---|---|
| SSH | `ali-cloud` |
| 服务器目录 | `/opt/ciweimao-api-reverse` |
| Compose project | `ciweimao-api-reverse` |
| Service | `api` |
| Egress service | `egress`，Compose 私网内 `socks5h://egress:1080` |
| 宿主监听 | `127.0.0.1:18086` |
| 容器监听 | `0.0.0.0:8000` |
| 数据目录 | `runtime/data/` |
| 下载目录 | `runtime/output/` |
| 运行凭据 | `runtime/data/guest-tokens.json`，权限 `0600`，不入 Git |
| NAS SSH 配置 | `runtime/nas-egress/connection.env`，权限 `0600` |
| NAS SSH 密码 | `runtime/nas-egress/password`，权限 `0600` |
| NAS host key | `runtime/nas-egress/known_hosts`，权限 `0600` |

服务不复用其他项目的 network、volume、container name 或公开端口。宿主的 80 端口由 1Panel 管理，本部署不修改 1Panel、Nginx、iptables、云安全组或宿主默认路由。

在线 A/B 已确认：ali-cloud 直连、`self-server:44001` 和 `self-server:44005` 均能调用 `auto_reg_v2`，但新游客随后的搜索/个人信息接口仍返回 `320002`；因此不是 token 搬运、DNS 或 SSH 隧道故障，而是数据中心/专线出口策略。NAS 住宅出口下，同一套 `curl_cffi` 注册与搜索返回 `code=100000`、10 本。

NAS SSH 禁用了 OpenSSH `direct-tcpip`。Compose 的 `egress` sidecar 不修改 NAS sshd，而是复用一个 Paramiko transport；每个 SOCKS CONNECT 创建普通 SSH session channel，在 NAS 内存执行 Python TCP relay：

```text
api container
  -> socks5h://egress:1080
  -> Paramiko password SSH + pinned host key
  -> NAS session channel / in-memory Python relay
  -> App API/CDN
```

SOCKS 端口不发布到宿主，仅 `ciweimao-api-reverse_default` network 内可见。目标域名由 NAS 解析；sidecar 仅允许转发 80/443，容器使用只读 root filesystem、`cap_drop: ALL` 和 `no-new-privileges`。NAS 不落脚本、不新增监听端口，也不改现有容器或系统配置。

## 资源限制

- CPU：`0.75`；
- Memory limit：`384 MiB`；
- Memory reservation：`128 MiB`；
- PIDs：`128`；
- Queue worker：`1`；
- Uvicorn worker：`1`。

Egress sidecar 单独限制为 `0.25 CPU / 160 MiB / 64 PIDs`。

## 运行凭据

API 设置 `CIWEIMAO_GUEST_BOOTSTRAP_ENABLED=1` 和
`CIWEIMAO_TOKEN_PATH=/app/data/guest-tokens.json`。启动阶段先通过 Compose 私网内的
`socks5h://egress:1080` 校验已有游客；文件缺失，或服务端返回 `200100` / `320002`
时，才调用 `auto_reg_v2` 创建与当前出口绑定的新游客。新凭据在容器内以 `0600`
权限原子写入 bind mount，不进入环境变量、命令行、日志、镜像层或 Git。运行中
出现 `200100` 或当前会话重试后仍为 `320002` 时，credential bootstrap 使用单锁
刷新游客；其他并发请求检测到 token 文件已更新后直接复用，原业务操作重试一次。

旧版 `runtime/app.env` 不再被 Compose 读取，升级验证成功后应只删除本项目目录下的
该陈旧文件，避免后续误用。

NAS SSH secret 只在部署时从本机 `%USERPROFILE%\.nas\credentials.json` 注入：

```dotenv
# runtime/nas-egress/connection.env
SSH_EXEC_HOST=<local-secret>
SSH_EXEC_PORT=<local-secret>
SSH_EXEC_USERNAME=<local-secret>
```

密码单独写入 `runtime/nas-egress/password`，host key 写入
`runtime/nas-egress/known_hosts`。三个文件均为 `0600`、归容器 uid `10001` 读取，
只读挂载且不复制进镜像层。`known_hosts` 必须来自已认证的 NAS 会话，禁止运行时
`AutoAddPolicy` 或盲信 `ssh-keyscan`。

启动顺序固定为：

```text
egress healthy
  -> pinned SSH transport ready
  -> API lifespan 经 NAS 出口校验/创建游客
  -> SQLite 初始化
  -> queue worker 启动
  -> scheduler 启动
```

## Compose 操作

服务器安装的是独立 Compose v2 命令：

```bash
cd /opt/ciweimao-api-reverse
docker-compose -p ciweimao-api-reverse config
docker-compose -p ciweimao-api-reverse build
docker-compose -p ciweimao-api-reverse up -d
docker-compose -p ciweimao-api-reverse ps
```

Docker 基础镜像默认使用 DaoCloud 的 Python 镜像，Python 依赖默认使用阿里云 PyPI 镜像；可通过 `PIP_INDEX_URL` 覆盖。所有镜像源设置仅存在于本项目 build，不修改宿主 Docker daemon 或系统 pip 配置。

更新时只操作本项目：

```bash
cd /opt/ciweimao-api-reverse
docker-compose -p ciweimao-api-reverse up -d --build --remove-orphans
```

禁止在共享主机执行无项目范围的 `docker-compose down`、`docker system prune -a`、`docker volume prune` 或批量容器清理。

## 验证

服务器本机：

```bash
curl --fail --silent http://127.0.0.1:18086/health
docker inspect --format '{{json .State.Health}}' ciweimao-api-reverse-api-1
```

本地通过 SSH tunnel 使用：

```powershell
ssh -L 18086:127.0.0.1:18086 ali-cloud
```

随后访问：

```text
http://127.0.0.1:18086/docs
http://127.0.0.1:18086/health
```

## 持久化与备份

- SQLite：`/opt/ciweimao-api-reverse/runtime/data/ciweimao.sqlite3`；
- 游客凭据：`/opt/ciweimao-api-reverse/runtime/data/guest-tokens.json`；
- TXT：`/opt/ciweimao-api-reverse/runtime/output/`；
- Compose 重建不会删除这两个 bind mount 目录；
- 备份 SQLite 前优先停止本项目，或使用 SQLite backup API，不直接复制活跃 WAL 文件组中的单个主库文件。
