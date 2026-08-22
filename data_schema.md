# Echo Graph 数据结构规范

- `schemaVersion`: `1.1`
- 存储与读取:策展数据与公开读取均以 SQLite(`data/echo-graph.db`)为准;`data/export/*.csv` 为确定性导出产物(git 审计 / 跨机器传输);Neo4j 查询层与 JSON 兜底已退役
- 所有 `createdAt` / `updatedAt` 均为 UTC ISO-8601 字符串

## 通用约定

- **主键与 URL 标识**:`id` 使用 UUID(建议 UUID v7,时间有序),同时也是 URL 使用的标识;新增作者/作品/涟漪时由后端自动生成。
- **空间归属(多用户)**:`authors` / `works` / `edges` 各含 `owner_id`(引用 `users.id`,
  空值 = 尚未认领的历史数据,启动时认领给引导管理员);公共星云 = 引导管理员空间,
  个人空间(`/api/me/*`)仅本人可见;`contributions` 含 `user_id`(登录用户提交归属)。
- **命名风格**:通用属性使用 camelCase(`originalTitle`、`publicationYear`);中英文标题/姓名使用大写前缀约定(`Title_CN`、`Title_EN`、`Name_CN`、`Name_EN`),作为对外展示字段。
- **语言编码**:优先 ISO 639-1;无法表达时(如中古英语、古典日语)使用 ISO 639-3(`enm`、`ojp`)或自定义枚举,并在文档中登记。
- **国籍编码**:使用 ISO 3166-1 alpha-2 大写代码(如 `CN` 中国、`US` 美国);无国籍/未知时留空。

## 节点类型与属性

### User 用户

| 属性 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | UUID | 是 | 唯一标识,主键 |
| `email` | String | 是 | 登录邮箱(唯一,统一小写) |
| `password_hash` | String | 是 | Argon2 密码哈希,不存明文 |
| `role` | String | 是 | `user` / `admin`(引导管理员邮箱注册自动为 admin) |
| `status` | String | 是 | `active` / `disabled` |
| `space_visibility` | String | 是 | 星云可见性:`public`(默认,星际跃迁可访问)/ `private`(仅本人与 admin) |
| `createdAt` / `updatedAt` | DateTime | 是 | 时间戳 |

### Work 作品节点

| 属性 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | UUID | 是 | 唯一标识,主键 |
| `language` | String | 是 | 作品语言(ISO 639-1,兜底 639-3) |
| `originalTitle` | String | 是 | 原著标题 |
| `Title_CN` | String | 是 | 中文版标题 |
| `Title_EN` | String | 否 | 英文版标题 |
| `Title_Other` | String | 否 | 其他可能的标题 |
| `author_id` | String | 否 | 作者 id(UUID,关联 `Author.id`),展示名由作者表提供,改名不破坏关联 |
| `publicationYear` | Integer | 否 | 出版年份 |
| `genre` | String | 否 | 体裁，(`Fiction` / `Non-fiction`/ `Poetry` / `Drama`) |
| `note` | String | 否 | 备注（内部说明文字，不参与图谱展示） |
| `reviewStatus` | String | 否 | 审核状态（`draft` / `reviewed` / `rejected`；公共星云默认 `draft`，普通用户空间默认 `reviewed`——用户输入即确认） |
| `visibility` | String | 否 | 可见性（`public` 公开 / `private` 隐藏，默认 `public`）；仅对访客视图生效，owner 自己始终可见；公共星云恒为公开 |
| `recommendation` | String | 否 | 个人评分（`recommend` 推荐 / `not_recommend` 不推荐，默认空）；仅用户空间语义，不进 CSV |
| `review` | String | 否 | 个人评价（长文本，最多 2000 字，默认空）；仅用户空间语义，不进 CSV |
| `createdAt` | DateTime | 是 | 创建时间 |
| `updatedAt` | DateTime | 是 | 更新时间 |
| `deletedAt` | DateTime | 否 | 软删除时间(可选,默认不设置) |

