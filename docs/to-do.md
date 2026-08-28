# Echo Graph · 需求与进度清单

> 整理自项目启动以来的全部需求,按模块分类。
> 状态:✅ 已完成 · 🟡 部分完成 · ⬜ 待办
>
> 本文为需求与进度清单:保留当前架构下仍有效的已完成项、未完成项与最近变更;已退役功能(Neo4j 查询层、原生 JS、CSV 事实源、ADMIN_TOKEN、贡献收件箱等)的演进记录见 docs/migration/ 与 docs/audit/。

## 1. 数据与模型

- [x] 评估 readme.md 方案可行性并输出结论(技术栈可行,主要风险在数据策展)
- [x] 数据模型按 `data_schema.md`(schemaVersion 1.1)规范:`Author` / `Work` 节点及属性
  - Work:`id`、`language`(ISO 639-1)、`originalTitle`、`Title_CN`、`Title_EN`、`publicationYear`、`creationYear`、时间戳
  - 补充:`genre`(体裁)、可选 `deletedAt`;`id` 为 UUID(新增自动生成 UUID v7),URL 直接使用 UUID
- [x] 结构关系 `(Work)-[:AUTHORED_BY]->(Author)`,基数 N:N(允许合著)
- [x] 回声关系 `(Work)-[:ECHO]->(Work)`:A 在书中提及 B 即建立 A→B;属性含 `evidence`、`evidenceSource`(出处/章节/译本)、`note`、`reviewStatus` 与时间戳
- [x] 涟漪关系(边)增加 `id`(UUID v7):`edges.csv` 新增 `id` 列并回填存量 3 条;管理页新增/编辑/删除按 `id` 定位,与作者/作品一致
- [x] 作者/作品增加 `reviewStatus` 审核状态(默认 `draft`),管理页作者/作品表格列由「删除时间」改为「审核状态」,编辑表单同步支持
- [x] 图谱隐藏佚名(Anonymous)作者节点:每部佚名作品独立显示,不再经共享的"佚名"星连成中枢(数据层不变,搜索/详情保留)
- ⬜ 扩充数据量与出处精确性(需人工策展)

## 2. 后端 / API

- [x] FastAPI 接口:
  - `GET /api/graph` 全量图谱
  - `GET /api/search?q=` 搜索作者/作品
  - `GET /api/work/{id}` 作品详情(谁提及它 / 它提及谁)
  - `GET /api/path?from=&to=` 有向最短提及链
  - `GET /api/expansion/{workId}?hops=N` N 级扩散子图
  - `GET /api/stats` 数据统计
- [x] 数据管理页(长期方案):左侧栏「数据管理」入口;作者/作品/提及三 Tab 表格 + 搜索筛选;表单弹窗(枚举下拉、作者/作品选择器);保存前全量校验、失败不落盘;软删除与恢复;导入 Neo4j 已随查询层退役(Phase 4);导出 JSON/CSV 已移除(备份由自动 CSV 导出 + git 承担);保存快照已在 P3d 移除(`data/versions/` 为历史遗留)
- [x] React 版数据管理页补齐:搜索筛选、新增/编辑表单(作品选择器/枚举下拉/必填校验)、软删除与恢复(「上传↑」导入与保存快照已随 Phase 4/P3d 移除)
- [x] 扩散子图:沿 ECHO 无向扩展 N 级,返回节点/边/中心作品
- [x] 涟漪视图:未勾选「隐藏孤岛星」时,展示视图中已出现作者名下的全部作品,额外作品围绕作者形成隐约星云(更小更暗、悬停显示标签);勾选后仅保留涟漪节点(即时重渲染,保持相机)
- [x] 安全修复:静态资源接口拒绝路径穿越(`..` / 绝对路径 / 越界解析),含回归测试
- [x] lint 门禁恢复通过:ruff 0 errors(import 排序、`X | None` 风格、B904/B008 处理、未用变量清理)
- [x] 审核状态落地:模型默认 `draft`;`GET /api/graph?status=` 按审核状态过滤;`/api/stats` 输出 `reviewStatus` 分布
- [x] 时间戳语义:管理 API 新增/编辑维护 `createdAt`/`updatedAt`;导入不再全量刷新 `updatedAt`(仅新增时写入)
- [x] 账号体系(多用户第一步):users/sessions 表(Argon2 密码哈希 + httpOnly Cookie 会话,
      DB 只存 token 的 SHA-256 哈希);`/api/auth/register|login|logout|me|config`;
      注册 Cloudflare Turnstile 人机验证;注册/登录 IP 滑动窗口限流
       (限流抽为 app/ratelimit.py,与关注等写接口共用);带 Origin 头的跨站状态请求拒绝
