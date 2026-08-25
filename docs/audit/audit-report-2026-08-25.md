# Litnebula（echo-graph）全局审查报告

> 审查日期：2026-08-25　审查对象：`E:\Code\echo-graph` 全仓库（后端 / 前端 / 数据 / 部署 / CI / 文档 / Git 历史）
> 关联文档：上一轮审查见 `./audit-report-2026-08-21.md`；本次为 4 天后的跟进审查。
>
> **同日跟进（2026-08-25）**：P1-1 已处理——`agent_temp` 完成整合优化（共享工具收敛、
> `pipeline_ingest` 改为进程内调用、删除一次性脚本 `agent_temp/tmp/e2e_llm_review.py`、
> 新增 `tests/test_llm_pipeline.py`），`ruff check .` 已清零；P2-2 已补 `.env.example` 的
> `DEEPSEEK_*` / `ALIYUN_*` 配置项。

## 一、结论摘要

整体判断：**架构健康，迁移持续收敛，无 P0 级缺陷**。上轮审查的 7 个问题已基本解决
（见第四节复查表）；SQLite 唯一权威 + CSV 确定性导出 + React 受控渲染的形态未变，
并在此基础上新增了多用户星云、关注模型、AI 草稿审核管道等能力，分层依然清晰。

本轮实测质量门禁：后端测试 130/130 通过、前端测试 61/61 通过、前端 lint/typecheck
通过、生产构建成功、版本号一致（0.5.0）。**唯一红灯是后端 lint 门禁：`ruff check .`
当前报 20 个错误，`.github/workflows/ci.yml` 的 backend lint 步骤在 main 上会失败**，
需尽快处理（详见 P1-1）。

其余发现以「文档滞后 / 代码卫生」为主：

1. **CI lint 门禁红色**：20 个 ruff 错误，19 个集中在 `agent_temp/`（含一次性脚本
   `agent_temp/tmp/e2e_llm_review.py`），1 个在 `app/llm_review.py`（导入排序）；
2. `.env.example` 未收录 AI 管线所需的 `DEEPSEEK_*` / `ALIYUN_*` 配置项；
3. 少量文档仍残留「贡献收件箱」表述（schema v22 已于 2026-08-24 删除该表）。

## 二、审查方法

- Git 跟踪清单 + `.gitignore` 对照，排查未跟踪/多余文件与本地杂物体积；
- 上轮审查问题逐条复查（P1-1 ~ P2-9 全部核对）；
- 后端逐模块通读：`main / db / db_sqlite / sqlite_store / data_store / data_models /
  space_crud / space / me / read_routes / auth / users / follows / ratelimit / security /
  backups / admin / llm_account / llm_review`；
- 前端结构通读：`lib/renderer*` 拆分、`lib/graph(graphData)`、`components/*` 与
  `components/admin/*`、`components/sidebar/*`，并做文件级「被引用」死代码扫描；
