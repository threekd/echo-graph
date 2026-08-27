/* 数据管理页的类型定义(与后端 /api/admin/* 响应对齐)。 */

export type ReviewStatus = "draft" | "reviewed" | "rejected";
export type Recommendation = "recommend" | "not_recommend";
export type ReadingStatus = "read" | "reading" | "unread";

export interface AuthorRow {
  id: string;
  originalName: string;
  Name_CN: string;
  Name_EN?: string | null;
  nationality?: string | null;
  birthYear?: number | null;
  deathYear?: number | null;
  note?: string | null;
  reviewStatus: ReviewStatus;
  published_to_id?: string | null; // AI 草稿发布到自己的星云后的映射(仅草稿行有值)
  createdAt?: string | null;
  updatedAt?: string | null;
  deletedAt?: string | null;
}

export interface WorkRow {
  id: string;
  language: string;
  originalTitle: string;
  Title_CN: string;
  Title_EN?: string | null;
  Title_Other?: string | null;
  author_id?: string | null;
  author_ids?: string[];
  publicationYear?: number | null;
  genre?: string | null;
  note?: string | null;
  readingStatus?: ReadingStatus | null; // 个人阅读状态(已读/在读/未读),仅用户空间语义,不进 CSV
  recommendation?: Recommendation | null; // 个人评分,仅用户空间语义,不进 CSV
  review?: string | null; // 个人评价(最多 2000 字),仅用户空间语义,不进 CSV
  reviewStatus: ReviewStatus;
  published_to_id?: string | null; // AI 草稿发布到自己的星云后的映射(仅草稿行有值)
  createdAt?: string | null;
  updatedAt?: string | null;
  deletedAt?: string | null;
}

export interface EdgeRow {
  id: string;
  source_work_id: string;
  target_work_id: string;
  evidence: string;
  evidenceSource?: string | null;
  note?: string | null;
  reviewStatus: ReviewStatus;
  published_to_id?: string | null; // AI 草稿发布到自己的星云后的映射(仅草稿行有值)
  createdAt?: string | null;
  updatedAt?: string | null;
  deletedAt?: string | null;
}

export interface AuditEntry {
  id: number;
  ts: string;
  actor: string;
  action: string;
  kind: string;
  row_id: string | null;
  detail: string;
  before?: string | null;
  after?: string | null;
}

export type UserRole = "user" | "admin";
export type UserStatus = "active" | "disabled";
export type SpaceVisibility = "public" | "private";

// 用户管理列表项(/api/admin/users 响应形状)
export interface UserRow {
  id: string;
  email: string;
  username: string;
  nickname?: string | null;
  bio?: string | null;
  role: UserRole;
  status: UserStatus;
  space_visibility: SpaceVisibility;
  vip: boolean;
  counts: { authors: number; works: number; edges: number };
  createdAt?: string | null;
  updatedAt?: string | null;
}

// 三张业务表行的联合(管理表格/表单的通用行类型)
export type AdminRow = AuthorRow | WorkRow | EdgeRow;

export interface AdminData {
  authors: AuthorRow[];
  works: WorkRow[];
  edges: EdgeRow[];
  warnings: {
    duplicateAuthorNames: string[];
    duplicateWorkTitles: string[];
    duplicateEdgePairs: string[];
  };
  counts: {
    authors: number;
    works: number;
    edges: number;
    deleted: { authors: number; works: number; edges: number };
  };
}

export type AdminKind = "authors" | "works" | "edges";
export type AdminTab = AdminKind | "llm";

// AI 草稿审核页:/api/admin/llm/drafts 响应形状
export interface DedupeHint {
  level: string;
  score: number;
  existing_id: string;
  existing_label: string;
}

// 书籍导入任务:/api/admin/import-book 提交与轮询响应形状
export interface BookImportTask {
  task_id: string;
  status: "queued" | "running" | "done" | "error";
  stage: string;
  log: string[];
  result: {
    batch_id: string;
    extracted: { authors: number; works: number; edges: number };
    counts: { staged: number; already: number; failed: number };
  } | null;
  error: string | null;
}

export interface LlmDraftsData {
  batches: LlmDraftBatch[];
  published: {
    kind: "authors" | "works" | "edges";
    id: string;
    label: string;
    public_id: string;
  }[];
  counts: {
    batches: number;
    ripples: number;
    published: number;
  };
  space_counts: { authors: number; works: number }; // 审核人(上传者)自己星云的数据量
  space: { authors: AuthorRow[]; works: WorkRow[] }; // 审核人个人库全量(排除 AI 草稿),供编辑弹窗下拉
  reuse_labels: { authors: Record<string, string>; works: Record<string, string> }; // 复用/发布目标的名称映射
}

export interface LlmDraftBatch {
  source: {
    work: WorkRow;
    authors: AuthorRow[];
    hint?: DedupeHint | null;
    author_hint?: DedupeHint | null;
  };
  ripples: LlmDraftRipple[];
  created_at: string;
}

export interface LlmDraftRipple {
  edge: EdgeRow;
  target: {
    work: WorkRow;
    authors: AuthorRow[];
  } | null;
  hint?: DedupeHint | null;
  author_hint?: DedupeHint | null;
  edge_hint?: DedupeHint | null;
}