### Author 作家节点

| 属性 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | UUID | 是 | 唯一标识,主键 |
| `originalName` | String | 是 | 全名/原文名 |
| `Name_CN` | String | 是 | 中文名 |
| `Name_EN` | String | 否 | 英文名 |
| `nationality` | String | 否 | 国籍(ISO 3166-1 alpha-2 大写代码,如 `CN`、`US`;留空表示无/未知) |
| `birthYear` | Integer | 否 | 出生年份(取值 -9999 ~ 9999) |
| `deathYear` | Integer | 否 | 去世年份(取值 -9999 ~ 9999) |
| `note` | String | 否 | 备注（内部说明文字，不参与图谱展示） |
| `reviewStatus` | String | 否 | 审核状态（`draft` / `reviewed` / `rejected`；公共星云默认 `draft`，普通用户空间默认 `reviewed`） |
| `visibility` | String | 否 | 可见性（`public` / `private`，默认 `public`，仅作者/作品节点） |
| `createdAt` | DateTime | 是 | 创建时间 |
| `updatedAt` | DateTime | 是 | 更新时间 |
| `deletedAt` | DateTime | 否 | 软删除时间(可选,默认不设置) |

## 结构关系

| 关系类型 | 方向 | 基数 | 语义 |
|---|---|---|---|
| `AUTHORED_BY` | `(Work)-[:AUTHORED_BY]->(Author)` | N:N(允许合著) | 作品由作者写作 |

## 回声关系

关系类型:`(Work)-[:ECHO]->(Work)`

方向:source 这本书在正文中提及 target 这本书,方向 source → target。

| 属性 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | UUID | 是 | 唯一标识,新增时后端自动生成 UUID v7 |
| `source_work_id` | String | 是 | 当前作品(引用 Work.id) |
| `target_work_id` | String | 是 | 被提及作品(引用 Work.id) |
| `evidence` | String | 是 | 原文片段(摘抄文本),即正文某片段出现另一本书的名称 |
| `evidenceSource` | String | 否 | 证据出处:作品章节 / 页码 / 译本版本 |
| `note` | String | 否 | 备注或补充说明 |
| `reviewStatus` | String | 否 | 审核状态,枚举:`draft`(草稿)/ `reviewed`(已审核)/ `rejected`(驳回),默认 `draft` |
| `createdAt` | DateTime | 是 | 创建时间 |
| `updatedAt` | DateTime | 是 | 更新时间 |
| `deletedAt` | DateTime | 否 | 软删除时间(可选,默认不设置) |

## 约束与索引

- 唯一约束:`Work.id`、`Author.id`
- 空间归属:`authors` / `works` / `edges` 的 `owner_id` 指向 `users.id`(空 = 未认领,
  认领后归引导管理员);公共星云 = admin 空间;用户星云默认公开可被星际跃迁访问。
- 全文检索:数据量增长后可对 `Work(Title_CN, Title_EN, originalTitle)` 建 SQLite FTS5 索引;`evidence` 属长文本,当前用包含匹配,后续可拆分为独立 Evidence 表或接入 FTS5
- 建议查询:`edges` 按 `source_work_id` / `target_work_id` 建索引(已有 `idx_edges_target`、`idx_edges_source`),路径与扩散查询在读取层以内存 BFS 实现,数据量增长后可加 FTS5 与进程内邻接缓存

## 说明

- 早期演示数据曾为编造;现以 SQLite 真实策展数据为准(CSV 导出在 `data/export/`),`evidence` 摘抄来自公开译本,审核状态按行记录,正式发布前需逐条人工审核并置为 `reviewed`。
- 软删除(`deletedAt`)只在 SQLite/CSV 数据层表达:标记为删除的行保留在库与存档中,读取层一律过滤,图上只出现活跃数据。
- 本规范为 1.1 版;数据结构演进时递增 `schemaVersion` 并保持向后兼容。
