

> 产品名 **Litnebula**;代码/仓库/部署标识沿用 `echo-graph`(工程标识与产品名分离,
> 避免牵动仓库、CI、systemd 服务名等既有设施)。

---


## 当前实现状态

已按实施路线搭建出可运行的 MVP 骨架：

- **数据模型**：按 `data_schema.md`(schemaVersion 1.5)实现——`Author` / `Work` 节点及属性(`id` 为 UUID,新增自动生成 UUID v7,URL 直接使用 UUID);结构关系 `(Work)-[:AUTHORED_BY]->(Author)`(N:N,允许合著,物理实现为 `work_authors`);回声关系 `(Work)-[:ECHO]->(Work)`(A 提及 B),属性含 `id`(UUID,新增自动生成)、`evidence` / `evidenceSource`、`note`、`reviewStatus` 与时间戳。图谱中**同时显示作者与作品节点**。
- **策展数据主存与读取**：SQLite(`data/echo-graph.db`,已 gitignore)为唯一权威,公共星云与用户私有空间同库(`owner_id` 区分);公开接口(`/api/graph` 等)直接查 SQLite;`data/export/*.csv` 为公共星云写入时自动导出的确定性产物(git 跟踪,审计/回滚/跨机器传输),**只含公共数据,不含用户私有空间**。曾作为查询层的 Neo4j 与 JSON 兜底种子已退役。
- **后端**：FastAPI,接口见下方;路径查询为内存 BFS(有向,ECHO),扩散为无向 BFS,单核 VPS 上毫秒级。
- **AI 数据管线与审核**：书籍解析(`agent_temp/tools/extract_source_book.py`)→ 去重
  校验(`dedupe_check.py`,基础匹配 + 阿里云百炼 qwen3.7-text-embedding 语义辅助)→
  批次登记(`review_publish.py make-batch / ingest`)以 `created_by='llm'`、
  `reviewStatus='draft'` 写入 `system_llm` 机器账号私有空间(草稿区,外界不可见);
  admin 在管理端「AI 草稿」页逐条审核——批准(复制进公共星云)/ 复用(去重命中现有
  记录)/ 驳回 / 重开 / 编辑,批准后回写 `published_to_id` 防重复发布。
- **前端**：React 19 + Vite 5 + TypeScript(构建产物由 FastAPI 托管于 `frontend/dist`),Three.js(0.185,npm 依赖 + addons)。3D 渲染为**受控模式**:React store 持有 `viewData`/`currentView`/相机,`GraphCanvas` 的 effect 驱动渲染器执行绘制,渲染器退化为纯执行器(`update(kind, data)`,同视图增量同步);节点点击/悬停由 React 事件委托驱动。主视图为**球状星云**——作者为蓝白星、作品为金星(均带光晕并随机呼吸闪烁),`AUTHORED_BY` 归属关系为暗淡弱连线,ECHO 提及关系为青色发光星轨;支持右键旋转、左键平移、滚轮缩放、点击选星,并有 CSS 星空背景与流星点缀。

### 运行方式

