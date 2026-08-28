# Echo Graph 数据结构规范

- `schemaVersion`(本文档版本):`1.8`(2026-08-28 按实际数据库结构修订)
- 对应数据库:`data/echo-graph.db`,`meta.schema_version = 27`(schema 迁移定义见
  `app/db_sqlite.py` 的 `MIGRATIONS`;本文档版本与数据库迁移版本相互独立)
- 存储与读取:策展数据与公开读取均以 SQLite(`data/echo-graph.db`)为准;
  备份为**整库快照**(`backups/` 下 `.db` + 管理端「快照」恢复);`data/export/*.csv`
  自动导出层已于 2026-08-27 移除(星云工坊页「导出 CSV」按钮为手动导出);Neo4j
  查询层与 JSON 兜底已退役
- 时间戳:所有时间字段(`createdAt` / `updatedAt` / `deletedAt` / `created_at` /
  `expires_at` / `ts`)均为 UTC 秒级 ISO-8601 字符串(统一 `+00:00`)

## 表总览

当前库共 11 张业务表:

| 表 | 用途 | 归属 / 隔离 |
|---|---|---|
| `users` | 账号(邮箱 + 密码哈希 + 角色/状态/星云可见性/资料) | — |
| `sessions` | 登录会话(只存 token 的 SHA-256 哈希) | 按 `user_id` 关联 |
| `email_tokens` | 邮箱验证 / 密码重置的一次性令牌(只存 SHA-256 哈希) | 按 `user_id` 关联 |
| `authors` | 作者节点(所有用户星云,含 admin 星云) | `owner_id` |
| `works` | 作品节点(所有用户星云,含 admin 星云) | `owner_id` |
| `work_authors` | 作品-作者关联(合著 N:N) | 经 `works.owner_id` 派生 |
| `edges` | 回声关系 `(Work)-[:ECHO]->(Work)` | `owner_id` |
| `friendships` | 单向关注(模型好友) | `user_id` / `friend_id` |
| `embeddings` | AI 语义去重向量缓存(作者/作品标题嵌入) | 经实体 id 关联,不承载业务数据 |
| `audit_log` | 管理写操作审计 | — |
| `meta` | 元信息(`schema_version` 等) | — |

## 通用约定

- **主键与 URL 标识**:`id` 使用 UUID(优先 UUID v7,时间有序),同时也是 URL 使用的
  标识;新增作者/作品/涟漪/用户/会话/关注时由后端自动生成。
- **空间归属(多用户)**:`authors` / `works` / `edges` 各含 `owner_id`
  (引用 `users.id`,非空)。公共星云/官方图谱/默认视图概念已于 2026-08-28 移除:
  不存在默认视图,admin 星云与其他用户星云语义一致;个人空间(`/api/me/*`)
  仅本人可见,他人公开星云经 `/api/space/*` 按可见性访问。
- **溯源列**:`authors` / `works` / `edges` 含 `created_by`(默认 `curated`);
  取值 `curated`(人工策展)/ `user`(用户空间写入)/ `llm`(AI 提取,经 admin 审核发布)。
  API 手工写入不允许显式传 `llm`(仅 AI 管线内部使用),显式 `curated`/`user` 或缺省按
  owner 推导(admin 空间 = `curated`,其他 = `user`);创建后不可修改,
  不进公共导出(与个人字段同策略)。
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
| `role` | TEXT | 是 | `user` / `admin`,默认 `user`(引导管理员邮箱注册自动为 admin;开启邮箱验证时改为验证通过后提权) |
| `email_verified_at` | TEXT | 否 | 邮箱验证时间(UTC);`EMAIL_VERIFY_REQUIRED=1` 时新注册用户未验证不可登录;`EMAIL_VERIFY_REQUIRED=0` 时注册即信任(以 createdAt 标记,与存量用户迁移回填策略一致);存量用户迁移时回填 createdAt 视为已信任 |
| `status` | TEXT | 是 | `active` / `disabled`,默认 `active`;禁用用户不可登录,其星云不可访问(2026-08-24 起空间访问统一按 active 判定) |
| `createdAt` / `updatedAt` | TEXT | 否 | 时间戳(UTC ISO-8601) |
| `space_visibility` | TEXT | 是 | `public`(默认,星际跃迁可访问)/ `private`(仅本人与 admin) |
| `username` | TEXT | 应用层必填 | 用户名(仅 5-32 位英文字母/数字/下划线,ASCII 大小写不敏感唯一;
  登录可用邮箱或用户名;**系统标识,用户不可自行修改**)。DB 层可空(存量回填 + 注册校验),
  唯一索引 `idx_users_username` 带 `COLLATE NOCASE` |
