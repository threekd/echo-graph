# Litnebula 部署到 VPS 手册

目标架构(1核2G VPS 即可,与 `../README.md` 一致):

```
用户浏览器 → nginx(80/443, HTTPS) → uvicorn(127.0.0.1:8000, 单 worker)
                                └─ 静态资源直接由 nginx 托管(frontend/dist)
数据:SQLite(data/echo-graph.db)为唯一权威,公开读取直接查 SQLite;
备份 = 整库快照(backups/ 下 sqlite3 .backup 产物 + 管理端「快照」恢复)。
```

> 架构说明:曾使用 Neo4j Aura 作为查询层,现已退役——公开读取直接由 SQLite 提供,
> 不再有手动「上传↑」、同步比对与兜底种子。`data/export/*.csv` 自动导出层
> 已于 2026-08-27 移除(多设备/调试导致漂移),备份统一为整库快照。小内存 VPS 上更省资源、无网络依赖。

## 0. 上线前决策(请逐项确认)

1. **域名与备案**:VPS 对外提供 80/443 服务,国内机房绑定域名需 ICP 备案;不想备案可选香港/新加坡 VPS。
2. **公开数据范围**:公共星云/官方图谱概念已移除(2026-08-28)——不存在默认视图,
   `/api/*` 公共只读端点与 `PUBLIC_REVIEWED_ONLY` 均已下线。登录用户首页即自己的
   星云(草稿/驳回对自己可见);游客无默认图谱,可通过星际跃迁浏览公开星云
   (`/api/space/*`)。如需公开展示某星云,把该用户的星云可见性设为公开。
3. **引导管理员**:在 `.env` 配置 `ADMIN_BOOTSTRAP_EMAIL`,该邮箱注册时自动获得
   admin 角色(首个管理员引导);管理接口(`/api/admin/*`)只认 admin 角色登录态,
   已移除 ADMIN_TOKEN。
4. **账号体系(可选但建议)**:注册接口含 Cloudflare Turnstile 人机验证——在
   Cloudflare Dashboard 创建 Site,把 `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY`
   写入 `.env`(**未配置密钥时注册默认失败**,仅本地开发可设
   `TURNSTILE_ALLOW_SKIP=1` 临时跳过,请勿在生产设置);HTTPS 部署**必须**设
   `COOKIE_SECURE=1`(未设置时服务启动会输出告警日志)。
5. **书籍导入上传大小**:nginx 模板已内置 `client_max_body_size 20m`(与后端
   `MAX_BOOK_BYTES` 一致);若手动配置 nginx,需同步添加该指令,否则 >1MB 的
   电子书会被 nginx 以 413 拒绝。
6. **邮件服务(可选但建议)**:注册邮箱验证与「忘记密码」依赖邮件送达。推荐
   阿里云邮件推送 DirectMail(见「0.5 邮件服务配置」),生产设置
   `EMAIL_VERIFY_REQUIRED=1` 后,新注册用户必须先验证邮箱才能登录,引导管理员
   也会在验证通过后才获得 admin 角色(杜绝抢先注册提权)。

## 0.5 邮件服务配置(阿里云邮件推送 DirectMail)

新加坡 VPS 可直接使用阿里云邮件推送:API 与 SMTP 均支持国际站区域
(`ap-southeast-1`,无需国内 ICP 备案;大陆区域 `cn-hangzhou` 的发信域名需备案)。
ECS 默认封禁 25 端口出站,不影响本方案的 API(HTTPS 443)与 SMTP 465/587。

配置步骤:

1. 阿里云控制台开通「邮件推送」,添加**发信域名**并完成 DNS 验证
   (控制台「配置信息」里的 MX / SPF / DKIM / DMARC / CNAME 跟踪等记录全部
   加上并等验证状态为「已验证」),再创建**发信地址**(如 `noreply@你的域名`)。
2. 创建 RAM 用户并授予 `AliyunDirectMailFullAccess`,生成 AccessKey。
3. `.env` 填写(区域按 VPS 所在地选择):

   ```bash
   MAILER=api
   SITE_BASE_URL=https://你的域名
   EMAIL_VERIFY_REQUIRED=1
   ALIYUN_DM_ACCESS_KEY_ID=...
   ALIYUN_DM_ACCESS_KEY_SECRET=...
   ALIYUN_DM_ACCOUNT_NAME=noreply@你的域名
   ALIYUN_DM_REGION=ap-southeast-1   # 新加坡;大陆用 cn-hangzhou
   ```

