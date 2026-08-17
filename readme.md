**项目全称**  
The Echo Graph — A Ripple Atlas of World Literature  
中文名：**回声图谱——世界文学的涟漪地图**

**一句话定义**  
以“回声”为链接隐喻、“涟漪”为传播隐喻，构建一张跨语言、跨文化的世界文学影响图谱，让人清晰看见一部作品、一位作家如何穿越时间与语言，在后世产生回响与传承。

**核心概念**
- **回声（Echo）**：每一次提及，都是一部作品在另一部作品中的再次发声。
- **涟漪（Ripple）**：思想从中心向外扩散，在异时、异地、异语中激起新的创作。

**核心价值**
为文学研究者和爱好者提供一种全新的交互方式，用来探索：
- 哪些作家影响了哪些作家？
- 一部作品如何从母国传播到他国？
- 是否存在被遗忘的重要“回声链”？


**核心功能**
1. **影响力图谱**：总体类似于一张立体星云图，以节点代表作品，边代表连接关系（一本书提及了另一本书，则这本书指向另一本书并连接），支持点击展开、拖拽浏览。
2. **时间涟漪视图**：选择一部作品，其所提及的作品成球状散开。
3. **跨语言路径**：输入任意两部作品，计算并展示它们之间的影响传播链（如果能连接的话）
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

- **数据模型**：按上方规范实现——`Author` / `Work` 节点及属性(originalTitle、Title_CN、Title_EN、publicationYear、creationYear、language、summary 等);结构关系 `(Work)-[:AUTHORED_BY]->(Author)`;回声关系 `(Work)-[:ECHO]->(Work)`(A 提及 B),属性为 `evidence`(摘抄文本)与 `note`(备注)。图谱中**同时显示作者与作品节点**。
- **演示种子数据**：50 位作家、100 部作品、50 条 ECHO 关系,由 `scripts/generate_seed_data.py` 生成到 `data/seed.json`。
- **Neo4j**：`scripts/import_data.py` 将种子数据导入 Aura(凭据在 `.env`,已 gitignore);若 Neo4j 不可用,后端自动回退到 JSON 内存数据,演示不会中断。
- **后端**：FastAPI,接口见下方;路径查询使用 Cypher 最短路径(有向,ECHO);Neo4j 查询失败时自动回退 JSON 数据,演示不会中断。
- **前端**：无构建单页(HTML + Three.js,3D 渲染),已按原生 ES module 拆分(util / state / renderer / panels / actions / main,无打包器)。主视图为**球状星云**——作者为蓝白星、作品为金星(均带光晕并随机呼吸闪烁),`AUTHORED_BY` 归属关系为暗淡弱连线,ECHO 提及关系为青色发光星轨;支持右键旋转、左键平移、滚轮缩放、点击选星,并有 CSS 星空背景与流星点缀。

### 运行方式

```bash
uv sync               # 安装依赖(已在 pyproject.toml)
uv run python scripts/generate_seed_data.py   # 重新生成演示数据(可选)
uv run python scripts/import_data.py          # 导入 Neo4j(可选)
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000/>。

### 视图与深链

| 视图 | 说明 | 深链示例 |
|---|---|---|
| 主图谱 | 全量球状星云 | `http://127.0.0.1:8000/` |
| 提及链 | 两作品间的 3D 提及路径(螺旋排列) | `http://127.0.0.1:8000/#path=iliad,living` |
| 涟漪 | 以某作品为中心的 3D 扩散球 | `http://127.0.0.1:8000/#ripple=hundred_years` |

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

(书籍A) -[:ECHO]-> (被书籍A所提及的书籍B)

| 属性 | 类型 | 说明 |
|---|---|---|
| `evidence` | String | 摘抄文本，即正文某片段出现另一本书的名称 |
| `note` | String | 备注或补充说明 |
