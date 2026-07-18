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
| 快代理密钥 | `runtime/secrets/kdl_secret_id`、`runtime/secrets/kdl_secret_key` |
| 游客凭据 | `runtime/data/guest-tokens.json` |

服务不复用其他项目的 network、volume、container name 或公开端口。宿主 80 端口由
1Panel 管理，本部署不修改 1Panel、Nginx、iptables、云安全组或宿主默认路由。

## 按需出口

ali-cloud 数据中心出口访问 App 业务接口会返回 `320002`，因此 API 容器使用已经购买
的快代理 20 分钟 DPS 私密代理。代理由进程内 `ProxyLeaseManager` 管理，不再部署
NAS SSH egress sidecar：

```text
FastAPI / queue worker
  -> task-scoped ProxyLease
  -> curl_cffi.AsyncSession
  -> 快代理 DPS 国内 IP
  -> App API / CDN
```

租约策略：

- 容器启动、FastAPI lifespan、healthcheck 和 scheduler 投递阶段均不调用 `GetDPS`；
- scheduler 每 30 分钟只投递一个 `sync_all`；
- `sync_all` 开始执行时提取 1 个新 IP，榜单和新书全程共享同一个租约；
- 指定书名下载优先复用当前仍有效的 IP；没有租约、租约到期或代理失败时才提取；
- 搜索接口与指定书下载使用相同的复用规则；
- `320002` 先在当前 IP 下刷新游客身份；新游客校验仍失败时才判定出口不可用并换 IP；
- 连接、代理、timeout、HTTP 407/502/503/504 等错误会废弃当前动态租约并重试一次；
- 租约只保存在进程内，health 仅返回 provider、generation 和剩余秒数，不返回代理 URL。

默认租约为 `1200` 秒，并预留 `30` 秒安全窗口。应用不会调用额外的代理测速接口，
第一次 App 业务请求本身就是可用性验证，避免浪费有效期。
按默认 30 分钟周期且无失败刷新时，定时同步约消耗 2 个 IP/小时。

游客身份与出口有关，因此 App 网络工作流在单进程内串行切换代理。生产配置仍固定
`CIWEIMAO_QUEUE_WORKERS=1` 和单 Uvicorn worker。

## Secrets

创建只读密钥文件，不要把值写入 Compose、镜像、日志或 Git：

```bash
install -d -m 700 runtime/secrets
install -m 600 /dev/null runtime/secrets/kdl_secret_id
install -m 600 /dev/null runtime/secrets/kdl_secret_key
chown 10001:10001 runtime/secrets/kdl_secret_id runtime/secrets/kdl_secret_key
```

将订单级 `SecretId` 和 `SecretKey` 分别写入上述文件，保持容器 uid `10001` 所有、
权限 `0600`。Compose 通过
`KDL_SECRET_ID_FILE` / `KDL_SECRET_KEY_FILE` 挂载到 `/run/secrets/`。代理用户名和
密码默认在第一次实际提取前通过 `GetProxyAuthorization` 获取；该调用不启动 DPS
有效期。生产 Compose 使用 `required`，鉴权信息取不到就不会调用 `GetDPS`，避免浪费
IP；若订单明确使用 IP 白名单，再设置 `CIWEIMAO_KDL_AUTH_MODE=whitelist`。

游客凭据由服务在第一次真实请求时按需校验或创建，并以 `0600` 权限原子写入
`runtime/data/guest-tokens.json`。动态代理模式不会为了启动服务提前创建游客。

## 资源限制

- CPU：`0.75`；
- Memory limit：`384 MiB`；
- Memory reservation：`128 MiB`；
- PIDs：`128`；
- Queue worker：`1`；
- Uvicorn worker：`1`。

## Compose 操作

服务器使用独立 Compose v2 命令：

```bash
cd /opt/ciweimao-api-reverse
docker-compose -p ciweimao-api-reverse config
docker-compose -p ciweimao-api-reverse build
docker-compose -p ciweimao-api-reverse up -d --remove-orphans
docker-compose -p ciweimao-api-reverse ps
```

`--remove-orphans` 只清理本 Compose project 中已经从配置删除的旧 `egress` 容器。
禁止在共享主机执行无项目范围的 `docker-compose down`、`docker system prune -a`、
`docker volume prune` 或批量容器清理。

## 验证

先验证启动不消耗代理：

```bash
curl --fail --silent http://127.0.0.1:18086/health
```

首次 health 应显示：

```json
{"proxy":{"provider":"kuaidaili_dps","acquired":false,"generation":0}}
```

只有随后执行真实搜索或投递同步/下载任务时才允许 `acquired` 变为 `true`。端到端验证
至少覆盖搜索 10 本、一次 `sync_all` 合并同步和一次指定书名免费章节下载；合并任务结果
应同时包含榜单与新书统计，正常路径下 proxy generation 只增加 1。

## 持久化与备份

- SQLite：`runtime/data/ciweimao.sqlite3`；
- 游客凭据：`runtime/data/guest-tokens.json`；
- TXT：`runtime/output/`；
- Compose 重建不会删除 bind mount 数据；
- 备份 SQLite 前优先停止本项目，或使用 SQLite backup API，不直接复制活跃 WAL 文件。
