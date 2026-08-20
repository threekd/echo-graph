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
4. **来源追溯**：每条关系都附有一小段原文片段。

**技术架构**
- 数据存储：Neo4j 图数据库 + SQLite
- 后端：Python / FastAPI，提供查询路径、扩散计算、影响力算法
- 前端：React + Three.js，支持大数据量图谱可视化

---

## 实施路线


**主要任务：**
- 定义数据模型：作家、作品、关系类型、属性字段。
- 初始数据集：选取 **50位核心作家 + 100部经典作品**
- 人工策展 **50条高置信度影响链**，作为种子数据。
- 搭建 Neo4j 图数据库，导入数据。
- 开发一个简单前端页面，可视化种子图谱。

---

## 当前实现状态

已按实施路线搭建出可运行的 MVP 骨架：

- **数据模型**：按 `data_schema.md`(schemaVersion 1.1)实现——`Author` / `Work` 节点及属性(`id` 为 UUID,新增自动生成 UUID v7,URL 直接使用 UUID);结构关系 `(Work)-[:AUTHORED_BY]->(Author)`(1:N,允许合著);回声关系 `(Work)-[:ECHO]->(Work)`(A 提及 B),属性含 `id`(UUID,新增自动生成)、`evidence` / `evidenceSource`、`note`、`reviewStatus` 与时间戳。图谱中**同时显示作者与作品节点**。
- **真实数据**：来自 `data/real/authors.csv` / `works.csv` / `edges.csv` 三份 CSV,已全量导入 Neo4j;
- **Neo4j**：`scripts/import_data.py` 将真实数据导入 Aura(凭据在 `.env`,已 gitignore);若 Neo4j 不可用,后端自动回退到 JSON 内存数据(部署时由 `scripts/export_seed.py` 从 CSV 生成 `data/seed.json` 兜底,本地未生成时为空图)。
- **后端**：FastAPI,接口见下方;路径查询使用 Cypher 最短路径(有向,ECHO);Neo4j 查询失败时自动回退 JSON 数据。
- **前端**：React 19 + Vite 5 + TypeScript(构建产物由 FastAPI 托管于 `frontend/dist`),Three.js(0.185,npm 依赖 + addons)。3D 渲染为**受控模式**:React store 持有 `viewData`/`currentView`/相机,`GraphCanvas` 的 effect 驱动渲染器执行绘制,渲染器退化为纯执行器(`update(kind, data)`,同视图增量同步);节点点击/悬停由 React 事件委托驱动。主视图为**球状星云**——作者为蓝白星、作品为金星(均带光晕并随机呼吸闪烁),`AUTHORED_BY` 归属关系为暗淡弱连线,ECHO 提及关系为青色发光星轨;支持右键旋转、左键平移、滚轮缩放、点击选星,并有 CSS 星空背景与流星点缀。

### 运行方式

