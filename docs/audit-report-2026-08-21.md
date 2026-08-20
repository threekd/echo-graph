# Litnebula（echo-graph）全局审查报告

> 审查日期：2026-08-21　审查对象：`E:\Code\echo-graph` 全仓库（后端 / 前端 / 数据 / 部署 / CI / 文档 / Git 历史）

## 一、结论摘要

整体判断：**结构合理，迁移收敛干净，无重大功能缺陷**。经过 React 迁移、Neo4j → SQLite 迁移和多轮需求修正后，项目已收敛为「SQLite 唯一权威 + CSV 确定性导出 + React 受控渲染」的简洁形态，旧架构（Neo4j 查询层、JSON 兜底、原生 JS 静态页、CSV 事实源）的代码均已删除，没有发现指向已删除模块的运行时引用。

质量门禁全部通过：后端 77 个测试、前端 50 个测试、ruff、tsc、eslint、生产构建、运行时接口抽查均正常；CSV 与 SQLite 往返一致，数据无重复、无孤儿作品、无缺失出处。

发现的问题以「一致性 / 边界 / 可维护性」为主，无 P0 级缺陷。最重要的三点：

1. `.env.example` 默认开启 `PUBLIC_REVIEWED_ONLY=1`，与 README 所述「默认关闭」矛盾，且当前仅 23/106 部作品为 `reviewed`——新部署会呈现一个近乎空图的公开视图；
2. 本地环境残留 Neo4j/OpenPyXL 依赖包与大量已删除模块的 `__pycache__`；
3. 贡献接口限流依赖代理头，仅在 nginx 后安全，缺少显式信任边界与 nginx 层限流。

## 二、审查方法

本次审查执行了以下检查：

- 全仓库文件清单 + Git 跟踪清单 + `.gitignore` 对照，排查未跟踪/遗漏文件；
- Git 历史（含 `--diff-filter=D` 删除记录）核对迁移是否留下引用、文档或脚本残留；
- 后端逐模块通读：`main / db / sqlite_store / db_sqlite / data_models / data_store / admin / backups / contributions`；
- 前端逐模块通读：`store / graph / graphData / renderer / layout(+worker) / util` 与全部组件；
- 部署脚本（`setup-vps.sh` / `deploy.sh` / systemd / nginx）与 CI 工作流逐行检查；
- 实际运行验证：后端测试、ruff、tsc、eslint、Vitest、`pnpm build`、`uvicorn` 启动 + 接口抽查；
- 数据核验：CSV ↔ SQLite 往返一致性、审核状态分布、孤儿作品、缺失出处、重复项、软删除行、审计/贡献表状态；
- 安全扫描：Git 全历史中是否出现过 `.env`、ADMIN_TOKEN 等敏感信息（结果为否）。

## 三、结构与分层评估

### 3.1 当前架构

```
前端 React 19 + TS ──> /api/* ──> FastAPI
                                      │
                     ┌────────────────┼──────────────────┐
                     ▼                ▼                  ▼
              db.py(公开读)    admin.py(管理写)     contributions.py(收件箱)
                     │                │                  │
                     └──────── db_sqlite.py(连接/事务/schema 迁移/审计) ──┘
                                      │
                              data/echo-graph.db(唯一权威)
                                      │
                              data/export/*.csv(确定性导出, git 审计)
```

### 3.2 分层评估

| 层 | 文件 | 评估 |
|---|---|---|
| 路由 | `app/main.py` | 职责单一，版本号单一来源（pyproject），静态路径穿越防护有回归测试 |
| 公开读 | `app/db.py` | 输出形状稳定，`reviewed_only` 过滤语义清晰；每请求全表载入（见问题 P2-4） |
| 管理写 | `app/admin.py` | 行级 CRUD + 校验 + 乐观锁 + 审计 + 自动 CSV 导出，链路完整 |
| 连接/schema | `app/db_sqlite.py` | 统一连接、迁移 runner（v1-v4）、时间戳归一，设计良好 |
| 数据模型 | `app/data_models.py` | Pydantic 校验单一来源，导入与 admin 共用 |
| CSV 层 | `app/data_store.py` | 确定性导出、原子替换、清洗函数独立 |
| 快照 | `app/backups.py` | 路径白名单校验 + 恢复前安全备份，边界处理到位 |
| 前端核心 | `store/graph/renderer/layout` | 受控化拆分清晰：store 持状态、graph 编排、renderer 纯执行、layout 纯算法（主线程/Worker 共用） |
| 前端管理 | `components/admin/*` | 通用表格 + 三个独立面板 + 纯函数筛选排序，测试覆盖良好 |
| 部署 | `deploy/*` | 与当前架构一致（单 worker、SQLite 备份、CSV 重建、nginx 托管静态） |
| CI | `.github/workflows/ci.yml` | 后端测试/lint、前端 lint/typecheck/test/build、版本一致性、CSV 新鲜度门禁齐全 |