- 文档核对：README / to-do.md / docs/* / deploy/* 与代码、schema、接口的实际一致性；
- 实际运行验证：后端 unittest、ruff、前端 eslint / tsc / vitest / vite build；
- 数据核验：schema_version、三表活跃行数、用户/会话/审计/关注表规模。

## 三、验证结果（2026-08-25 实测）

| 检查项 | 结果 |
|---|---|
| 后端测试 `unittest discover` | 130/130 通过 |
| 后端 lint `ruff check .` | **20 个错误（CI 会红）** |
| 前端 lint `eslint .` | 通过 |
| 前端 typecheck `tsc --noEmit` | 通过 |
| 前端单测 `vitest run` | 61/61 通过（7 个文件） |
| 前端生产构建 `pnpm build` | 成功 |
| 版本一致性 | pyproject 与 package.json 均为 0.5.0 |
| 依赖 | uv.lock 无 neo4j/openpyxl 等退役依赖 |

当前数据规模（`data/echo-graph.db`，schema_version=24）：

| 表 | 总数 | 活跃（deletedAt 为空） |
|---|---|---|
| authors | 60 | 57 |
| works | 156 | 153 |
| edges | 66 | 64 |
| users | 5 | — |
| sessions | 3 | — |
| audit_log | 166 | — |
| friendships | 1 | — |

## 四、上轮问题复查（./audit-report-2026-08-21.md）

| # | 上轮问题 | 现状 |
|---|---|---|
| P1-1 | `PUBLIC_REVIEWED_ONLY` 默认值前后矛盾 | ✅ 已修复：`.env.example` 默认 `0`，`../../deploy/DEPLOY.md` 上线前清单明确「逐条审核后自行开启」 |
| P1-2 | 本地 venv 残留 neo4j/openpyxl | ✅ 已修复：uv.lock 与新版 `.venv` 均干净 |
| P1-3 | 限流信任边界（X-Forwarded-For 伪造） | ✅ 已修复：`app/ratelimit.py` 引入 `TRUSTED_PROXIES` 白名单，非可信对端不解析代理头；`.env.example` 有注释 |
| P2-4 | 公开读每请求全量载入 | ✅ 已修复：`app/db.py` 增加进程内读缓存（默认 3 秒 TTL），键含 DB 路径 + owner + reviewed_only，admin 写/快照恢复显式 `invalidate_cache()` |
| P2-5 | 列定义重复 | ✅ 已修复：`data_store` 直接引用 `sqlite_store` 的 `AUTHOR_COLS/WORK_COLS/EDGE_COLS` |
| P2-6 | `rewrite_all` 仅测试使用 | 🟡 部分：docstring 已注明与 `replace_all` 分工，但仍留在生产模块、仍只被测试调用（见 P2-4） |
| P2-7 | pnpm 构建许可双机制 | ✅ 已修复：`frontend/.npmrc` 已删除，仅留 workspace 精确许可 |
| P2-8 | 文档过期点 | 🟡 大部分修复：to-do.md 头部注明「历史日志、部分条目过时」；README「存储与读取」重复要点已合并；`graph.ts` 注释已更新；`../migration/sqlite-migration.md` 已加「第 1-10 节为历史档案」标注。仍残留少量「贡献收件箱」表述（见 P2-2） |
| P2-9 | 同主题重复提交 | ✅ 已处理（提交信息已恢复为中文业务描述） |

## 五、新发现问题

### P1（尽快处理）

1. **CI 后端 lint 门禁当前为红**
   `uvx ruff check .` 共 20 个错误：
   - `agent_temp/tmp/e2e_llm_review.py`：E401 / E701 / E402 / F401 / I001 共 16 处——该文件是
     一次性端到端校验脚本，未被 README/文档/任何代码引用；
   - `agent_temp/tools/llm_space.py`：UP017（`datetime.UTC` 别名）；
   - `agent_temp/tools/review_publish.py`：I001 导入排序 + F841 未使用变量 `public_ids`；
   - `app/llm_review.py`：I001 导入排序（唯一的 app 生产文件问题）。
   由于 CI 在仓库根执行 `uvx ruff check .` 且 pyproject 未配置 exclude，main 分支的
   backend lint 步骤自「审批管道 / AI 录入」提交以来必然失败。
   建议：`app/llm_review.py` 与 agent_temp 的 3 个脚本用 `ruff check --fix` 修复
   （F841/E701 需手工）；`agent_temp/tmp/e2e_llm_review.py` 若已用完，直接从 git 删除。

### P2（文档 / 一致性 / 卫生）

2. **`.env.example` 未收录 AI 管线配置**
   `agent_temp/tools/extract_source_book.py`、`llm_client.py`、`dedupe_check.py` 依赖
   `DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL`、`ALIYUN_API_KEY /
   ALIYUN_BASE_URL / ALIYUN_MODEL`，README 也描述了该管线，但 `.env.example` 没有这些键。
   新环境照模板配置会缺键。建议补入 `.env.example` 并注明「仅 AI 录入管线需要」。

3. **文档残留「贡献收件箱」表述**（schema v22 已删 `contributions` 表）
   - `../ops-manual.md:19`：「公共星云 / 用户星云 / 贡献收件箱 / 审计日志 / 用户与会话」；
   - `../ops-manual.md:110`：「用户星云 / 贡献 / 审计 / 会话一并回退」；
   - `../../data/export/README.md`：「贡献与审计表不受影响」。
   建议删除「贡献收件箱 / 贡献」字样（审计与用户数据保留）。

4. **`app/llm_review.py` 跨模块私有导入**
   `from app.space_crud import _after_write  # noqa: PLC2701` 以关闭 lint 的方式引入
   下划线私有成员。建议把 `_after_write` 提升为公共名（如 `after_write`）或抽到
   共享收尾模块，避免私有 API 在模块间成为隐式契约。

5. **`rewrite_all` 仍留生产模块、仅测试使用**（上轮遗留）
   建议移入 `tests/` 公共 helper（如 `tests/_helpers.py`），或加 `_test_only` 标注，
   减少「生产代码里躺着一个只被测试用的整库重写路径」的维护歧义。

### P3（本地环境 / 可选）

6. **本地杂物（均被 gitignore，不入库）**
   - `backups/venv-broken-20260822/`（约 14.2MB 损坏 venv）：应用侧快照裁剪只匹配
     `echo-graph-*.db`，不会清理它，会一直占用磁盘，可手动删除；
   - `agent_temp/books/`（约 18.1MB 电子书）与 `agent_temp/output/`（约 0.3MB JSON）：
     本地管线产物，建议定期清理；
   - 审查期间重建了 `.venv`（旧的已改名 `.venv-broken-local`，可删除）。
7. **`scripts/check_public_sync.py` 文档覆盖不足**
   仅在 `../to-do.md` 与 `../migration/multi-user-migration.md` 出现；建议在 `../ops-manual.md`
   例行检查一节补一句（本地库公共数据 ↔ 仓库 CSV 漂移检查）。

## 六、冗余与脚本必要性评估

| 项 | 结论 |
|---|---|
| `app/db.py`（读） / `app/sqlite_store.py`（写） / `app/db_sqlite.py`（连接+迁移） / `app/data_store.py`（CSV 导出） / `app/data_models.py`（校验） | 职责单一、互不重叠；列定义已单一来源，无冗余 |
| `app/read_routes.py` 工厂 | 消除了 `/api`、`/api/me`、`/api/space` 三套并行端点，正面收敛 |
| `app/users.py` | 收敛了 `space.py` / `follows.py` 各自的展示名/用户行实现，正面收敛 |
| `scripts/*`（export_csv / migrate_csv_to_sqlite / prune_audit / check_public_sync） | 全部有 CI 或文档对应用途，保留 |
| `agent_temp/tools/*`（extract / dedupe / llm_client / llm_space / read_book / pipeline_ingest / review_publish） | AI 录入管线的组成部分，README 有描述，保留 |
| `agent_temp/tmp/e2e_llm_review.py` | 一次性校验脚本，无引用且拖垮 lint，建议删除 |
| 前端 `lib/*`、`components/*` | 文件级无死代码；`renderer.ts` 为 `renderer/` 子模块组合入口，正常 |
| `backups/venv-broken-20260822` | 本地损坏 venv 备份，不入库，建议手动删除 |

## 七、架构评估

当前架构（与 08-21 一致并继续收敛）：

```
React 19 + TS ──> /api/* ──> FastAPI（单 worker）
                              │
        ┌─────────────────────┼──────────────────────┐
        ▼                     ▼                      ▼
  read_routes 工厂       admin.py / space_crud    llm_review.py
  （/api /api/me        （行级 CRUD+校验+乐观锁   （system_llm 草稿
   /api/space 三套共用）  +审计+自动 CSV 导出）      区 → admin 审核发布）
        │                     │                      │
        └────────── db_sqlite.py（连接/事务/schema v1-v24/审计）──┘
                              │
                      data/echo-graph.db（唯一权威）
                              │
                      data/export/*.csv（确定性导出，git 审计）
```

正面要点：

- **分层与收敛**：读（`db.py`）、写（`sqlite_store`）、路由（`read_routes` 工厂）、
  用户辅助（`users.py`）各自单一职责；只读五件套三套端点共用一份实现；
- **多用户隔离**：`owner_id` + 「公共星云 = 引导管理员 + 未认领行」，隔离在查询层强制，
  越权 404/403、跨空间引用拒绝均有测试覆盖；
- **AI 管线设计**：`system_llm` 机器账号私有空间承载草稿（随机密码不可登录、不可人工
  登录），admin 在管理端审核发布，`created_by='llm'` + `published_to_id` 溯源并防重复
  发布，依赖守卫保证发布顺序——无共享凭证、审计可追溯；
- **一致性**：时间戳归一（UTC 秒级 ISO-8601）、乐观锁、审计日志、软删除、CSV 确定性
  导出 + CI 新鲜度门禁；
- **安全**：CSRF 同源校验、限流可信代理白名单、静态资源路径穿越防护、Argon2 密码、
  会话仅存 token 哈希；Git 全历史无 `.env` / 密钥泄露；
- **文档**：`../data_schema.md` 已按 schema v24 更新（2026-08-25，9 张业务表）；
  `../to-do.md` 含 2026-08-25 最近变更；`../migration/sqlite-migration.md` 有历史归档标注。

可优化（非阻塞）：

- 单 worker + 进程内限流/缓存是设计约束，数据量增长后需同步考虑读缓存 TTL、索引与
  FTS5 搜索（当前 150 级规模毫秒级，无压力）；
- `_after_write` 私有导入与 `rewrite_all` 测试专用函数属于模块边界卫生，建议顺手收敛。

## 八、建议处理顺序

1. 修复 ruff（P1-1）：`ruff check --fix` + 手工修 F841/E701，删除或修复
   `agent_temp/tmp/e2e_llm_review.py`，恢复 CI 绿色；
2. 补 `.env.example` 的 `DEEPSEEK_*` / `ALIYUN_*`（P2-2）；
3. 清理 `../ops-manual.md` / `../../data/export/README.md` 的「贡献收件箱」残留（P2-3）；
4. 顺手处理 `_after_write` 命名与 `rewrite_all` 归属（P2-4/P2-5）；
5. 删除本地 `backups/venv-broken-20260822` 与多余 venv 备份（P3-6）。
