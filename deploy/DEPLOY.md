# Litnebula 部署到 VPS 手册

目标架构(1核2G VPS 即可,与 `README.md` 一致):

```
用户浏览器 → nginx(80/443, HTTPS) → uvicorn(127.0.0.1:8000, 单 worker)
                                └─ 静态资源直接由 nginx 托管(frontend/dist)
数据:SQLite(data/echo-graph.db)为唯一权威,公开读取直接查 SQLite;
data/export/*.csv 为确定性导出产物(git 审计 / 跨机器传输通道)。
```

> 架构说明:曾使用 Neo4j Aura 作为查询层,现已退役——公开读取直接由 SQLite 提供,
> 不再有手动「上传↑」、同步比对与兜底种子。小内存 VPS 上更省资源、无网络依赖。

## 0. 上线前决策(请逐项确认)

1. **域名与备案**:VPS 对外提供 80/443 服务,国内机房绑定域名需 ICP 备案;不想备案可选香港/新加坡 VPS。
2. **公开数据范围**:公开接口默认返回全部审核状态(便于管理/开发);
   **已在代码内置方案**——在 `.env` 设置 `PUBLIC_REVIEWED_ONLY=1`,公开视图即只返回
   `reviewed` 内容(草稿/驳回不可见)。上线前请逐条人工审核并置 `reviewed`,再决定是否开启。
3. **引导管理员**:在 `.env` 配置 `ADMIN_BOOTSTRAP_EMAIL`,该邮箱注册时自动获得
   admin 角色并认领公共星云数据;数据管理只认 admin 角色登录态,已移除 ADMIN_TOKEN。
4. **账号体系(可选但建议)**:注册接口含 Cloudflare Turnstile 人机验证——在
   Cloudflare Dashboard 创建 Site,把 `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY`
   写入 `.env`(未配置时注册跳过验证,仅限本地开发);HTTPS 部署请设 `COOKIE_SECURE=1`。

## 1. 准备仓库

- 把代码推到 git 远端,并修改 `deploy/setup-vps.sh` 顶部的 `REPO_URL`。
- 私有仓库两种方式:
  - **HTTPS + 个人访问令牌(PAT)**:`REPO_URL=https://<token>@github.com/user/echo-graph.git`(注意 token 会出现在进程列表,谨慎);
  - **SSH deploy key(推荐)**:`REPO_URL=git@github.com:user/echo-graph.git`,初始化后为 `echograph` 用户生成 key 并加入仓库 Deploy keys。

## 2. 首次初始化

```bash
sudo bash deploy/setup-vps.sh litnebula.com <certbot邮箱>
```

脚本会:装系统依赖 → Node 24 + pnpm → 建 `echograph` 用户 → 装 uv → 拉代码 →
`uv sync --frozen` → 从仓库 CSV 重建 SQLite(`scripts/migrate_csv_to_sqlite.py`) →
配置 `.env` → 构建前端 → 安装 systemd 服务 + nginx + HTTPS(certbot)。

之后:

```bash
sudo nano /opt/echo-graph/.env          # 填入 ADMIN_BOOTSTRAP_EMAIL(及可选的 TURNSTILE_* / COOKIE_SECURE)
# 可选:若只展示已审核内容,追加 PUBLIC_REVIEWED_ONLY=1
sudo systemctl start echo-graph
curl https://litnebula.com/api/health    # 期望 {"status":"ok","store":"sqlite"}
```

