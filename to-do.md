# Echo Graph · 需求与进度清单

> 整理自项目启动以来的全部需求,按模块分类。
> 状态:✅ 已完成 · 🟡 部分完成 · ⬜ 待办
>
> 本文为历史需求与进度日志;早期条目(Neo4j 查询层、原生 JS、CSV 事实源时代)已过时,仅作记录,当前架构以 README.md 与 docs/sqlite-migration.md 第 11 节为准。

## 1. 数据与模型

- [x] 评估 readme.md 方案可行性并输出结论(技术栈可行,主要风险在数据策展)
- [x] 数据模型按 `data_schema.md`(schemaVersion 1.1)规范:`Author` / `Work` 节点及属性
  - Work:`id`、`language`(ISO 639-1)、`originalTitle`、`Title_CN`、`Title_EN`、`publicationYear`、`creationYear`、时间戳
  - 补充:`genre`(体裁)、可选 `deletedAt`;`id` 为 UUID(新增自动生成 UUID v7),URL 直接使用 UUID
- [x] 结构关系 `(Work)-[:AUTHORED_BY]->(Author)`,基数 1:N(允许合著)
- [x] 回声关系 `(Work)-[:ECHO]->(Work)`:A 在书中提及 B 即建立 A→B;属性含 `evidence`、`evidenceSource`(出处/章节/译本)、`note`、`reviewStatus` 与时间戳
- [x] 涟漪关系(边)增加 `id`(UUID v7):`edges.csv` 新增 `id` 列并回填存量 3 条;管理页新增/编辑/删除按 `id` 定位,与作者/作品一致
- [x] 作者/作品增加 `reviewStatus` 审核状态(默认 `draft`),管理页作者/作品表格列由「删除时间」改为「审核状态」,编辑表单同步支持
- [x] 图谱隐藏佚名(Anonymous)作者节点:每部佚名作品独立显示,不再经共享的"佚名"星连成中枢(数据层不变,搜索/详情保留)
- [x] 真实数据接入:`authors.csv` / `works.csv` / `edges.csv` 三份 CSV 为数据源,已全量导入 Neo4j;
- [x] 提供新增/修改数据的标准流程(CSV → `import_data.py` 或数据管理页)
- [x] 修复导入缺陷:`SET = $props` 覆盖 `id` 导致节点重复,改为 `SET += $props`;采用显式事务
- ⬜ 扩充数据量与出处精确性(需人工策展)

## 2. 后端 / API

- [x] FastAPI 接口:
  - `GET /api/graph` 全量图谱
  - `GET /api/search?q=` 搜索作者/作品
  - `GET /api/work/{id}` 作品详情(谁提及它 / 它提及谁)
  - `GET /api/path?from=&to=` 有向最短提及链
  - `GET /api/expansion/{workId}?hops=N` N 级扩散子图
  - `GET /api/stats` 数据统计