| `nickname` | TEXT | 否 | 昵称(展示用,优先于用户名;为空时展示名回退用户名) |
| `bio` | TEXT | 否 | 简介(最多 500 字,应用层校验) |
| `vip` | INTEGER | 是 | VIP 标记(0/1,默认 0):VIP 用户拥有 AI 书籍导入权限
  (导入的草稿按 owner_id=上传者 隔离,上传者(admin/VIP)在「AI 草稿」页审核
  自己上传的草稿并发布到自己的星云;VIP 标记由 admin 通过
  `POST /api/admin/users/{id}/vip` 维护) |

约束:`CHECK (role IN ('user','admin'))`、`CHECK (status IN ('active','disabled'))`、
`CHECK (space_visibility IN ('private','public'))`、`CHECK (vip IN (0, 1))`。

### sessions 会话

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | TEXT(UUID) | 是(PK) | 主键 |
| `token_hash` | TEXT | 是(UNIQUE) | 会话 token 的 SHA-256 哈希;原始 token 只出现在 httpOnly Cookie |
| `user_id` | TEXT | 是 | 引用 `users.id` |
| `created_at` | TEXT | 是 | 创建时间(UTC) |
| `expires_at` | TEXT | 是 | 过期时间(默认 30 天);过期/登出即失效 |

索引:`idx_sessions_user(user_id)`、`idx_sessions_expires(expires_at)`。

### email_tokens 邮箱令牌

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | TEXT(UUID) | 是(PK) | 主键 |
| `token_hash` | TEXT | 是(UNIQUE) | 令牌的 SHA-256 哈希;原始令牌只出现在邮件深链中,泄露 DB 无法伪造 |
| `user_id` | TEXT | 是 | 引用 `users.id` |
| `purpose` | TEXT | 是 | `verify`(注册邮箱验证)/ `reset`(密码重置) |
| `expires_at` | TEXT | 是 | 过期时间(默认 24 小时) |
| `used_at` | TEXT | 否 | 消费时间;已用 / 过期即失效,重发时同用户同用途旧未用令牌作废 |
| `created_at` | TEXT | 是 | 创建时间(UTC) |

索引:`idx_email_tokens_user(user_id)`、`idx_email_tokens_user_purpose(user_id, purpose)`。