- [x] 账号体系后续:admin 用户管理(用户列表 / 禁用 `users.status` / 角色调整 /
      星云可见性管理 / VIP 标记)——见「最近变更(2026-08-25)」
- [x] 账号体系后续:邮箱验证 + 密码找回(2026-08-28 落地):「引导管理员邮箱可被抢先
      注册提权」与「无密码修改/重置、账号无法找回」两个问题已解决——注册邮箱验证
      确保引导管理员邮箱归属(验证通过后才提权 admin),并作为密码重置的找回通道;
      实现见 app/mailer.py(阿里云邮件推送 DirectMail / SMTP 可插拔发送器)+
      email_tokens 一次性令牌(schema v27)+ `/api/auth/verify-email|resend-verification|
      forgot-password|reset-password`
- ⬜ 账号体系后续:OIDC 社交登录
- [x] 用户空间数据隔离(阶段 2):业务表 `owner_id` + 贡献 `user_id`;`/api/me/*`
      私有空间(图/搜索/详情/扩散/路径 + 行级 CRUD);默认视图 = admin 星云(官方图谱)
      (`ADMIN_BOOTSTRAP_EMAIL` 注册自动提权 + 旧库遗留数据一次性兼容认领);隔离测试
      (越权 404/403、跨空间引用拒绝)
- [x] ~~阶段 2 后续:发布/聚合到官方图谱~~(2026-08-28 随官方图谱概念移除)
- [x] ~~后台发布管线~~(2026-08-28 随官方图谱概念移除):不再规划「复制进官方图谱」
- [x] 数据管理视图开放给所有登录用户:非 admin 用 `/api/me/*` 管理自己的
      作者/作品/涟漪(日志/快照仅 admin 可见),新增 `/api/me/data`
- [x] 星际跃迁:左侧栏「公共星云 / 我的星云」下方新增跃迁按钮(随机访问公开星云);
      数据源标签显示所在星云账号(默认视图显示 public);`/api/space/*` 附 displayName
- [x] SQLite 迁移后优化(P0-P2):行级 CRUD 消除整库重写与并发丢更新;统一连接层(`app/db_sqlite.py`);schema 迁移 runner(v1-v3,迁移前自动备份);索引补齐;DB CHECK 补充;时间戳归一 UTC;`audit_log` 日志表;同步计数预检
- [x] SQLite 迁移后优化(P3a-e):级联删除/恢复纯 SQL;行级校验(目标行+SQL 交叉引用);乐观并发(updatedAt 守卫 409);快照降频+分层清理(load_rows 迁入 sqlite_store,移除 save_rows,删除更新 updatedAt);`GET /api/admin/audit` 日志查询
- [x] 溯源列 `created_by`(2026-08-24,schema v23):作者/作品/涟漪三表新增
      `created_by`(curated 人工策展 / user 用户空间写入 / llm AI 提取预留);
      显式传值优先、缺省按 owner 推导(admin=curated,其他=user),创建后不可修改、
      不进 CSV;为后续书籍解析管线直写专用用户空间提供来源追溯

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
- [x] 扩散范围输入框 + 步进器(1 至当前节点实际可达跳数,上限动态变化):输入/点按
      保持当前视角,实时显示"N 级 · M 本书"
- [x] 修复:中文输入法候选框弹出导致左侧栏误隐藏(输入聚焦/组合期间不隐藏)
- [x] 扩散级数防抖(输入/点按时数值即时更新,停止 400ms 后再请求)
- [x] 快捷键:搜索下拉 ↑↓ 选择、Enter 确认;路径输入回车查询(全局 Esc 返回主视图不再实现)

## 5. 布局与 UI