- [x] Neo4j Aura 数据导入与约束(index)
- [x] 导入管线重构:`data/export/*.csv`(原 `data/real`)为数据源;Pydantic 校验(类型/枚举/交叉引用/作者匹配/重复 id),校验失败不导入;UNWIND 批量幂等 MERGE + SET +=,默认不删数据;软删除(`deletedAt`);`--wipe` / `--version` 参数;导入后导出 JSON 快照
- [x] 数据管理页(长期方案):左侧栏「数据管理」入口;作者/作品/提及三 Tab 表格 + 搜索筛选;表单弹窗(枚举下拉、作者/作品选择器);保存前全量校验、失败不落盘;软删除与恢复;导入 Neo4j 已随查询层退役(Phase 4);导出 JSON/CSV 已移除(备份由自动 CSV 导出 + git 承担);保存快照已在 P3d 移除(`data/versions/` 为历史遗留)
- [x] React 版数据管理页补齐:搜索筛选、新增/编辑表单(作品选择器/枚举下拉/必填校验)、软删除与恢复(「上传↑」导入与保存快照已随 Phase 4/P3d 移除)
- [x] 软删除同步 Neo4j:导入时从图谱物理移除 `deletedAt` 非空的行;`deletedAt` 仅在 CSV 层表达,Neo4j 节点/关系不写入该属性,查询层无需(也不应)按它过滤(避免触发"property key does not exist"通知)
- [x] 真实数据接入:`data/export/*.csv`(原 `data/real`)已全量导入 Neo4j;对齐 schema 1.1(Work 含 `Title_Other`、genre 枚举);id 为 UUID(新增自动生成 UUID v7,URL 直接用 UUID,slug 已移除);Echo 默认 draft
- [x] Neo4j 连接失败/空闲断开时自动回退 JSON 数据(`ResilientStore`;未内置数据集时为空图)
- [x] 扩散子图:沿 ECHO 无向扩展 N 级,返回节点/边/中心作品
- [x] 涟漪视图:未勾选「隐藏孤岛星」时,展示视图中已出现作者名下的全部作品,额外作品围绕作者形成隐约星云(更小更暗、悬停显示标签);勾选后仅保留涟漪节点(即时重渲染,保持相机)
- [x] 安全修复:静态资源接口拒绝路径穿越(`..` / 绝对路径 / 越界解析),含回归测试
- [x] lint 门禁恢复通过:ruff 0 errors(import 排序、`X | None` 风格、B904/B008 处理、未用变量清理)
- [x] 审核状态落地:模型默认 `draft`;`GET /api/graph?status=` 按审核状态过滤;`/api/stats` 输出 `reviewStatus` 分布
- [x] 时间戳语义:管理 API 新增/编辑维护 `createdAt`/`updatedAt`;导入不再全量刷新 `updatedAt`(仅新增时写入)
- [x] 数据一致性:涟漪边对唯一性校验下沉到 `parse_rows`;Neo4j 详情页提及列表改用 OPTIONAL MATCH,与 JSON 兜底输出对齐;快照保留最近 20 份
- [x] 贡献数据收件箱:SQLite 存储(并入主库 `data/echo-graph.db` 的 `contributions` 表);公开接口 `POST /api/contribute/echo`(无需令牌,基础 IP 限流,长度/清洗校验);管理接口 `/api/admin/contributions` 列表 + 通过/驳回
- [x] 前端「贡献数据」入口(左侧栏底部,「数据管理」上方):源/目标作品与作者为组合框(可选已有数据或自由填写,均必填)+ 原文片段/出处(必填)+ 备注/联系方式(选填),提交进待审核队列,不进入正式数据
- [x] 管理页「贡献」Tab:按状态列出提交,支持通过/驳回
- ⬜ 贡献数据后续:AI 校正、审核通过后自动录入策展 CSV、验证码/持久化限流、按联系方式跟进用户
- [x] 账号体系(多用户第一步):users/sessions 表(Argon2 密码哈希 + httpOnly Cookie 会话,
      DB 只存 token 的 SHA-256 哈希);`/api/auth/register|login|logout|me|config`;
      注册 Cloudflare Turnstile 人机验证;注册/登录 IP 滑动窗口限流
      (限流抽为 app/ratelimit.py,与贡献接口共用);带 Origin 头的跨站状态请求拒绝
- ⬜ 账号体系后续:密码重置/邮箱验证、OIDC 社交登录、用户空间数据隔离、
      管理权限从 ADMIN_TOKEN 迁移为 user/admin 角色
- [x] 用户空间数据隔离(阶段 2):业务表 `owner_id` + 贡献 `user_id`;`/api/me/*`
      私有空间(图/搜索/详情/扩散/路径 + 行级 CRUD);公共星云 = admin 空间
      (`ADMIN_BOOTSTRAP_EMAIL` 注册自动提权 + 启动认领未归属数据);隔离测试
      (越权 404/403、跨空间引用拒绝)
- [x] 角色迁移(阶段 2):移除 ADMIN_TOKEN / 管理令牌弹窗;管理接口只认 admin 角色
      登录态;前端「数据管理」按用户角色显隐,左侧栏新增「公共星云 / 我的星云」切换
