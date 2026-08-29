# Litnebula 运维手册

> 适用范围:单机部署(`nginx → uvicorn(单 worker) → SQLite`),与
> [`../deploy/DEPLOY.md`](../deploy/DEPLOY.md) 配套;上线流程见 DEPLOY.md,
> 本文覆盖日常运维、备份恢复、用户数据迁移与故障排查。

## 1. 架构与数据全景

```
浏览器 → nginx(80/443,静态资源 + 反代 /api/)
              └→ uvicorn(127.0.0.1:8000,单 worker)
                    └→ data/echo-graph.db(SQLite,WAL,唯一权威)
备份:整库快照 backups/echo-graph-*.db(sqlite3 .backup)+ 管理端「快照」恢复
```

| 数据 | 位置 | 是否进 git | 说明 |
|---|---|---|---|
| 权威库(全部数据) | `data/echo-graph.db` | 否 | 全部用户星云 / 审计 / 用户与会话;schema 迁移启动时自动执行 |
| 整库快照 | `backups/echo-graph-*.db` | 否 | 管理端快照 + `deploy.sh` 自动备份 |
| 历史快照 | `data/versions/` | 否 | 只读恢复来源(旧机制遗留,新代码不再写入;通常不存在) |
| 部署备份包 | `backups/data-*.tgz` | 否 | `deploy.sh` 对数据目录的打包 |

关键语义:

- **不存在默认视图/官方图谱**(2026-08-28 移除):登录用户首页即自己的星云
  (`/api/me/*`),游客无默认图谱,经星际跃迁浏览公开星云(`/api/space/*`)。
- **用户星云** = `authors/works/edges` 中 `owner_id=用户id` 的行,只存于 SQLite。
- **单 worker 是设计约束**:限流(进程内滑动窗口)、读缓存与写锁(`_write_lock`)
  都依赖单进程语义,不要增加 uvicorn worker。

## 2. 备份体系

### 2.1 备份矩阵

| 方式 | 覆盖范围 | 触发 | 保留 |
|---|---|---|---|
| 管理端快照(UI / API) | 整库 | 手动 | 最近 30 份(`SNAPSHOT_RETENTION`) |
| `deploy.sh` | 整库 `.db` + 数据目录 `.tgz` | 每次更新部署 | 各 14 份 |
| `scripts/prune_audit.py` | `audit_log` | cron(建议每日) | 默认保留 90 天 |

### 2.2 手动备份

`.backup` 是 SQLite 官方一致性备份 API,可在服务运行中执行:

```bash
mkdir -p backups
sqlite3 data/echo-graph.db ".backup 'backups/manual-$(date +%Y%m%d-%H%M%S).db'"
```

或通过应用 API(需 admin 登录态 Cookie):

```bash
curl -X POST -b cookies.txt http://127.0.0.1:8000/api/admin/backups/create
```

### 2.3 `deploy.sh` 自动备份

每次部署前自动执行:`backups/echo-graph-<时间戳>.db`(SQLite `.backup` 一致性快照)
+ `backups/data-<时间戳>.tgz`(打包实际存在的 `data/versions` 等数据目录),
各自保留最近 14 份。建议把 `backups/` 定期同步到异地(rsync / rclone / 对象存储),
否则单机磁盘故障等于没有备份。

### 2.4 备份验证(每月演练)

```bash
sqlite3 backups/echo-graph-<时间戳>.db "PRAGMA integrity_check;"
sqlite3 backups/echo-graph-<时间戳>.db "SELECT 'authors', count(*) FROM authors
UNION ALL SELECT 'works', count(*) FROM works
UNION ALL SELECT 'edges', count(*) FROM edges
UNION ALL SELECT 'users', count(*) FROM users;"
```

## 3. 快照列表与恢复

### 3.1 可恢复快照来源

管理端「运维管理 → 快照」(或 `GET /api/admin/backups`)列出:

- `backups/echo-graph-*.db`(当前实际来源);
- `data/versions/<目录>/echo-graph.db` 历史库快照(旧机制遗留,仅当目录存在时出现)。

路径白名单:只允许 `backups/` 与 `data/versions/` 下的快照,防止任意文件覆盖。

### 3.2 整库恢复

UI:运维管理 → 快照 → 选择 db 条目 → 恢复。API:

```bash
curl -X POST -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"file":"backups/echo-graph-<时间戳>.db"}' \
  http://127.0.0.1:8000/api/admin/backups/restore
```

语义与护栏:

- 用 SQLite backup API 把快照内容**覆盖**当前库,回到快照时刻(用户星云 / 审计 /
  会话一并回退);
- 恢复前自动生成安全备份 `backups/echo-graph-pre-restore-<时间戳>.db`;
- 恢复全程与所有写事务互斥,**恢复期间请勿编辑数据**;
- 成功后自动清空读缓存;引导管理员角色由 `bootstrap_admin()` 兜底补齐。