- [x] 左右悬浮侧边栏:鼠标移到屏幕边缘感应带(◀/▶)滑出,移出侧栏区域收回
- [x] 左侧功能栏:品牌标题、搜索、路径输入(边输入边联想 + ⇄ 交换按钮)、返回全部图谱、扩散范围输入框 + 步进器
- [x] "隐藏孤岛星"开关:默认不勾选;勾选后隐藏无任何提及关系的作品;固定在左侧栏底部;设置跨视图保持;附测试参数 `?hideislands=1`
- [x] 默认过滤:名下作品不超过 1 部的作者(连同其作品)默认隐藏,仅当作品有提及关系时保留;与"隐藏孤岛星"勾选框逻辑相互独立
- [x] 右侧栏:仅显示节点详情 / 提及链结果
- [x] 移除页面底部图例与说明;顶部内容迁入侧边栏
- [x] 视图状态指示条(视图:全图谱 / 涟漪 ·《X》 / 作者 · X / 提及链)
- [x] toast 操作反馈(涟漪展开、提及链结果、扩散级数、孤岛星过滤等)
- [x] 首访引导卡(可关闭,localStorage 记忆;`?skipguide=1` 可跳过)
- [x] 修复:下拉框相对定位错误、遮挡输入框(改为输入框与下拉成组定位)

## 6. 工程与体验

- [x] ~~前端拆分为原生 ES module(util / state / renderer / panels / actions / main,无构建)~~(已被 React + Vite 架构取代)
- [x] 主图谱力导向布局分帧计算,避免大数据量卡顿(含视图令牌防止异步覆盖)
- [x] 静态资源版本号防缓存(v=12)
- [x] README 随进度同步维护
- [x] URL 状态化 + 分享/导出:视图类型、扩散级数、孤岛过滤写入 URL(`#v=ripple:workId:hops&islands=1`),相机位置不再由新链接携带(兼容解析旧 `cam=`);浏览器前进/后退可导航;侧边栏「分享链接 / 导出图片」按钮已移除
- [x] 移除"导出数据"按钮与"示例"按钮;"数据管理"入口移至侧边栏底部;路径输入区改为上下等宽下拉框 + 切换按钮 + 右侧"寻找路径"
- [x] React + Vite 迁移:前端重构为 React 18 + Vite 5(`frontend/`),FastAPI 托管构建产物;核心功能(图谱渲染/搜索/路径/涟漪/作者视图/深链/管理页)已验证
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
6. **国际化(中英双语)**:待项目功能完善后再进行。2026-08-24 已评估——
   代码层面中等偏易(前端约 400-500 条硬编码文案、无 i18n 基建,需引入字典/库并处理
   侧栏固定宽度溢出、排序 collator、时间显示、Turnstile 语言);数据层面作品已有
   `Title_EN`(74%),但作者 `Name_EN` 仅 18.5%,英文界面会大面积中文兜底,需先补数据;
   建议渐进式:先界面文案 + 字段选择链(`en → original → cn`),后端错误消息与审计日志
   暂缓或保持中文。详细评估见对话记录。
7. **VIP 会员功能**:待核心功能完善后启动。2026-08-24 已评估——代码层面低难度
   (已有 `require_user`/`require_admin` 依赖模式,新增 `require_vip` 即可;星云可见性
   触点集中:后端 auth/space 3 处 + 前端 AuthUser/Sidebar/SettingsTab 3 处),数据模型
   加 `users.vip_expires_at`(或 memberships 表)即常规迁移;真正成本在支付环节
   (国际 Stripe 3-5 天;微信/支付宝需商户资质 5-10 天)。建议 MVP 先做**兑换码模式**
   (管理员发码、用户兑换,1.5-3 天,绕开支付资质),到期只降级不删数据;
   需先定产品决策:「公开可见(可被跃迁)是会员权益」vs「私密是会员权益」,
   以及存量用户空间(当前默认 public)是否一次性翻为 private。详细评估见对话记录。
8. **整库异地备份(2026-08-27 新增,承接已移除的 CSV 备份层)**:CSV 自动导出层
   已移除(`data/export/*.csv`、`export_csv.py` / `check_public_sync.py` /
   `migrate_csv_to_sqlite.py`、CI 新鲜度门禁、csv 类型快照恢复全部下线,2026-08-27)。
   备份介质统一为**整库快照**(`backups/echo-graph-*.db`,`sqlite3 .backup` + 管理端
   「快照」恢复);待办:把 `backups/` 定期同步到异地(rsync / rclone / 对象存储)的
   自动化方案,以及「全新环境从整库备份引导」的操作文档与演练。
9. **草稿/驳回显示的用户级设置(2026-08-27 提出,2026-08-28 更新)**:全局
   `PUBLIC_REVIEWED_ONLY` 开关已随公共星云/官方图谱概念移除。规划改为「设置」里的
   用户级选项:**用户可自行选择是否显示自己星云的草稿/驳回内容**(默认显示全部,
   与当前行为一致);涉及个人空间读取过滤与前端设置 UI。

## 最近变更(2026-08-21)

