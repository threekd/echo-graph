**项目全称**  
The Echo Graph — A Ripple Atlas of World Literature  
中文名：**回声图谱——世界文学的涟漪地图**

**一句话定义**  
构建一张跨语言、跨文化的世界文学影响图谱，让人清晰看见一部作品、一位作家如何穿越时间与语言，在后世产生回响与涟漪。

**核心概念**
- **回声（Echo）**：每一次提及，都是一部作品在另一部作品中的再次发声。
- **涟漪（Ripple）**：思想从中心向外扩散，在异时、异地、异语中激起新的创作。

**核心价值**
为文学爱好者提供一种全新的交互方式，用来探索：
- 哪部作品提到过哪部作品？
- 哪些作家影响了哪些作家？
- 两个看似不相干的作品是否可能存在一个隐藏的链条？


**核心功能**
1. **影响力图谱**：总体类似于一张立体星云图，以节点代表作品和作家，边代表连接关系（一本书提及了另一本书，则这本书指向另一本书并连接），支持点击展开、拖拽浏览。
2. **时间涟漪视图**：选择一部作品，其所提及的作品成球状散开。
3. **跨语言路径**：输入任意两部作品，计算并展示它们之间的影响传播链。
5. **来源追溯**：每条关系都附有一小段原文片段。

**技术架构**
- 数据存储：Neo4j 图数据库
- 后端：Python / FastAPI，提供查询路径、扩散计算、影响力算法
- 前端：React + AntV G6 + Three.js，支持大数据量图谱可视化

---

## 实施路线


**主要任务：**
- 定义数据模型：作家、作品、关系类型、属性字段。
- 初始数据集：选取 **50位核心作家 + 100部经典作品**
- 人工策展 **50条高置信度影响链**，作为种子数据。
- 搭建 Neo4j 图数据库，导入数据。
- 开发一个简单前端页面，可视化种子图谱。

---

## 当前实现状态(演示版)

已按实施路线搭建出可运行的 MVP 骨架：

- **数据模型**：按 `data_schema.md`(schemaVersion 1.1)实现——`Author` / `Work` 节点及属性(含 `slug`、`genre` 等);结构关系 `(Work)-[:AUTHORED_BY]->(Author)`(N:N,允许合著);回声关系 `(Work)-[:ECHO]->(Work)`(A 提及 B),属性含 `evidence` / `evidenceSource` / `evidenceLang`、`note`、`confidence`(0–1)、`reviewStatus`(draft/reviewed/rejected)、`dataSource`(manual/auto/nlp)与时间戳。图谱中**同时显示作者与作品节点**。
- **演示种子数据**：50 位作家、100 部作品、50 条 ECHO 关系,由 `scripts/generate_seed_data.py` 生成到 `data/seed.json`。
- **Neo4j**：`scripts/import_data.py` 将种子数据导入 Aura(凭据在 `.env`,已 gitignore);若 Neo4j 不可用,后端自动回退到 JSON 内存数据,演示不会中断。
- **后端**：FastAPI,接口见下方;路径查询使用 Cypher 最短路径(有向,ECHO);Neo4j 查询失败时自动回退 JSON 数据,演示不会中断。
- **前端**：无构建单页(HTML + Three.js,3D 渲染),已按原生 ES module 拆分(util / state / renderer / panels / actions / main,无打包器)。主视图为**球状星云**——作者为蓝白星、作品为金星(均带光晕并随机呼吸闪烁),`AUTHORED_BY` 归属关系为暗淡弱连线,ECHO 提及关系为青色发光星轨;支持右键旋转、左键平移、滚轮缩放、点击选星,并有 CSS 星空背景与流星点缀。

### 运行方式

```bash
uv sync               # 安装依赖(已在 pyproject.toml)
uv run python scripts/generate_seed_data.py   # 重新生成演示数据(可选)
uv run python scripts/import_data.py          # 导入 Neo4j(自动:有 data/real/*.csv 则导入真实数据,否则导入演示数据)
uv run python scripts/import_data.py --source seed --wipe      # 强制用演示数据全量重建
uv run python scripts/import_data.py --source real --version 1.0  # 导入 data/real/ 真实数据(幂等,可重复执行)
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

真实数据模板见 `data/real/README.md`(authors.csv / works.csv / echoes.csv),导入前会自动校验(类型、枚举、交叉引用、重复 id),通过后批量写入并导出 JSON 快照到 `data/snapshots/`。

浏览器打开 <http://127.0.0.1:8000/>。

### 视图与深链

| 视图 | 说明 | 深链示例 |
|---|---|---|
| 主图谱 | 全量球状星云 | `http://127.0.0.1:8000/#v=main` |
| 提及链 | 两作品间的 3D 提及路径(螺旋排列) | `http://127.0.0.1:8000/#v=path:iliad,living` |
| 涟漪 | 以某作品为中心的 3D 扩散球(N 级扩散) | `http://127.0.0.1:8000/#v=ripple:hundred_years:2` |
| 作者 | 该作者与全部作品 | `http://127.0.0.1:8000/#v=author:christie` |

URL 参数:`v=`(视图)、`islands=1`(隐藏孤岛星)、`cam=theta,phi,radius,cx,cy,cz`(相机位置,由"分享链接"生成)。旧格式 `#path=` / `#ripple=` / `#author=` 仍兼容。

左侧栏提供"分享链接 / 导出图片 / 导出数据":分享链接复制含相机位置的完整 URL;导出图片为当前视图 PNG;导出数据为全量图谱 JSON。

### API

| 接口 | 说明 |
|---|---|
| `GET /api/graph` | 全量图谱(节点 + 边) |
| `GET /api/search?q=` | 搜索作家 / 作品 |
| `GET /api/work/{id}` | 作品详情 + 谁提及它 / 它提及谁(涟漪数据) |
| `GET /api/path?from={workId}&to={workId}` | 有向最短提及链 |
| `GET /api/stats` | 数据统计 |

### 重要声明

- 当前所有提及关系与"引文"均为**编造演示数据**,仅用于展示产品形态;作家/作品元信息大致符合文学史,但关系不可作为学术依据。正式版本需人工策展并附真实原文片段。
- 前端目前采用无构建的单页实现(暂不依赖 npm);npm 已可用(12.0.2),后续可平滑迁移到 React + Vite。
- Neo4j 实例中另有 591 个存量 `Entity` 节点,接口查询已限定在 `Author` / `Work`,不影响这些数据。
