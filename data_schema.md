# Echo Graph 数据结构规范

- `schemaVersion`: `1.1`
- 存储:Neo4j 图数据库(演示环境同时提供 JSON 兜底数据)
- 所有 `createdAt` / `updatedAt` 均为 UTC ISO-8601 字符串

## 通用约定

- **主键与 URL 标识**:`id` 使用 UUID(建议 UUID v7,时间有序),同时也是 URL 使用的标识;新增作者/作品/涟漪时由后端自动生成。
- **命名风格**:通用属性使用 camelCase(`originalTitle`、`publicationYear`);中英文标题/姓名使用大写前缀约定(`Title_CN`、`Title_EN`、`Name_CN`、`Name_EN`),作为对外展示字段。
- **语言编码**:优先 ISO 639-1;无法表达时(如中古英语、古典日语)使用 ISO 639-3(`enm`、`ojp`)或自定义枚举,并在文档中登记。
- **国籍编码**:使用 ISO 3166-1 alpha-2 大写代码(如 `CN` 中国、`US` 美国);无国籍/未知时留空。

## 节点类型与属性

### Work 作品节点

| 属性 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | UUID | 是 | 唯一标识,主键 |
| `language` | String | 是 | 作品语言(ISO 639-1,兜底 639-3) |
| `originalTitle` | String | 是 | 原著标题 |
| `Title_CN` | String | 是 | 中文版标题 |
| `Title_EN` | String | 否 | 英文版标题 |
| `Title_Other` | String | 否 | 其他可能的标题 |
| `Author` | String | 否 | 作者，（多人用逗号","隔开） |
| `publicationYear` | Integer | 否 | 出版年份 |
| `creationYear` | Integer | 否 | 创作年份 |
| `genre` | String | 否 | 体裁，枚举:(Fiction / Non-fiction/ Poetry / Drama) |
| `reviewStatus` | String | 否 | 审核状态，枚举:`draft` / `reviewed` / `rejected`，默认 `draft` |
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
| `birthYear` | Integer | 否 | 出生年份 |
| `deathYear` | Integer | 否 | 去世年份 |
| `reviewStatus` | String | 否 | 审核状态，枚举:`draft` / `reviewed` / `rejected`，默认 `draft` |
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
| `evidence` | String | 是 | 摘抄文本,即正文某片段出现另一本书的名称 |
| `evidenceSource` | String | 否 | 证据出处:作品章节 / 页码 / 译本版本 |
| `evidenceLang` | String | 否 | 摘抄原文语言(ISO 639-1,兜底 639-3) |
| `note` | String | 否 | 备注或补充说明 |
| `reviewStatus` | String | 是 | 审核状态,枚举:`draft`(草稿)/ `reviewed`(已审核)/ `rejected`(驳回),默认 `draft` |
| `createdAt` | DateTime | 是 | 创建时间 |
| `updatedAt` | DateTime | 是 | 更新时间 |
| `deletedAt` | DateTime | 否 | 软删除时间(可选,默认不设置) |

## 约束与索引

- 唯一约束:`Work.id`、`Author.id`
- 全文索引:Neo4j 全文索引仅支持节点属性,建议对 `Work(Title_CN, Title_EN, originalTitle)` 建 fulltext;`evidence` 属于关系属性,无法直接用 Neo4j fulltext,检索时用 `CONTAINS` 或后续拆分为独立 Evidence 节点
- 建议查询:`(Work)-[:ECHO]` 两端均命中唯一约束,路径与扩散查询走变长路径

## 说明

- 早期演示数据曾为编造;现以 `data/real/*.csv` 真实策展数据为准,`evidence` 摘抄来自公开译本,审核状态按行记录,正式发布前需逐条人工审核并置为 `reviewed`。
- 本规范为 1.1 版;数据结构演进时递增 `schemaVersion` 并保持向后兼容。