- ⬜ 阶段 2 后续:个人空间数据管理 UI(复用 Admin 组件按空间切换)、
      发布/聚合到公共星云(阶段 4)
- ⬜ 后台发布管线(暂缓,已确认设计):用户星云数据 → 后台采集 →
      AI 预审(查重/纠错) → 人工确认 → 复制进公共星云(owner=admin,内部留溯源);
      公共行只取客观字段,不含用户隐私;不拆表、用户无需手动提交
- [x] 数据管理视图开放给所有登录用户:非 admin 用 `/api/me/*` 管理自己的
      作者/作品/涟漪(贡献/日志/快照仅 admin 可见),新增 `/api/me/data`
- [x] 点亮星空改为「添加到我的星云」:登录后直接写入本人空间(/api/me),
      不再进贡献收件箱;下拉框搜不到时第一行提供「添加新作品 / 新作者」,
      弹出与数据管理共用的标准新增弹窗(NodeFormModal 抽取复用)
- [x] 星际跃迁:左侧栏「公共星云 / 我的星云」下方新增跃迁按钮(随机访问公开星云);
      数据源标签显示所在星云账号(公共星云显示 public);`/api/space/*` 附 displayName
- [x] 同步状态提示:管理页将 CSV 活跃数据与 Neo4j 规范化比对(忽略时间戳),不一致时显示「数据未上传」小字提醒(与重复提醒同区;Phase 4 已随 Neo4j 退役移除)
- [x] 策展数据迁移 SQLite(Phase 1-3 完成):SQLite 主存(`app/sqlite_store.py`)+ 迁移脚本 + admin/importer/sync 切换 + 每次写入自动 CSV 导出 + CI 导出新鲜度门禁 + 贡献表并入同库(方案见 `docs/sqlite-migration.md`)
- [x] SQLite 迁移后优化(P0-P2):行级 CRUD 消除整库重写与并发丢更新;统一连接层(`app/db_sqlite.py`);schema 迁移 runner(v1-v3,迁移前自动备份);索引补齐;DB CHECK 补充;时间戳归一 UTC;`audit_log` 日志表;同步计数预检
- [x] SQLite 迁移后优化(P3a-e):级联删除/恢复纯 SQL;行级校验(目标行+SQL 交叉引用);乐观并发(updatedAt 守卫 409);快照降频+分层清理(load_rows 迁入 sqlite_store,移除 save_rows,删除更新 updatedAt);`GET /api/admin/audit` 日志查询
- [x] 前端优化(A/B):数据行类型化(`lib/adminTypes.ts`)+ Admin 拆分(AdminTable/ContributionsPanel/AuditPanel)+ jsdom 组件测试;Admin/Contribute 懒加载(首屏减约 30KB);乐观更新+409 版本冲突弹窗;日志 Tab;导出 JSON/CSV 按钮已移除(自动 CSV 导出 + git 备份足够);`author_ids` 数组化;`/api/admin/data?include_deleted=` 按需拉取
- [x] Neo4j 查询层退役(Phase 4,P1-P3 清理):公开读取全部由 SQLite 提供(`app/db.py` → `SqliteStore`);删除 importer / export_seed / `/api/admin/sync` / `/api/admin/import` 与管理页「上传↑」;部署收敛为单 worker + SQLite `.backup` 备份 + CSV 重建;依赖清理(neo4j/openpyxl 移除、pydantic 显式声明);清理死代码(snapshot / migrate_contributions / merge_legacy_db)与过期文档;版本 0.5.0

## 3. 可视化效果

- [x] 3D 球状星云主视图(Three.js):作者蓝白星、作品金星,带光晕并随机呼吸闪烁
- [x] 深邃星空氛围:CSS 星群、流星、星云渐变背景
- [x] 连接线方向表达:微弱轨道线 + "流星"光尾(头亮尾暗的渐变短光线)沿 A→B 流动
- [x] 涟漪视图:中心作品 + 相邻作品球状散开
- [x] 提及链视图:作品按 3D 螺旋排列
- [x] 作者视图:作者居中,全部作品环绕(点击作者星进入)
- [x] 切换视图后清除旧标签,避免书名残留
- ⬜ 可选:按年代 / 语言 / 国别为节点配色或聚类