```bash
uv sync               # 安装依赖(已在 pyproject.toml)
cd frontend && pnpm install && pnpm typecheck && pnpm build   # 构建 React 前端(产物进入 frontend/dist)
uv run python scripts/migrate_csv_to_sqlite.py   # 全新环境引导:从仓库 CSV 初始化 SQLite
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

SQLite 库缺失时执行 `scripts/migrate_csv_to_sqlite.py` 从 CSV 初始化(仅限全新环境;已有用户数据时
不要执行——它会整库重建策展表,清空用户星云)。

**Windows 本地环境提示**:若仓库/虚拟环境报"dubious ownership"或 `uv` 无法启动
`.venv` 里的 Python(常见于 Windows 账户变更),先执行
`git config --global --add safe.directory E:/Code/echo-graph` 放行仓库;随后备份并重建虚拟环境:
`Rename-Item .venv .venv-broken`(或直接删除后)`uv sync --frozen`。`.venv` 为可再生构建产物,
重建不影响 `data/echo-graph.db` 与 `data/export/*.csv`。

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
日常运维(备份/恢复/用户数据迁移)另见 [`docs/ops-manual.md`](docs/ops-manual.md)。

`deploy/` 目录提供开箱模板:

- `setup-vps.sh` — 一键初始化:装系统依赖、建应用用户、拉代码、由 uv 托管 Python 3.14、构建前端、配置 systemd + nginx + HTTPS
- `deploy.sh` — 日常更新:备份数据(含 SQLite)→ 拉代码 → 装依赖 → 构建前端 → 重启服务
  (SQLite 为权威库,不再从 CSV 重建;schema 迁移由服务启动时自动执行)
- `echo-graph.service` — systemd 单元模板
- `nginx.conf` — nginx 站点模板(手动部署用)

步骤:

1. 把仓库推到 git 远端,修改 `deploy/setup-vps.sh` 顶部的 `REPO_URL`。
2. VPS 上执行初始化(第二个参数是 certbot 邮箱,用于自动签发 HTTPS 证书):

   ```bash
   sudo bash deploy/setup-vps.sh litnebula.com <certbot邮箱>
   ```

3. 编辑 `/opt/echo-graph/.env`,填入 `ADMIN_BOOTSTRAP_EMAIL`(第一个管理员邮箱)等配置。
4. 启动并验证:

   ```bash
   sudo systemctl start echo-graph
   curl https://litnebula.com/api/health
   ```

5. 之后每次更新代码(`deploy.sh` 会自动备份数据(含 SQLite)、拉代码、装依赖、构建前端并重启):

   ```bash
   sudo -u echograph bash /opt/echo-graph/deploy/deploy.sh
   ```

注意事项:国内机房绑域名对外提供 80/443 服务需要 ICP 备案,不想备案可选香港/新加坡 VPS;
1核2G 即可运行(systemd 单 worker);`data/echo-graph.db` 是数据事实源(备份=用 `sqlite3 .backup`
或 deploy.sh 自动备份),`data/export/*.csv` 为导出产物配合 git 完成版本审计与跨机器传输。

> 数据管理视图对**所有登录用户**开放:作者/作品/涟漪三个 Tab 管理**自己的星云**
> (`/api/me/*`,仅本人可见);`ADMIN_BOOTSTRAP_EMAIL`(在 `.env` 配置)注册即自动获得
> admin 角色,其「自己的星云」就是公共星云,并可额外使用「日志 / 快照」
> 三个平台级 Tab(`/api/admin/*`)。`?admin` / `#v=admin` 深链需先登录。
> 公共星云写入自动导出 CSV;用户私有数据不进 git 审计产物。

### 账号体系(注册 / 登录)

多用户账号体系已落地:邮箱+密码注册;登录可用**邮箱或用户名**,Argon2 密码哈希,**httpOnly Cookie 会话**(30 天,登出立即失效),注册含 Cloudflare Turnstile 人机验证。
注册时填写**用户名**(必填,唯一,仅 5-32 位英文字母/数字/下划线,ASCII 大小写不敏感)与
  **昵称**(可选,展示用);公开展示名优先昵称、其次用户名,不再暴露邮箱。
  用户名是系统标识,**不在个人资料中展示、用户不可自行修改**。

- 接口:`POST /api/auth/register` / `POST /api/auth/login` / `POST /api/auth/logout` / `GET /api/auth/me` / `GET /api/auth/config`
- 资料接口:`PATCH /api/auth/me`(支持 `nickname` / `bio` / `space_visibility` 修改;用户名不可修改)
- 环境变量:`.env` 配置 `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY`(未配置时注册跳过人机验证,仅限本地开发);HTTPS 部署时设置 `COOKIE_SECURE=1`。
  注册报「人机验证失败」多为浏览器无法加载 challenges.cloudflare.com(部分地区网络受限)或验证超时——
  前端会提示组件加载失败并可重试;服务端 siteverify 仅对公网 IP 传 `remoteip`,避免本地回环地址导致校验失败
- 会话安全:token 只放在 httpOnly + SameSite=Lax Cookie 中,数据库仅存其 SHA-256 哈希,泄露 DB 也无法伪造会话;注册/登录与关注写接口按 IP 滑动窗口限流(共用 `app/ratelimit.py`);全局中间件(`app/main.py` 的 `csrf_same_origin_guard`,同源判定函数在 `app/security.py`)对所有状态变更请求(含 `/api/me`、`/api/admin`)做同源校验——带 Origin 头的跨站请求一律 403
- 用户空间:每个账号有独立的私有星云(`/api/me/*`,仅本人可见);登录后左侧栏
  「公共星云 / 我的星云」切换。公共星云 = 引导管理员认领的数据,未登录游客可浏览。
- 左侧功能栏采用 **Tab 列**(类 VS Code 侧边栏):展开后左侧窄条为「星云 / 我的 / 消息 /
  设置」四个 Tab:
  - **星云**:图谱操作(搜索/路径/扩散/过滤/点亮星空/数据管理);
  - **我的**:个人资料编辑(昵称/简介)+ 关注/粉丝列表(可点击跳转到对方星云);
  - **消息**:占位(第二阶段通知,暂未实现,见 `docs/multi-user-migration.md`);
  - **设置**:星云可见性(公开/仅自己可见)、退出登录(未登录时提供登录/注册)。
- 左右两侧栏右上角各有「📌 钉住」按钮:钉住后不再随移出/计时自动隐藏,
  状态记忆在 localStorage(桌面加载时自动恢复);移动端栏外点击收起同样尊重钉住。
- 右侧详情栏同样采用 **Tab 列**:「涟漪」(当前视图内容)/「书签」(所选作品的评分与评价)/
  「个人资料」(当前星云所有者的昵称与简介,owner 资料随图谱接口返回,不含邮箱)。
- 数据管理:侧边栏「数据管理」对所有登录用户显示,管理自己的作者/作品/涟漪;
  admin 额外拥有审计日志与快照恢复能力。
- 点亮星空(添加到我的星云):登录后打开,直接向自己的星云写入作者/作品/涟漪
  (作品/作者下拉列表来自你自己的星云数据,与数据管理页一致;
  搜不到时下拉框第一行可打开标准新增弹窗),数据直接进入本人星云。
- 星际跃迁:左侧栏「公共星云 / 我的星云」下方「✦ 星际跃迁」按钮,随机访问一个
  公开星云(排除自己与公共星云所有者);数据源标签显示所在星云账号,公共星云显示 public。
  接口:`GET /api/space/random/graph`(随机)、`GET /api/space/{user_id}/graph`(定向);
  跃迁后可继续在目标星云内完整交互(搜索 / 作品详情 / 扩散 / 路径),
  由 `GET /api/space/{user_id}/search|work/{id}|expansion/{id}|path` 提供,前端按空间上下文自动路由。
- 关注模型好友:单向关注(关注 TA 不要求 TA 关注你),仅登录用户可用,不可关注自己;
  目标用户不存在 / 已禁用返回 404(不暴露存在性);每用户每小时关注操作上限 50 次(取关不计入)。
  接口:`POST/DELETE /api/follow/{user_id}`(关注/取关,幂等)、`GET /api/follow/following|followers`
  (我的关注 / 粉丝列表)、`GET /api/follow/relation/{user_id}`(我与该用户的关系)。
  关注/粉丝列表展示在左侧栏「我的」Tab,点击条目可直接跃迁到对方星云。
- 用户数据语义:作者/作品/涟漪**新增即「已审核」**(输入即确认,含管理员手动新增;
  普通用户管理界面不显示审核状态,admin 显式传 `draft` 仍可保留草稿);
  作品另有个人阅读状态(已读/在读/未读)、评分(推荐/不推荐)与评价(长文本)字段;
  普通用户界面隐藏「备注」,admin 保持原样;阅读状态、评分与评价在右侧「书签」Tab 展示。
- 新增作者/作品时,原文名/原著标题输入框会联想**当前空间已有数据**
  (普通用户 = 自己的星云,admin = 公共星云,同等逻辑);选中已存在数据时提示
  「数据已存在,请勿重复新增」并**禁止保存**(命中本空间已有数据即拦截);
  涟漪与作品关联作者的选取同样基于当前空间已有数据。
- 点亮星空需登录使用(未登录点击会先弹出登录框),提交进入自己的星云。

**发布过滤与快照恢复**:在 `.env` 设置 `PUBLIC_REVIEWED_ONLY=1` 后,公开接口只返回 `reviewStatus=reviewed` 的内容(草稿/驳回不可见),默认关闭以便开发时看到全部数据;管理页新增「快照」Tab,可一键创建当前库快照(`backups/echo-graph-<时间>.db`),也可查看并恢复 `backups/`(SQLite 备份)下的快照(`data/versions/` 历史 CSV 目录仅在旧机器残留时可用)——恢复前会自动为当前库做安全备份,恢复成功后自动重新导出 CSV。


策展数据以 SQLite(`data/echo-graph.db`)为准,`data/export/*.csv` 为每次写入自动导出的确定性产物;授权后通过页面左侧「**数据管理**」入口编辑(表单校验、软删除/恢复、日志记录),字段说明见 `data/export/README.md`;保存前自动校验(类型、枚举、交叉引用、作者 id 关联、重复 id),保存后自动导出 CSV,公开接口即时读到新数据。

**软删除设计**:`deletedAt` 仅在 SQLite/CSV 数据层表达——被删除的行保留在库中与 CSV 存档(`deletedAt` 非空),但读取层一律过滤,图上只出现活跃数据。删除作品时,与其相关的涟漪边会一并软删除;删除作者时,其名下作品及相关涟漪边会一并软删除;恢复时,同一删除动作删掉的作品/涟漪(相同 `deletedAt`)会一并恢复。

浏览器打开 <http://127.0.0.1:8000/>。

### 视图与深链

| 视图 | 说明 | 深链示例 |
|---|---|---|
| 主图谱 | 全量球状星云 | `http://127.0.0.1:8000/#v=main` |
| 提及链 | 两作品间的 3D 提及路径(螺旋排列) | `http://127.0.0.1:8000/#v=path:{fromWorkId},{toWorkId}` |
| 涟漪 | 以某作品为中心的 3D 扩散球(N 级扩散) | `http://127.0.0.1:8000/#v=ripple:{workId}:2` |
| 作者 | 该作者与全部作品 | `http://127.0.0.1:8000/#v=author:{authorId}` |

URL 参数:`v=`(视图)、`islands=1`(隐藏孤岛星)、`authors=0`(隐藏作者节点)、
`space=public|mine|<用户id>`(当前星云,刷新/分享后保持;他人星云按可见性访问,
未登录访问 `mine` 或 private/无效星云时自动回退公共星云)、
`cam=theta,phi,radius,cx,cy,cz`(相机位置,旧版分享链接格式,仍兼容解析)。旧格式 `#path=` / `#ripple=` / `#author=` 已在 React 迁移后移除,统一使用 `#v=` 格式,标识均为 UUID。

### API

| 接口 | 说明 |
|---|---|
| `GET /api/graph?status=` | 全量图谱(节点 + 边);`status` 可选 `draft` / `reviewed` / `rejected`,按审核状态过滤 |
| `GET /api/search?q=` | 搜索作家 / 作品 |
| `GET /api/work/{id}` | 作品详情 + 谁提及它 / 它提及谁(涟漪数据) |
| `GET /api/path?from={workId}&to={workId}` | 有向最短提及链 |
| `GET /api/expansion/{workId}?hops=N` | N 级涟漪扩散子图 |
| `GET /api/stats` | 数据统计(含 `reviewStatus` 分布) |

