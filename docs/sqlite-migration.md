# Echo Graph 策展数据迁移方案：CSV 事实源 → SQLite 主存 + 确定性 CSV 导出

> 状态：Phase 1-3 已实现（SQLite 主存、admin/importer/sync 切换、自动 CSV 导出、CI 导出门禁、贡献表并入同库）。P0-P2 优化已完成：行级 CRUD、统一连接层、schema 迁移 runner、索引、时间戳归一、DB CHECK、审计表、同步计数预检。P3a-e 已完成：级联纯 SQL、行级校验、乐观并发、快照降频与分层清理、审计查询接口。前端 A/B 优化已完成：类型化与组件拆分、懒加载、乐观更新、审计 UI、导出按钮、author_ids 数组化。
> **Phase 4（已完成，2026-08-21）**：Neo4j 查询层与 JSON 兜底退役——公开读取全部由 SQLite 提供（`app/db.py` 改为 `SqliteStore`）；`importer.py`、`scripts/import_data.py`、`scripts/export_seed.py`、`/api/admin/sync`、管理页「上传↑」全部移除；部署脚本/文档收敛为单 worker + SQLite 备份 + CSV 重建；依赖清理（neo4j/openpyxl 移除、pydantic 显式声明）；版本 0.5.0。本文档第 1-10 节为历史迁移记录，第 11 节为本次演进说明。

## 一、背景与目标

当前策展数据（作者 / 作品 / 涟漪）以 `data/export/*.csv`（原名 `data/real`）为事实源，管理页编辑 CSV、导入脚本同步 Neo4j。随着写入方扩展到“网页管理页 + AI agent”，CSV 整文件读改写存在并发覆盖风险，且已不需要人直接阅读/编辑 CSV。

目标：

- SQLite 成为策展数据的**唯一权威存储**；
- 所有写操作（网页管理页 / AI agent）走“校验 + 事务”的同一写路径；
- CSV 降级为**确定性导出产物**（git 跟踪，用于审计 / 回滚 / 备份）；
- Neo4j 保持查询层；导入与同步比对改为 SQLite → Neo4j；
- 用户贡献收件箱（`contributions`）沿用 SQLite，并入同一库或同一种模式。

## 二、目标架构

```
写入路径(唯一):  网页管理页 / AI agent ──> 校验 + 事务 ──> SQLite(事实源)
                                                        │
                                        ┌───────────────┼────────────────┐
                                        ▼               ▼                ▼
                              Neo4j(查询层)      CSV 导出(git 审计)   contributions 表
                              导入/同步比对        确定性 + CI 门禁
```

原则：**SQLite 是唯一权威；CSV 是派生产物（只读、确定性、git 跟踪）；Neo4j 只做查询与导入目标；所有写操作必须过校验层。**

> 演进说明：上述为 Phase 1-3 的目标架构。Phase 4 进一步收敛——Neo4j 查询层退役，
> 公开读取直接由 SQLite 提供（`SqliteStore`），因此目标架构中的"Neo4j(查询层)"分支已删除。

## 三、数据库设计（`data/echo-graph.db`）

| 表 | 关键列 | 约束 |
|---|---|---|
| `authors` | id PK, originalName, Name_CN, Name_EN, nationality, birthYear, deathYear, reviewStatus, createdAt, updatedAt, deletedAt | NOT NULL(必填项), CHECK(reviewStatus) |
| `works` | id PK, language, originalTitle, Title_CN, Title_EN, Title_Other, publicationYear, creationYear, genre, reviewStatus, createdAt, updatedAt, deletedAt | NOT NULL(必填项) |
| `work_authors` | work_id FK→works.id, author_id FK→authors.id | PRIMARY KEY(work_id, author_id) |
| `edges` | id PK, source_work_id FK, target_work_id FK, evidence, evidenceSource, note, reviewStatus, createdAt, updatedAt, deletedAt | UNIQUE(source_work_id, target_work_id), CHECK(禁自环) |
| `contributions` | 现有 schema（后续并入同库） | 不变 |
| `meta` | schema_version 等 | — |

要点：

- 作者关联规范化：CSV 的逗号分隔 `author_id` 拆为 `work_authors` 关联表，消除多作者靠字符串解析的隐患；
- 软删除行保留在库中（`deletedAt` 非空），与现有 CSV 存档语义一致；导入 Neo4j 时跳过；
- 每个连接开启 `PRAGMA foreign_keys=ON` + WAL + busy timeout（沿用贡献表验证过的连接模式）；
- 数据库列名与现有 CSV 表头一致，便于行级形状复用与导出。

## 四、一次性数据迁移

`scripts/migrate_csv_to_sqlite.py`（核心逻辑在 `app/sqlite_store.migrate_from_csv`）：

