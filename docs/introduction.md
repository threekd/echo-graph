# 产品与技术总览

> 本文为根目录 README 的详细版:架构、运行方式、部署、账号体系与接口说明。
> 数据结构见 `data_schema.md`,运维见 `ops-manual.md`,需求进度见 `to-do.md`,
> 权限矩阵见 `permissions.md`,界面设计见 `ui.md`。
>
> 产品名 **Litnebula**;代码/仓库/部署标识沿用 `echo-graph`(工程标识与产品名分离)。

## 当前实现状态

**数据模型**(`docs/data_schema.md`,schemaVersion 1.8):
`Author` / `Work` 节点(id 为 UUID v7),`(Work)-[:AUTHORED_BY]->(Author)`(N:N,
物理实现 `work_authors`),`(Work)-[:ECHO]->(Work)` 提及关系(`edges`,含 evidence /
evidenceSource / note / reviewStatus)。图谱同时显示作者与作品节点。

**存储与读取**:SQLite(`data/echo-graph.db`)是唯一权威,所有星云同库以 `owner_id`
区分。**不存在默认视图/公共星云**:登录用户首页即自己的星云(`/api/me/*`),
游客默认空图 + 登录提示,可经星际跃迁浏览公开星云(`/api/space/*`);
配置 `LANDING_SPACE`(用户名)时游客打开首页自动进入该展示星云。
备份以**整库快照**为准(`backups/*.db`,`sqlite3 .backup` + 管理端恢复)。
曾作为备份层的 `data/export/*.csv` 自动导出与 Neo4j 查询层均已退役
(演进见 `docs/migration/`)。路径查询为内存 BFS(有向 ECHO),扩散为无向 BFS,
单核 VPS 毫秒级。

**后端**:FastAPI;只读六件套(`graph / search / work / expansion / path / stats`)
由 `app/read_routes.py` 工厂同时注册到 `/api/me` 与 `/api/space/{user_id}`。
行级 CRUD(`app/space_crud.py`)带 Pydantic 校验、SQL 交叉引用、乐观并发
(`updatedAt` 守卫 409)、软删除/恢复、审计;手工新增/编辑一律强制 `reviewed`
(输入即确认,所有用户一致),`created_by` 溯源列创建后不可修改。

**AI 数据管线与审核**:书籍解析(`app/ai_assistant/tools/extract_source_book.py`,
涟漪只取正文,提示词统一在 `app/ai_assistant/prompts.py`)→ 去重校验
(基础匹配 + 语义嵌入 + LLM 兜底确认,`dedupe_check.py`)→ 批次登记
(`review_publish.py`)以 `owner_id=上传者`、`created_by='llm'`、`reviewStatus='draft'`
写入草稿区。上传者(admin 或 VIP)在管理端「AI 草稿」页只看到/审核**自己上传**的草稿,
批准即发布进自己的星云,`published_to_id` 防重复发布;多 admin 各自独立、互不审核。

**前端**:React 19 + Vite 5 + TypeScript(构建产物由 FastAPI 托管于 `frontend/dist`),
Three.js 3D 渲染为**受控模式**:React store 持有 `viewData`/`currentView`/相机,
`GraphCanvas` 的 effect 驱动渲染器执行绘制,渲染器退化为纯执行器;节点点击/悬停
由 React 事件委托驱动。主视图为球状星云——作者蓝白星、作品金星(带光晕呼吸闪烁),
`AUTHORED_BY` 为暗淡弱连线,ECHO 为青色发光星轨;右键旋转、左键平移、滚轮缩放、
点击选星,并有 CSS 星空背景与流星点缀。

## 运行方式

```bash
uv sync               # 安装依赖
cd frontend && pnpm install && pnpm typecheck && pnpm build
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

SQLite 库缺失时服务启动自动建 schema(空库);全新环境的数据从整库备份恢复
(见 `ops-manual.md` 3.3)。质量检查(CI 中自动执行):

```bash
uv run python -m unittest discover -s tests -v   # 后端测试
uvx ruff check .                                  # 后端 lint
cd frontend && pnpm lint && pnpm typecheck && pnpm test   # 前端
```

前端开发模式:`cd frontend && pnpm dev`(Vite 5173,`/api` 代理到 8000)。

## 部署到 VPS(Ubuntu)

架构:`nginx(80/443) → uvicorn(127.0.0.1:8000) → SQLite(本地文件)`,
前端构建产物由 nginx 托管。`deploy/` 提供开箱模板(`setup-vps.sh` 一键初始化、
`deploy.sh` 日常更新自动备份+构建+重启、systemd + nginx + HTTPS),
完整上线清单见 [`../deploy/DEPLOY.md`](../deploy/DEPLOY.md)。

1. 仓库推送到 git 远端,改 `deploy/setup-vps.sh` 顶部 `REPO_URL`;
2. `sudo bash deploy/setup-vps.sh litnebula.com <certbot邮箱>`;
3. 编辑 `/opt/echo-graph/.env`(`ADMIN_BOOTSTRAP_EMAIL` 等,模板见 `.env.example`);
4. `sudo systemctl start echo-graph` 并 `curl https://<域名>/api/health` 验证;
5. 之后每次更新执行 `sudo -u echograph bash /opt/echo-graph/deploy/deploy.sh`。