### authors 作者节点

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | TEXT(UUID) | 是(PK) | 唯一标识,主键 |
| `originalName` | TEXT | 是 | 原文名:以作者所属国籍语言文字书写的全名(如俄语作者用西里尔「Лев Толстой」、日语作者用日文「村上春樹」) |
| `Name_CN` | TEXT | 是 | 中文名 |
| `Name_EN` | TEXT | 否 | 英文名 |
| `nationality` | TEXT | 否 | 国家(ISO 3166-1 alpha-2 大写,如 `CN`、`US`;留空表示无/未知) |
| `birthYear` / `deathYear` | INTEGER | 否 | 出生/去世年份(应用层校验 -9999 ~ 9999 且出生早于去世) |
| `note` | TEXT | 否 | 备注(内部说明,不参与图谱展示) |
| `reviewStatus` | TEXT | 是 | `draft` / `reviewed` / `rejected`,默认 `draft`;新增按 `created_by` 推导默认值:`user` / `curated`(人工录入)默认 `reviewed`,`llm`(AI 提取)默认 `draft`;手工新增/编辑(经 `/api/me`、`/api/admin` 的 API)一律强制 `reviewed`,admin 不做特殊化,显式传 `draft`/`rejected` 会被回正;历史存量数据保持 `draft` 待审核 |
| `created_by` | TEXT | 是 | 溯源:`curated` / `user` / `llm`,默认 `curated`;API 手工写入不允许显式传 `llm`(仅 AI 管线内部使用),显式 `curated`/`user` 或缺省按 owner 推导;创建后不可修改;不进公共导出 |
| `createdAt` / `updatedAt` / `deletedAt` | TEXT | 否 | 时间戳;`deletedAt` 非空 = 软删除 |
| `owner_id` | TEXT | 是 | 引用 `users.id`;admin 星云与其他用户星云语义一致,不存在默认视图 |
| `published_to_id` | TEXT | 否 | AI 草稿发布映射:上传者空间草稿(owner_id=上传者、created_by='llm')批准后回写公共行 id(复用场景为被复用行 id);仅草稿区行有值,公共行恒为 NULL,不进公共导出 |

约束:`CHECK (reviewStatus IN ('draft','reviewed','rejected'))`、
`CHECK (created_by IN ('curated','user','llm'))`。
索引:`idx_authors_owner(owner_id)`。

### works 作品节点

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | TEXT(UUID) | 是(PK) | 唯一标识,主键 |
| `language` | TEXT | 是 | 语言代码,ISO 639-1 优先、639-3 兜底(DB 层 CHECK 长度 2-3) |
| `originalTitle` | TEXT | 是 | 原著标题:与 `language` 一致,以作品原文语言文字书写的标题(如日语「ノルウェイの森」);非拉丁语言不使用拉丁转写 |
| `Title_CN` | TEXT | 是 | 中文版标题 |
| `Title_EN` | TEXT | 否 | 英文版标题 |
| `Title_Other` | TEXT | 否 | 其他可能的标题 |
| `publicationYear` | INTEGER | 否 | 出版年份 |
| `genre` | TEXT | 否 | `Fiction` / `Non-fiction` / `Poetry` / `Drama` |
| `note` | TEXT | 否 | 备注(内部说明,不参与图谱展示) |
| `reviewStatus` | TEXT | 是 | 同 authors 的审核状态语义 |
| `created_by` | TEXT | 是 | 溯源:`curated` / `user` / `llm`,默认 `curated`;API 手工写入不允许显式传 `llm`(仅 AI 管线内部使用),显式 `curated`/`user` 或缺省按 owner 推导;创建后不可修改;不进公共导出 |
| `createdAt` / `updatedAt` / `deletedAt` | TEXT | 否 | 时间戳;`deletedAt` 非空 = 软删除 |
| `owner_id` | TEXT | 是 | 引用 `users.id`;admin 星云与其他用户星云语义一致 |
| `recommendation` | TEXT | 否 | 个人评分 `recommend` / `not_recommend`;仅用户空间语义(用户导出 CSV 会包含,不进公共导出) |
| `review` | TEXT | 否 | 个人评价(应用层校验最多 2000 字);仅用户空间语义(用户导出 CSV 会包含,不进公共导出) |
| `readingStatus` | TEXT | 否 | 个人阅读状态 `read` / `reading` / `unread`;仅用户空间语义(用户导出 CSV 会包含,不进公共导出) |
| `published_to_id` | TEXT | 否 | AI 草稿发布映射:同 authors,草稿批准后回写公共行 id;仅草稿区行有值,不进公共导出 |

**注意:`works` 表没有 `author_id` 列。** 作品-作者关联存于 `work_authors`;
用户导出 CSV 与 API 形状中的 `author_id`(逗号分隔的作者 id 串)是 `work_authors`
派生的展示字段。