### 3.3 全新环境引导(不是恢复,谨慎!)

服务首次启动自动创建并迁移 SQLite schema(**空库**)。全新环境的数据需从整库备份
恢复:把 `backups/echo-graph-*.db` 放到目标机器后,用管理端「快照」恢复,或停服后
直接替换 `data/echo-graph.db`(建议先跑 `PRAGMA integrity_check`)。

## 4. 用户数据的备份与迁移

用户数据 = 每个账号的个人星云 + 用户表 / 会话,只存在于 SQLite,**不进 git**。

### 4.1 备份

唯一可靠方式 = **整库快照**(见 2.2)。单用户导出:星云工坊页「导出 CSV」按钮
(`GET /api/me/export`,所有登录用户统一)。

### 4.2 迁移场景

- **整体回滚(最简单)**:db 快照恢复(3.2),代价是快照后的变更一并回退;
- **单用户空间迁移**:把某用户数据从备份库复制进当前库(或另一个账号名下),
  无内置接口,用 SQLite `ATTACH` 手动完成,模板见 4.3;
- **单用户数据导出(查看/审计)**:按 `owner_id` SELECT,见 4.4。

### 4.3 单用户空间迁移 SQL 模板

操作前提:先对当前库做安全备份;低峰期执行;迁移前后核对行数。

```sql
ATTACH 'backups/echo-graph-<时间戳>.db' AS bak;
BEGIN;

INSERT OR IGNORE INTO authors
  (id, originalName, Name_CN, Name_EN, nationality, birthYear, deathYear,
   note, reviewStatus, owner_id, createdAt, updatedAt, deletedAt)
SELECT id, originalName, Name_CN, Name_EN, nationality, birthYear, deathYear,
       note, reviewStatus, '<dst_user_id>', createdAt, updatedAt, deletedAt
FROM bak.authors WHERE owner_id = '<src_user_id>';

INSERT OR IGNORE INTO works
  (id, language, originalTitle, Title_CN, Title_EN, Title_Other, publicationYear,
   genre, note, reviewStatus, recommendation, review,
   owner_id, createdAt, updatedAt, deletedAt)
SELECT id, language, originalTitle, Title_CN, Title_EN, Title_Other, publicationYear,
       genre, note, reviewStatus, recommendation, review,
       '<dst_user_id>', createdAt, updatedAt, deletedAt
FROM bak.works WHERE owner_id = '<src_user_id>';

-- 作品-作者关联表必须同步迁移,否则作品会失去作者
INSERT OR IGNORE INTO work_authors (work_id, author_id)
SELECT wa.work_id, wa.author_id
FROM bak.work_authors wa
JOIN bak.works w ON w.id = wa.work_id
WHERE w.owner_id = '<src_user_id>';

INSERT OR IGNORE INTO edges
  (id, source_work_id, target_work_id, evidence, evidenceSource, note,
   reviewStatus, owner_id, createdAt, updatedAt, deletedAt)
SELECT id, source_work_id, target_work_id, evidence, evidenceSource, note,
       reviewStatus, '<dst_user_id>', createdAt, updatedAt, deletedAt
FROM bak.edges WHERE owner_id = '<src_user_id>';

COMMIT;
DETACH bak;
```

要点:

- 业务行 id 与用户 id 均为 UUID,跨库冲突概率可忽略;`INSERT OR IGNORE` 兜底;
- **作品迁移必须同时迁移 `work_authors`**,否则关联作者丢失;
- 涟漪两端作品、作品关联作者必须同属目标空间(应用层 `validate_row` 拒绝跨空间引用);
- 软删除行随行保留,读取层自动过滤;
- 目标用户不存在时需先在目标库创建(users 表),否则产生孤儿 `owner_id`;
  **注意 sqlite3 CLI 默认不开启外键检查**,务必自行保证 `<dst_user_id>` 已存在。

### 4.4 单用户数据导出(SELECT 模板)

```bash
sqlite3 data/echo-graph.db -header -csv "SELECT * FROM authors WHERE owner_id='<user_id>';" > user-authors.csv
sqlite3 data/echo-graph.db -header -csv "SELECT * FROM works WHERE owner_id='<user_id>';" > user-works.csv
sqlite3 data/echo-graph.db -header -csv "SELECT * FROM edges WHERE owner_id='<user_id>';" > user-edges.csv
```

导出仅供查看/审计;完整迁移(含 `work_authors` 与用户账号)走 4.3。

## 5. 日常运维清单

```bash
curl -fsS http://127.0.0.1:8000/api/health   # 期望 {"status":"ok","store":"sqlite"}
journalctl -u echo-graph -f                   # 实时日志
du -sh data backups                           # 磁盘占用
```

