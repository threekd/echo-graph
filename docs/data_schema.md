# Echo Graph 数据结构规范

- `schemaVersion`(本文档版本):`1.2`(2026-08-24 按实际数据库结构修订)
- 对应数据库:`data/echo-graph.db`,`meta.schema_version = 21`(schema 迁移定义见
  `app/db_sqlite.py` 的 `MIGRATIONS`;本文档版本与数据库迁移版本相互独立)
- 存储与读取:策展数据与公开读取均以 SQLite(`data/echo-graph.db`)为准;
  `data/export/*.csv` 为确定性导出产物(git 审计 / 跨机器传输);Neo4j 查询层与
  JSON 兜底已退役
- 时间戳:所有时间字段(`createdAt` / `updatedAt` / `deletedAt` / `created_at` /
  `reviewed_at` / `expires_at` / `ts`)均为 UTC 秒级 ISO-8601 字符串(统一 `+00:00`)

## 表总览

当前库共 10 张业务表:

| 表 | 用途 | 归属 / 隔离 |
|---|---|---|
| `users` | 账号(邮箱 + 密码哈希 + 角色/状态/星云可见性/资料) | — |
| `sessions` | 登录会话(只存 token 的 SHA-256 哈希) | 按 `user_id` 关联 |
| `authors` | 作者节点(公共星云 + 用户空间) | `owner_id` |
| `works` | 作品节点(公共星云 + 用户空间) | `owner_id` |
| `work_authors` | 作品-作者关联(合著 N:N) | 经 `works.owner_id` 派生 |
| `edges` | 回声关系 `(Work)-[:ECHO]->(Work)` | `owner_id` |
| `contributions` | 用户贡献收件箱(提交不直接入正式数据) | `user_id` |
| `friendships` | 单向关注(模型好友) | `user_id` / `friend_id` |
| `audit_log` | 管理写操作审计 | — |
| `meta` | 元信息(`schema_version` 等) | — |

## 通用约定

- **主键与 URL 标识**:`id` 使用 UUID(优先 UUID v7,时间有序),同时也是 URL 使用的
  标识;新增作者/作品/涟漪/用户/会话/关注时由后端自动生成。
- **空间归属(多用户)**:`authors` / `works` / `edges` 各含 `owner_id`
  (引用 `users.id`;空值 = 尚未认领的历史数据,启动时认领给引导管理员);公共星云 =
  引导管理员空间,个人空间(`/api/me/*`)仅本人可见;`contributions` 含 `user_id`
  (登录用户提交归属)。
- **命名风格**:通用属性使用 camelCase(`originalTitle`、`publicationYear`);
  中英文标题/姓名使用大写前缀约定(`Title_CN`、`Title_EN`、`Name_CN`、`Name_EN`),
  作为对外展示字段。
- **语言编码**:优先 ISO 639-1;无法表达时(如中古英语、古典日语)使用 ISO 639-3
  (`enm`、`ojp`)或自定义枚举,并在文档中登记。
- **国籍编码**:使用 ISO 3166-1 alpha-2 大写代码(如 `CN` 中国、`US` 美国);
  无国籍/未知时留空。
- **软删除**:`deletedAt` 非空的行保留在库中,但**不进入任何读取结果**;软删除
  只在数据层表达,图上只出现活跃数据。

## 表结构

### users 用户

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | TEXT(UUID) | 是(PK) | 唯一标识,主键 |
| `email` | TEXT | 是(UNIQUE) | 登录邮箱,统一小写 |
| `password_hash` | TEXT | 是 | Argon2 密码哈希,不存明文 |
| `role` | TEXT | 是 | `user` / `admin`,默认 `user`(引导管理员邮箱注册自动为 admin) |
| `status` | TEXT | 是 | `active` / `disabled`,默认 `active`;禁用用户不可登录,其星云不可访问(2026-08-24 起空间访问统一按 active 判定) |
| `createdAt` / `updatedAt` | TEXT | 否 | 时间戳(UTC ISO-8601) |
| `space_visibility` | TEXT | 是 | `public`(默认,星际跃迁可访问)/ `private`(仅本人与 admin) |
| `username` | TEXT | 应用层必填 | 用户名(仅 5-32 位英文字母/数字/下划线,ASCII 大小写不敏感唯一;
  登录可用邮箱或用户名;**系统标识,用户不可自行修改**)。DB 层可空(存量回填 + 注册校验),
  唯一索引 `idx_users_username` 带 `COLLATE NOCASE` |