- [x] 发布流程落地:公开视图按 `reviewStatus` 过滤草稿(`PUBLIC_REVIEWED_ONLY` 环境开关,默认关闭);管理端「快照」Tab 列举并一键恢复 SQLite 快照(`backups/` + `data/versions/`,恢复前自动安全备份、恢复后自动导出 CSV);顺带修复重构后 `.env` 未加载回归(`app/db_sqlite.py` 统一 `load_dotenv`)

## 最近变更(2026-08-22)

- [x] 星际跃迁空间上下文修复:store 的 `space` 扩展为 `public | mine | space:<userId>` 三元状态,
      前端按空间路由 `/api/space/{id}/search|work|expansion|path`,跃迁后可在目标星云内完整交互
- [x] 星云可见性自服务:`PATCH /api/auth/me`(侧边栏「星云:公开/仅自己可见」开关)
- [x] 资料与数据模型卫生:schema v14 删除 `sessions.last_seen_at`;`now_iso`/`new_uuid`/`KIND_TABLE`
      统一单一来源;`adminTypes.ts` 补全 `visibility` / `recommendation` / `review` 字段
- [x] 文档同步:`data_schema.md` 字段错位修正(评分/评价归入作品)、`migration/sqlite-migration.md` 与
      `migrate_csv_to_sqlite.py` 过期表述更新、README 补充 Windows 账户变更环境处理
- [x] 用户资料字段:users 新增 `username`(唯一)与 `nickname`(可选);注册/资料编辑支持,
      `displayName` 改用「昵称 > 用户名」,星际跃迁与界面不再暴露邮箱
- [x] 用户名规则收紧:仅英文字母/数字/下划线(v16 重写存量),登录支持用户名
- [x] 用户名最短长度 5 位(v17 补齐存量),前后端校验与文案同步
- [x] 左侧功能栏重构为 Tab 列(类 VS Code):「星云」Tab 收纳原图谱操作,
      「设置」Tab 收纳个人资料/星云可见性/退出登录;桌面竖排、移动端横向顶栏
- [x] 左右侧栏右上角新增「钉住」按钮:钉住后不再自动隐藏,localStorage 记忆,
      移动端栏外收起与自动隐藏逻辑均尊重钉住状态
- [x] 用户新增表单统一基于本人数据:数据管理/点亮星空不再提供公共数据联想下拉
      (admin 同样移除,NodeFormModal 公共联想组件与字段整体清理)
- [x] 新增作者/作品原文名/原著标题联想改为本空间已有数据(admin 同逻辑),
      选中已存在数据时提示「数据已存在,请勿重复新增」且保存被拦截
- [x] 用户资料新增 `bio` 简介字段(v18):设置页个人资料只显示昵称/简介,
      用户名不再展示、不可自行修改
- [x] 右侧详情栏 Tab 化:「涟漪 / 书签(评分评价)/ 个人资料(星云所有者昵称简介)」,
      图谱接口附 owner 公开资料

## 最近变更(2026-08-23)

- [x] 关注模型好友(schema v19 新增 `friendships` 单向关注表):`/api/follow/*` 关注/取关(幂等)、
      我的关注/粉丝列表、与目标用户的关系查询;仅登录用户可用、不可关注自己、
      目标不存在/已禁用 404;每用户每小时关注操作限流 50 次
- [x] 左侧功能栏 Tab 扩展为「星云 / 我的 / 消息 / 设置」四个:「我的」Tab 收纳
      个人资料编辑(昵称/简介)与关注/粉丝列表(点击条目定向跃迁到对方星云);
      「消息」Tab 为占位(第二阶段通知,后端未实现)
- [x] 右侧详情栏「个人资料」卡片完善(星云所有者昵称/简介,不含邮箱)
- [x] 随机跃迁排除自己与默认视图所有者(admin);定向跃迁支持好友/粉丝列表入口
- [x] URL 状态深化:hash 携带 `space` 参数(public/mine/<用户id>),刷新/分享后保持星云上下文;
      深链与空间切换在首载时按 space 路由
- [x] 数据管理页面排序/布局调整;修复下拉框、自动填充、新增作者、刷新等问题
- [x] 工程收尾(2026-08-23 审查修复):移除 `app/security.py` 未注册的死中间件;
      前端 `getJson` 统一检查 HTTP 状态(404/500 不再当成功载荷);`backups.py` CSV 恢复
      先校验引导管理员再落盘;只读路由收敛为工厂(消除 `/api`、`/api/me`、`/api/space`
      三套并行端点);用户展示名/行查询抽公共模块;读缓存键补 `reviewed_only`;
      新增 `scripts/check_public_sync.py` 检查本地库公共数据与仓库 CSV 一致性并支持
      备份后合并追平(用户空间保留);README/to-do/data_schema/multi-user-migration 文档同步
