/* AI 草稿审核面板:浏览 system_llm 私有空间的 AI 提取草稿,批准/复用/驳回/编辑。

   批准 = 复制进公共星云(created_by='llm', reviewStatus='reviewed');
   复用 = 去重命中现有公共记录时,直接把草稿映射到该记录;
   驳回/重开 = 草稿保留在 system_llm 空间,不删除。
   顺序要求:作者 → 作品 → 涟漪(作品依赖作者、涟漪依赖两端作品已批准)。
*/

import { useCallback, useEffect, useState } from "react";
import type {
  AdminKind,
  AdminRow,
  AuthorRow,
  DedupeHint,
  EdgeRow,
  LlmDraftsData,
  WorkRow,
} from "../../lib/adminTypes";
import { authorLabelOf, workLabel } from "./pickers";
import { authorDisplayNames } from "./query";
import AdminTable from "./AdminTable";
import NodeFormModal, { type NodeKind } from "./NodeFormModal";

const SUB_KINDS: { key: AdminKind; label: string }[] = [
  { key: "authors", label: "作者" },
  { key: "works", label: "作品" },
  { key: "edges", label: "涟漪" },
];

const shortId = (id: string): string => (id.length > 8 ? id.slice(0, 8) : id);

function hintText(hint: DedupeHint | null | undefined): string {
  if (!hint) return "";
  if (hint.level === "exact") return "疑似重复:" + hint.existing_label;
  if (hint.level === "exact_diff_author") return "同名异书:" + hint.existing_label;
  if (hint.level === "edge_duplicate") return "该涟漪已存在:" + hint.existing_label;
  return "可能重复:" + hint.existing_label;
}

interface Props {
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  onStatus: (msg: string) => void;
  onPublicChanged: () => void;
}

