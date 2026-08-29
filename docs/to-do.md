# Echo Graph · 需求与进度清单

> 状态:✅ 已完成 · 🟡 部分完成 · ⬜ 待办
>
> 本文只保留**当前架构下仍有效**的条目;历史演进过程(Neo4j 查询层、CSV 事实源、
> 公共星云/官方图谱、贡献收件箱等已退役功能)见 `docs/migration/`、`docs/audit/`
> 与 git 历史,不再在本文重复。

## 1. 数据与模型

- [x] 数据模型按 `docs/data_schema.md` 实现(schemaVersion 1.8,`meta.schema_version` = 27):
  `Author` / `Work` 节点(UUID v7 主键)、`AUTHORED_BY` 关系(N:N,物理实现 `work_authors`)、
  `ECHO` 提及关系(`edges`,含 evidence / evidenceSource / note)
- [x] 软删除设计:`deletedAt` 非空的行保留在库中,读取层一律过滤;删除/恢复按
  作品→涟漪边、作者→作品+边级联(相同 `deletedAt` 时间戳一批恢复)
- [x] 审核状态 `reviewStatus` 与溯源列 `created_by`(`curated` / `user` / `llm`);
  手工新增/编辑一律强制 `reviewed`,显式传 `draft`/`rejected` 回正
- [x] 作品个人语义字段:`readingStatus` / `recommendation` / `review`(仅用户空间,导出 CSV 附带)
- [x] 佚名(Anonymous)作者节点隐藏,每部佚名作品独立显示
- ⬜ 扩充数据量与出处精确性(需人工逐条策展)

## 2. 后端 / API

- [x] 只读六件套 `graph / search / work / expansion / path / stats`:
  `/api/me/*`(个人空间)与 `/api/space/{user_id}/*`(星际跃迁)共用
  `app/read_routes.py` 工厂实现;不再有面向默认视图的公共 `/api/*` 端点
- [x] 星云工坊行级 CRUD(`app/space_crud.py`,所有登录用户同一实现):
  Pydantic 行级校验 + SQL 交叉引用、乐观并发(`updatedAt` 守卫,冲突 409)、
  软删除/恢复/永久删除、审计日志、写后读缓存失效
- [x] 账号体系:邮箱+用户名注册/登录、Argon2 哈希、httpOnly Cookie 会话
  (DB 只存 token SHA-256)、Turnstile 人机验证(fail-closed)、IP 滑动窗口限流、
  全局 CSRF 同源校验、邮箱验证 + 密码重置(可插拔 DirectMail/SMTP 发送器)
- [x] 用户管理(`/api/admin/users`):禁用/角色/星云可见性/VIP,保护引导管理员与
  至少一名可用管理员
- [x] 审计(`/api/admin/audit`)与快照(`/api/admin/backups`):`sqlite3 .backup` 整库
  快照、恢复前安全备份、路径白名单
- [x] AI 书籍导入(`/api/admin/import-book`)+ 草稿审核(`/api/admin/llm/*`):
  上传者=审核者=发布到自己星云;去重(基础+语义+LLM 三阶段)、`published_to_id`
  防重复发布、依赖顺序自动建库
- ⬜ OIDC 社交登录

## 3. 可视化与交互

- [x] Three.js 3D 球状星云:作者蓝白星、作品金星、ECHO 青色发光星轨(流星光尾表达方向)
- [x] 视图:主图谱 / 涟漪(无向扩散,N 级,上限动态)/ 提及链(有向最短路径,螺旋排布)/
  作者(居中 + 作品环绕)
- [x] 交互:右键旋转、左键平移、滚轮缩放(50-8000)、触摸(单指平移/双指旋转缩放)、
  悬停 0.3s 出详情、长按查看、交互停止自动恢复旋转
- [x] 渲染器受控化:React store 持有 `viewData` / 相机,渲染器退化为纯执行器;
  力导向布局主线程/Worker 共用同一算法
- [x] 阅读状态筛选、孤岛开关、作者开关、作品标签开关,URL 状态化 + 深链
- ⬜ 按年代 / 语言 / 国别配色或聚类

## 4. 布局与 UI

- [x] 左右侧栏 Tab 化(星云 / 我的 / 消息 / 设置;涟漪 / 书签)、钉住、边缘感应滑出
- [x] 星云工坊(所有登录用户):作者/作品/涟漪三表管理,AI 草稿 Tab(admin/VIP)
- [x] 用户管理 / 运维管理窗口(admin)、星际跃迁、书友卡片(自动收起)、
  点亮星空(添加到我的星云)、首访引导卡
- [x] 登录弹窗:登录 / 注册 / 忘记密码 / 重置密码(邮件深链)
- ⬜ 消息 Tab(第二阶段通知,暂为占位)

## 5. 工程

- [x] React 19 + Vite 5 + TypeScript(strict),FastAPI 托管构建产物
- [x] CI:后端测试 + ruff、前端 lint/typecheck/test/build、版本一致性
  (pyproject == package.json)、依赖审计
- [x] 部署模板 `deploy/`(nginx → uvicorn 单 worker → SQLite),`setup-vps.sh` / `deploy.sh`
- ⬜ 部署到个人 VPS 服务器(模板就绪,按 `deploy/DEPLOY.md` 执行)

## 遗留与下一步建议

1. **数据审核与扩充**:逐条审核真实提及并置 `reviewed`,补充出处精确性,扩充数据集。
2. **渲染层收尾**:补集成/快照测试、按需懒加载 three、评估高频相机动画是否纳入
   `useSyncExternalStore` 订阅。
3. **按年代 / 语言 / 国别配色或聚类**,让图谱携带更多语义。
4. **加载状态指示等体验细节**。
5. **国际化(中英双语)**:前端约 400-500 条硬编码文案、无 i18n 基建;数据层面
   作品 `Title_EN` 覆盖率约 74%,作者 `Name_EN` 仅约 18.5%,需先补数据。
   建议渐进式:先界面文案 + 字段选择链(`en → original → cn`),后端错误与审计暂缓。
6. **VIP 会员功能**:代码层面低难度(已有 `require_user`/`require_admin`,新增
   `require_vip` 即可);成本在支付环节。建议 MVP 先做**兑换码模式**(管理员发码、
   用户兑换,绕开支付资质),到期只降级不删数据。需先定产品决策:
   「公开可见(可被跃迁)是会员权益」vs「私密是会员权益」,以及存量空间是否翻 private。
7. **整库异地备份自动化**:把 `backups/` 定期同步到异地(rsync / rclone / 对象存储),
   以及「全新环境从整库备份引导」的操作演练。
8. **草稿/驳回显示的用户级设置**:规划改为「设置」里的用户级选项——用户自行选择
   是否显示自己星云的草稿/驳回内容(默认显示全部,与当前行为一致)。
9. **OIDC 社交登录**(账号体系后续)。