- [x] 作品新增个人阅读状态字段(schema v20):`works.readingStatus`(read/reading/unread,
      默认空,仅用户空间语义、不进 CSV,与评分/评价同策略);新增/编辑作品表单提供
      「阅读状态」下拉(已读/在读/未读),右侧「书签」Tab 同步展示
- [x] 移除作者/作品的节点级可见性(schema v21):`authors/works.visibility` 列删除,
      后端访客视图过滤(SqliteStore include_private/visibility_sql)、前端「可见性」
      列/筛选/表单字段全部清理;星云可见性(`users.space_visibility` 与星际跃迁 404)
      保留不变

## 最近变更(2026-08-25)

- [x] admin 用户管理:侧边栏新增「用户管理」入口(点亮星空下方、数据管理上方,
      与数据管理同样式,仅 admin 可见),打开**独立用户管理窗口**(不并入数据
      管理窗口);接口 `GET /api/admin/users`、`PATCH /api/admin/users/{id}`,
      支持禁用/启用、角色调整、星云可见性、VIP 维护;保护规则:不能修改自己的
      角色/状态、引导管理员不可禁用/降级、至少保留一名可用管理员;
      变更写入审计(kind=`users`,不含 `password_hash`);
      旧 `POST /api/admin/users/{id}/vip` 接口保持兼容
- [x] AI 草稿审核管道(schema v24):`system_llm` 机器账号私有空间承载 AI 提取草稿
      (`created_by='llm'`、`reviewStatus='draft'`、随机密码不可登录,不可人工登录);
      admin 管理端新增「AI 草稿」Tab,作者/作品/涟漪分页浏览(附与自己星云的基础
      去重提示),支持编辑/驳回/重开/批准(复制进自己的星云,admin 即官方图谱)/复用(去重命中现有记录);
      批准后草稿行回写 `published_to_id` 防重复发布;依赖守卫保证作品依赖作者、
      涟漪依赖两端作品均已先批准;新增审计动作 `llm_ingest` / `llm_publish` /
      `llm_reuse` / `llm_reject` / `llm_reopen`
- [x] 审核管道 CLI:`app/ai_assistant/tools/review_publish.py` 新增 `ingest` 子命令,
      批次条目单事务写入 system_llm 草稿区,增量跳过已处理条目
      (2026-08-27 起 make-batch / review / publish 等 legacy CLI 已移除,
      `ingest` 能力由 `stage_batch` 提供,见「最近变更(2026-08-27)」)

## 最近变更(2026-08-26)

- [x] 提示词统一维护到 `app/ai_assistant/prompts.py`:抽取共享字段块
      (`_AUTHOR_FIELDS` / `_WORK_FIELDS`)消除 AUTHOR↔ENTITY_AUTHOR、
      WORK↔ENTITY_WORK 重复;去重兜底确认提示词从 `dedupe_check.py` 内嵌
      文案整合为 `DEDUPE_CONFIRM_SYSTEM_PROMPT` + 用户模板(补 system 角色、
      变体识别、保守阈值与严格数字输出约束)
- [x] 涟漪只取正文:代码层过滤(不依赖提示词)——`read_book.find_book_titles_with_context`
      新增 `body_only=True`,在聚合前剔除前言/序言/尾记/附录等非正文章节;
      RIPPLE 提示词 `mention_type` 改为 前言/正文/尾记/其它 四类,
      `skipped` 新增 `out_of_body` 计数
- [x] 修复三体导入「作者栏出现全部涟漪作者」:涟漪作者改存
      `extract["ripple_authors"]`(不再混入源书作者 `extract["authors"]`),
      `collect_candidates_from_extract` / `build_batch` 同步修正,
      `build_batch` 对旧版污染数据容错(按元数据作者 + 涟漪作者键过滤)
- [x] AI 草稿按上传者隔离:废除共享 `system_llm` 机器账号,草稿直接
      `owner_id=上传者` + `created_by='llm'` 落库;上传者(admin/VIP)在「AI 草稿」页
      只能看到/审核自己上传的草稿;官方图谱/策展/去重读取统一排除 AI 草稿
      (`db_sqlite.ai_draft_clause`);旧共享账号草稿由
      `app/llm_account.migrate_legacy_llm_drafts()` 在服务启动时一次性迁移到
      引导管理员并删除空账号
