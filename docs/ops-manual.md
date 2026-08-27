# Litnebula 运维手册

> 适用范围:单机部署(`nginx → uvicorn(单 worker) → SQLite`),与 [`../deploy/DEPLOY.md`](../deploy/DEPLOY.md) 配套。
> 部署上线流程见 DEPLOY.md;本文覆盖日常运维、备份恢复、用户数据迁移与故障排查。

## 1. 架构与数据全景

```
浏览器 → nginx(80/443,静态资源 + 反代 /api/)
              └→ uvicorn(127.0.0.1:8000,单 worker)
                    └→ data/echo-graph.db(SQLite,WAL,唯一权威)
备份:整库快照 backups/echo-graph-*.db(sqlite3 .backup)+ 管理端「快照」恢复
```

数据存放位置:

| 数据 | 位置 | 是否进 git | 说明 |
|---|---|---|---|
| 权威库(全部数据) | `data/echo-graph.db` | 否 | 全部用户星云(含 admin)/ 审计日志 / 用户与会话;schema 迁移启动时自动执行 |
| 整库快照 | `backups/echo-graph-*.db` | 否 | 管理端快照 + `deploy.sh` 自动备份 |
| 历史快照 | `data/versions/` | 否 | 只读恢复来源(旧机制遗留,新代码不再写入;**当前环境不存在此目录,仅有旧机器残留时才有内容**) |
| 部署备份包 | `backups/data-*.tgz` | 否 | `deploy.sh` 对数据目录的打包 |

关键语义:

- **不存在默认视图/官方图谱(2026-08-28 移除)**:功能栏「公共星云」标签、`/api/*`
  默认视图端点与 `PUBLIC_REVIEWED_ONLY` 均已下线;登录用户首页即自己的星云
  (`/api/me/*`),游客无默认图谱,可通过星际跃迁浏览公开星云(`/api/space/*`)。
- **用户星云 = `authors/works/edges` 中 `owner_id=用户id` 的行**,只存在 SQLite 中,不进 git。
- 单 worker 是设计约束:限流(进程内滑动窗口)与写锁(`_write_lock`)都依赖单进程语义,不要增加 uvicorn worker。

## 2. 备份体系

### 2.1 备份矩阵

| 方式 | 覆盖范围 | 触发 | 保留 |
|---|---|---|---|
| 管理端快照(UI / API) | 整库(含用户星云) | 手动 | 最近 30 份(`SNAPSHOT_RETENTION`) |
| `deploy.sh` | 整库 `.db` + 数据目录 `.tgz` | 每次更新部署 | 各 14 份 |
| `scripts/prune_audit.py` | `audit_log` | cron(建议每日) | 默认保留 90 天 |

### 2.2 手动备份(推荐 sqlite3 .backup)

`.backup` 是 SQLite 官方一致性备份 API,不依赖 WAL 文件,可以在服务运行中执行:

```bash
mkdir -p backups
sqlite3 data/echo-graph.db ".backup 'backups/manual-$(date +%Y%m%d-%H%M%S).db'"
```

或通过应用 API(需 admin 登录态 Cookie):

```bash
curl -X POST -b cookies.txt http://127.0.0.1:8000/api/admin/backups/create
```

### 2.3 `deploy.sh` 自动备份

每次部署前自动执行:

- `backups/data-<时间戳>.tgz`:打包**实际存在**的 `data/versions`、`data/snapshots`
  (目录不存在时自动跳过;`data/export` CSV 备份层已于 2026-08-27 移除);
- `backups/echo-graph-<时间戳>.db`:SQLite `.backup` 一致性快照;
- 各自只保留最近 14 份,旧文件自动删除。

建议把 `backups/` 定期同步到异地(rsync / rclone / 对象存储),否则单机磁盘故障等于没有备份。

### 2.4 备份验证(每月演练)

备份是否可恢复必须定期验证,不能只看文件存在:

```bash
# 完整性检查
sqlite3 backups/echo-graph-<时间戳>.db "PRAGMA integrity_check;"

# 行数核对
sqlite3 backups/echo-graph-<时间戳>.db "SELECT 'authors', count(*) FROM authors
UNION ALL SELECT 'works', count(*) FROM works
UNION ALL SELECT 'edges', count(*) FROM edges
UNION ALL SELECT 'users', count(*) FROM users;"
```

## 3. 快照列表与恢复

### 3.1 可恢复快照来源

管理端「运维管理 → 快照」Tab(日志/快照自 2026-08-26 起位于运维管理窗口;或
`GET /api/admin/backups`)会列出两类:

- `db`:`backups/echo-graph-*.db`(当前实际来源);
- `db`:`data/versions/<目录>/echo-graph.db` 历史库快照(旧机制遗留,**仅当该目录存在时**才会出现;
  当前环境没有 `data/versions`,可恢复来源只有 `backups/` 下的 db 快照)。

