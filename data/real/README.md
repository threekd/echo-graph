# data/real 真实数据目录

把真实策展数据按下列三张表放入本目录,然后运行:

```bash
uv run python scripts/import_data.py --source real --version 1.0
```

导入是**幂等**的(可重复执行,不删除已有数据);需要全量重建时加 `--wipe`。
每行 `deletedAt` 非空表示软删除,导入时跳过。
校验失败(引用不存在、重复 id、置信度越界等)会整批拒绝并打印原因。

## authors.csv

`id,originalName,Name_CN,Name_EN,nationality,birthYear,deathYear,primaryLanguage,bio,reviewer,reviewedAt,deletedAt`

- `id`:`slug` 格式(字母/数字/下划线/连字符),URL 使用
- `originalName` / `Name_CN` / `Name_EN`:原文名、中文名、英文名(必填)
- `primaryLanguage`:ISO 639-1(无法表达时用 639-3)

## works.csv

`id,author_id,language,originalTitle,Title_CN,Title_EN,publicationYear,creationYear,genre,summary,reviewer,reviewedAt,deletedAt`

- `author_id` 必须存在于 authors.csv
- `publicationYear` 与 `creationYear` 至少填一个

## echoes.csv

`source_work_id,target_work_id,evidence,evidenceSource,evidenceLang,note,confidence,reviewStatus,dataSource,reviewer,reviewedAt,source_url,deletedAt`

- `source_work_id` 这本书在正文中提及 `target_work_id`
- `evidence`:摘抄原文(必填);`evidenceSource`:章节/页码/译本版本
- `confidence`:0–1;`reviewStatus`:`draft` / `reviewed` / `rejected`;`dataSource`:`manual` / `auto` / `nlp`

## 示例行

```csv
# authors.csv
lu_xun,周树人,鲁迅,Lu Xun,中国,1881,1936,zh,,

# works.csv
crazy_diary,lu_xun,zh,狂人日記,狂人日记,Diary of a Madman,,1918,小说,,

# echoes.csv
crazy_diary,gogol_diary,演示摘抄:正文提及《狂人日记》,第1章,zh,,0.85,draft,manual,,,,
```

说明:真实数据请务必填写 `evidenceSource`(出处)与 `reviewer` / `reviewedAt`,审核通过后把 `reviewStatus` 改为 `reviewed`。