约束:`CHECK (length(language) BETWEEN 2 AND 3)`、
`CHECK (genre IN ('Fiction','Non-fiction','Poetry','Drama') OR genre IS NULL)`、
`CHECK (reviewStatus IN ('draft','reviewed','rejected'))`、
`CHECK (created_by IN ('curated','user','llm'))`、
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
| `evidence` | TEXT | 是 | 原文片段(摘抄文本);DB 层 CHECK 长度 ≤ 2000,应用层 Pydantic 同上限校验(超长 400) |
| `evidenceSource` | TEXT | 否 | 证据出处:作品章节 / 页码 / 译本版本 |
| `note` | TEXT | 否 | 备注或补充说明 |
| `reviewStatus` | TEXT | 是 | `draft` / `reviewed` / `rejected`,默认 `draft`;新增按 `created_by` 推导默认值:`user` / `curated` 默认 `reviewed`,`llm` 默认 `draft`;手工新增(API)一律强制 `reviewed`,admin 不做特殊化;历史存量保持 `draft` |
| `created_by` | TEXT | 是 | 溯源:`curated` / `user` / `llm`,默认 `curated`;API 手工写入不允许显式传 `llm`(仅 AI 管线内部使用),显式 `curated`/`user` 或缺省按 owner 推导;创建后不可修改;不进公共导出 |
| `createdAt` / `updatedAt` / `deletedAt` | TEXT | 否 | 时间戳;`deletedAt` 非空 = 软删除 |
| `owner_id` | TEXT | 是 | 引用 `users.id`;admin 星云与其他用户星云语义一致 |
| `published_to_id` | TEXT | 否 | AI 草稿发布映射:同 authors,草稿批准后回写公共行 id;仅草稿区行有值,不进公共导出 |

约束:`UNIQUE(source_work_id, target_work_id)`(同空间内边对唯一,应用层叠加 owner 判定)、
`CHECK (source_work_id <> target_work_id)`、`CHECK (length(evidence) <= 2000)`、
`CHECK (created_by IN ('curated','user','llm'))`。
索引:`idx_edges_source(source_work_id)`、`idx_edges_target(target_work_id)`、
`idx_edges_owner(owner_id)`。

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

### embeddings AI 语义去重向量缓存

由 `app/ai_assistant/tools/dedupe_check.py` 使用:把库内作者/作品标题向量落库,
避免每次管线运行对全库重复调用阿里云百炼 embedding。不属于业务数据,不进公共导出,
无 admin 维护入口。

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `entity_type` | TEXT | 是 | 实体类型:`author` / `work` |
| `entity_id` | TEXT | 是 | 实体 id(引用 authors/works.id) |
| `model` | TEXT | 是 | 使用的 embedding 模型名 |
| `version` | INTEGER | 是 | 向量方案版本(`VECTOR_VERSION`,模型/阈值调整时递增失效缓存) |
| `text_hash` | TEXT | 是 | 嵌入文本的 SHA-256;标题/作者字段变更后 hash 变化即重新嵌入 |
| `vector` | TEXT | 是 | 向量 JSON 文本(1024 维约 8KB/行) |
| `updated_at` | TEXT | 是 | 写入时间(UTC ISO-8601) |

主键:`PRIMARY KEY (entity_type, entity_id, model, version)`;读取为全量线性
余弦扫描,当前量级(几十~几百条)开销可忽略。

### audit_log 审计

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | INTEGER | 是(PK) | 自增主键 |
| `ts` | TEXT | 是 | 操作时间(UTC) |
| `actor` | TEXT | 是 | 操作者(邮箱),默认 `admin` |
| `action` | TEXT | 是 | `create` / `update` / `delete` / `restore` / `approve` / `reject` / `llm_ingest` / `llm_publish` / `llm_reuse` / `llm_reject` / `llm_reopen` |
| `kind` | TEXT | 是 | `authors` / `works` / `edges` / `users`(历史行可能含 `contributions`,仅作记录) |
| `row_id` | TEXT | 否 | 操作对象 id |
| `detail` | TEXT | 否 | 人读摘要(对象名称与变更字段) |
| `before` / `after` | TEXT | 否 | 改动前后的行 JSON(审计页展开对比用) |