1. 用现有 `load_rows()` + `parse_rows()` 先全量校验，失败即中止；
2. 单事务整库重建：authors → works → work_authors（拆分 author_id）→ edges；软删除行原样保留；
3. 迁移后自动做**往返一致性校验**：`sqlite 规范化载荷 == CSV 规范化载荷`，不一致则报错；
4. 回滚保证：迁移前 CSV 原样保留；`restore` 方向可由导出脚本反推（后续提供）。

## 五、数据层（`app/sqlite_store.py`）

- 统一连接层 `app/db_sqlite.py`（连接、事务、schema 迁移 runner、审计、时间戳归一）；
- 行级 CRUD（`get_row / insert_row / update_row / set_work_authors / mark_deleted / restore_by_ts`），admin 写入不再整库重写；
- `replace_all / rewrite_all`：单事务整库重建（迁移 / 恢复工具用）；
- `list_all()`：返回与 CSV `load_rows` 同形状的行（works 行重组 `author_id` 逗号串）；
- `canonical_payload(rows...)` / `sync_payload()`：规范化载荷，供 CSV <-> SQLite 往返一致性校验（`migrate_from_csv` 与测试共用）；
- 级联软删除（作品→边、作者→作品+边）在 admin 侧单事务内执行。

## 五之二、P0-P2 优化清单（已完成）

- **行级 CRUD**：create/update/delete/restore 改为按 id 的事务写入，消除整库重写与并发丢更新；
- **统一连接层**：`app/db_sqlite.py` 一处管理连接/PRAGMA/事务，sqlite_store 与 contributions 共用；
- **schema 迁移 runner**：按 `meta.schema_version` 顺序执行迁移（v1 建表 / v2 索引+审计+时间戳归一 / v3 重建补 CHECK），迁移前自动一致性备份；
- **索引**：`edges(target_work_id)`、`work_authors(author_id)`、`contributions(status, created_at)`；
- **DB CHECK**：`works.language` 长度、`edges.evidence` 长度、`contributions.status` 枚举；
- **时间戳归一**：所有 createdAt/updatedAt/deletedAt 统一为 UTC `+00:00`（一次性数据迁移 + 写入归一）；
- **审计表** `audit_log`：每次管理写操作记录 action/kind/row_id/detail；
- **同步计数预检**：`/api/admin/sync` 先比 3 个活跃计数（单次查询），不一致即判未同步，一致才做全量比对（Phase 4 已随 Neo4j 退役移除该接口）。

## 五之三、P3a-e 优化清单（已完成）

- **P3a 级联纯 SQL**：删除/恢复作品的涟漪边、作者名下作品与边，全部下推为 SQL（`UPDATE ... WHERE`/子查询），不再整库读取 + Python 算 id 集合；
- **P3b 行级校验**：create/update 改为“目标行 Pydantic 校验 + SQL 交叉引用（作者/作品存在性、边对唯一性）”，全量 `parse_rows` 仅保留给导入/迁移；变更响应不再附带全量重复警告（由 `get_data` 统一提供）；
- **P3c 乐观并发**：update 以客户端 `updatedAt` 为版本守卫，冲突返回 409；
- **P3d 快照降频与分层清理**：管理写操作不再每次做整库文件快照（由 audit_log + git CSV 承担历史）；`load_rows` 迁入 `sqlite_store`，删除残留的 `data_store.save_rows`；删除/级联同时更新 `updatedAt`；
- **P3e 审计查询**：新增 `GET /api/admin/audit`（按 action/kind/limit/offset 过滤审计记录）。

## 五之四、前端优化清单（A/B,已完成）

- **A1 类型化 + 拆分**：`lib/adminTypes.ts` 定义行/审计类型;Admin 拆出 `AdminTable`(通用表格)、`ContributionsPanel`、`AuditPanel`;引入 jsdom + testing-library,补组件测试(表格排序/筛选/软删除行);
- **A2 懒加载**：Admin/Contribute 改为 `React.lazy`,普通用户首屏不再下载管理代码(主 chunk 约 -30KB,Admin 独立 chunk 31KB);
- **A3 乐观更新 + 409**：增删改/恢复成功后本地更新行,不再整页重拉;409 版本冲突弹出「重新加载最新数据」确认框;
- **A4 审计 UI**：管理页新增「审计」Tab,按操作过滤查看 audit_log;
- **A5 导出按钮**：管理页导出 JSON / CSV 已移除(含 `/api/admin/export/*` 接口),备份由每次写入的自动 CSV 导出 + git 承担;
- **B6 author_ids 数组化**：API works 行附带 `author_ids` 数组,前端显示/编辑优先消费数组;
- **B7 include_deleted**：`/api/admin/data?include_deleted=` 支持按需拉取(服务端分页/筛选留待规模驱动)。