路径白名单:只允许 `backups/` 与 `data/versions/` 下的快照,防止任意文件覆盖。
`data/versions/` 缺失时不影响任何功能——`list_snapshots` 对不存在的目录自动跳过。

### 3.2 整库恢复(db 类型)

UI:运维管理 → 快照 → 选择 db 条目 → 恢复。

API:

```bash
curl -X POST -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"file":"backups/echo-graph-<时间戳>.db"}' \
  http://127.0.0.1:8000/api/admin/backups/restore
```

语义与护栏:

- 用 SQLite backup API 把快照内容**覆盖**当前库,回到快照时刻(用户星云 / 审计 / 会话一并回退);
- 恢复前自动生成安全备份 `backups/echo-graph-pre-restore-<时间戳>.db`;
- 恢复全程与所有写事务互斥,**恢复期间请勿编辑数据**;
- 成功后自动清空读缓存(旧库遗留未归属行由启动引导一次性认领)。

### 3.3 全新环境引导(不是恢复,谨慎!)

服务首次启动会自动创建并迁移 SQLite schema(**空库**)。全新环境的数据需要从
整库备份恢复:把 `backups/echo-graph-*.db` 放到目标机器后,用管理端「快照」恢复,
或停服后直接替换 `data/echo-graph.db`(建议先跑 `PRAGMA integrity_check`)。
跨机器的整库备份/恢复方案见 `to-do.md` 的「整库备份」待办。

## 4. 用户数据的备份与导入(重点)

用户数据 = 每个账号的个人星云(`authors/works/edges` 中 `owner_id=该用户` 的行)+ 用户表 / 会话。
它们**只存在于 SQLite,不进 git**——代码仓库无法携带用户数据,备份必须走整库快照。

### 4.1 用户数据备份

唯一可靠方式 = **整库快照**:

```bash
# 推荐:SQLite .backup(一致性,可在线执行)
sqlite3 data/echo-graph.db ".backup 'backups/full-$(date +%Y%m%d-%H%M%S).db'"
```

或使用管理端快照 / `deploy.sh` 自动备份(见 2.2、2.3)。备份粒度是"全库",包含全部用户;
单用户导出:登录后星云工坊页「导出 CSV」按钮,可把本人星云三张表打包为 zip
(`GET /api/me/export`,admin 为 `GET /api/admin/export`)。

### 4.2 用户数据导入

按场景选择:

**a) 整体回滚(最简单,覆盖全库)** —— 用 db 类型快照恢复(见 3.2)。适用于"整体回到某个时间点",
代价是快照之后的所有变更(含其他用户数据)一并回退。

**b) 单用户空间迁移** —— 把某个用户的数据从备份库复制进当前库(或另一个账号名下)。
当前无内置接口,用 SQLite `ATTACH` 手动完成,示例见 4.3。

**c) 单用户数据导出(给用户本人 / 审计)** —— 按 `owner_id` 查询即可,示例见 4.4。

### 4.3 单用户空间迁移 SQL 模板

操作前提(必须):

1. 先对当前库做一次安全备份(`sqlite3 data/echo-graph.db ".backup ..."`);
2. 低峰期 / 停服窗口执行,迁移期间建议暂停写操作;
3. 迁移前后核对行数,迁移后抽查目标用户星云。

先只读核对源备份库中该用户的数据量:

```bash
sqlite3 backups/echo-graph-<时间戳>.db "
SELECT 'authors' AS kind, count(*) AS n FROM authors WHERE owner_id='<src_user_id>'
UNION ALL SELECT 'works', count(*) FROM works WHERE owner_id='<src_user_id>'
UNION ALL SELECT 'edges', count(*) FROM edges WHERE owner_id='<src_user_id>';"
```

在目标库执行迁移(把 `<src_user_id>` 的用户数据迁到 `<dst_user_id>` 名下):

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

迁移要点:

- 业务行 id 与用户 id 均为 UUID(v7),跨库冲突概率可忽略;`INSERT OR IGNORE` 兜底跳过已存在行;
- **作品迁移必须同时迁移 `work_authors`**,否则作品关联作者丢失;
- 涟漪边两端作品、作品关联作者必须同属目标空间——应用层 `validate_row` 拒绝跨空间引用,
  手工 SQL 绕过校验时更要保证完整性;
- 软删除行(`deletedAt` 非空)随行保留,读取层会自动过滤,无需特殊处理;
- 目标用户不存在时,需先在目标库注册/创建该用户(users 表),否则会产生孤儿 `owner_id`。
  注意:应用连接层开启了外键约束,但 **sqlite3 CLI 默认不开启外键检查**——手工 SQL 迁移不会
  自动拦截,务必自行保证 `<dst_user_id>` 已存在。