| `nickname` | TEXT | 否 | 昵称(展示用,优先于用户名;为空时展示名回退用户名) |
| `bio` | TEXT | 否 | 简介(最多 500 字,应用层校验) |

约束:`CHECK (role IN ('user','admin'))`、`CHECK (status IN ('active','disabled'))`、
`CHECK (space_visibility IN ('private','public'))`。

### sessions 会话

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | TEXT(UUID) | 是(PK) | 主键 |
| `token_hash` | TEXT | 是(UNIQUE) | 会话 token 的 SHA-256 哈希;原始 token 只出现在 httpOnly Cookie |
| `user_id` | TEXT | 是 | 引用 `users.id` |
| `created_at` | TEXT | 是 | 创建时间(UTC) |
| `expires_at` | TEXT | 是 | 过期时间(默认 30 天);过期/登出即失效 |

索引:`idx_sessions_user(user_id)`、`idx_sessions_expires(expires_at)`。

### authors 作者节点

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | TEXT(UUID) | 是(PK) | 唯一标识,主键 |
| `originalName` | TEXT | 是 | 全名/原文名 |
| `Name_CN` | TEXT | 是 | 中文名 |
| `Name_EN` | TEXT | 否 | 英文名 |
| `nationality` | TEXT | 否 | 国家(ISO 3166-1 alpha-2 大写,如 `CN`、`US`;留空表示无/未知) |
| `birthYear` / `deathYear` | INTEGER | 否 | 出生/去世年份(应用层校验 -9999 ~ 9999 且出生早于去世) |
| `note` | TEXT | 否 | 备注(内部说明,不参与图谱展示) |
| `reviewStatus` | TEXT | 是 | `draft` / `reviewed` / `rejected`,默认 `draft`;新增(输入即确认)默认 `reviewed`,CSV 引导的存量数据保持 `draft` 待审核 |
| `createdAt` / `updatedAt` / `deletedAt` | TEXT | 否 | 时间戳;`deletedAt` 非空 = 软删除 |
| `owner_id` | TEXT | 否 | 引用 `users.id`;空 = 未认领历史数据,启动时认领给引导管理员 |

约束:`CHECK (reviewStatus IN ('draft','reviewed','rejected'))`。
索引:`idx_authors_owner(owner_id)`。

### works 作品节点

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | TEXT(UUID) | 是(PK) | 唯一标识,主键 |
| `language` | TEXT | 是 | 语言代码,ISO 639-1 优先、639-3 兜底(DB 层 CHECK 长度 2-3) |
| `originalTitle` | TEXT | 是 | 原著标题 |
| `Title_CN` | TEXT | 是 | 中文版标题 |
| `Title_EN` | TEXT | 否 | 英文版标题 |
| `Title_Other` | TEXT | 否 | 其他可能的标题 |
| `publicationYear` | INTEGER | 否 | 出版年份 |
| `genre` | TEXT | 否 | `Fiction` / `Non-fiction` / `Poetry` / `Drama` |
| `note` | TEXT | 否 | 备注(内部说明,不参与图谱展示) |
| `reviewStatus` | TEXT | 是 | 同 authors 的审核状态语义 |
| `createdAt` / `updatedAt` / `deletedAt` | TEXT | 否 | 时间戳;`deletedAt` 非空 = 软删除 |
| `owner_id` | TEXT | 否 | 引用 `users.id`;空 = 未认领历史数据 |
| `recommendation` | TEXT | 否 | 个人评分 `recommend` / `not_recommend`;仅用户空间语义,不进 CSV |
| `review` | TEXT | 否 | 个人评价(应用层校验最多 2000 字);仅用户空间语义,不进 CSV |
| `readingStatus` | TEXT | 否 | 个人阅读状态 `read` / `reading` / `unread`;仅用户空间语义,不进 CSV |

**注意:`works` 表没有 `author_id` 列。** 作品-作者关联存于 `work_authors`;
CSV 导出与 API 形状中的 `author_id`(逗号分隔的作者 id 串)是 `work_authors`
派生的展示字段。