| 频率 | 任务 | 命令 |
|---|---|---|
| 每日 03:00 | SQLite 一致性备份 | `sqlite3 data/echo-graph.db ".backup 'backups/daily.db'"` |
| 每日 03:30 | 审计日志裁剪 | `cd /opt/echo-graph && uv run --frozen python scripts/prune_audit.py --days 90` |
| 每次部署 | 自动备份 + 更新 | `sudo -u echograph bash /opt/echo-graph/deploy/deploy.sh` |
| 每月 | 恢复演练 + 完整性检查 | 见 2.4 |
| 持续 | 异地同步 `backups/` | rsync / rclone / 对象存储 |

## 6. 更新 / 回滚

- **日常更新**:`sudo -u echograph bash /opt/echo-graph/deploy/deploy.sh`
  (自动备份 → `git pull --ff-only` → 装依赖 → 构建前端 → 重启 → 健康检查)。
- **git pull 失败**:多为本地有未推送提交或未提交改动,先提交推送再部署。
- **代码回滚**:`git -C /opt/echo-graph checkout <旧commit> -- .` 后重新执行
  `deploy.sh`(数据目录已由 deploy 自动备份)。
- **数据回滚**:整库用 db 快照恢复(3.2)。

## 7. 故障排查速查

| 现象 | 排查思路 |
|---|---|
| 页面空图,`/api/health` 正常 | 未登录用户无默认图谱(预期);确认 `data/echo-graph.db` 存在且有数据;看 `journalctl -u echo-graph -e` |
| 服务起不来 | `.env` 是否配置 `ADMIN_BOOTSTRAP_EMAIL`;uv/pnpm 路径;`uv run --frozen python -c "from app.main import app"` 导入自检 |
| 磁盘满 | WAL(`-wal`/`-shm`)与 `backups/` 是主要增长源;清理旧快照并异地转移 |
| 恢复后数据不对 | 恢复前有 `echo-graph-pre-restore-*.db` 安全备份,可再恢复一次;核对 2.4 行数 |
| AI 导入 500「创建上传目录失败:Permission denied」 | 服务账号对 git 检出目录不可写。一次性修复:`sudo chown -R echograph:echograph /opt/echo-graph`;新版上传目录默认在 `data/imports`(服务账号可写),也可用 `IMPORT_DIR` 指向专用可写盘 |
| 忘记密码/验证邮件发不出 | 看后端日志中 DirectMail 的 `Code/Message`:`Forbidden` = AccessKey 无邮件推送权限或不属于开通邮件推送的账号;`InvalidMailAddress.NotFound` = 发信地址不在当前配置的区域(`ALIYUN_DM_REGION` 必须与控制台创建地址的区域一致) |
| 邮件进 Gmail/QQ 垃圾箱 | 看邮件头 `Authentication-Results` 是否 `spf=pass`/`dkim=pass`/`dmarc=pass`:不全则补 DNS;全 pass 是新域名/共享 IP 信誉冷启动——收件人标记「不是垃圾邮件」+ 加入联系人,检查链接是否被阿里云跟踪域名改写,保持少量真实事务邮件养 1~4 周 |

## 8. 关键配置(.env)

| 变量 | 作用 | 运维注意 |
|---|---|---|
| `ADMIN_BOOTSTRAP_EMAIL` | 引导管理员(首个管理员) | 必须配置 |
| `COOKIE_SECURE` | HTTPS 下置 1 | 与证书配套 |
| `TURNSTILE_*` | 注册人机验证 | 生产必须配置;未配置且未设 `TURNSTILE_ALLOW_SKIP=1` 时注册 fail-closed |
| `TRUSTED_PROXIES` | 限流可信代理白名单 | 多级代理时逐级加入 |
| `MAILER` | 邮件发送器(api = DirectMail / smtp) | 邮箱验证与忘记密码依赖;未配置时仅本地日志,相关接口 503 |
| `ALIYUN_DM_*` | DirectMail AccessKey / 发信地址 / 区域 | `MAILER=api` 必填;`ACCOUNT_NAME` 填控制台创建的发信地址(不是随机账号),`REGION` 必须与发信地址所在区域一致;大陆区域需 ICP 备案,海外 VPS 用 `ap-southeast-1` |
| `SMTP_*` | SMTP 备用通道 | `MAILER=smtp` 必填;465 SSL 或 587 STARTTLS |
| `SITE_BASE_URL` | 邮件深链的外部站点地址 | 生产必须配置(如 `https://litnebula.com`) |
| `EMAIL_VERIFY_REQUIRED` | 注册邮箱验证开关 | 生产建议 1;开启后引导管理员验证后才提权 |
| `LANDING_SPACE` | 游客落地星云(用户名,可选) | 游客打开首页自动进入该公开星云;用户名仅服务端配置,不出现在 URL/界面 |
| `IMPORT_DIR` | AI 书籍导入上传临时目录(可选) | 缺省 `<项目>/data/imports`(服务账号可写);目录须服务账号可写 |