**正面亮点**：迁移纪律很好——`docs/sqlite-migration.md` 完整记录了演进过程；删除的文件（importer、import_data、export_seed、generate_seed_data、static/、旧 JS 模块、data/real、data/snapshots、seed.json）没有留下任何运行时代码引用；Git 历史中从未跟踪 `.env`，无敏感信息泄露。

## 四、验证结果

| 检查项 | 结果 |
|---|---|
| 后端测试 `unittest discover` | 77/77 通过 |
| 后端 lint `ruff check .` | 0 错误 |
| 前端 typecheck `tsc --noEmit` | 通过 |
| 前端 lint `eslint .` | 通过 |
| 前端单测 `vitest run` | 50/50 通过（6 个文件） |
| 前端生产构建 `pnpm build` | 成功（主包 245KB / three 518KB / Admin 33KB 独立 chunk） |
| 运行时 `uvicorn` + 接口抽查 | `/api/health`、`/api/stats`、`/api/graph`、`/api/search` 正常 |
| CSV 导出新鲜度 `export_csv.py --check` | 与仓库一致 |
| 数据一致性 | SQLite ↔ CSV 规范化载荷一致，schema_version=4 |
| 数据质量 | 无重复作者名/作品名/涟漪对；无孤儿作品；0 条活跃边缺失出处 |

当前数据规模：19 位作者（18 reviewed）、106 部作品（23 reviewed / 83 draft）、19 条涟漪边（18 reviewed）、1 条待审核贡献、1 部软删除作品、1 条软删除边。

## 五、发现的问题与建议

### P1（建议尽快处理）

1. **`PUBLIC_REVIEWED_ONLY` 默认值前后矛盾**
   README 写「默认关闭以便开发时看到全部数据」，`.env.example` 却已改为 `PUBLIC_REVIEWED_ONLY=1`，且 `deploy/setup-vps.sh` 会直接把 `.env.example` 复制为生产 `.env`。当前 83/106 部作品仍是 draft，一旦部署，公开视图只剩 23 部作品、18 位作者、18 条边，几乎空图。
   建议：`.env.example` 改回 `# PUBLIC_REVIEWED_ONLY=0`（默认注释/关闭），并把「上线前逐条审核并开启」写进 `deploy/DEPLOY.md` 的启动检查清单；或者反过来，先完成数据审核再默认开启。

2. **本地依赖环境残留旧包**
   `.venv/Lib/site-packages/` 中仍存在 `neo4j/`、`openpyxl/`（uv.lock 已无这些依赖），说明 venv 在依赖清理后未重新同步。执行一次 `uv sync --frozen` 即可清除。

3. **贡献接口限流的信任边界**
   `contributions.py` 以 `request.client.host` 限流。uvicorn 默认开启 `--proxy-headers` 信任任意来源的 `X-Forwarded-For`：当前部署（nginx → uvicorn）下生效，但如果 uvicorn 被直接暴露，客户端可伪造请求头绕过限流。建议：nginx 层加 `limit_req`，或 uvicorn 配置 `--proxy-headers` + 可信代理，并明确写入部署文档。

### P2（结构性冗余 / 可优化）

4. **公开读层每请求全量载入**
   `app/db.py` 的 `_tables()` 每次请求都读三张全表 + 关联表，路径/扩散用内存 BFS。当前 106 行无碍（毫秒级），但这是明确记录的取舍。建议在数据量到数千行时：进程内缓存（admin 写后失效，可直接挂在 `export_csv_files` 之后）+ `edges(source_work_id)` 索引 + 搜索改 SQLite FTS5。可先只做索引与缓存，改动很小。

5. **列定义重复**
   `app/sqlite_store.py` 的 `AUTHOR_COLS/WORK_COLS/EDGE_COLS` 与 `app/data_store.py` 的 `AUTHOR_HEADER/WORK_HEADER/EDGE_HEADER` 内容相同。建议收敛为单一来源（例如定义在 `sqlite_store.py`，`data_store` 引用），避免未来加列时漏改一处。

6. **`rewrite_all` 实际只被测试使用**
   该函数（含从 `author_id` 字符串反推 `work_authors` 的逻辑）在生产代码中无调用方，仅测试用于造数据。建议标注为「迁移/测试工具」或移入测试 helper，并说明它与 `replace_all` 的分工，避免维护两套整库重写路径。