防火墙(可选但推荐):

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
```

## 3. 日常更新

```bash
sudo -u echograph bash /opt/echo-graph/deploy/deploy.sh
```

`deploy.sh` 会:备份 `data/`(SQLite 走 `sqlite3 .backup` 一致性快照,保留 14 份)→
`git pull --ff-only` → `uv sync --frozen` → 构建前端 → 重启服务 → 等待健康检查。
SQLite 为权威库,日常更新**不再从 CSV 重建**(避免清空用户星云);schema 迁移由服务启动时自动执行。

## 4. 数据回传(重要)

`data/echo-graph.db` 不在 git 中。`data/export/*.csv` 是**公共星云的确定性导出**
(git 跟踪,审计/回滚通道),**只含公共数据,不含用户私有空间**:

- 在 VPS 上通过「数据管理」编辑公共星云时,改动写入 SQLite 并自动导出公共 CSV(文件进 git)。
- 每次在 VPS 上改完公共数据,请提交并推送 CSV:

  ```bash
  sudo -u echograph bash -lc "cd /opt/echo-graph && \
    git config user.name 'echograph' && \
    git config user.email 'echograph@localhost' && \
    git add data/export && \
    git commit -m 'data: update from VPS admin' && \
    git push"
  ```

- 新机器首次初始化仍走 `setup-vps.sh` 的 CSV 引导(公共星云)。
- **用户私有空间不在 CSV 中**:跨机器迁移完整数据(含用户星云)需手动同步
  `backups/echo-graph-*.db` 快照(部署时自动生成),不要依赖 git。
- 若 VPS 本地有未提交的数据改动,`git pull --ff-only` 会失败——先按上面提交推送再部署。
- 也可反向操作:本机改好数据 → 提交 CSV 推远端 → VPS 上跑 `deploy.sh` 同步。

> 提示:建议把 VPS 当作**只读运行环境**,数据只在本机改好推上去,管理页仅在应急时使用。

## 5. 备份策略

| 数据 | 位置 | 备份方式 |
|---|---|---|
| 策展数据 + 投稿 + 审计 `data/echo-graph.db` | VPS 本地 | `deploy.sh` 每次 `sqlite3 .backup` 到 `backups/`(保留 14 份);建议再 rsync 到异地 |
| CSV 导出 `data/export/*.csv` | git 仓库 | push 到远端即备份 |
| 编辑版本快照 `data/versions/` | VPS 本地 | `deploy.sh` 打包;建议 rsync(历史遗留,新代码不再写入) |
| Neo4j 时代快照 `data/snapshots/` | VPS 本地 | 同上(历史遗留,不再产生) |
| 审计日志 `audit_log` | SQLite 内 | 用 `scripts/prune_audit.py --days 90` 裁剪(可加 cron 定期执行) |

> **快照恢复入口**:管理端「数据管理 → 快照」Tab 可一键创建当前库快照,也可查看并恢复
> `backups/` 的 SQLite 备份(`data/versions/` 的历史 CSV 目录仅在旧机器残留时可用);
> 恢复前会自动为当前库做安全备份,恢复后自动重新导出 CSV。应用侧创建的快照保留最近 30 份(`backups/` 下),
> deploy.sh 自身的备份保留 14 份;**恢复期间请勿编辑数据**,后端在恢复与写事务之间
> 做了进程内互斥,单 worker 下不会出现并发覆盖。

审计日志裁剪(可选 cron,每天 03:30):

```bash
30 3 * * * cd /opt/echo-graph && uv run --frozen python scripts/prune_audit.py --days 90
```

如需要每日自动备份,可加一条 cron(复用 deploy.sh 里的 backup 逻辑):

```bash
sudo crontab -e
# 每天 03:00 一致性备份 SQLite
0 3 * * * cd /opt/echo-graph && uv run --frozen python -c "import sqlite3,sys; s=sqlite3.connect('data/echo-graph.db'); d=sqlite3.connect('backups/echo-graph-daily.db'); s.backup(d); d.close(); s.close()" 2>/dev/null || true
```

## 6. 常见问题

- **页面空图但 `/api/health` 返回 `store":"sqlite"`**:检查 `data/echo-graph.db` 是否存在、
  `journalctl -u echo-graph -e` 是否有报错;全新机器请确认 `setup-vps.sh` 的重建 SQLite 步骤已执行。
- **`git pull` 报本地修改冲突**:按第 4 节先提交推送,或从 `backups/` 恢复后再拉。
- **uv/pnpm 安装慢或失败**:VPS 需要能访问 pypi.org / npm registry / astral.sh;国内 VPS 可配镜像
  (`UV_DEFAULT_INDEX`、`.npmrc` registry)后再跑 `deploy.sh`。
- **证书续期**:certbot 自动续期,`sudo certbot renew --dry-run` 可验证。
- **回滚部署**:`git -C /opt/echo-graph checkout <旧commit> -- .` 后重新执行 `deploy.sh`;数据目录先备份。
- **内存**:1核2G 请保持单 worker,不要额外加 uvicorn workers 或常驻进程;VPS 上 `pnpm build` 较慢属正常。

## 7. 日志与监控

```bash
journalctl -u echo-graph -e            # 实时日志
curl https://<你的域名>/api/health     # 期望 {"status":"ok","store":"sqlite"}
```

## 8. 限流策略(贡献提交)

公开接口 `POST /api/contribute/echo` 采用三层防护:

1. **应用层策略(细粒度)**:进程内滑动窗口,默认每 IP 每小时最多 20 条
   (`app/contributions.py` 的 `SUBMIT_LIMIT`)。单 worker 部署下计数精确;
   若改为多 worker,进程间不共享计数,需依赖 nginx 层或换共享存储(如 Redis)。
2. **信任边界**:仅当对端属于 `TRUSTED_PROXIES`(默认 `127.0.0.1,::1`,可在
   `.env` 用逗号分隔的 IP/CIDR 覆盖)时,应用才解析 `X-Forwarded-For` 取最左
   客户端 IP;直连 uvicorn 或伪造请求头时一律使用对端地址。该解析在应用内完成,
   不依赖 uvicorn 的 `--proxy-headers` 设置。
3. **nginx 防洪(粗粒度)**:`setup-vps.sh` 自动生成
   `/etc/nginx/conf.d/echo-graph-ratelimit.conf`(`rate=10r/m burst=20 nodelay`,
   约 630 条/小时上限),只挡洪峰流量,不替代应用层策略;手动部署见
   `deploy/nginx.conf` 文件头注释。

调整方式:改 `.env` 的 `TRUSTED_PROXIES`(多级代理时逐级加入);
改 nginx zone 的 `rate`/`burst` 值后 `systemctl reload nginx`。