- [x] AI 草稿页交互:「清空」按钮(确认弹窗,软删除自己上传的草稿,审计留痕);
      「导入」按钮在 AI 草稿页签同样显示,导入完成后草稿列表自动刷新
- [x] AI 草稿审核改版:去掉 作者/作品/涟漪 三个 Tab,改为按导入批次(源书)分组的
      卡片,每条涟漪按「点亮星空」字段展示并可单独批准(依赖按 源作者→源作品→
      目标作者→目标作品→涟漪 顺序自动建库,与自己星云精确重复时自动复用
      (exact/edge_duplicate,同名异书 exact_diff_author 不自动复用)/驳回/重开;
     批准后进入「已发布」折叠区;新增接口
      `POST /api/admin/llm/ripples/{edge_id}/approve` 与
      `POST /api/admin/llm/source/{work_id}/approve`(无涟漪批次的源书批准)
- [x] 去重逻辑统一:新增 `dedupe_check.dedupe_entity(kind, candidate, *, user_id, ...)`
      统一入口(author/work 走 基础+语义+LLM 三阶段,edge 只走端点对基础匹配);
      判重目标**严格按用户自己空间**(admin 即官方图谱,`load_user_rows`,
      排除 AI 草稿);`run_dedupe`、AI 草稿提示/自动复用、
      个人空间新增全部改走统一入口;删除 llm_review 自写的 `_best_hit` 匹配
- [x] 运维管理页:侧边栏新增 admin 专属「运维管理」入口(与数据管理/用户管理同款
      窗口),把数据管理里的「日志/快照」两个 Tab 迁入,窗口内子 Tab 切换;
      数据管理窗口只保留 作者/作品/涟漪/AI草稿;涟漪重复提示改为端点先解析到
      公共 id(已发布或精确命中)再查同对边,未发布也能提示 edge_duplicate
- [x] AI 草稿模型定型(产品决策 2026-08-26):**导入者 = 审核者 = 发布到自己星云**——
      admin 与 VIP 均可导入书籍并在「AI 草稿」页审核**自己上传**的草稿,批准后
      发布到自己的星云(owner_id=上传者;admin 的星云即官方图谱);普通用户
      无 AI 导入/审核能力;多 admin 各自独立星云、互不审核;去重/复用判重目标
      改为上传者自己的星云(`llm_drafts` 的 `space_counts` 即本人星云数据量);
      修复涟漪去重提示误用边 id 查 works 表的映射 bug(按草稿作品 id 批量取
      `published_to_id`);`/api/admin/llm/*` 鉴权由 admin 放开为 admin/VIP。
- [x] ~~admin 整合用户数据进官方图谱通道~~(2026-08-28 随官方图谱概念移除):
      发布落点恒为上传者自己的星云,不再规划汇聚通道。

## 最近变更(2026-08-27)

- [ ] 账号体系后续:邮箱验证列入计划(见上文「账号体系后续」条目)——一次性解决
      「引导管理员邮箱可被抢先注册提权」(P2)与「无密码修改/重置、账号无法找回」
      (P2)两个问题;邮箱验证作为注册前置 + 密码重置找回通道;OIDC 社交登录另行规划。
- [x] 审查 P3 修复:
  - 空白搜索: `/api/search` 对纯空白 `q` 返回空结果,不再命中全量数据
    (`app/read_routes.py` 先 `strip()`,`app/db.py` `search()` 加空查询守卫,补单测);
  - GET 写副作用: `app/llm_review.py` 的 `GET /api/admin/llm/drafts` 不再执行
    `migrate_legacy_llm_drafts()`,改为 `app/main.py` 启动生命周期统一执行
    (GET 保持只读,与 `bootstrap_admin()` 同处启动);
  - 文档不一致: `docs/ui.md` 扩散范围描述由「滑动条 1-8 级」修正为
    「输入框 + 步进器,上限 = 当前节点实际可达跳数(动态),后端 hops 无上限」,
    `docs/to-do.md` 同步更新。
- [x] **CSV 备份层移除(审查 P1 跟进)**:多设备/调试导致 `data/export/*.csv` 与库漂移,
      备份统一改为**整库快照**——
  - 移除写入路径自动导出(`space_crud.after_write`)、快照恢复后导出(`admin_restore`)、
    `data/export/*.csv` 与 `scripts/export_csv.py` / `check_public_sync.py` /
    `migrate_csv_to_sqlite.py`、CI `csv-export` job、csv 类型快照恢复
    (`backups.py` 只保留 `.db` 类型);
  - 全新环境引导改为「启动自动建 schema(空库)+ 从整库备份恢复数据」;
  - 异地整库备份自动化列入「遗留与下一步建议」第 8 条待办。
- [x] **数据管理页「导出 CSV」按钮(所有登录用户)**:把当前星云三张表
      (作者/作品/涟漪)打包为 zip 下载;`GET /api/me/export`(admin 为
      `GET /api/admin/export`),与数据管理页同口径(仅本人空间、排除 AI 草稿、
      含软删除行、works 附带个人字段);前端按钮在作者/作品/涟漪三个 Tab 显示。
- [x] **公共星云概念移除(架构变更)**:公共星云 ≡ admin 星云(官方图谱),admin 星云
      不做特殊对待——
  - 默认视图(功能栏「公共星云」标签)= admin 星云:公开接口 `/api/*` 直接读
    `owner_id=引导管理员` 的空间,与用户星云同口径(`app/db.py` `_owner_clause`
    删除 `owner_id IS NULL` 分支);点击「公共星云」与跃迁到 admin 星云效果一致;
  - 移除「未认领历史行」支持:`adopt_unowned`、`load_rows(public_only=...)`、
    `_own_space_scope` 的 admin 特判、`_publish_draft_entity` 复用目标 NULL 分支
    全部删除;旧库遗留 NULL 行由启动/注册时 `claim_unowned_rows()` 一次性兼容认领;
  - AI 草稿/去重/审核判重目标统一为「上传者自己的星云」(admin 即官方图谱),
    VIP 与 admin 口径一致;「admin 整合用户数据进官方图谱」见上文 ⬜ 条目,
    「审核过滤用户级设置」列入遗留第 9 条待办(见上);功能栏「公共星云」标签保留。
- [x] **清理 legacy CLI 与一次性脚本**:`review_publish.py` 的 make-batch / list /
      show / review / publish / ingest 子命令及配套展示/发布函数全部移除(约 500 行),
      保留管线核心 `build_batch` / `stage_batch` / `build_dedupe_info`;
      `scripts/backfill_ripple_work_authors.py` 一次性回填脚本删除(无任何引用)。

## 最近变更(2026-08-28)

- [x] **手工新增审核语义收口 + 并发一致性修复(审查跟进)**:API 手工新增/编辑
      作者/作品/涟漪一律强制 `reviewed`(所有用户一致,admin 不做特殊化,显式
      `draft`/`rejected` 回正);`created_by` 显式传 `llm` 被 API 拒绝(仅 AI 管线
      内部使用),溯源列仍创建后不可修改;乐观并发守卫改为必传 `updatedAt`
      (缺失 400);书籍导入并发上限检查与任务登记原子化(撞线 429);
      API 响应统一 `Cache-Control: no-store`;文档同步(`introduction.md` /
      `data_schema.md` / `ops-manual.md`);`EMAIL_VERIFY_REQUIRED=0` 时注册即信任
      (`email_verified_at` 以 `createdAt` 标记,与存量回填策略一致),修复
      `test_auth.py` 缺失 `import re` 与未验证登录 403 断言越出 env patch 的
      测试缺陷(后端 286/286 全绿)。
- [x] **公共星云/官方图谱概念移除(架构变更,审查跟进)**:不再存在「默认视图」——
  - 前端:功能栏「公共星云」按钮删除;`Space` 收敛为 `mine | space:<userId>` 二元态,
    未登录无默认图谱(空图 + 登录提示),可通过星际跃迁浏览公开星云;
    URL `space=public` 参数废弃;
  - 后端:公共只读六件套(`/api/graph`、`/api/search`、`/api/work/{id}`、
    `/api/expansion/{id}`、`/api/path`、`/api/stats`)随默认视图删除,个人空间
    使用 `/api/me/*`,他人星云使用 `/api/space/*`;`SqliteStore` 必须绑定
    `owner_id`,`reviewed_only`/`PUBLIC_REVIEWED_ONLY` 环境变量移除;
  - 引导管理员语义收窄:仅保留首个 admin 引导(`bootstrap_admin` 补角色),
    `claim_unowned_rows` / `admin_profile` 与「认领公共星云」逻辑删除;
    随机跃迁不再排除 admin(其星云与其他用户星云一致);
  - 文档同步:`docs/introduction.md` / `permissions.md` / `data_schema.md` /
    `ops-manual.md` / `ui.md` / `deploy/DEPLOY.md` / `.env.example` 移除
    公共星云/官方图谱/默认视图描述。
- [x] 侧边栏「数据管理」更名为「星云工坊」:按钮、管理窗口标题与文档中的
      用户可见叫法统一(代码注释与历史 changelog 保留原称谓)。
- [x] **邮箱验证 + 密码找回(账号体系后续,用户指定阿里云邮件推送 DirectMail)**:
  - 可插拔发送器 `app/mailer.py`:`MAILER=api` 走 DirectMail SingleSendMail
    (HMAC-SHA1 签名,纯标准库,支持 cn-hangzhou / ap-southeast-1 区域)、
    `MAILER=smtp` 走 465 SSL / 587 STARTTLS、未配置仅本地日志;
  - schema v27:`email_tokens` 表(只存 SHA-256 哈希,verify/reset 两类用途,
    24 小时有效,重发作废旧令牌)+ `users.email_verified_at`(存量用户回填
    createdAt,视为已信任,不锁旧账号);
  - 新接口:`POST /api/auth/verify-email`(验证通过即登录)、
    `POST /api/auth/resend-verification`、`POST /api/auth/forgot-password`(不泄露
    账号是否存在)、`POST /api/auth/reset-password`(重置后吊销全部会话);
    `EMAIL_VERIFY_REQUIRED=1` 时注册后需验证才能登录,登录接口对未验证账号 403;
  - 安全收口:引导管理员在**验证通过后**才提权 admin(`bootstrap_admin` 启动补角色
    也只认已验证用户),「抢先注册引导管理员邮箱提权」问题闭环;
    `EMAIL_VERIFY_REQUIRED=1` 但邮件服务未配置时注册 fail-closed(503)并回滚用户;
  - 前端:登录弹窗新增「忘记密码?」/重置密码流程,邮件深链 `#v=verify:TOKEN` /
    `#v=reset:TOKEN` 进入应用,验证/重置后立即清除 URL 中的一次性令牌;
  - 配置:`.env.example` / `deploy/DEPLOY.md`(0.5 节 DirectMail 配置步骤)/
    `docs/ops-manual.md`(8 节配置表)同步更新。
- [x] **DirectMail 实测排错与改进(2026-08-28)**:生产实测「重置邮件发送失败」,
  排错结论沉淀到 `deploy/DEPLOY.md` 0.5.1 与 `docs/ops-manual.md` 7 节——
  - `app/mailer.py` 不再吞掉 HTTP 4xx/5xx 响应体:DirectMail 的 `Code/Message/
    RequestId` 直接透传到日志(此前只报「HTTP 400」无法定位),补单测
    (`tests/test_mailer.py` HTTPError 用例);
  - 排错结论:`Forbidden` = RAM 未授权 `AliyunDirectMailFullAccess` 或
    AccessKey 不属于开通邮件推送的账号;`InvalidMailAddress.NotFound` =
    发信地址按区域隔离,`ALIYUN_DM_REGION` 必须与创建地址的控制台区域一致
    (实测:地址建在 cn-hangzhou,配 ap-southeast-1 即报该错);
  - 送达率:Gmail 实测 SPF/DKIM/DMARC 全 pass 仍进垃圾箱 = 新域名/共享 IP
    信誉冷启动 + 链接跟踪改写;处理:收件人标「不是垃圾邮件」+ 加联系人、
    关闭跟踪或配自定义跟踪域名、保持少量真实事务邮件养 1~4 周、高要求可迁
    新加坡区域或购买独立 IP。
- [x] **游客落地星云(方案 B,2026-08-28)**:`.env` 配置 `LANDING_SPACE=<用户名>`
  (可空),游客打开首页自动进入该公开星云——
  - 后端:`GET /api/space/by-username/{username}/graph`(用户名大小写不敏感,
    未公开/已禁用/不存在一律 404,与按 id 访问同口径;注册在 {user_id} 路由之前);
    `GET /api/auth/config` 返回 `landingSpace`(用户名仅服务端配置,不出现在
    URL/界面,避免暴露可用作登录的账号标识);
  - 前端:首载时未登录且 URL 无显式 `space` 参数才应用落地星云(显式深链优先),
    目标不可用时回退空图 + 登录提示;登录用户仍进自己的星云,不受影响;
  - 文档:`docs/introduction.md` / `ui.md` / `ops-manual.md` / `.env.example` 同步。
