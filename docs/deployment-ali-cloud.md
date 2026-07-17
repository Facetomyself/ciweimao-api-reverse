# ali-cloud Docker Compose 部署

## 部署边界

| 项目 | 值 |
|---|---|
| SSH | `ali-cloud` |
| 服务器目录 | `/opt/ciweimao-api-reverse` |
| Compose project | `ciweimao-api-reverse` |
| Service | `api` |
| 宿主监听 | `127.0.0.1:18086` |
| 容器监听 | `0.0.0.0:8000` |
| 数据目录 | `runtime/data/` |
| 下载目录 | `runtime/output/` |
| 运行凭据 | `runtime/app.env`，权限 `0600`，不入 Git |

服务不复用其他项目的 network、volume、container name 或公开端口。宿主的 80 端口由 1Panel 管理，本部署不修改 1Panel、Nginx、iptables 或云安全组。

## 资源限制

- CPU：`0.75`；
- Memory limit：`384 MiB`；
- Memory reservation：`128 MiB`；
- PIDs：`128`；
- Queue worker：`1`；
- Uvicorn worker：`1`。

## 运行凭据

`runtime/app.env` 只包含运行时变量：

```dotenv
CIWEIMAO_LOGIN_TOKEN=<local-secret>
CIWEIMAO_ACCOUNT=<local-secret>
CIWEIMAO_DEVICE_TOKEN=<local-secret>
```

文件由部署流程从本地忽略的 capture 内存提取后通过 SSH stdin 写入，不在命令行、日志、镜像层或 Git 中出现。

## Compose 操作

服务器安装的是独立 Compose v2 命令：

```bash
cd /opt/ciweimao-api-reverse
docker-compose -p ciweimao-api-reverse config
docker-compose -p ciweimao-api-reverse build
docker-compose -p ciweimao-api-reverse up -d
docker-compose -p ciweimao-api-reverse ps
```

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
- TXT：`/opt/ciweimao-api-reverse/runtime/output/`；
- Compose 重建不会删除这两个 bind mount 目录；
- 备份 SQLite 前优先停止本项目，或使用 SQLite backup API，不直接复制活跃 WAL 文件组中的单个主库文件。