## 六、模块改动点

| 模块 | 改动 |
|---|---|
| `app/admin.py` | CRUD 接口路径与响应不变，内部改调 SQLite 层；`/api/admin/sync`、`/api/admin/import` 已随 Neo4j 退役删除 |
| `app/importer.py` + `scripts/import_data.py` | Phase 4 已删除（Neo4j 查询层退役，不再需要导入管线） |
| `app/db.py` | Phase 4 改为 `SqliteStore`：公开读取直接查 SQLite，JsonStore/Neo4jStore/ResilientStore 全部移除 |
| `app/contributions.py` | 表并入同库后仅连接路径统一 |
| 前端 | **零改动**（API 形状保持不变） |
| 测试 | 数据层测试改为 SQLite（临时库）；admin/贡献测试适配；新增迁移往返一致性、导出确定性、SqliteStore 读取测试 |

## 七、确定性 CSV 导出 + git 纪律

- 从 SQLite 按 `ORDER BY id` 生成三份 CSV，表头与现在完全一致、UTF-8 BOM、格式稳定；
- 每次成功写入后自动刷新 `data/export/*.csv`（文件进 git，人工 / agent 提交）；
- CI 新增 `check-export` 门禁：跑导出 → `git diff --exit-code`，有差异即失败；
- 保留审计 / 回滚 / diff 能力，同时不让文件参与运行时真相。

## 八、分阶段实施

1. **Phase 1（已完成）**：建库建表、数据层 CRUD、迁移脚本、往返一致性测试；
2. **Phase 2（已完成）**：admin / importer / sync 全切到 SQLite；每次写入自动导出 CSV；旧 CSV 读写路径移除；
3. **Phase 3（已完成）**：CI 导出门禁、贡献表并入同库、文档（README / data_schema / data_real README）与 to-do 更新、`.gitignore` 调整。
4. **Phase 4（已完成）**：Neo4j 查询层与 JSON 兜底退役，SQLite 承担全部读取；删除 importer/export_seed/sync 链路；部署脚本与文档收敛（单 worker、SQLite 备份、CSV 重建）；依赖与死代码清理；版本 0.5.0。

## 九、风险与注意

- **响应形状不变是硬约束**：前端零改动全靠它；`work_authors` 归一化后必须在 API 层重组回 `author_id` 串；
- 时间戳卫生：现有 CSV 部分时间戳无时区，建议迁移/后续统一为 `+00:00`（避免导出比对抖动）；
- 并发：WAL + 单写事务覆盖“网页 + agent 同时写”；busy timeout 5s；
- AI agent 写路径即现有管理 API（Bearer + 校验 + 事务），无需新接口；“校验失败即回滚”作为强约束。

## 十、工作量粗估

Phase 1 约 2–3 天（含测试）；Phase 2 约 1–2 天；Phase 3 约 1 天。大头在数据层重构与测试适配，导入管线与 Neo4j 侧改动很小。

## 十一、Phase 4 演进：Neo4j 查询层退役（SQLite 承担全部读取）

背景：Phase 1-3 后，架构为"SQLite 写权威 + Neo4j 查询层 + JSON 兜底种子 + CSV 审计"，四套数据表示并存，
每次管理编辑后需手动「上传↑」同步 Neo4j，兜底种子(seed.json)仅在部署时生成、可能漂移。
目标运行环境为 1核2G VPS，进一步放大了这套链路的维护成本。

变更：

- `app/db.py` 重写为单一 `SqliteStore`：`graph / search / path / work_detail / expansion / stats` 全部直接查 SQLite，
  输出形状与旧 JsonStore 完全一致（前端零改动）；软删除行读取时一律过滤。
- 删除 `app/importer.py`、`scripts/import_data.py`、`scripts/export_seed.py`、`/api/admin/sync`、`/api/admin/import`；
  管理页移除「上传↑」按钮与「数据未上传」提示。
- 部署收敛：`echo-graph.service` 单 worker；`deploy.sh` 用 `sqlite3 .backup` 备份权威库、部署时从仓库 CSV 重建 SQLite
  （contributions / audit_log 表不受影响）；`setup-vps.sh` 初始化时从 CSV 引导建库；`.env` 仅需 `ADMIN_TOKEN`。
- 依赖：移除 `neo4j` / `openpyxl`，显式声明 `pydantic`；版本升至 0.5.0。
- 清理：删除死代码 `data_store.snapshot`、`migrate_contributions.py`、`merge_legacy_db`、空目录与过期文档引用。

数据流（当前）：

```
写入+读取:  admin/AI/公开接口 ──> SQLite(唯一权威)
                                 └──> CSV 导出(git 审计 / 跨机器传输)
```
