# data/real 真实数据目录

真实数据以三个 **CSV** 文件维护(UTF-8 BOM,可用 Excel/WPS/Google Sheets 打开):

- `authors.csv` — 作者表
- `works.csv` — 作品表
- `edges.csv` — 提及关系表

**推荐通过应用内的「数据管理」页面编辑**(左侧栏入口):表单 + 下拉校验 + 一键导入 Neo4j,保存时自动做版本快照。
保存/导入时自动清洗:去除首尾空白、空串归一为 null、移除零宽/不可见格式字符(如 U+200B,网页复制文本常带入)。

命令行方式:

```bash
uv run python scripts/import_data.py --source csv --wipe --version 1.1   # 从 CSV 导入(全量重建)
```

`--wipe` 会全量重建;不加则幂等更新(合并已有实体)。`deletedAt` 非空的行保留在 CSV 存档,但不会进入图谱。
校验失败(引用不存在、重复 id、作者 id 未匹配、genre 越界等)会整批拒绝并打印原因。

列名与 `data_schema.md` 一致:`id` 使用 UUID,新增作者/作品/涟漪时后端自动生成 UUID v7;`works.csv` 的 `author_id` 存作者 UUID(多人用逗号分隔),展示名由作者表提供;`edges.csv` 的 `id` 列必填(手工在 CSV 里新增行时需自行补齐 UUID,或通过管理页新增);`reviewStatus` 留空默认 `draft`。
