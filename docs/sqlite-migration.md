# Echo Graph 策展数据迁移方案：CSV 事实源 → SQLite 主存 + 确定性 CSV 导出

> 状态：Phase 1-3 已实现（SQLite 主存、admin/importer/sync 切换、自动 CSV 导出、CI 导出门禁、贡献表并入同库）。P0-P2 优化已完成：行级 CRUD、统一连接层、schema 迁移 runner、索引、时间戳归一、DB CHECK、审计表、同步计数预检。本文档记录完整方案。

## 一、背景与目标

当前策展数据（作者 / 作品 / 涟漪）以 `data/real/*.csv` 为事实源，管理页编辑 CSV、导入脚本同步 Neo4j。随着写入方扩展到“网页管理页 + AI agent”，CSV 整文件读改写存在并发覆盖风险，且已不需要人直接阅读/编辑 CSV。

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
- `canonical_payload(rows...)` / `sync_payload()`：规范化载荷，供同步比对（与 admin 的 CSV 侧共用同一实现）；
- 级联软删除（作品→边、作者→作品+边）在 admin 侧单事务内执行。

## 五之二、P0-P2 优化清单（已完成）

- **行级 CRUD**：create/update/delete/restore 改为按 id 的事务写入，消除整库重写与并发丢更新；
- **统一连接层**：`app/db_sqlite.py` 一处管理连接/PRAGMA/事务，sqlite_store 与 contributions 共用；
- **schema 迁移 runner**：按 `meta.schema_version` 顺序执行迁移（v1 建表 / v2 索引+审计+时间戳归一 / v3 重建补 CHECK），迁移前自动一致性备份；
- **索引**：`edges(target_work_id)`、`work_authors(author_id)`、`contributions(status, created_at)`；
- **DB CHECK**：`works.language` 长度、`edges.evidence` 长度、`contributions.status` 枚举；
- **时间戳归一**：所有 createdAt/updatedAt/deletedAt 统一为 UTC `+00:00`（一次性数据迁移 + 写入归一）；
- **审计表** `audit_log`：每次管理写操作记录 action/kind/row_id/detail；
- **同步计数预检**：`/api/admin/sync` 先比 3 个活跃计数（单次查询），不一致即判未同步，一致才做全量比对。

## 六、模块改动点

| 模块 | 改动 |
|---|---|
| `app/admin.py` | CRUD/导出/导入接口路径与响应不变，内部改调 SQLite 层；`/api/admin/sync` 的 CSV 侧比对改为 SQLite 侧 |
| `app/importer.py` + `scripts/import_data.py` | `run_import` 改为从 SQLite 读；`--source csv` 退役或改为恢复工具 |
| `app/db.py` | 不变（JsonStore 兜底、Neo4j 查询层不动） |
| `app/contributions.py` | 表并入同库后仅连接路径统一 |
| 前端 | **零改动**（API 形状保持不变） |
| 测试 | 数据层测试改为 SQLite（临时库）；admin/sync/贡献测试适配；新增迁移往返一致性、导出确定性测试 |

## 七、确定性 CSV 导出 + git 纪律

- 从 SQLite 按 `ORDER BY id` 生成三份 CSV，表头与现在完全一致、UTF-8 BOM、格式稳定；
- 每次成功写入后自动刷新 `data/real/*.csv`（文件进 git，人工 / agent 提交）；
- CI 新增 `check-export` 门禁：跑导出 → `git diff --exit-code`，有差异即失败；
- 保留审计 / 回滚 / diff 能力，同时不让文件参与运行时真相。

## 八、分阶段实施

1. **Phase 1（已完成）**：建库建表、数据层 CRUD、迁移脚本、往返一致性测试；
2. **Phase 2（已完成）**：admin / importer / sync 全切到 SQLite；每次写入自动导出 CSV；旧 CSV 读写路径移除；
3. **Phase 3（已完成）**：CI 导出门禁、贡献表并入同库、文档（README / data_schema / data_real README）与 to-do 更新、`.gitignore` 调整。

## 九、风险与注意

- **响应形状不变是硬约束**：前端零改动全靠它；`work_authors` 归一化后必须在 API 层重组回 `author_id` 串；
- 时间戳卫生：现有 CSV 部分时间戳无时区，建议迁移/后续统一为 `+00:00`（避免导出比对抖动）；
- 并发：WAL + 单写事务覆盖“网页 + agent 同时写”；busy timeout 5s；
- AI agent 写路径即现有管理 API（Bearer + 校验 + 事务），无需新接口；“校验失败即回滚”作为强约束。

## 十、工作量粗估

Phase 1 约 2–3 天（含测试）；Phase 2 约 1–2 天；Phase 3 约 1 天。大头在数据层重构与测试适配，导入管线与 Neo4j 侧改动很小。
