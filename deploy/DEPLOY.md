# Echo Graph 部署到 VPS 手册

目标架构(与 `README.md` 一致):

```
用户浏览器 → nginx(80/443, HTTPS) → uvicorn(127.0.0.1:8000, 2 workers) → Neo4j Aura
                                └─ 静态资源直接由 nginx 托管(frontend/dist)
```

## 0. 上线前决策(请逐项确认)

1. **域名与备案**:VPS 对外提供 80/443 服务,国内机房绑定域名需 ICP 备案;不想备案可选香港/新加坡 VPS。
2. **公开数据范围**:当前 `works.csv` 中 99/105 为 `draft`(仅 6 部 `reviewed`),`/api/graph` 默认返回全部状态。
   - 选择 A:先完成数据审核,再上线;
   - 选择 B:接受草稿内容公开(演示/内部使用);
   - 选择 C:上线前增加"公开视图只返回 reviewed"的过滤(需改代码)。
3. **Neo4j 凭据**:准备好 `NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD / NEO4J_DATABASE`(Aura 默认库 `neo4j`)。
4. **ADMIN_TOKEN**:生成强随机值,例如 `openssl rand -hex 32`。
5. **备份确认**:确认 Aura 中数据与 `data/real/*.csv` 一致(管理页"数据未上传"提示为空),CSV 是数据事实源。

## 1. 准备仓库

- 把代码推到 git 远端,并修改 `deploy/setup-vps.sh` 顶部的 `REPO_URL`。
- 私有仓库两种方式:
  - **HTTPS + 个人访问令牌(PAT)**:`REPO_URL=https://<token>@github.com/user/echo-graph.git`(注意 token 会出现在进程列表,谨慎);
  - **SSH deploy key(推荐)**:`REPO_URL=git@github.com:user/echo-graph.git`,初始化后为 `echograph` 用户生成 key 并加入仓库 Deploy keys:

    ```bash
    sudo -u echograph ssh-keygen -t ed25519 -N "" -f /home/echograph/.ssh/id_ed25519
    sudo cat /home/echograph/.ssh/id_ed25519.pub   # 粘贴到仓库 Settings → Deploy keys
    ```

## 2. 首次初始化

```bash
sudo bash deploy/setup-vps.sh litnebula.com <certbot邮箱>
```

脚本会:装系统依赖 → Node 24 + pnpm → 建 `echograph` 用户 → 装 uv → 拉代码 →
`uv sync --frozen` → 从 CSV 生成 JSON 兜底种子(`data/seed.json`) → 配置 `.env`
→ 构建前端 → 安装 systemd 服务 + nginx + HTTPS(certbot)。

之后:

```bash
sudo nano /opt/echo-graph/.env          # 填入 NEO4J_* 与 ADMIN_TOKEN
sudo systemctl start echo-graph
curl https://litnebula.com/api/health    # 期望 {"status":"ok","store":"neo4j","fallbacks":0}
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

`deploy.sh` 会:备份 `data/` 到 `backups/`(保留 14 份)→ `git pull --ff-only`
→ `uv sync --frozen` → 重新生成兜底种子 → 构建前端 → 重启服务 → 等待健康检查。

## 4. 数据回传(重要)

在 VPS 上用「数据管理」页编辑数据时,改动直接写入
`/opt/echo-graph/data/real/*.csv`(这些文件在 git 中)。若不同步回远端:

- `deploy.sh` 的 `git pull --ff-only` 会因本地修改失败;
- VPS 数据丢失(重装/换机)时无法从远端恢复。

因此每次在 VPS 上改完数据后,请提交并推送:

```bash
sudo -u echograph bash -lc "cd /opt/echo-graph && \
  git config user.name 'echograph' && \
  git config user.email 'echograph@localhost' && \
  git add data/real data/snapshots && \
  git commit -m 'data: update from VPS admin' && \
  git push"
```

> 提示:也可以反过来把 VPS 当作只读运行环境,数据只在本机改好推上去
> (`deploy.sh` 拉取时会自动带上最新 CSV),管理页只在应急时用。

## 5. 备份策略

| 数据 | 位置 | 备份方式 |
|---|---|---|
| 策展数据 `data/real/*.csv` | git 仓库 | push 到远端即备份 |
| 编辑版本快照 `data/versions/` | VPS 本地 | `deploy.sh` 打包 + 建议 rsync 到异地 |
| 导入快照 `data/snapshots/` | VPS 本地 | 同上(提交到 git 可选) |
| 用户投稿 `data/contributions.db` | VPS 本地 | 同上;换机时需手工拷贝 |
| Neo4j Aura | 云端 | 可由 CSV + `scripts/import_data.py` 全量重建 |

建议加一条每日定时任务(可选):

```bash
sudo crontab -e
# 每天 03:00 打包数据目录
0 3 * * * tar czf /opt/echo-graph/backups/data-daily-$(date +\%F).tgz -C /opt/echo-graph data 2>/dev/null || true
```

## 6. 常见问题

- **页面空图但 `/api/health` 返回 `store":"json"`**:Neo4j 连不上,已回退兜底种子。
  检查 `journalctl -u echo-graph -e`、Aura 实例状态、`.env` 凭据、`fallbacks` 计数是否持续增长。
- **`git pull` 报本地修改冲突**:按第 4 节先提交推送,或从 `backups/` 恢复后再拉。
- **uv/pnpm 安装慢或失败**:VPS 需要能访问 pypi.org / npm registry / astral.sh;国内 VPS 可配镜像
  (`UV_DEFAULT_INDEX`、`.npmrc` registry)后再跑 `deploy.sh`。
- **证书续期**:certbot 自动续期,`sudo certbot renew --dry-run` 可验证。
- **回滚部署**:`git -C /opt/echo-graph checkout <旧commit> -- .`(或 `git reset --hard` 谨慎使用)
  后重新执行 `deploy.sh`;数据目录先备份。

## 7. 日志与监控

```bash
journalctl -u echo-graph -e            # 实时日志
curl https://<你的域名>/api/health     # store / fallbacks
```

`echo-graph.service` 已设 `Restart=always`,进程崩溃会自动拉起;
多 worker 下投稿限流按进程独立计数(见 `app/contributions.py` 注释)。