```bash
uv sync               # 安装依赖(已在 pyproject.toml)
cd frontend && pnpm install && pnpm typecheck && pnpm build   # 构建 React 前端(产物进入 frontend/dist)
uv run python scripts/import_data.py          # 导入 Neo4j(自动识别 csv)
uv run python scripts/import_data.py --source csv --wipe --version 1.1  # 从 data/real/*.csv 导入(推荐)
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

质量检查(已在 CI 中自动执行):

```bash
uv run python -m unittest discover -s tests -v   # 后端测试(无需额外依赖)
uvx ruff check .                                  # 后端 lint
cd frontend && pnpm lint                          # 前端 lint
cd frontend && pnpm typecheck                     # 前端类型检查
cd frontend && pnpm test                          # 前端单元测试(Vitest)
```

前端开发模式:`cd frontend && pnpm dev`(Vite 开发服务器 5173 端口,`/api` 代理到 8000)。

### 部署到自己的 VPS(Ubuntu)

架构:`nginx(80/443) → uvicorn(127.0.0.1:8000) → Neo4j Aura`,前端构建产物由 nginx 直接托管。
上线前清单、运维手册与常见问题见 [`deploy/DEPLOY.md`](deploy/DEPLOY.md)。

`deploy/` 目录提供开箱模板:

- `setup-vps.sh` — 一键初始化:装系统依赖、建应用用户、拉代码、由 uv 托管 Python 3.14、构建前端、配置 systemd + nginx + HTTPS
- `deploy.sh` — 日常更新:备份数据 → 拉代码 → 装依赖 → 生成兜底种子 → 构建前端 → 重启服务
- `echo-graph.service` — systemd 单元模板
- `nginx.conf` — nginx 站点模板(手动部署用)

步骤:

1. 把仓库推到 git 远端,修改 `deploy/setup-vps.sh` 顶部的 `REPO_URL`。
2. VPS 上执行初始化(第二个参数是 certbot 邮箱,用于自动签发 HTTPS 证书):

   ```bash
   sudo bash deploy/setup-vps.sh <你的域名> <certbot邮箱>
   ```

3. 编辑 `/opt/echo-graph/.env`,填入 `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD` / `ADMIN_TOKEN`。
4. 启动并验证:

   ```bash
   sudo systemctl start echo-graph
   curl https://<你的域名>/api/health
   ```

5. 之后每次更新代码(`deploy.sh` 会自动备份数据、重新生成 JSON 兜底种子、构建前端并重启):

   ```bash
   sudo -u echograph bash /opt/echo-graph/deploy/deploy.sh
   ```

注意事项:国内机房绑域名对外提供 80/443 服务需要 ICP 备案,不想备案可选香港/新加坡 VPS;Neo4j 继续用 Aura,不在 VPS 上自建图库;`data/real/*.csv` 是数据事实源,配合 git 即完成备份。

> **兜底数据**:`setup-vps.sh` / `deploy.sh` 会自动从 CSV 生成 `data/seed.json`(已 gitignore),
> Neo4j 短暂不可用时站点自动回退到该数据,而不是空图;回退状态可通过 `/api/health` 的
> `store` 与 `fallbacks` 字段观察。

> 数据管理接口(`/api/admin/*`)需要 Bearer 令牌:在 `.env` 配置 `ADMIN_TOKEN`(已内置一个随机值),请求头带 `Authorization: Bearer <token>`。前端「数据管理」按钮默认隐藏:在 URL 后加 `?admin` 或 `#v=admin` 会弹出令牌授权框(注意 `?admin` 要放在 `#` 之前,如 `http://host/?admin`;若误加在 `#` 之后如 `#v=main?admin` 也会被识别),输入有效令牌后按钮显示;未授权用户在授权框点「取消」会退出管理页并自动清除 URL 中的 admin 参数;管理页内可「退出授权」清除令牌并隐藏按钮。CSV 与 Neo4j 内容不一致时(新增/修改/删除后未上传),管理页会显示「数据未上传」小字提示。

> **贡献数据**:普通用户可通过左侧栏「贡献数据」按钮提交涟漪建议(源/目标作品与作者可下拉选择已有数据或自由填写新名称;必填项:源作品、源作品作者、目标作品、目标作品作者、原文片段、出处;备注与联系方式选填)。提交只写入待审核收件箱(SQLite `data/contributions.db`,已 gitignore),不会直接进入图谱;管理员在「数据管理 → 贡献」Tab 中审核(通过/驳回),通过后由后续流程(人工录入 / AI 校正)再并入正式数据。公开接口为 `POST /api/contribute/echo`(带基础 IP 限流)。

真实数据以 `data/real/authors.csv` / `works.csv` / `edges.csv` 三份表格为准,授权后通过页面左侧「**数据管理**」入口编辑(表单校验 + 一键导入 Neo4j + 版本快照),字段说明见 `data/real/README.md`;导入前会自动校验(类型、枚举、交叉引用、作者 id 关联、重复 id),通过后批量写入并导出 JSON 快照到 `data/snapshots/`。

**软删除设计**:`deletedAt` 仅在 CSV 数据层表达——被删除的行保留在 CSV 存档(`deletedAt` 非空),但不会进入 Neo4j:导入时这类行会从图中物理移除(DETACH DELETE),图中只存活跃数据,节点/关系上不写入 `deletedAt` 属性,查询层也不按该属性过滤。删除作品时,与其相关的涟漪边会一并软删除;删除作者时,其名下作品及相关涟漪边会一并软删除;恢复时,同一删除动作删掉的作品/涟漪(相同 `deletedAt`)会一并恢复。

浏览器打开 <http://127.0.0.1:8000/>。

### 视图与深链

| 视图 | 说明 | 深链示例 |
|---|---|---|
| 主图谱 | 全量球状星云 | `http://127.0.0.1:8000/#v=main` |
| 提及链 | 两作品间的 3D 提及路径(螺旋排列) | `http://127.0.0.1:8000/#v=path:{fromWorkId},{toWorkId}` |
| 涟漪 | 以某作品为中心的 3D 扩散球(N 级扩散) | `http://127.0.0.1:8000/#v=ripple:{workId}:2` |
| 作者 | 该作者与全部作品 | `http://127.0.0.1:8000/#v=author:{authorId}` |

URL 参数:`v=`(视图)、`islands=1`(隐藏孤岛星)、`authors=0`(隐藏作者节点)、`cam=theta,phi,radius,cx,cy,cz`(相机位置,旧版分享链接格式,仍兼容解析)。旧格式 `#path=` / `#ripple=` / `#author=` 已在 React 迁移后移除,统一使用 `#v=` 格式,标识均为 UUID。

### API

| 接口 | 说明 |
|---|---|
| `GET /api/graph?status=` | 全量图谱(节点 + 边);`status` 可选 `draft` / `reviewed` / `rejected`,按审核状态过滤 |
| `GET /api/search?q=` | 搜索作家 / 作品 |
| `GET /api/work/{id}` | 作品详情 + 谁提及它 / 它提及谁(涟漪数据) |
| `GET /api/path?from={workId}&to={workId}` | 有向最短提及链 |
| `GET /api/expansion/{workId}?hops=N` | N 级涟漪扩散子图 |
| `GET /api/stats` | 数据统计(含 `reviewStatus` 分布) |

### 重要声明

- 当前数据为**真实策展数据**,以 `data/real/*.csv` 为准;摘抄与出处来自 `data/real/edges.csv`;审核状态按行记录(`draft` / `reviewed`),正式发布前需逐条人工审核并置为 `reviewed`。
- 前端已迁移到 React + Vite;旧版无构建静态页已移除,前端以 `frontend/dist` 构建产物为唯一维护源(由 FastAPI 托管)。
- Neo4j 实例中另有存量 `Entity` 节点,接口查询已限定在 `Author` / `Work`,不影响这些数据。