约束:`CHECK (length(language) BETWEEN 2 AND 3)`、
`CHECK (genre IN ('Fiction','Non-fiction','Poetry','Drama') OR genre IS NULL)`、
`CHECK (reviewStatus IN ('draft','reviewed','rejected'))`、
`CHECK (recommendation IN ('recommend','not_recommend'))`、
`CHECK (readingStatus IN ('read','reading','unread'))`。
索引:`idx_works_owner(owner_id)`。

### work_authors 作品-作者关联

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `work_id` | TEXT(UUID) | 是(PK) | 引用 `works.id` |
| `author_id` | TEXT(UUID) | 是(PK) | 引用 `authors.id` |

`AUTHORED_BY` 关系 `(Work)-[:AUTHORED_BY]->(Author)` 的物理实现,支持合著(N:N)。
索引:`idx_work_authors_author(author_id)`(按作者反查作品)。

### edges 回声关系

方向:`source_work_id` 这本书在正文中提及 `target_work_id` 这本书,方向 source → target。

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | TEXT(UUID) | 是(PK) | 唯一标识,新增时后端自动生成 UUID v7 |
| `source_work_id` | TEXT | 是 | 当前作品(引用 `works.id`) |
| `target_work_id` | TEXT | 是 | 被提及作品(引用 `works.id`) |
| `evidence` | TEXT | 是 | 原文片段(摘抄文本);DB 层 CHECK 长度 ≤ 2000 |
| `evidenceSource` | TEXT | 否 | 证据出处:作品章节 / 页码 / 译本版本 |
| `note` | TEXT | 否 | 备注或补充说明 |
| `reviewStatus` | TEXT | 是 | `draft` / `reviewed` / `rejected`,默认 `draft`;新增默认 `reviewed`,CSV 引导存量保持 `draft` |
| `createdAt` / `updatedAt` / `deletedAt` | TEXT | 否 | 时间戳;`deletedAt` 非空 = 软删除 |
| `owner_id` | TEXT | 否 | 引用 `users.id`;空 = 未认领历史数据 |

约束:`UNIQUE(source_work_id, target_work_id)`(同空间内边对唯一,应用层叠加 owner 判定)、
`CHECK (source_work_id <> target_work_id)`、`CHECK (length(evidence) <= 2000)`。
索引:`idx_edges_source(source_work_id)`、`idx_edges_target(target_work_id)`、
`idx_edges_owner(owner_id)`。

### contributions 贡献收件箱

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | TEXT(UUID) | 是(PK) | 主键 |
| `source_work` / `target_work` | TEXT | 是 | 源/目标作品名称(自由填写,不要求已收录) |
| `source_author` / `target_author` | TEXT | 是 | 源/目标作品作者(自由填写) |
| `evidence` | TEXT | 是 | 原文片段 |
| `evidence_source` | TEXT | 是 | 出处 |
| `note` / `contact` | TEXT | 否 | 备注 / 联系方式 |
| `status` | TEXT | 是 | `pending` / `approved` / `rejected`,默认 `pending` |
| `created_at` / `reviewed_at` | TEXT | 是/否 | 提交时间 / 审核时间 |
| `user_id` | TEXT | 否 | 登录用户提交归属(引用 `users.id`;匿名提交为 NULL) |

索引:`idx_contributions_status_created(status, created_at)`、
`idx_contributions_user(user_id)`。
说明:提交只进入收件箱,审核通过仅改状态;正式并入策展表由后续人工/AI 流程完成。

### friendships 关注关系(模型好友)

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | TEXT(UUID) | 是(PK) | 主键,新增时后端自动生成 UUID v7 |
| `user_id` | TEXT | 是 | 关注者(引用 `users.id`) |
| `friend_id` | TEXT | 是 | 被关注者(引用 `users.id`) |
| `created_at` | TEXT | 是 | 关注时间(UTC ISO-8601) |

约束:`UNIQUE(user_id, friend_id)`、`CHECK (user_id <> friend_id)`。
索引:`idx_friendships_user(user_id)`、`idx_friendships_friend(friend_id)`。
语义:单向关注(不要求互相关注),不改变星云可见性;不可关注自己,目标用户不存在/
已禁用返回 404;关注操作按用户每小时限流 50 次(取关不计入)。
接口:`POST/DELETE /api/follow/{user_id}`、`GET /api/follow/following|followers`、
`GET /api/follow/relation/{user_id}`。

