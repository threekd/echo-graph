# 权限矩阵梳理（admin / VIP / 普通用户 / 游客）

> 梳理日期:2026-08-26
> 梳理对象:当前代码的实际行为(schema v26)。「AI 草稿」模型已按产品决策定型:
> **导入者 = 审核者 = 发布到自己星云**;普通用户无 AI 导入;多 admin 各自独立、
> 互不审核;admin 审核后进入公共星云的统一通道为后续规划。
> 与 `docs/to-do.md`、`docs/data_schema.md` 配套阅读。

## 1. 角色与身份模型

- **角色**:`users.role` ∈ `user` / `admin`(普通用户 / 管理员)。
- **VIP**:`users.vip` 是布尔标记(0/1,schema v26,`app/db_sqlite.py:635-643`),不是独立角色;
  仅由 admin 通过用户管理接口维护(`app/admin.py:119-127`)。
- **引导管理员**:`.env` 配置 `ADMIN_BOOTSTRAP_EMAIL` 的邮箱注册时自动获得 `admin` 角色,
  并把未归属(owner_id 为空)的策展行认领为其空间,即「公共星云」(`app/auth.py:372,379`、`bootstrap_admin` `app/auth.py:112-127`)。
- **游客**:未登录(无会话 Cookie)。

## 2. 能力 × 角色总表

| 能力 | 游客 | 普通用户 | VIP | admin |
| --- | --- | --- | --- | --- |
| 浏览公共星云 / 搜索 / 作品详情 / 扩散 / 路径(`/api/*`) | ✅ | ✅ | ✅ | ✅ |
| 星际跃迁(随机 / 定向访问公开星云,`/api/space/*`) | ✅ 仅公开星云 | ✅ 仅公开星云 | ✅ 仅公开星云 | ✅ 公开星云 + 任意 private 星云 |
| 个人星云管理(图/搜索/详情/扩散/路径 + 数据 CRUD,`/api/me/*`) | ❌ 401 | ✅ 仅本人数据 | ✅ 仅本人数据 | ✅ 仅本人数据 |
| 数据管理(公共星云 CRUD + CSV 导出按钮,`/api/admin/data`) | ❌ | ❌ | ❌ | ✅ |
| 用户管理(禁用/角色/星云可见性/VIP,`/api/admin/users`) | ❌ | ❌ | ❌ | ✅ |
| 运维(审计日志 / 快照备份恢复,`/api/admin/audit`、`/api/admin/backups`) | ❌ | ❌ | ❌ | ✅ |
| 关注 / 粉丝(`/api/follow/*`) | ❌ 401 | ✅ | ✅ | ✅ |
| 个人资料(读取 / 修改昵称、简介、星云可见性,`/api/auth/me`) | ❌ 401 | ✅ | ✅ | ✅ |
| AI 书籍导入(`/api/admin/import-book`) | ❌ 401 | ❌ 403 | ✅ | ✅ |
| AI 草稿审核(列表 / 批准 / 复用 / 驳回 / 重开 / 编辑 / 清空,`/api/admin/llm/*`) | ❌ 401 | ❌ 403 | ✅ 仅自己上传的草稿 | ✅ 仅自己上传的草稿 |
| 发布(审核批准 → 写入空间) | ❌ | ❌ | ✅ 发布到**自己的星云** | ✅ 发布到**自己的星云**(引导管理员即公共星云) |

## 3. 各能力的鉴权实现(证据)

