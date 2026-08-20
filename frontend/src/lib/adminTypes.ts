/* 数据管理页的类型定义(与后端 /api/admin/* 响应对齐)。 */

export type ReviewStatus = "draft" | "reviewed" | "rejected";
export type ContributionStatus = "pending" | "approved" | "rejected";

export interface AuthorRow {
  id: string;
  originalName: string;
  Name_CN: string;
  Name_EN?: string | null;
  nationality?: string | null;
  birthYear?: number | null;
  deathYear?: number | null;
  reviewStatus: ReviewStatus;
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
  creationYear?: number | null;
  genre?: string | null;
  reviewStatus: ReviewStatus;
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
  createdAt?: string | null;
  updatedAt?: string | null;
  deletedAt?: string | null;
}

export interface ContributionRow {
  id: string;
  source_work: string;
  target_work: string;
  source_author: string;
  target_author: string;
  evidence: string;
  evidence_source: string;
  note?: string | null;
  contact?: string | null;
  status: ContributionStatus;
  created_at: string;
  reviewed_at?: string | null;
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
export type AdminTab = AdminKind | "contributions" | "audit" | "snapshots";