## 4. 交互操作

- [x] 滚轮缩放(相机距离 50–8000,放宽原有限制)
- [x] 鼠标右键拖拽旋转、左键拖拽平移
- [x] 触摸支持:单指平移、双指旋转 / 缩放
- [x] 点击作品星:自动进入涟漪视图,侧边栏显示详情
- [x] 点击作者星:显示该作者及其书籍
- [x] 悬停节点:暂停自动旋转,右侧栏滑出并显示详情(不切换 3D 视图)
- [x] 交互停止后自动恢复旋转(恢复阈值可调,当前 500ms)
- [x] 扩散范围滑动条(1–8 级):拖动时保持当前视角,实时显示"N 级 · M 本书"
- [x] 修复:中文输入法候选框弹出导致左侧栏误隐藏(输入聚焦/组合期间不隐藏)
- [x] 扩散滑动条防抖(拖动时数值即时更新,停止 400ms 后再请求)
- [x] 快捷键:搜索下拉 ↑↓ 选择、Enter 确认;路径输入回车查询(全局 Esc 返回主视图不再实现)

## 5. 布局与 UI

- [x] 左右悬浮侧边栏:鼠标移到屏幕边缘感应带(◀/▶)滑出,移出侧栏区域收回
- [x] 左侧功能栏:品牌标题、搜索、路径输入(边输入边联想 + ⇄ 交换按钮)、返回全部图谱、扩散范围滑动条
- [x] "隐藏孤岛星"开关:默认不勾选;勾选后隐藏无任何提及关系的作品;固定在左侧栏底部;设置跨视图保持;附测试参数 `?hideislands=1`
- [x] 默认过滤:名下作品不超过 1 部的作者(连同其作品)默认隐藏,仅当作品有提及关系时保留;与"隐藏孤岛星"勾选框逻辑相互独立
- [x] 右侧栏:仅显示节点详情 / 提及链结果
- [x] 移除页面底部图例与说明;顶部内容迁入侧边栏
- [x] 视图状态指示条(视图:全图谱 / 涟漪 ·《X》 / 作者 · X / 提及链)
- [x] toast 操作反馈(涟漪展开、提及链结果、扩散级数、孤岛星过滤等)
- [x] 首访引导卡(可关闭,localStorage 记忆;`?skipguide=1` 可跳过)
- [x] 修复:下拉框相对定位错误、遮挡输入框(改为输入框与下拉成组定位)

## 6. 工程与体验