| 能力 | 鉴权 | 位置 |
| --- | --- | --- |
| 公共只读六件套 | 无登录要求(游客可访问) | `app/main.py` `register_read_routes(.../api)`;`app/read_routes.py` |
| 星际跃迁 | 可见性判定:目标用户 active 且 `space_visibility='public'`,或访问者是本人 / admin | `app/space.py:31-40`(`_require_visible`) |
| 个人星云 | 登录 | `app/me.py:24`(router `dependencies=[Depends(require_user)]`) |
| 数据管理 / 用户管理 / 运维 | admin 角色 | `app/admin.py:37`(`dependencies=[Depends(require_admin)]`) |
| AI 书籍导入 | admin 或 VIP | `app/book_import.py:53-55`(`require_admin_or_vip`);端点 `:338`、`:390` |
| AI 草稿审核 | admin 或 VIP;数据范围 = 当前用户自己上传,互不审核 | `app/llm_review.py:42`(`require_admin_or_vip`);`llm_drafts` `:239`(`owner = user["id"]`);审核端点 `:752` 等(`staging_owner = user["id"]`);判重目标 = 自己星云(`_own_space_scope` `:48`) |
| 关注 | 登录 | `app/follows.py:15`(require_user) |
| 认证依赖 | 未登录 401 / 非 admin 403 / 非 admin 且非 VIP 403 | `app/auth.py:316`(`require_user`)、`:324`(`require_admin`)、`:332`(`require_admin_or_vip`) |

## 4. 数据归属与「公共星云」语义

- **公共星云** = 引导管理员认领的行(`owner_id = 引导管理员`) + 尚未认领的历史行(`owner_id IS NULL`);
  读取层按该口径过滤(`app/db.py` `SqliteStore._owner_clause`)。
- **用户星云** = `owner_id = 该用户` 的行;`/api/me/*` 只读写本人数据,越权一律 404。
- **AI 草稿** = `owner_id = 上传者` + `created_by='llm'` 的行(未发布或已发布保留映射);
  公共星云 / 个人空间 / 星际跃迁读取统一排除(`app/db_sqlite.py` `ai_draft_clause`)。
- **发布落点(已定型)**:批准时发布行以 `owner_id = 上传者(=审核者)id` 写入
  (`app/llm_review.py:604/625/709` 取 `admin_id = user["id"]`,`insert_row ... owner_id=admin_id` `:550`)。
  只有引导管理员发布时,落点才等于「公共星云」;
  普通 admin / VIP 发布的数据留在各自星云,不进公共图谱
  (CSV 自动导出层已于 2026-08-27 移除,备份走整库快照)。

## 5. 已确认的模型(2026-08-26 产品决策)

1. **导入者 = 审核者 = 发布到自己星云**:admin 与 VIP 均可导入书籍,在「AI 草稿」页
   审核**自己上传**的草稿,批准后发布到自己的星云(`owner_id = 上传者`);去重/复用
   判重目标同样是自己的星云(`llm_drafts` 的 `space_counts` 即本人星云数据量)。
2. **普通用户**:无 AI 导入 / 审核能力(`/api/admin/import-book`、`/api/admin/llm/*`
   均要求 admin 或 VIP),仅能管理自己的星云(手动 CRUD)与关注关系。
3. **多 admin 各自独立、互不审核**:草稿按 `owner_id` 隔离,审核接口只操作本人
   上传的草稿,跨上传者一律 404。
4. **发布到公共星云的通道 = 后续规划**:当前发布落点恒为上传者自己的星云;
   后续将新增「admin 审核 → 复制进引导管理员公共星云」的统一通道
   (涉及 `llm_review` 发布落点、判重目标,见 `docs/to-do.md`)。

## 6. 边界与注意点

- **公共星云的特殊性**:引导管理员的星云 = 公共星云,其数据对游客可见;
  因此引导管理员审核批准的内容会直接进入公共图谱,与普通 admin / VIP 的发布落点不同。
- **VIP 发布不进公共图谱**:VIP 批准后的数据留在自己的星云,只有星云设为公开
  (`space_visibility='public'`)时才可被星际跃迁访问。
- **导入任务可见性**:`/api/admin/import-book/{task_id}` 按创建者隔离,admin 可查看
  任意 admin 的任务进度(仅任务状态/日志,不含草稿数据)。
