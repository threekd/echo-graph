**项目全称**  
项目名称： Litnebula
副标题：**回声图谱——世界文学的涟漪地图**(A Ripple Atlas of World Literature)

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
- 数据存储：SQLite(`data/echo-graph.db`)为唯一权威,**公开读取也直接由 SQLite 提供**;`data/export/*.csv` 为确定性导出产物(git 审计 / 跨机器传输)
- 后端：Python / FastAPI，提供查询路径、扩散计算、影响力算法
- 前端：React + Three.js，支持大数据量图谱可视化

> 产品名 **Litnebula**;代码/仓库/部署标识沿用 `echo-graph`(工程标识与产品名分离,
> 避免牵动仓库、CI、systemd 服务名等既有设施)。

---

## 实施路线


**主要任务：**
- 定义数据模型：作家、作品、关系类型、属性字段。
- 初始数据集：选取 **50位核心作家 + 100部经典作品**
- 人工策展 **50条高置信度影响链**，作为种子数据。
- 搭建 SQLite 数据库，导入数据。
- 开发一个简单前端页面，可视化种子图谱。

---

## 当前实现状态

已按实施路线搭建出可运行的 MVP 骨架：

- **数据模型**：按 `data_schema.md`(schemaVersion 1.1)实现——`Author` / `Work` 节点及属性(`id` 为 UUID,新增自动生成 UUID v7,URL 直接使用 UUID);结构关系 `(Work)-[:AUTHORED_BY]->(Author)`(1:N,允许合著);回声关系 `(Work)-[:ECHO]->(Work)`(A 提及 B),属性含 `id`(UUID,新增自动生成)、`evidence` / `evidenceSource`、`note`、`reviewStatus` 与时间戳。图谱中**同时显示作者与作品节点**。
- **策展数据主存与读取**：SQLite(`data/echo-graph.db`,已 gitignore)为唯一权威,作者/作品/涟漪与贡献收件箱同库;公开接口(`/api/graph` 等)直接查 SQLite;`data/export/*.csv` 为每次写入自动导出的确定性产物(git 跟踪,审计/回滚/跨机器传输)。曾作为查询层的 Neo4j 与 JSON 兜底种子已退役。
- **后端**：FastAPI,接口见下方;路径查询为内存 BFS(有向,ECHO),扩散为无向 BFS,单核 VPS 上毫秒级。
- **前端**：React 19 + Vite 5 + TypeScript(构建产物由 FastAPI 托管于 `frontend/dist`),Three.js(0.185,npm 依赖 + addons)。3D 渲染为**受控模式**:React store 持有 `viewData`/`currentView`/相机,`GraphCanvas` 的 effect 驱动渲染器执行绘制,渲染器退化为纯执行器(`update(kind, data)`,同视图增量同步);节点点击/悬停由 React 事件委托驱动。主视图为**球状星云**——作者为蓝白星、作品为金星(均带光晕并随机呼吸闪烁),`AUTHORED_BY` 归属关系为暗淡弱连线,ECHO 提及关系为青色发光星轨;支持右键旋转、左键平移、滚轮缩放、点击选星,并有 CSS 星空背景与流星点缀。

### 运行方式