- [x] 验证 npm 修复(npm 12.0.2,registry 可达,Node v24)
- [x] ~~前端拆分为原生 ES module(util / state / renderer / panels / actions / main,无构建)~~(已被 React + Vite 架构取代)
- [x] 主图谱力导向布局分帧计算,避免大数据量卡顿(含视图令牌防止异步覆盖)
- [x] 静态资源版本号防缓存(v=12)
- [x] README 随进度同步维护
- [x] URL 状态化 + 分享/导出:视图类型、扩散级数、孤岛过滤写入 URL(`#v=ripple:workId:hops&islands=1`),相机位置不再由新链接携带(兼容解析旧 `cam=`);浏览器前进/后退可导航;侧边栏「分享链接 / 导出图片」按钮已移除
- [x] 移除"导出数据"按钮与"示例"按钮;"数据管理"入口移至侧边栏底部;路径输入区改为上下等宽下拉框 + 切换按钮 + 右侧"寻找路径"
- [x] React + Vite 迁移:前端重构为 React 18 + Vite 5(`frontend/`),FastAPI 托管构建产物;核心功能(图谱渲染/搜索/路径/涟漪/作者视图/深链/管理页)已验证
- [x] 数据管理功能的权限设置:管理接口统一 Bearer Token 鉴权(`ADMIN_TOKEN`,前端管理页输入令牌后可用)
- [x] 管理员入口:数据管理按钮默认隐藏;`#v=admin` / `?admin` 深链弹出令牌授权,有效令牌驱动按钮显示,支持「退出授权」
- [x] 恢复 URL 状态化:视图/扩散级数/孤岛过滤/作者开关自动写入 hash,浏览器前进/后退可导航;支持 `cam=` / `islands=` / `authors=` 参数与首载深链(兼容旧版分享链接);路径输入恢复作品联想下拉
- [x] 清理旧版 `static/` 页面与前端死代码(`lib/actions.js` / `admin.js` / `panels.js`、重复 vendor 副本),前端单一维护源
- [x] React 迁移复盘·清理:移除 `viewData` 死状态;`viewLabel` 去重;纯函数抽取到 `lib/graphData.js` 并接入 Vitest 单测(7 个用例)
- [x] React 迁移复盘·解耦:深链 `applyHash` 不再篡改 `stateRef`,过滤状态改为显式 flags 透传;同视图刷新改为增量同步场景(保留节点/相机,不再全量重建)
- [x] React 迁移复盘·依赖:three 0.185 升级为 npm 依赖(`three` + addons),移除 vendored 全局脚本
- [x] React 19 升级(19.2.8,`@types/react` 19);lint/test/build 全绿
- [x] 相机状态回传 React store(`SET_CAMERA`,视图切换/交互结束时节流同步)
- [x] 节点点击/悬停改为 React 事件委托(`pickNode` / `setHoveredNode` API,移除注入式 onNodeClick/onNodeHover)
- [x] TypeScript 迁移:全部 `src` 转 `.ts`/`.tsx`(strict + tsc --noEmit),接入 typescript-eslint 与 CI typecheck;tsconfig 单一来源
- [x] 渲染器内核完全受控化:`viewData` 重新入 store 并被 GraphCanvas effect 消费;`graph.ts` 只计算并 dispatch(SET_VIEW / SET_VIEW_DATA / SET_CAMERA),不再直接调渲染器;renderer 退化为 `update(kind, data)` 纯执行器(相机由 `data.camera` 驱动,默认相机上移到 React 侧);移除 onViewChange 注入
- [x] 作品关联改为按 id:`works.csv` 的 `Author`(名字)列迁移为 `author_id`(UUID,多人逗号分隔);后端按 id 校验关联,前端 AuthorPicker 按 id 选择;作者改名不再破坏作品关联(修复改名死锁)
- [x] 数据管理页表格:表头点击排序(升降序循环 + 指示符)、筛选行(下拉:reviewStatus/国籍/体裁/语言;按列搜索框:作者中文名/原文名、作品中文名/原著标题/作者、涟漪源/目标作品,按显示值包含匹配);删除状态筛选 UI 已移除(纯函数 `applyAdminQuery` 保留能力并补单测);新增 `?admin=1` 深链直达
- ⬜ 部署到个人VPS服务器

## 遗留与下一步建议

1. **数据审核与扩充**:逐条审核真实提及并置 `reviewed`,补充出处精确性,扩充数据集
2. ~~渲染器受控化~~(已完成):剩余可选项为给渲染层补集成/快照测试、按需懒加载 three、评估高频相机动画是否值得纳入 `useSyncExternalStore` 订阅
3. 按年代 / 语言 / 国别配色或聚类,让图谱携带更多语义
4. 加载状态指示等体验细节
5. ~~发布流程:按 `reviewStatus` 过滤草稿内容的公开视图,以及快照恢复入口~~(已完成,2026-08-21)

## 最近变更(2026-08-21)

- [x] 发布流程落地:公开视图按 `reviewStatus` 过滤草稿(`PUBLIC_REVIEWED_ONLY` 环境开关,默认关闭);管理端「快照」Tab 列举并一键恢复 SQLite 快照(`backups/` + `data/versions/`,恢复前自动安全备份、恢复后自动导出 CSV);顺带修复重构后 `.env` 未加载回归(`app/db_sqlite.py` 统一 `load_dotenv`)
