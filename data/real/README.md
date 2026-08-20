# data/real CSV 导出目录

**这里的三份 CSV 是派生产物,不是数据事实源。** 事实源是 SQLite(`data/echo-graph.db`):

- `authors.csv` — 作者表
- `works.csv` — 作品表
- `edges.csv` — 提及关系表

每次在「数据管理」页面保存/删除/恢复时,后端都会自动按 `id` 排序重新导出这三份文件(UTF-8 BOM),提交进 git 用于审计与回滚。**请勿手工编辑这些 CSV**:CI 会执行 `scripts/export_csv.py --check` 校验导出与仓库一致,手工改动会被拒绝;需要改数据请走管理页,或修改 SQLite 后重新导出。

手动重新生成:

```bash
uv run python scripts/export_csv.py          # 覆盖 data/real/*.csv
uv run python scripts/export_csv.py --check  # 仅校验(CI 门禁)
```

导入 Neo4j(从 SQLite 读取):

```bash
uv run python scripts/import_data.py --wipe --version 1.1   # 全量重建
```

`--wipe` 会全量重建;不加则幂等更新。`deletedAt` 非空的行保留在库与 CSV 存档,但不会进入图谱。校验失败(引用不存在、重复 id、作者 id 未匹配、genre 越界等)会整批拒绝并打印原因。

列名与 `data_schema.md` 一致:`id` 使用 UUID,新增作者/作品/涟漪时后端自动生成 UUID v7;`works.csv` 的 `author_id` 存作者 UUID(多人用逗号分隔),展示名由作者表提供;`reviewStatus` 留空默认 `draft`。