### 4.4 单用户数据导出(SELECT 模板)

```bash
sqlite3 data/echo-graph.db -header -csv "
SELECT * FROM authors WHERE owner_id='<user_id>';" > user-authors.csv
sqlite3 data/echo-graph.db -header -csv "
SELECT * FROM works WHERE owner_id='<user_id>';" > user-works.csv
sqlite3 data/echo-graph.db -header -csv "
SELECT * FROM edges WHERE owner_id='<user_id>';" > user-edges.csv
```

导出仅供查看/审计;要完整迁移(含 `work_authors` 关联与用户账号)仍建议走 4.3 的整空间 SQL 迁移。

## 5. 日常运维清单

```bash
# 健康检查(期望 {"status":"ok","store":"sqlite"})
curl -fsS http://127.0.0.1:8000/api/health

# 实时日志
journalctl -u echo-graph -f

# 最近日志
journalctl -u echo-graph -e

# 磁盘与备份目录
du -sh data backups
ls -lt backups | head -20
```

建议的例行任务:

| 频率 | 任务 | 命令 |
|---|---|---|
| 每日 03:00 | SQLite 一致性备份 | `sqlite3 data/echo-graph.db ".backup 'backups/daily.db'"` |
| 每日 03:30 | 审计日志裁剪 | `cd /opt/echo-graph && uv run --frozen python scripts/prune_audit.py --days 90` |
| 每次部署 | 自动备份 + 更新 | `sudo -u echograph bash /opt/echo-graph/deploy/deploy.sh` |
| 每月 | 恢复演练 + 完整性检查 | 见 2.4 |
| 持续 | 异地同步 `backups/` | rsync / rclone / 对象存储 |

## 6. 更新 / 回滚

- **日常更新**:`sudo -u echograph bash /opt/echo-graph/deploy/deploy.sh`(自动备份 → `git pull --ff-only` → 装依赖 → 构建前端 → 重启 → 健康检查)。
- **git pull 失败**:多为本地有未推送的提交或未提交改动;先提交推送再部署(`data/export` 已随 CSV 备份层移除,不再因此冲突)。
- **代码回滚**:`git -C /opt/echo-graph checkout <旧commit> -- .` 后重新执行 `deploy.sh`(数据目录已由 deploy 自动备份)。
- **数据回滚**:整库用 db 快照恢复(3.2)。

## 7. 故障排查速查

| 现象 | 排查思路 |
|---|---|
| 页面空图,`/api/health` 正常 | 未登录用户无默认图谱(空图属预期,需登录或星际跃迁);确认 `data/echo-graph.db` 存在且有数据;`journalctl -u echo-graph -e` |
| 服务起不来 | `.env` 是否配置 `ADMIN_BOOTSTRAP_EMAIL`;uv/pnpm 路径;`uv run --frozen python -c "from app.main import app"` 做导入自检 |
| git pull 报本地修改冲突 | 本地有未推送提交或未提交改动,先提交推送再部署 |
| 磁盘满 | WAL(`-wal`/`-shm`)与 `backups/` 是主要增长源;清理旧快照并异地转移 |
| 恢复后数据不对 | 恢复前有 `echo-graph-pre-restore-*.db` 安全备份,可再恢复一次;核对 2.4 的行数 |
| 想导出单个用户数据 | 见 4.4(仅查看)或 4.3(完整迁移) |

## 8. 关键配置(.env)

| 变量 | 作用 | 运维注意 |
|---|---|---|
| `ADMIN_BOOTSTRAP_EMAIL` | 引导管理员(首个管理员) | 必须配置 |
| `COOKIE_SECURE` | HTTPS 下置 1 | 与证书配套 |
| `TURNSTILE_*` | 注册人机验证 | 生产必须配置;未配置且未设 `TURNSTILE_ALLOW_SKIP=1` 时注册默认失败(fail-closed) |
| `TRUSTED_PROXIES` | 限流可信代理白名单 | 多级代理时逐级加入 |

## 9. 快速命令参考

```bash
# 备份
sqlite3 data/echo-graph.db ".backup 'backups/full-$(date +%Y%m%d-%H%M%S).db'"

# 整库恢复(管理端 API)
curl -X POST -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"file":"backups/full-<时间戳>.db"}' \
  http://127.0.0.1:8000/api/admin/backups/restore

# 审计裁剪
uv run python scripts/prune_audit.py --days 90 --dry-run   # 先统计
uv run python scripts/prune_audit.py --days 90             # 再执行

# 用户数据导出(星云工坊页「导出 CSV」按钮)
curl -b cookies.txt http://127.0.0.1:8000/api/me/export -o my-nebula.zip
```