7. **pnpm 构建许可配置双机制重叠**
   `frontend/.npmrc` 的 `dangerouslyAllowAllBuilds=true` 全局放行所有构建脚本，与 `pnpm-workspace.yaml` 的 `allowBuilds: esbuild: true` 重复且前者更宽。建议只保留 workspace 内的 `allowBuilds`（精确许可），删除全局开关。

8. **文档/注释过期点**
   - `README.md`「策展数据主存」与「存储与读取」两个要点内容重复；
   - `to-do.md` 中仍有 `graphData.js`、`v=12` 静态资源版本号、Neo4j 时代条目等旧引用（作为历史日志可接受，建议在文件头注明「历史记录，部分条目已过时」）；
   - `frontend/src/lib/graph.ts` 注释写「纯函数统一来自 graphData.js」，实际已是 `.ts`；
   - `docs/sqlite-migration.md` 第 1-10 节描述已退役架构，建议整体归档为 `docs/archive/sqlite-migration.md`（或保留但加醒目标记），正文只留第 11 节现状说明。

9. **两个同主题提交**
   `34d1e3b` 与 `1a1de2f` 提交信息相同（「公开视图按 reviewStatus 过滤草稿、快照恢复入口」），内容互补但难以从日志区分。属仓库卫生小项，可忽略。

### P3（运维 / 数据 / 体验）

10. **快照与审计无保留策略**
    `backups/` 中管理页手动创建的快照只在 `deploy.sh` 运行时被裁剪；`audit_log` 无限增长。建议给 `create_snapshot` 或 `list_snapshots` 加保留上限（如最近 30 份），并为审计表提供归档/裁剪脚本。

11. **`deploy.sh` 备份命令静默吞错**
    `tar czf ... data/export data/versions data/snapshots 2>/dev/null || true` 在 `data/versions`、`data/snapshots` 不存在时会部分失败且不提示。建议改为 `mkdir -p` 后打包，或逐个判断目录存在性，确保备份完整性可感知。

12. **恢复快照的并发窗口**
    `backups.py` 恢复时替换库文件并删除 `-wal/-shm`。若此时有请求正在写入，可能产生瞬时不一致。当前单 worker + 低流量下风险很低，建议在恢复接口前做一次写入互斥（或至少在文档/UI 中提示「恢复期间请勿编辑」）。

13. **数据策展是当前最大瓶颈**
    106 部作品只有 19 条涟漪边，83 部 draft；1 条待审核贡献。公开发布前需完成逐条审核与扩充（to-do.md 已跟踪）。另外「贡献通过」目前只改状态、不自动录入策展表，与 README 描述一致，但建议把「通过后自动建草稿行」提上路线图，避免人工复制。

## 六、推荐行动清单

### 短期（1-2 天）

- [ ] 统一 `PUBLIC_REVIEWED_ONLY` 语义（.env.example / README / DEPLOY.md）
- [ ] `uv sync --frozen` 清理 venv 残留；删除仓库内 `__pycache__`（含已删除模块的 .pyc）
- [ ] 补 `edges(source_work_id)` 索引（顺手）
- [ ] 修正过期注释（`graph.ts`），合并 README 重复段落

### 中期

- [ ] 公开读层加进程内缓存（admin 写后失效）或按需 SQL 化
- [ ] nginx `limit_req` + uvicorn 代理信任边界
- [ ] 快照/审计保留策略
- [ ] `deploy.sh` 备份健壮性修正
- [ ] 收敛列定义单一来源；`rewrite_all` 移入测试工具或明确标注

### 长期（已在 to-do 跟踪）

- [ ] 数据审核与扩充（83 部 draft 需逐条处理）
- [ ] 贡献审核通过后自动录入草稿行（人工/AI 校正）
- [ ] FTS5 全文检索、按年代/语言/国别配色、加载状态指示

## 七、遗留与废弃文件清单

### 已确认清理干净（Git 历史中已删除，代码无引用）

- `app/importer.py`、`scripts/import_data.py`、`scripts/export_seed.py`
- `scripts/generate_seed_data.py`、`scripts/migrate_contributions.py`
- `data/seed.json`、`data/snapshots/`、`data/real/`（现为 `data/export`）
- `static/` 整套、`frontend/src/lib/{actions,admin,panels,state,vendor}.js`
- `frontend/public/vendor/`、旧 `.jsx/.js` 源文件
- 测试 `test_json_store.py`、`test_neo4j_store.py`、`test_sync_status.py`
- 依赖 `neo4j`、`openpyxl`（uv.lock 中已移除，仅本地 venv 残留）

### 仅本地残留（建议清理）