4. 重启服务后查看日志确认「邮件服务已配置:MAILER=api」;用注册/找回密码实测
   一封邮件。测试期可先 `EMAIL_VERIFY_REQUIRED=0` 避免误锁,确认送达后再开启。

> `EMAIL_VERIFY_REQUIRED=1` 但未配置发送器时,注册接口 fail-closed 全部失败
> (503),服务启动也会输出告警日志——这是有意的安全行为,防止产生永远收不到
> 验证邮件、无法登录的孤儿账号。

备用 SMTP 通道:`MAILER=smtp` + `SMTP_HOST/PORT/USER/PASS/FROM/TLS`(465 SSL
或 587 STARTTLS),适合已有邮件服务商的场景。

### 0.5.1 排错与送达率(2026-08-28 实测经验)

后端日志(或 `MailSendError` 消息)会直接透传阿里云返回的 `Code/Message`,
常见错误:

| 错误码 | 含义 | 处理 |
|---|---|---|
| `Forbidden` | AccessKey 无邮件推送权限,或不属于开通邮件推送的账号 | RAM 用户附加 `AliyunDirectMailFullAccess`(或 `SendOnly`);核对 AccessKey 归属账号 |
| `InvalidMailAddress.NotFound` | 发信地址不在当前配置的区域 | **发信域名/发信地址按区域隔离**:`ALIYUN_DM_REGION` 必须与创建发信地址的控制台区域一致(地址建在大陆区就配 `cn-hangzhou`,建在新加坡区才配 `ap-southeast-1`) |
| 邮件进垃圾箱 | DNS 认证记录不全,或新域名/共享 IP 信誉冷启动 | 见下 |

送达率要点(Gmail 实测:SPF/DKIM/DMARC 全 pass 仍可能进垃圾箱):

- **认证记录**:发信域名需配齐 MX / SPF / DKIM / DMARC(及可选的 CNAME 跟踪);
  收件方(Gmail 等)在 2024-02 起对 SPF/DKIM/DMARC 三件套有硬性要求。
- **链接跟踪改写**:邮件里的链接可能被 DirectMail 点击跟踪改写为阿里云跳转域名,
  影响收件方判定——可关闭跟踪或配置自定义跟踪域名,让链接显示为自己的域名。
- **新域名/共享 IP 信誉**:新发信域名 + 共享 IP 池冷启动,收件人把邮件移回收件箱并
  标记「不是垃圾邮件」、加入联系人可立即改善;保持少量真实事务邮件(注册/重置,
  勿群发)一般 1~4 周信誉恢复。
- **区域选择**:大陆 `cn-hangzhou` 集群发海外(Gmail 等)信誉通常不如新加坡
  `ap-southeast-1` 集群;对送达率要求高可把发信域名/地址迁到新加坡区对比。
- 更高要求可咨询阿里云「独立 IP / 高信誉发信」(付费)。

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
`uv sync --frozen` → 配置 `.env` → 构建前端 → 安装 systemd 服务 + nginx + HTTPS(certbot)。
首次启动服务会自动创建并迁移 SQLite schema(**空库**);要恢复已有数据,请把
整库快照(`backups/echo-graph-*.db`)放到目标机器后用管理端「快照」恢复
(或停服直接替换 `data/echo-graph.db`),详见第 4 节。

之后:

```bash
sudo nano /opt/echo-graph/.env          # 填入 ADMIN_BOOTSTRAP_EMAIL、TURNSTILE_* / COOKIE_SECURE,以及 0.5 节的邮件配置
sudo systemctl start echo-graph
curl https://litnebula.com/api/health    # 期望 {"status":"ok","store":"sqlite"}
```