注意:国内机房对外提供 80/443 需 ICP 备案;1核2G 即可运行(systemd 单 worker);
`data/echo-graph.db` 是数据事实源,异地备份方案见 `to-do.md` 遗留 7。

## 账号体系

- **注册/登录**:邮箱+密码,Argon2 哈希,httpOnly Cookie 会话(30 天,登出立即失效);
  注册含 Cloudflare Turnstile 人机验证(fail-closed);用户名必填
  (仅 5-32 位英文字母/数字/下划线,ASCII 大小写不敏感唯一,**不可自行修改**),
  昵称可选;公开展示名优先昵称、其次用户名,不暴露邮箱。
- **接口**:`/api/auth/register|login|logout|me|config|verify-email|
  resend-verification|forgot-password|reset-password`;资料 `PATCH /api/auth/me`
  (`nickname` / `bio` / `space_visibility`)。
- **邮箱验证与密码找回**:`MAILER=api`(阿里云 DirectMail)或 `MAILER=smtp`;
  `EMAIL_VERIFY_REQUIRED=1` 时新注册需验证邮箱才能登录;引导管理员在**验证通过后**
  才提权 admin(防抢先注册提权);重置密码后自动吊销该用户全部会话;
  一次性令牌(verify/reset,24h)只存 SHA-256 哈希,邮件深链 `#v=verify:TOKEN` /
  `#v=reset:TOKEN`,用后立即从 URL 清除。
- **安全**:token 只放 httpOnly + SameSite=Lax Cookie,DB 仅存哈希;注册/登录/
  关注写接口按 IP 滑动窗口限流(`app/ratelimit.py`,`TRUSTED_PROXIES` 白名单);
  全局中间件对所有状态变更请求做 CSRF 同源校验;API 响应统一
  `Cache-Control: no-store`;静态资源拒绝路径穿越。
- **用户空间**:每个账号独立私有星云(`/api/me/*`);关注模型好友(单向关注,
  `/api/follow/*`,不可关注自己,目标不存在/已禁用 404);「消息」Tab 为占位。
- **星云工坊**:所有登录用户管理自己的作者/作品/涟漪(表单校验、软删除/恢复、
  审计、重复拦截、按 id 关联作者);「导出 CSV」把三张表打包 zip
  (`GET /api/me/export`)。admin 另有用户管理 / 运维管理(审计/快照)入口,
  admin/VIP 另有 AI 草稿审核。
- **星际跃迁**:左侧栏「✦ 星际跃迁」随机访问公开星云(`/api/space/random/graph`,
  排除自己);定向访问 `/api/space/{user_id}/*`;private 星云仅本人与 admin 可见
  (404 不暴露存在性);星云所有者资料为书友卡片(昵称/简介/关注,不含邮箱)。

## 视图与深链

| 视图 | 说明 | 深链示例 |
|---|---|---|
| 主图谱 | 全量球状星云 | `#v=main` |
| 提及链 | 两作品间的 3D 提及路径(螺旋排列) | `#v=path:{fromWorkId},{toWorkId}` |
| 涟漪 | 以某作品为中心的 3D 扩散球(N 级扩散) | `#v=ripple:{workId}:2` |
| 作者 | 该作者与全部作品 | `#v=author:{authorId}` |

URL 参数:`v=`(视图)、`islands=1`(隐藏孤岛星)、`authors=0`(隐藏作者节点)、
`space=mine|<用户id>`(星云上下文;旧版 `space=public` 已废弃)、
`cam=theta,phi,radius,cx,cy,cz`(旧版相机格式,仍兼容解析)。旧格式
`#path=` / `#ripple=` / `#author=` 已移除,统一 `#v=`;标识均为 UUID。

## API 摘要

| 接口 | 说明 |
|---|---|
| `GET /api/me/graph?status=` | 我的星云全量图谱(需登录);`status` 可选 `draft`/`reviewed`/`rejected` |
| `GET /api/me/search?q=` | 在我的星云中搜索作者 / 作品 |
| `GET /api/me/work/{id}` | 作品详情 + 谁提及它 / 它提及谁(涟漪数据) |
| `GET /api/me/path?from=&to=` | 有向最短提及链 |
| `GET /api/me/expansion/{workId}?hops=N` | N 级涟漪扩散子图 |
| `GET /api/me/stats` | 我的星云数据统计(含 `reviewStatus` 分布) |
| `GET /api/me/data` · 行级 CRUD · `/export` | 星云工坊:管理表格 + 增删改/软删除恢复/永久删除 + CSV zip 导出 |
| `GET /api/space/{user_id}/graph\|search\|work/{id}\|expansion/{id}\|path\|stats` | 星际跃迁目标星云同一套只读接口(按可见性) |
| `GET /api/space/random/graph` · `by-username/{username}/graph` | 随机跃迁 / 游客落地星云 |
| `/api/auth/*`、`/api/follow/*`、`/api/admin/*` | 账号 / 关注 / 平台级管理(见 permissions.md) |

> 公共 `/api/graph`、`/api/search` 等默认视图端点已随公共星云概念移除(2026-08-28),
> 不再注册。