- `app/__pycache__/importer.*.pyc`
- `scripts/__pycache__/import_data.*.pyc`、`generate_seed_data.*.pyc`、`_check_review.*.pyc`、`_smoke_admin.*.pyc`、`_smoke_edge_id.*.pyc`
- `tests/__pycache__/test_json_store.*.pyc`、`test_neo4j_store.*.pyc`、`test_sync_status.*.pyc`
- `.venv/Lib/site-packages/neo4j/`、`openpyxl/`（执行 `uv sync` 清除）

### 保留（有意支持的历史路径）

- `data/versions/`：管理端「快照」Tab 的历史 CSV/DB 恢复来源（新代码不再写入，仅读取）
- `backups/`：SQLite 备份目录（deploy.sh 与快照面板共用）

## 八、附：本次审查未覆盖/建议后续补充

- `frontend/src/styles.css`（约 25KB）未做逐条死选择器审计，若在意可后续用 CSS 覆盖率工具扫描；
- 未做浏览器端 3D 渲染性能实测（依赖真实机型/显卡）；
- 未对 `deploy/` 脚本做真实 VPS 演练（需要远端环境）。

## 九、修复记录（2026-08-21）

### 已修复

- **P1-1 配置矛盾**：`.env.example` 改为 `PUBLIC_REVIEWED_ONLY=0`，与 README 一致。
- **P1-2 本地残留**：`uv sync` 清除 venv 中的 neo4j/openpyxl；删除 11 个已删除模块的 `.pyc`（importer、import_data、generate_seed_data、旧测试等）。
- **P1-3 限流信任边界**：应用层自行解析客户端 IP（`TRUSTED_PROXIES` 白名单，默认 `127.0.0.1,::1`，仅可信代理采信 X-Forwarded-For）；nginx 模板增加 `limit_req` 防洪；提交上限调整为每 IP 每小时 20 条（`SUBMIT_LIMIT=20`）；补 6 个限流单测。
- **P2-4 读层缓存与索引**：`app/db.py` 增加按 DB 路径的进程内缓存（TTL 3 秒），admin 写路径 / 整库重建 / 快照恢复显式 `invalidate_cache()`；新增 schema 迁移 v5（`idx_edges_source`）。FTS5 留作长期项。
- **P2-5 列定义单一来源**：`data_store.py` 表头由 `sqlite_store.py` 列定义派生（works 在 Title_Other 后插入 author_id），CSV 导出字节级一致。
- **P2-6 rewrite_all 职责标注**：docstring 明确「测试/恢复工具」，说明与 `replace_all` 的分工。
- **P2-7 pnpm 许可收敛**：删除 `frontend/.npmrc` 的全局 `dangerouslyAllowAllBuilds`，仅保留 `pnpm-workspace.yaml` 的 `allowBuilds: esbuild: true`；install/build/test 均验证通过。
- **P2-8 文档/注释过期点**：README 合并重复段落；to-do.md 顶部加历史说明；`docs/sqlite-migration.md` 加历史档案横幅；`graph.ts` 注释修正为 `.ts`；`data_schema.md` 索引说明更新。
- **P3-10 快照与审计保留**：应用侧 `create_snapshot` 后保留最近 30 份（`SNAPSHOT_RETENTION`，含 pre-restore 安全备份）；新增 `scripts/prune_audit.py --days N [--dry-run]` 裁剪审计日志（默认 90 天），配套 schema 迁移 v6（`idx_audit_ts`）。
- **P3-11 deploy.sh 备份健壮性**：只打包实际存在的目录（data/export / data/versions / data/snapshots），失败显式告警且不中断部署。
- **P3-12 恢复并发窗口**：db 恢复改用 SQLite backup API 覆盖（不再文件替换 + 删除 -wal/-shm）；恢复持有 `db_sqlite._write_lock`，与 admin 写事务、贡献提交互斥；快照面板与 DEPLOY.md 增加「恢复期间请勿编辑数据」提示。

### 未处理（有意跳过）

- **P2-9 两个同主题提交**（`34d1e3b` / `1a1de2f`）：仅仓库卫生问题，改写历史风险大于收益，建议忽略。
- **P3-13 数据策展**：106 部作品中 83 部仍为 draft、涟漪边仅 19 条，需人工逐条审核与扩充，代码层面无法自动完成。

### 修复后验证

- 后端 87 个测试（含新增缓存/限流/保留策略/审计裁剪测试）+ ruff 全绿；
- 前端 50 个测试 + typecheck + lint + 生产构建全绿；
- CSV 导出新鲜度校验与仓库一致（表头派生未改变输出）；
- 本地库已迁移至 schema v6，`idx_edges_source` / `idx_edges_target` / `idx_audit_ts` 均就位。