全新环境数据引导:启动后 `data/echo-graph.db` 为空库(仅 schema)。需要把生产数据
带到新机器时,先在本机执行 `sqlite3 data/echo-graph.db ".backup 'backups/full.db'"`
并把 `backups/full.db` 上传到新机器,再用管理端「快照」恢复(见第 4 节)。

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
SQLite 为权威库,schema 迁移由服务启动时自动执行;数据备份/恢复一律走整库快照。

## 4. 数据备份与恢复(重要)

`data/echo-graph.db` 不在 git 中,**备份介质只有整库快照**(含全部用户星云、
审计日志、用户与会话):

- **日常备份**:`deploy.sh` 每次部署前自动 `sqlite3 .backup` 到 `backups/`(保留 14 份);
  也可手动:

  ```bash
  sudo -u echograph bash -lc "cd /opt/echo-graph && \
    sqlite3 data/echo-graph.db \".backup 'backups/full-$(date +%Y%m%d-%H%M%S).db'\""
  ```

- **恢复**:把快照放到 VPS 后,在管理端「运维管理 → 快照」Tab 选择并恢复
  (恢复前自动安全备份当前库,恢复后自动重新认领未归属行);或停服直接替换
  `data/echo-graph.db`(先 `PRAGMA integrity_check`,并移除旧的 `-wal`/`-shm`)。
- **跨机器迁移**:复制 `backups/echo-graph-*.db` 到目标机器后按上述恢复,完整包含
  用户星云;不要依赖 git 或 CSV。
- **异地备份**:建议把 `backups/` 定期同步到异地(rsync / rclone / 对象存储);
  自动化方案见 `docs/to-do.md`「整库异地备份」待办。

> 提示:单用户数据导出请用星云工坊页「导出 CSV」按钮(`/api/me/export`,zip)。

## 5. 备份策略

| 数据 | 位置 | 备份方式 |
|---|---|---|
| 策展数据 + 审计日志 + 用户与会话 `data/echo-graph.db` | VPS 本地 | `deploy.sh` 每次 `sqlite3 .backup` 到 `backups/`(保留 14 份);建议再 rsync 到异地 |
| 编辑版本快照 `data/versions/` | VPS 本地 | `deploy.sh` 打包;建议 rsync(历史遗留,新代码不再写入) |
| Neo4j 时代快照 `data/snapshots/` | VPS 本地 | 同上(历史遗留,不再产生) |
| 审计日志 `audit_log` | SQLite 内 | 用 `scripts/prune_audit.py --days 90` 裁剪(可加 cron 定期执行) |

> **快照恢复入口**:管理端「运维管理 → 快照」Tab 可一键创建当前库快照,也可查看并恢复
> `backups/` 的 SQLite 备份(`data/versions/` 的历史库快照仅在旧机器残留时可用);
> 恢复前会自动为当前库做安全备份。应用侧创建的快照保留最近 30 份(`backups/` 下),
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
  `journalctl -u echo-graph -e` 是否有报错;全新机器数据为空属正常,需从整库快照恢复(第 4 节)。
- **`git pull` 报本地修改冲突**:本地有未推送提交或未提交改动,先提交推送,或从 `backups/` 恢复后再拉。
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

## 8. 限流策略

写接口限流在应用层完成(`app/ratelimit.py` 的进程内滑动窗口,单 worker 部署下计数精确;
若改为多 worker,进程间不共享计数,需换共享存储如 Redis):

- 注册 / 登录按客户端 IP 限流(见 `app/auth.py`);
- 关注 / 取关按用户每小时限流(见 `app/follows.py`)。

信任边界:`TRUSTED_PROXIES`(默认 `127.0.0.1,::1`,可在 `.env` 用逗号分隔的 IP/CIDR
覆盖)决定是否解析 `X-Forwarded-For`;解析**从右向左跳过可信代理段**取第一个不可信
客户端 IP,客户端无法通过在左侧预置伪造值绕过限流。部署模板(nginx.conf /
setup-vps.sh)已把 `X-Forwarded-For` 直接设为 `$remote_addr`(单层代理,不再追加
客户端可控值);直连 uvicorn 或伪造请求头时一律使用对端地址。

> 早期贡献收件箱的 `/api/contribute/echo` 与对应 nginx `limit_req` zone 已随
> contributions 移除(2026-08-24),部署模板不再包含该限流块。
