# Litnebula 部署到 VPS 手册

目标架构(1核2G VPS 即可,与 `README.md` 一致):

```
用户浏览器 → nginx(80/443, HTTPS) → uvicorn(127.0.0.1:8000, 单 worker)
                                └─ 静态资源直接由 nginx 托管(frontend/dist)
数据:SQLite(data/echo-graph.db)为唯一权威,公开读取直接查 SQLite;
data/real/*.csv 为确定性导出产物(git 审计 / 跨机器传输通道)。
```

> 架构说明:曾使用 Neo4j Aura 作为查询层,现已退役——公开读取直接由 SQLite 提供,
> 不再有手动「上传↑」、同步比对与兜底种子。小内存 VPS 上更省资源、无网络依赖。

## 0. 上线前决策(请逐项确认)

1. **域名与备案**:VPS 对外提供 80/443 服务,国内机房绑定域名需 ICP 备案;不想备案可选香港/新加坡 VPS。
2. **公开数据范围**:`/api/graph` 默认返回全部审核状态;若希望线上只展示 `reviewed`,
   需要增加"公开视图只返回 reviewed"的过滤(需改代码)。
3. **ADMIN_TOKEN**:生成强随机值,例如 `openssl rand -hex 32`,写入 `/opt/echo-graph/.env`。

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
sudo nano /opt/echo-graph/.env          # 填入 ADMIN_TOKEN
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
`git pull --ff-only` → `uv sync --frozen` → 从仓库 CSV 重建 SQLite(contributions / audit_log 表不受影响)
→ 构建前端 → 重启服务 → 等待健康检查。

## 4. 数据回传(重要)

`data/echo-graph.db` 不在 git 中;**`data/real/*.csv` 是跨机器传输与审计通道**:

- 在 VPS 上通过「数据管理」页编辑时,改动写入 `/opt/echo-graph/data/echo-graph.db`,
  并自动导出 `data/real/*.csv`(文件进 git)。
- 每次在 VPS 上改完数据,请提交并推送 CSV:

  ```bash
  sudo -u echograph bash -lc "cd /opt/echo-graph && \
    git config user.name 'echograph' && \
    git config user.email 'echograph@localhost' && \
    git add data/real && \
    git commit -m 'data: update from VPS admin' && \
    git push"
  ```

- 其他机器/新机器拉取后,`deploy.sh` 会用新 CSV 重建本地 SQLite。
- 若 VPS 本地有未提交的数据改动,`git pull --ff-only` 会失败——先按上面提交推送再部署。
- 也可反向操作:本机改好数据 → 提交 CSV 推远端 → VPS 上跑 `deploy.sh` 同步。

> 提示:建议把 VPS 当作**只读运行环境**,数据只在本机改好推上去,管理页仅在应急时使用。

## 5. 备份策略

| 数据 | 位置 | 备份方式 |
|---|---|---|
| 策展数据 + 投稿 + 审计 `data/echo-graph.db` | VPS 本地 | `deploy.sh` 每次 `sqlite3 .backup` 到 `backups/`(保留 14 份);建议再 rsync 到异地 |
| CSV 导出 `data/real/*.csv` | git 仓库 | push 到远端即备份 |
| 编辑版本快照 `data/versions/` | VPS 本地 | `deploy.sh` 打包;建议 rsync(历史遗留,新代码不再写入) |
| Neo4j 时代快照 `data/snapshots/` | VPS 本地 | 同上(历史遗留,不再产生) |

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