索引:`idx_audit_ts(ts)`;由 `scripts/prune_audit.py` 裁剪(默认保留 90 天)。

### meta 元信息

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `key` | TEXT | 是(PK) | 键,如 `schema_version` |
| `value` | TEXT | 否 | 值,当前 `schema_version = 27` |

## 约束与索引汇总

唯一约束 / 主键:

- `users.id`、`users.email`、`users.username`(`COLLATE NOCASE` 唯一索引)
- `sessions.id`、`sessions.token_hash`、`email_tokens.id`、`email_tokens.token_hash`
- `authors.id`、`works.id`、`edges.id`、`friendships.id`
- `edges(source_work_id, target_work_id)`、`friendships(user_id, friend_id)`、
  `work_authors(work_id, author_id)`、`meta.key`、`embeddings(entity_type, entity_id, model, version)`

非唯一索引:

- `idx_authors_owner`、`idx_works_owner`、`idx_edges_owner`(空间隔离查询)
- `idx_edges_source`、`idx_edges_target`(路径/扩散)
- `idx_work_authors_author`(作者反查作品)
- `idx_sessions_user`、`idx_sessions_expires`
- `idx_email_tokens_user`、`idx_email_tokens_user_purpose`
- `idx_friendships_user`、`idx_friendships_friend`
- `idx_users_space_visibility`(随机跃迁)
- `idx_audit_ts`(审计裁剪)

## 图谱关系语义

| 关系 | 物理实现 | 基数 | 语义 |
|---|---|---|---|
| `AUTHORED_BY` | `work_authors`(works ↔ authors) | N:N(允许合著) | 作品由作者写作 |
| `ECHO` | `edges`(source_work_id → target_work_id) | N:N | source 提及 target,方向 source → target |
| 关注 | `friendships`(user_id → friend_id) | N:N(单向) | user 关注 friend,不影响星云可见性 |

## 与用户导出 CSV / API 形状的对应

星云工坊页「导出 CSV」按钮(所有登录用户)返回三张表的 zip:

- `authors.csv` / `edges.csv` 的列与表列一一对应;
- `works.csv` 在 `Title_Other` 之后插入 `author_id` 派生列(work_authors 按
  `works.id` 聚合为逗号分隔串),末尾附加 `readingStatus` / `recommendation` / `review`
  个人字段;
- 导出仅含**导出者自己的星云**,排除 AI 草稿,含软删除行
  (`deletedAt` 列标注);内部列(owner_id / created_by / published_to_id)与
  sessions、audit_log 不进导出;
- API 的 `Work.author_id` / `author_ids` 同样为 work_authors 的派生展示字段。

## 演进方向(未实现)

- 数据量增长后:`edges` 按 `source_work_id` / `target_work_id` 的索引已就位;
  搜索可加 SQLite FTS5(`Title_CN` / `Title_EN` / `originalTitle`),`evidence`
  长文本可拆分独立表或接入 FTS5;读取层内存 BFS 可换进程内邻接缓存。

## 版本说明

本文档版本独立于数据库迁移版本(`meta.schema_version`,当前 27);
数据结构演进时递增本文档 `schemaVersion` 并保持向后兼容。

`1.7 → 1.8` 变更(2026-08-28):

- 新增 `email_tokens` 邮箱令牌表(schema v27 迁移):邮箱验证(verify)与密码重置
  (reset)共用,只存 SHA-256 哈希,24 小时有效,一次性消费;同用户同用途重发
  自动作废旧令牌;
- `users` 新增 `email_verified_at`(schema v27 迁移):`EMAIL_VERIFY_REQUIRED=1`
  时新注册用户需验证邮箱后才能登录;存量用户迁移回填 `createdAt`(历史注册
  无需验证,视为已信任);引导管理员在验证通过后才提权 admin
  (`app/auth.py` `verify_email` / `bootstrap_admin`)。

`1.6 → 1.7` 变更(2026-08-25):

