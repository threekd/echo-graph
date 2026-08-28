> 本文为项目产品与技术总览(根目录 README.md 的详细版):架构、运行方式、部署、
> 账号体系与接口说明。数据结构见 data_schema.md,运维见 ops-manual.md,
> 需求进度见 to-do.md。


> 产品名 **Litnebula**;代码/仓库/部署标识沿用 `echo-graph`(工程标识与产品名分离,
> 避免牵动仓库、CI、systemd 服务名等既有设施)。

---


## 当前实现状态

已按实施路线搭建出可运行的 MVP 骨架：

- **数据模型**：按 `data_schema.md`(schemaVersion 1.8)实现——`Author` / `Work` 节点及属性(`id` 为 UUID,新增自动生成 UUID v7,URL 直接使用 UUID);结构关系 `(Work)-[:AUTHORED_BY]->(Author)`(N:N,允许合著,物理实现为 `work_authors`);回声关系 `(Work)-[:ECHO]->(Work)`(A 提及 B),属性含 `id`(UUID,新增自动生成)、`evidence` / `evidenceSource`、`note`、`reviewStatus` 与时间戳。图谱中**同时显示作者与作品节点**。
- **策展数据主存与读取**：SQLite(`data/echo-graph.db`,已 gitignore)为唯一权威,所有星云同库(`owner_id` 区分)。**公共星云/官方图谱概念已移除(2026-08-28)**:不存在默认视图,admin 的星云与其他用户星云在数据语义上完全一致;登录用户首页即自己的星云(`/api/me/*`),游客默认空图 + 登录提示,可通过星际跃迁浏览其他用户的公开星云(`/api/space/*`);若配置 `LANDING_SPACE`(用户名),游客打开首页自动进入该展示星云。**备份以整库快照为准**(`backups/` 下 `sqlite3 .backup` 产物 + 管理端快照恢复,见 `ops-manual.md`);曾作为备份/传输通道的 `data/export/*.csv` 自动导出层已于 2026-08-27 移除(多设备/调试导致漂移)。曾作为查询层的 Neo4j 与 JSON 兜底种子已退役。
- **后端**：FastAPI,接口见下方;路径查询为内存 BFS(有向,ECHO),扩散为无向 BFS,单核 VPS 上毫秒级。
- **AI 数据管线与审核**：书籍解析(`app/ai_assistant/tools/extract_source_book.py`,
  书内书名提及**仅取正文**,涟漪出处标注为 前言/正文/尾记/其它 四类;提示词统一
  维护在 `app/ai_assistant/prompts.py`)→ 去重校验(`dedupe_check.py`,基础匹配 +
  阿里云百炼 qwen3.7-text-embedding 语义辅助 + DeepSeek 兜底确认)→ 批次登记
  (`review_publish.py build_batch / stage_batch`)以 `owner_id=上传者`、
  `created_by='llm'`、`reviewStatus='draft'` 写入草稿区(已不再使用共享
  `system_llm` 机器账号,历史草稿由 `migrate_legacy_llm_drafts()` 一次性迁移);
  上传者(admin 或 VIP)在管理端「AI 草稿」页只看到/审核自己上传的草稿,逐条
  审核——批准(复制进**自己的星云**)/ 复用(去重
  命中自己星云中的现有记录)/ 驳回 / 重开 / 编辑,批准后回写 `published_to_id`
  防重复发布;多 admin 各自独立、互不审核。
- **前端**：React 19 + Vite 5 + TypeScript(构建产物由 FastAPI 托管于 `frontend/dist`),Three.js(0.185,npm 依赖 + addons)。3D 渲染为**受控模式**:React store 持有 `viewData`/`currentView`/相机,`GraphCanvas` 的 effect 驱动渲染器执行绘制,渲染器退化为纯执行器(`update(kind, data)`,同视图增量同步);节点点击/悬停由 React 事件委托驱动。主视图为**球状星云**——作者为蓝白星、作品为金星(均带光晕并随机呼吸闪烁),`AUTHORED_BY` 归属关系为暗淡弱连线,ECHO 提及关系为青色发光星轨;支持右键旋转、左键平移、滚轮缩放、点击选星,并有 CSS 星空背景与流星点缀。

### 运行方式

