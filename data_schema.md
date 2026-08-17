## 节点类型与属性

### Work 作品节点

| 属性 | 类型 | 说明 |
|---|---|---|
| `id` | String / UUID | 唯一标识，主键 |
| `language` | String | 作品语言（ISO 639-1） |
| `originalTitle` | String | 原著标题 |
| `Title_CN` | String | 中文版标题 |
| `Title_EN` | String | 英文版标题 |
| `publicationYear` | Integer | 出版年份，可空 |
| `creationYear` | Integer | 创作年份，可空 |
| `summary` | String | 内容简介 |
| `createdAt` | DateTime | 创建时间 |
| `updatedAt` | DateTime | 更新时间 |


### Author 作家节点

| 属性 | 类型 | 说明 |
|---|---|---|
| `id` | String / UUID | 唯一标识，主键 |
| `nationality` | String | 国籍/族裔 |
| `originalName` | String | 全名（必填） |
| `Name_CN` | String | 中文名 |
| `Name_EN` | String | 英文名 |
| `birthYear` | Integer | 出生年份，可空 |
| `deathYear` | Integer | 去世年份，可空 |
| `primaryLanguage` | String | 主要写作语言（ISO 639-1） |
| `bio` | String | 简介 |
| `createdAt` | DateTime | 创建时间 |
| `updatedAt` | DateTime | 更新时间 |

## 结构关系

| 关系类型 | 方向 | 语义 |
|---|---|---|
| `AUTHORED_BY` | `(Work)-[:AUTHORED_BY]->(Author)` | 作品由作者写作 |

## 回声关系

### EDGES

| 属性 | 类型 | 说明 |
|---|---|---|
| `source_work_id` | String | 当前作品 |
| `target_work_id` | String | 被提及作品 |
| `evidence` | String | 摘抄文本，即正文某片段出现另一本书的名称 |
| `note` | String | 备注或补充说明 |
| `confidence` | String | 置信度 |
| `reviewStatus` | String | 草稿/已审核 |