export default function LlmDraftsPanel({ authFetch, onStatus, onPublicChanged }: Props) {
  const [kind, setKind] = useState<AdminKind>("authors");
  const [data, setData] = useState<LlmDraftsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState<AdminRow | null>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [textFilters, setTextFilters] = useState<Record<string, string>>({});
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>({ key: "updatedAt", dir: -1 });
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(() => {
    setLoading(true);
    authFetch("/api/admin/llm/drafts")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((d: LlmDraftsData) => { setData(d); setLoading(false); })
      .catch((e: Error) => { onStatus("AI 草稿加载失败: " + e.message); setLoading(false); });
  }, [authFetch, onStatus]);

  useEffect(() => { load(); }, [load, reloadKey]);

  const staging = data?.staging;
  const rows: AdminRow[] = staging ? (staging[kind] as AdminRow[]) : [];
  const authorsById: Record<string, AuthorRow> = {};
  const worksById: Record<string, WorkRow> = {};
  for (const a of staging?.authors || []) authorsById[a.id] = a;
  for (const w of staging?.works || []) worksById[w.id] = w;
  const hints: Record<string, DedupeHint | null> = data?.hints?.[kind] || {};

  const call = (url: string, options?: RequestInit): Promise<any> =>
    authFetch(url, options).then(async (r) => {
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || "操作失败");
      return d;
    });

  const approve = (row: AdminRow, reuseId?: string) => {
    call("/api/admin/llm/drafts/" + kind + "/" + encodeURIComponent(row.id) + "/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reuseId ? { reuse_id: reuseId } : {}),
    })
      .then((d: { mode: string; public_id: string }) => {
        onStatus((d.mode === "reuse" ? "已复用现有记录 → #" : "已发布到公共星云 → #") + d.public_id);
        onPublicChanged();
        setReloadKey((k) => k + 1);
      })
      .catch((e: Error) => onStatus(e.message));
  };

  const reject = (row: AdminRow) => {
    call("/api/admin/llm/drafts/" + kind + "/" + encodeURIComponent(row.id) + "/reject", { method: "POST" })
      .then(() => { onStatus("已驳回（草稿保留）"); setReloadKey((k) => k + 1); })
      .catch((e: Error) => onStatus(e.message));
  };

  const reopen = (row: AdminRow) => {
    call("/api/admin/llm/drafts/" + kind + "/" + encodeURIComponent(row.id) + "/reopen", { method: "POST" })
      .then(() => { onStatus("已重开为草稿"); setReloadKey((k) => k + 1); })
      .catch((e: Error) => onStatus(e.message));
  };

  const cellValue = (row: AdminRow, key: string): string => {
    const rec = row as unknown as Record<string, unknown>;
    if (key === "evidence") {
      const t = String(rec.evidence || "");
      return t.length > 60 ? t.slice(0, 60) + "…" : t;
    }
    if (key === "author_id") return authorDisplayNames(rec.author_id as string | undefined, authorsById, authorLabelOf);
    if (key === "source_work_id") {
      const w = worksById[String(rec.source_work_id || "")];
      return w ? workLabel(w) : String(rec.source_work_id || "");
    }
    if (key === "target_work_id") {
      const w = worksById[String(rec.target_work_id || "")];
      return w ? workLabel(w) : String(rec.target_work_id || "");
    }
    if (key === "hint") return hintText(hints[row.id]);
    return String(rec[key] || "");
  };

  const cols: { key: string; label: string }[] =
    kind === "authors"
      ? [
          { key: "Name_CN", label: "中文名" },
          { key: "originalName", label: "原文名" },
          { key: "nationality", label: "国家" },
          { key: "reviewStatus", label: "状态" },
          { key: "hint", label: "公共星云去重提示" },
        ]
      : kind === "works"
        ? [
            { key: "Title_CN", label: "中文名" },
            { key: "originalTitle", label: "原著标题" },
            { key: "author_id", label: "作者" },
            { key: "publicationYear", label: "年份" },
            { key: "reviewStatus", label: "状态" },
            { key: "hint", label: "公共星云去重提示" },
          ]
        : [
            { key: "source_work_id", label: "源作品" },
            { key: "target_work_id", label: "目标作品" },
            { key: "evidence", label: "原文片段" },
            { key: "evidenceSource", label: "章节/出处" },
            { key: "reviewStatus", label: "状态" },
            { key: "hint", label: "提示" },
          ];

  const filterCols = [
    { key: "reviewStatus", type: "select" as const },
    ...(kind === "authors"
      ? [{ key: "Name_CN", type: "text" as const }, { key: "originalName", type: "text" as const }]
      : kind === "works"
        ? [{ key: "Title_CN", type: "text" as const }, { key: "originalTitle", type: "text" as const }]
        : [{ key: "evidenceSource", type: "text" as const }]),
  ];

  const uniqueValues = (key: string): string[] =>
    Array.from(
      new Set(rows.map((r) => String((r as unknown as Record<string, unknown>)[key] || "")).filter(Boolean))
    ).sort((a, b) => a.localeCompare(b));

  const toggleSort = (key: string) => {
    setSort((prev) => {
      if (prev && prev.key === key) return prev.dir === 1 ? { key, dir: -1 } : null;
      return { key, dir: 1 };
    });
  };

  const switchKind = (k: AdminKind) => {
    setKind(k);
    setModal(null);
    setFilters({});
    setTextFilters({});
    setSort({ key: "updatedAt", dir: -1 });
  };

  const counts = staging?.counts;
  const publishedCount = rows.filter((r) => (r as unknown as Record<string, unknown>).published_to_id).length;

  return (
    <div className="llm-drafts">
      <div className="llm-head">
        <p className="llm-tip">
          AI 草稿存放于 system_llm 私有空间（公共星云不可见），按 作者 → 作品 → 涟漪 顺序批准。
          公共星云现有：作者 {data?.public_counts.authors ?? 0} · 作品 {data?.public_counts.works ?? 0}
          {counts ? `；草稿：作者 ${counts.authors} · 作品 ${counts.works} · 涟漪 ${counts.edges}` : ""}
        </p>
        <div className="admin-tabs">
          {SUB_KINDS.map((k) => (
            <button
              key={k.key}
              className={"admin-tab" + (kind === k.key ? " active" : "")}
              onClick={() => switchKind(k.key)}
            >
              {k.label}
            </button>
          ))}
        </div>
      </div>
      {loading ? (
        <p>加载中…</p>
      ) : (
        <AdminTable
          kind={kind}
          cols={cols}
          rows={rows}
          filterCols={filterCols}
          filters={filters}
          textFilters={textFilters}
          sort={sort}
          cellValue={cellValue}
          cellTitle={(row, key) =>
            key === "evidence" ? String((row as unknown as Record<string, unknown>).evidence || "") : undefined
          }
          uniqueValues={uniqueValues}
          onSort={toggleSort}
          onFilter={(k, v) => setFilters((f) => ({ ...f, [k]: v }))}
          onTextFilter={(k, v) => setTextFilters((f) => ({ ...f, [k]: v }))}
          renderActions={(row) => {
            const rec = row as unknown as Record<string, unknown>;
            const published = Boolean(rec.published_to_id);
            const hint = hints[row.id];
            if (published) {
              return <span className="llm-published">已发布 #{shortId(String(rec.published_to_id))}</span>;
            }
            if (row.reviewStatus === "rejected") {
              return (
                <span className="llm-actions">
                  <button onClick={() => reopen(row)}>重开</button>
                  <button onClick={() => setModal(row)}>编辑</button>
                </span>
              );
            }
            return (
              <span className="llm-actions">
                <button className="primary" onClick={() => approve(row)}>批准</button>
                {hint && (hint.level === "exact" || hint.level === "edge_duplicate") && (
                  <button
                    onClick={() => approve(row, hint.existing_id)}
                    title={"复用 " + hint.existing_label + " (免建新行)"}
                  >
                    复用
                  </button>
                )}
                <button onClick={() => reject(row)}>驳回</button>
                <button onClick={() => setModal(row)}>编辑</button>
              </span>
            );
          }}
        />
      )}
      {publishedCount > 0 && <p className="llm-tip">本页已有 {publishedCount} 条发布/复用（草稿行保留映射，不会重复发布）。</p>}

      {modal && (
        <NodeFormModal
          kind={kind as NodeKind}
          mode="edit"
          initial={modal}
          apiBase="/api/admin/llm/drafts"
          authorsList={staging?.authors || []}
          worksList={staging?.works || []}
          edgesList={staging?.edges || ([] as EdgeRow[])}
          isAdmin
          onClose={() => setModal(null)}
          onSaved={() => {
            setModal(null);
            onStatus("草稿已保存");
            setReloadKey((k) => k + 1);
          }}
        />
      )}
    </div>
  );
}