```bash
uv sync               # 安装依赖(已在 pyproject.toml)
cd frontend && pnpm install && pnpm typecheck && pnpm build   # 构建 React 前端(产物进入 frontend/dist)
uv run python scripts/migrate_csv_to_sqlite.py   # 从仓库 CSV 重建 SQLite(全新环境引导/恢复)
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

SQLite 库缺失或想从 CSV 重置数据时执行 `scripts/migrate_csv_to_sqlite.py`(贡献收件箱与审计表不受影响)。

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

架构:`nginx(80/443) → uvicorn(127.0.0.1:8000) → SQLite(本地文件)`,前端构建产物由 nginx 直接托管。
上线前清单、运维手册与常见问题见 [`deploy/DEPLOY.md`](deploy/DEPLOY.md)。

`deploy/` 目录提供开箱模板:

- `setup-vps.sh` — 一键初始化:装系统依赖、建应用用户、拉代码、由 uv 托管 Python 3.14、构建前端、配置 systemd + nginx + HTTPS
- `deploy.sh` — 日常更新:备份数据(含 SQLite)→ 拉代码 → 装依赖 → 重建 SQLite → 构建前端 → 重启服务
- `echo-graph.service` — systemd 单元模板
- `nginx.conf` — nginx 站点模板(手动部署用)

步骤:

1. 把仓库推到 git 远端,修改 `deploy/setup-vps.sh` 顶部的 `REPO_URL`。
2. VPS 上执行初始化(第二个参数是 certbot 邮箱,用于自动签发 HTTPS 证书):

   ```bash
   sudo bash deploy/setup-vps.sh litnebula.com <certbot邮箱>
   ```

3. 编辑 `/opt/echo-graph/.env`,填入 `ADMIN_TOKEN`(可用 `openssl rand -hex 32` 生成)。
4. 启动并验证:

   ```bash
   sudo systemctl start echo-graph
   curl https://litnebula.com/api/health
   ```

5. 之后每次更新代码(`deploy.sh` 会自动备份数据(含 SQLite)、从 CSV 重建 SQLite、构建前端并重启):

   ```bash
   sudo -u echograph bash /opt/echo-graph/deploy/deploy.sh
   ```

注意事项:国内机房绑域名对外提供 80/443 服务需要 ICP 备案,不想备案可选香港/新加坡 VPS;
1核2G 即可运行(systemd 单 worker);`data/echo-graph.db` 是数据事实源(备份=用 `sqlite3 .backup`
或 deploy.sh 自动备份),`data/export/*.csv` 为导出产物配合 git 完成版本审计与跨机器传输。

> 数据管理接口(`/api/admin/*`)需要 Bearer 令牌:在 `.env` 配置 `ADMIN_TOKEN`(已内置一个随机值),请求头带 `Authorization: Bearer <token>`。前端「数据管理」按钮默认隐藏:在 URL 后加 `?admin` 或 `#v=admin` 会弹出令牌授权框(注意 `?admin` 要放在 `#` 之前,如 `http://host/?admin`;若误加在 `#` 之后如 `#v=main?admin` 也会被识别),输入有效令牌后按钮显示;未授权用户在授权框点「取消」会退出管理页并自动清除 URL 中的 admin 参数;管理页内可「退出授权」清除令牌并隐藏按钮。编辑保存后立即写入 SQLite 并自动导出 CSV。

**发布过滤与快照恢复**:在 `.env` 设置 `PUBLIC_REVIEWED_ONLY=1` 后,公开接口只返回 `reviewStatus=reviewed` 的内容(草稿/驳回不可见),默认关闭以便开发时看到全部数据;管理页新增「快照」Tab,可一键创建当前库快照(`backups/echo-graph-<时间>.db`),也可查看并恢复 `backups/`(SQLite 备份)与 `data/versions/`(历史 CSV 目录,校验后重建)下的快照——恢复前会自动为当前库做安全备份,恢复成功后自动重新导出 CSV。

> **贡献数据**:普通用户可通过左侧栏「贡献数据」按钮提交涟漪建议(源/目标作品与作者可下拉选择已有数据或自由填写新名称;必填项:源作品、源作品作者、目标作品、目标作品作者、原文片段、出处;备注与联系方式选填)。提交只写入待审核收件箱(SQLite `data/echo-graph.db` 内 `contributions` 表),不会直接进入图谱;管理员在「数据管理 → 贡献」Tab 中审核(查看/驳回),通过后由后续流程(人工录入 / AI 校正)再并入正式数据。公开接口为 `POST /api/contribute/echo`(带基础 IP 限流:默认每 IP 每小时 20 条,策略详见 `deploy/DEPLOY.md`)。

策展数据以 SQLite(`data/echo-graph.db`)为准,`data/export/*.csv` 为每次写入自动导出的确定性产物;授权后通过页面左侧「**数据管理**」入口编辑(表单校验、软删除/恢复、审计记录),字段说明见 `data/export/README.md`;保存前自动校验(类型、枚举、交叉引用、作者 id 关联、重复 id),保存后自动导出 CSV,公开接口即时读到新数据。

**软删除设计**:`deletedAt` 仅在 SQLite/CSV 数据层表达——被删除的行保留在库中与 CSV 存档(`deletedAt` 非空),但读取层一律过滤,图上只出现活跃数据。删除作品时,与其相关的涟漪边会一并软删除;删除作者时,其名下作品及相关涟漪边会一并软删除;恢复时,同一删除动作删掉的作品/涟漪(相同 `deletedAt`)会一并恢复。

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

- 当前数据为**真实策展数据**,以 SQLite(`data/echo-graph.db`)为准,CSV 导出位于 `data/export/*.csv`;摘抄与出处来自 `data/export/edges.csv`;审核状态按行记录(`draft` / `reviewed`),正式发布前需逐条人工审核并置为 `reviewed`。
- 前端已迁移到 React + Vite;旧版无构建静态页已移除,前端以 `frontend/dist` 构建产物为唯一维护源(由 FastAPI 托管)。