- `users` 新增 `vip` 标记列(schema v26 迁移):布尔 0/1,默认 0;
  VIP 用户拥有 AI 书籍导入权限(`/api/admin/import-book`),
  导入草稿按 owner_id=上传者 隔离(见「1.4 → 1.5」草稿区说明);
  VIP 标记由 admin 接口 `POST /api/admin/users/{user_id}/vip` 维护。

`1.5 → 1.6` 变更(2026-08-25):

- 新增 `embeddings` 向量缓存表(schema v25 迁移):AI 语义去重把库内作者/作品
  标题向量落库,缓存键 = entity_type + entity_id + model + version,
  text_hash 感知标题/作者字段变更;不属于业务数据,不进公共导出,无管理入口。

`1.4 → 1.5` 变更(2026-08-25):

- AI 草稿审核管道(schema v24 迁移):作者/作品/涟漪三表新增 `published_to_id`,
  记录上传者空间草稿(owner_id=上传者、created_by='llm')批准后映射到的发布行 id
  (复用场景为被复用行 id),防重复发布;
- 草稿区 = 上传者空间(`owner_id`=上传者、`created_by='llm'`、`reviewStatus='draft'`),
  上传者(admin/VIP)只能看到/审核自己上传的草稿,多 admin 各自独立、互不审核;
  官方图谱/admin 星云与策展读取统一排除 AI 草稿
  (判定:`created_by='llm'` 且 `reviewStatus != 'reviewed'` 或 `published_to_id` 非空,
  见 `db_sqlite.ai_draft_clause`);批准后复制进**自己的星云**
  (`created_by='llm'`、`reviewStatus='reviewed'`,admin 的星云即官方图谱)
  或按去重提示复用自己星云中的现有记录;admin 整合用户数据进官方图谱的通道
  为后续规划;
- 历史数据:2026-08 之前的草稿曾落在共享 `system_llm` 账号空间,
  `app/llm_account.migrate_legacy_llm_drafts()` 在首次读取草稿时一次性
  改挂到引导管理员并删除空账号;
- 审计新增动作:`llm_ingest`(批次入库草稿)/ `llm_publish`(批准发布)/
  `llm_reuse`(批准复用)/ `llm_reject`(驳回)/ `llm_reopen`(重开)。

`1.3 → 1.4` 变更(2026-08-24):

- 作者/作品/涟漪三表新增溯源列 `created_by`(schema v23 迁移),取值
  `curated`(人工策展)/ `user`(用户空间写入)/ `llm`(AI 提取,预留);
- 显式传值优先,缺省按 owner 推导(admin 空间 = `curated`,其他 = `user`);
  创建后不可修改(与 `createdAt` 同策略),不进公共导出(与个人字段同策略);
- 存量行经迁移默认回填 `curated`,无需逐行处理。

`1.2 → 1.3` 变更(2026-08-24):

- 删除 `contributions` 贡献收件箱表(schema v22 迁移 `DROP TABLE`);
  同步移除 `app/contributions.py`、`POST /api/contribute/echo`、
  admin「贡献」审核接口与前端「贡献」Tab;
- 「点亮星空」早已直写个人空间(`/api/me/edges`),书籍解析管线后续将直接以
  专用用户空间承载,不再需要自由文本收件箱;
- 审计 `kind` 枚举去掉 `contributions`(历史审计行保留,仅不再产生新行)。

`1.1 → 1.2` 变更(2026-08-24,按实际数据库结构修订):

- 补充 `sessions` / `contributions` / `audit_log` / `meta` / `work_authors` 表结构;
- 修正 `works`:`author_id` 说明为 work_authors 派生的导出/API 字段,并补充
  `recommendation` / `review` / `readingStatus` 个人字段;
- 用户表补充 `username` 唯一索引的 `COLLATE NOCASE` 与 DB 层可空说明;
- 删除已退役的 `creationYear` / 节点级 `visibility` 相关描述;
- 约束与索引清单按实际 `PRAGMA` 输出更新(含 `idx_*_owner` 等);
- 明确禁用用户(status=disabled)的星云不可访问。