```bash
uv sync               # 安装依赖(已在 pyproject.toml)
cd frontend && pnpm install && pnpm typecheck && pnpm build   # 构建 React 前端(产物进入 frontend/dist)
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

SQLite 库缺失时服务启动会自动创建并迁移 schema(空库);全新环境的**数据**需从
整库备份恢复(`backups/echo-graph-*.db`,管理端「快照」恢复或直接替换库文件,
见 `ops-manual.md` 与 `to-do.md` 的整库备份待办)。

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
上线前清单、运维手册与常见问题见 [`../deploy/DEPLOY.md`](../deploy/DEPLOY.md)。
日常运维(备份/恢复/用户数据迁移)另见 [`ops-manual.md`](ops-manual.md)。

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
或 deploy.sh 自动备份,异地备份方案见 `to-do.md` 待办)。

> 星云工坊对**所有登录用户**开放:作者/作品/涟漪三个 Tab 管理**自己的星云**
> (`/api/me/*`,仅本人可见);`ADMIN_BOOTSTRAP_EMAIL`(在 `.env` 配置)注册(开启邮箱
> 验证时须验证通过)即自动获得 admin 角色,其「自己的星云」即其个人星云,并可额外使用「日志 / 快照 / 用户」
> 平台级 Tab(`/api/admin/*`)。`?admin` / `#v=admin` 深链需先登录。
> 所有登录用户可在星云工坊页导出自己星云的三张表为 CSV zip(「导出 CSV」按钮)。

### 账号体系(注册 / 登录)

多用户账号体系已落地:邮箱+密码注册;登录可用**邮箱或用户名**,Argon2 密码哈希,**httpOnly Cookie 会话**(30 天,登出立即失效),注册含 Cloudflare Turnstile 人机验证。
注册时填写**用户名**(必填,唯一,仅 5-32 位英文字母/数字/下划线,ASCII 大小写不敏感)与
  **昵称**(可选,展示用);公开展示名优先昵称、其次用户名,不再暴露邮箱。
  用户名是系统标识,**不在个人资料中展示、用户不可自行修改**。

- 接口:`POST /api/auth/register` / `POST /api/auth/login` / `POST /api/auth/logout` /
  `GET /api/auth/me` / `GET /api/auth/config` / `POST /api/auth/verify-email` /
  `POST /api/auth/resend-verification` / `POST /api/auth/forgot-password` /
  `POST /api/auth/reset-password`
- 资料接口:`PATCH /api/auth/me`(支持 `nickname` / `bio` / `space_visibility` 修改;用户名不可修改)
- 邮箱验证与密码找回:`.env` 配置 `MAILER=api`(阿里云邮件推送 DirectMail,见
  `deploy/DEPLOY.md` 0.5 节)或 `MAILER=smtp` 后,`EMAIL_VERIFY_REQUIRED=1` 时新注册
  用户需点击邮件验证链接才能登录(登录弹窗可重发);登录页「忘记密码?」通过邮件
  深链 `#v=reset:TOKEN` 重置密码,重置后自动吊销该用户全部会话。引导管理员在邮箱
  验证通过后才获得 admin 角色(未开启验证时保持注册即提权);`EMAIL_VERIFY_REQUIRED=0`
  时新注册用户以 `createdAt` 标记为已信任(注册即登录,与存量用户回填策略一致)。
- 环境变量:`.env` 配置 `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY`
  (未配置密钥时注册默认失败 fail-closed,仅本地开发可设
  `TURNSTILE_ALLOW_SKIP=1` 临时跳过);HTTPS 部署时设置 `COOKIE_SECURE=1`
  (未设置时启动会告警)。
  注册报「人机验证失败」多为浏览器无法加载 challenges.cloudflare.com(部分地区网络受限)或验证超时——
  前端会提示组件加载失败并可重试;服务端 siteverify 仅对公网 IP 传 `remoteip`,避免本地回环地址导致校验失败
- 会话安全:token 只放在 httpOnly + SameSite=Lax Cookie 中,数据库仅存其 SHA-256 哈希,泄露 DB 也无法伪造会话;注册/登录与关注写接口按 IP 滑动窗口限流(共用 `app/ratelimit.py`);全局中间件(`app/main.py` 的 `csrf_same_origin_guard`,同源判定函数在 `app/security.py`)对所有状态变更请求(含 `/api/me`、`/api/admin`)做同源校验——带 Origin 头的跨站请求一律 403
- 用户空间:每个账号有独立的私有星云(`/api/me/*`,仅本人可见);登录后首页即
  「我的星云」。公共星云/官方图谱概念已移除(2026-08-28):不存在默认视图,
  未登录游客默认看到空图与登录提示,可通过星际跃迁浏览公开星云;若配置
  `LANDING_SPACE`(用户名,见 `.env.example`),游客打开首页自动进入该展示星云
  (用户名仅服务端配置,不出现在 URL/界面)。
- 左侧功能栏采用 **Tab 列**(类 VS Code 侧边栏):展开后左侧窄条为「星云 / 我的 / 消息 /
  设置」四个 Tab:
  - **星云**:图谱操作(搜索/路径/扩散/过滤/点亮星空/星云工坊/用户管理/运维管理;
    admin 才有「用户管理」「运维管理」入口,与星云工坊同款按钮样式);
  - **我的**:个人资料编辑(昵称/简介)+ 关注/粉丝列表(可点击跳转到对方星云);
  - **消息**:占位(第二阶段通知,暂未实现,见 `migration/multi-user-migration.md`);
  - **设置**:星云可见性(公开/仅自己可见)、退出登录(未登录时提供登录/注册)。
- 左右两侧栏右上角各有「📌 钉住」按钮:钉住后不再随移出/计时自动隐藏,
  状态记忆在 localStorage(桌面加载时自动恢复);移动端栏外点击收起同样尊重钉住。
- 右侧详情栏同样采用 **Tab 列**:「涟漪」(当前视图内容)/「书签」(所选作品的评分与评价)。
- 星云所有者资料为**书友卡片**(星际跃迁后右上角常驻悬浮卡片,owner 资料随图谱接口返回,
  不含邮箱):展示昵称/简介与关注按钮;展开 10 秒无鼠标停留后自动向上收起为右上角
  小房子图标,点击图标重新展开;打开右侧详情栏时卡片自动淡出。
- 星云工坊:侧边栏「星云工坊」对所有登录用户显示,管理自己的作者/作品/涟漪;
  admin 的侧边栏另有「用户管理」入口(仅 admin 可见,位于星云工坊下方,样式与
  星云工坊一致),点击打开**独立用户管理窗口**(不并入星云工坊窗口),支持
  禁用/启用、角色、星云可见性、VIP 维护;
  admin 额外拥有审计日志与快照恢复能力。
- 点亮星空(添加到我的星云):登录后打开,直接向自己的星云写入作者/作品/涟漪
  (作品/作者下拉列表来自你自己的星云数据,与星云工坊页一致;
  搜不到时下拉框第一行可打开标准新增弹窗),数据直接进入本人星云。
- 星际跃迁:左侧栏「我的星云」下方「✦ 星际跃迁」按钮,随机访问一个公开星云
  (排除自己,避免跃迁到自己的星云);数据源标签显示所在星云账号。
  接口:`GET /api/space/random/graph`(随机)、`GET /api/space/{user_id}/graph`(定向);
  跃迁后可继续在目标星云内完整交互(搜索 / 作品详情 / 扩散 / 路径),
  由 `GET /api/space/{user_id}/search|work/{id}|expansion/{id}|path` 提供,前端按空间上下文自动路由。
- 关注模型好友:单向关注(关注 TA 不要求 TA 关注你),仅登录用户可用,不可关注自己;
  目标用户不存在 / 已禁用返回 404(不暴露存在性);每用户每小时关注操作上限 50 次(取关不计入)。
  接口:`POST/DELETE /api/follow/{user_id}`(关注/取关,幂等)、`GET /api/follow/following|followers`
  (我的关注 / 粉丝列表)、`GET /api/follow/relation/{user_id}`(我与该用户的关系)。
  关注/粉丝列表展示在左侧栏「我的」Tab,点击条目可直接跃迁到对方星云。
- 用户数据语义:作者/作品/涟漪**手工新增/编辑即「已审核」**(输入即确认,所有用户一致,
  admin 不做特殊化):经 `/api/me/*`、`/api/admin/*` 手工写入的作者/作品/涟漪一律强制
  `reviewStatus='reviewed'`,显式传 `draft`/`rejected` 会被回正,不允许制造"草稿"行;
  审核状态仅对 AI 提取草稿(`created_by='llm'`、默认 `draft`)有意义,草稿只在「AI 草稿」
  页出现,需审核后发布;溯源列 `created_by` 由服务端按 owner 推导(admin=curated,其他=user),
  API 不允许显式传 `llm`(仅 AI 管线内部使用),创建后不可修改;
  作品另有个人阅读状态(已读/在读/未读)、评分(推荐/不推荐)与评价(长文本)字段;
  普通用户界面隐藏「备注」,admin 保持原样;阅读状态、评分与评价在右侧「书签」Tab 展示。
- 新增作者/作品时,原文名/原著标题输入框会联想**当前空间已有数据**
  (普通用户与 admin 均为自己的星云,同等逻辑);选中已存在数据时提示
  「数据已存在,请勿重复新增」并**禁止保存**(命中本空间已有数据即拦截);
  涟漪与作品关联作者的选取同样基于当前空间已有数据。
- 点亮星空需登录使用(未登录点击会先弹出登录框),提交进入自己的星云。

**发布过滤与快照恢复**:`PUBLIC_REVIEWED_ONLY` 全局开关已随公共星云/官方图谱概念
移除(2026-08-28)——每个用户在自己的星云里看到自己的全部内容,草稿/驳回的
用户级显示设置见 `docs/to-do.md` 待办;运维管理窗口「快照」Tab(2026-08-26 起自
自原「数据管理」窗口迁入)可一键创建当前库快照(`backups/echo-graph-<时间>.db`),也可查看并
恢复 `backups/`(SQLite 备份)下的快照——恢复前会自动为当前库做安全备份
(CSV 类型历史快照已随 CSV 备份层于 2026-08-27 移除)。


策展数据以 SQLite(`data/echo-graph.db`)为准;授权后通过页面左侧「**星云工坊**」入口编辑
(表单校验、软删除/恢复、日志记录),保存前自动校验(类型、枚举、交叉引用、作者 id 关联、
重复 id),保存后本人图谱/公开星云接口即时读到新数据;「导出 CSV」按钮可把当前星云的三张表
(作者/作品/涟漪)打包下载(zip),所有登录用户可用。

**软删除设计**:`deletedAt` 在数据层表达——被删除的行保留在库中(`deletedAt` 非空,用户导出 CSV 亦含该列),但读取层一律过滤,图上只出现活跃数据。删除作品时,与其相关的涟漪边会一并软删除;删除作者时,其名下作品及相关涟漪边会一并软删除;恢复时,同一删除动作删掉的作品/涟漪(相同 `deletedAt`)会一并恢复。

浏览器打开 <http://127.0.0.1:8000/>。

### 视图与深链

| 视图 | 说明 | 深链示例 |
|---|---|---|
| 主图谱 | 全量球状星云 | `http://127.0.0.1:8000/#v=main` |
| 提及链 | 两作品间的 3D 提及路径(螺旋排列) | `http://127.0.0.1:8000/#v=path:{fromWorkId},{toWorkId}` |
| 涟漪 | 以某作品为中心的 3D 扩散球(N 级扩散) | `http://127.0.0.1:8000/#v=ripple:{workId}:2` |
| 作者 | 该作者与全部作品 | `http://127.0.0.1:8000/#v=author:{authorId}` |

URL 参数:`v=`(视图)、`islands=1`(隐藏孤岛星)、`authors=0`(隐藏作者节点)、
`space=mine|<用户id>`(当前星云,刷新/分享后保持;他人星云按可见性访问,
未登录访问 `mine` 或 private/无效星云时提示登录并回到「我的星云」(空图);
旧版 `space=public` 参数已废弃,不再识别)、
`cam=theta,phi,radius,cx,cy,cz`(相机位置,旧版分享链接格式,仍兼容解析)。旧格式 `#path=` / `#ripple=` / `#author=` 已在 React 迁移后移除,统一使用 `#v=` 格式,标识均为 UUID。

### API

| 接口 | 说明 |
|---|---|
| `GET /api/me/graph?status=` | 我的星云全量图谱(需登录);`status` 可选 `draft` / `reviewed` / `rejected`,按审核状态过滤 |
| `GET /api/me/search?q=` | 在我的星云中搜索作家 / 作品 |
| `GET /api/me/work/{id}` | 作品详情 + 谁提及它 / 它提及谁(涟漪数据) |
| `GET /api/me/path?from={workId}&to={workId}` | 有向最短提及链 |
| `GET /api/me/expansion/{workId}?hops=N` | N 级涟漪扩散子图 |
| `GET /api/me/stats` | 我的星云数据统计(含 `reviewStatus` 分布) |
| `GET /api/space/{user_id}/graph\|search\|work/{id}\|expansion/{id}\|path\|stats` | 星际跃迁目标星云的同一套只读接口(按可见性访问) |

> 公共 `/api/graph`、`/api/search` 等「默认视图」端点已随公共星云/官方图谱概念移除
> (2026-08-28),不再注册;游客无默认图谱,登录后使用 `/api/me/*`,浏览他人公开
> 星云使用 `/api/space/*`。