### audit_log 审计

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | INTEGER | 是(PK) | 自增主键 |
| `ts` | TEXT | 是 | 操作时间(UTC) |
| `actor` | TEXT | 是 | 操作者(邮箱),默认 `admin` |
| `action` | TEXT | 是 | `create` / `update` / `delete` / `restore` / `approve` / `reject` |
| `kind` | TEXT | 是 | `authors` / `works` / `edges` / `contributions` |
| `row_id` | TEXT | 否 | 操作对象 id |
| `detail` | TEXT | 否 | 人读摘要(对象名称与变更字段) |
| `before` / `after` | TEXT | 否 | 改动前后的行 JSON(审计页展开对比用) |

索引:`idx_audit_ts(ts)`;由 `scripts/prune_audit.py` 裁剪(默认保留 90 天)。

### meta 元信息

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `key` | TEXT | 是(PK) | 键,如 `schema_version` |
| `value` | TEXT | 否 | 值,当前 `schema_version = 21` |

## 约束与索引汇总

唯一约束 / 主键:

- `users.id`、`users.email`、`users.username`(`COLLATE NOCASE` 唯一索引)
- `sessions.id`、`sessions.token_hash`
- `authors.id`、`works.id`、`edges.id`、`contributions.id`、`friendships.id`
- `edges(source_work_id, target_work_id)`、`friendships(user_id, friend_id)`、
  `work_authors(work_id, author_id)`、`meta.key`

非唯一索引:

- `idx_authors_owner`、`idx_works_owner`、`idx_edges_owner`(空间隔离查询)
- `idx_edges_source`、`idx_edges_target`(路径/扩散)
- `idx_work_authors_author`(作者反查作品)
- `idx_sessions_user`、`idx_sessions_expires`
- `idx_contributions_status_created`、`idx_contributions_user`
- `idx_friendships_user`、`idx_friendships_friend`
- `idx_users_space_visibility`(随机跃迁)
- `idx_audit_ts`(审计裁剪)

## 图谱关系语义

| 关系 | 物理实现 | 基数 | 语义 |
|---|---|---|---|
| `AUTHORED_BY` | `work_authors`(works ↔ authors) | N:N(允许合著) | 作品由作者写作 |
| `ECHO` | `edges`(source_work_id → target_work_id) | N:N | source 提及 target,方向 source → target |
| 关注 | `friendships`(user_id → friend_id) | N:N(单向) | user 关注 friend,不影响星云可见性 |

## 与 CSV 导出 / API 形状的对应

- `authors.csv` / `edges.csv` 的列与表列一一对应;
- `works.csv` 在 `Title_Other` 之后插入 `author_id` 派生列(work_authors 按
  `works.id` 聚合为逗号分隔串),其余列与表列一致;
- CSV 只含**公共星云**(admin 认领的行 + 尚未认领的历史行),用户私有空间、
  sessions、contributions、audit_log 均不进 CSV;
- API 的 `Work.author_id` / `author_ids` 同样为 work_authors 的派生展示字段。

## 演进方向(未实现)

- 数据量增长后:`edges` 按 `source_work_id` / `target_work_id` 的索引已就位;
  搜索可加 SQLite FTS5(`Title_CN` / `Title_EN` / `originalTitle`),`evidence`
  长文本可拆分独立表或接入 FTS5;读取层内存 BFS 可换进程内邻接缓存。

## 版本说明

本文档版本独立于数据库迁移版本(`meta.schema_version`,当前 21);
数据结构演进时递增本文档 `schemaVersion` 并保持向后兼容。

`1.1 → 1.2` 变更(2026-08-24,按实际数据库结构修订):

- 补充 `sessions` / `contributions` / `audit_log` / `meta` / `work_authors` 表结构;
- 修正 `works`:`author_id` 说明为 work_authors 派生的导出/API 字段,并补充
  `recommendation` / `review` / `readingStatus` 个人字段;
- 用户表补充 `username` 唯一索引的 `COLLATE NOCASE` 与 DB 层可空说明;
- 删除已退役的 `creationYear` / 节点级 `visibility` 相关描述;
- 约束与索引清单按实际 `PRAGMA` 输出更新(含 `idx_*_owner` 等);
- 明确禁用用户(status=disabled)的星云不可访问。
