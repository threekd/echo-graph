/* AI 草稿审核面板:按导入批次(源书)分组展示,每条涟漪用「点亮星空」同款字段
   (源作品/源作者/目标作品/目标作者/原文片段/出处/备注),可单独批准(依赖
   自动建库)/复用/驳回/编辑;批准后进入「已发布」折叠区。

   数据形状见 lib/adminTypes.ts 的 LlmDraftsData:batches 按源书作品分组,
   每个涟漪含 edge / target(作品+作者) 与去重提示(hint / author_hint /
   edge_hint)。*/

import { useCallback, useEffect, useState } from "react";
import type {
  AdminRow,
  AuthorRow,
  DedupeHint,
  LlmDraftBatch,
  LlmDraftsData,
  WorkRow,
} from "../../lib/adminTypes";
import { authorLabelOf, workLabel } from "./pickers";
import NodeFormModal, { type NodeKind } from "./NodeFormModal";

const shortId = (id: string): string => (id.length > 8 ? id.slice(0, 8) : id);

function hintText(hint: DedupeHint | null | undefined): string {
  if (!hint) return "";
  if (hint.level === "exact") return "疑似重复:" + hint.existing_label;
  if (hint.level === "exact_diff_author") return "同名异书:" + hint.existing_label;
  if (hint.level === "edge_duplicate") return "该涟漪已存在:" + hint.existing_label;
  return "可能重复:" + hint.existing_label;
}

const isExact = (h: DedupeHint | null | undefined): boolean =>
  Boolean(h && (h.level === "exact" || h.level === "edge_duplicate"));

interface EditModal {
  kind: NodeKind;
  row: AdminRow;
}

interface Props {
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  onStatus: (msg: string) => void;
  onPublicChanged: () => void;
}

export default function LlmDraftsPanel({ authFetch, onStatus, onPublicChanged }: Props) {
  const [data, setData] = useState<LlmDraftsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [confirmClear, setConfirmClear] = useState(false);
  const [modal, setModal] = useState<EditModal | null>(null);
  const [publishedOpen, setPublishedOpen] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    authFetch("/api/admin/llm/drafts")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((d: LlmDraftsData) => { setData(d); setLoading(false); })
      .catch((e: Error) => { onStatus("AI 草稿加载失败: " + e.message); setLoading(false); });
  }, [authFetch, onStatus]);

  useEffect(() => { load(); }, [load, reloadKey]);

  const reload = () => setReloadKey((k) => k + 1);

  const call = (url: string, options?: RequestInit): Promise<any> =>
    authFetch(url, options).then(async (r) => {
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || "操作失败");
      return d;
    });

  const approveRipple = (
    edgeId: string,
    reuse?: { sourceWork?: string; sourceAuthor?: string; targetWork?: string; targetAuthor?: string; edge?: string },
  ) => {
    call("/api/admin/llm/ripples/" + encodeURIComponent(edgeId) + "/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reuse_source_work_id: reuse?.sourceWork || null,
        reuse_source_author_id: reuse?.sourceAuthor || null,
        reuse_target_work_id: reuse?.targetWork || null,
        reuse_target_author_id: reuse?.targetAuthor || null,
        reuse_edge_id: reuse?.edge || null,
      }),
    })
      .then(() => {
        onStatus(reuse ? "已复用现有记录并发布涟漪" : "涟漪已发布到公共星云");
        onPublicChanged();
        reload();
      })
      .catch((e: Error) => onStatus(e.message));
  };

  const approveSource = (
    workId: string,
    reuse?: { work?: string; author?: string },
  ) => {
    call("/api/admin/llm/source/" + encodeURIComponent(workId) + "/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reuse_work_id: reuse?.work || null,
        reuse_author_id: reuse?.author || null,
      }),
    })
      .then(() => {
        onStatus(reuse ? "已复用现有记录并发布源书" : "源书已发布到公共星云");
        onPublicChanged();
        reload();
      })
      .catch((e: Error) => onStatus(e.message));
  };

  const reject = (edgeId: string) => {
    call("/api/admin/llm/drafts/edges/" + encodeURIComponent(edgeId) + "/reject", { method: "POST" })
      .then(() => { onStatus("已驳回（草稿保留）"); reload(); })
      .catch((e: Error) => onStatus(e.message));
  };

  const reopen = (edgeId: string) => {
    call("/api/admin/llm/drafts/edges/" + encodeURIComponent(edgeId) + "/reopen", { method: "POST" })
      .then(() => { onStatus("已重开为草稿"); reload(); })
      .catch((e: Error) => onStatus(e.message));
  };

  const clearDrafts = () => {
    call("/api/admin/llm/drafts/clear", { method: "POST" })
      .then((d: { counts?: Record<string, number> }) => {
        const c = d.counts || {};
        onStatus(
          "AI 草稿已清空(作者 " + (c.authors ?? 0) +
          " · 作品 " + (c.works ?? 0) +
          " · 涟漪 " + (c.edges ?? 0) + ")"
        );
        setPublishedOpen(false);
        reload();
      })
      .catch((e: Error) => onStatus(e.message));
  };

  const counts = data?.counts;
  const sourceAuthorLabel = (a: AuthorRow): string => authorLabelOf(a);
  const workLabelOf = (w: WorkRow | undefined | null): string => (w ? workLabel(w) : "?");

  // 批次内全部作者/作品/涟漪行,供 NodeFormModal 的关联选择器使用
  const authorsList: AuthorRow[] = data
    ? Array.from(
        new Map(
          data.batches
            .flatMap((b) => [
              ...b.source.authors,
              ...b.ripples.flatMap((r) => r.target?.authors || []),
            ])
            .map((a) => [a.id, a] as const)
        ).values()
      )
    : [];
  const worksList: WorkRow[] = data
    ? Array.from(
        new Map(
          data.batches
            .flatMap((b) => [
              b.source.work,
              ...b.ripples.flatMap((r) => (r.target ? [r.target.work] : [])),
            ])
            .map((w) => [w.id, w] as const)
        ).values()
      )
    : [];
  const edgesList = data ? data.batches.flatMap((b) => b.ripples.map((r) => r.edge)) : [];

  const renderEntityActions = (
    batch: LlmDraftBatch,
    extra: { onSourceApprove?: (reuse?: { work?: string; author?: string }) => void },
  ) => (
    <span className="llm-actions">
      <button onClick={() => setModal({ kind: "works", row: batch.source.work as AdminRow })}>编辑作品</button>
      {batch.source.authors.map((a) => (
        <button key={a.id} onClick={() => setModal({ kind: "authors", row: a as AdminRow })}>
          编辑作者
        </button>
      ))}
      {batch.ripples.length === 0 && (
        <>
          {isExact(batch.source.hint) && (
            <button
              onClick={() => extra.onSourceApprove?.({ work: batch.source.hint?.existing_id })}
              title={"复用 " + batch.source.hint?.existing_label + " (免建新行)"}
            >
              复用源书
            </button>
          )}
          {isExact(batch.source.author_hint) && (
            <button
              onClick={() => extra.onSourceApprove?.({ author: batch.source.author_hint?.existing_id })}
              title={"复用 " + batch.source.author_hint?.existing_label}
            >
              复用作者
            </button>
          )}
          <button className="primary" onClick={() => extra.onSourceApprove?.()}>批准源书</button>
        </>
      )}
    </span>
  );

  return (
    <div className="llm-drafts">
      <div className="llm-head">
        <p className="llm-tip">
          AI 草稿仅上传者本人可见（owner_id=上传者、created_by=llm，公共星云不可见）。
          每条涟漪按 源作品 → 目标作品 独立批准，依赖的作者/作品会自动建库；
          命中公共星云重复时可选择「复用」。公共星云现有：
          作者 {data?.public_counts.authors ?? 0} · 作品 {data?.public_counts.works ?? 0}
          {counts
            ? `；草稿：批次 ${counts.batches} · 涟漪 ${counts.ripples} · 已发布 ${counts.published}`
            : ""}
        </p>
        <div className="llm-toolbar">
          <span className="llm-toolbar-title">待审核批次</span>
          <button className="llm-clear" onClick={() => setConfirmClear(true)} disabled={loading}>
            清空
          </button>
        </div>
      </div>

      {loading ? (
        <p>加载中…</p>
      ) : !data || data.batches.length === 0 ? (
        <p className="llm-empty">暂无待审核的 AI 草稿，可先导入书籍。</p>
      ) : (
        data.batches.map((b, bi) => (
          <div className="llm-batch" key={bi}>
            <div className="llm-batch-head">
              <span className="llm-batch-title">《{workLabelOf(b.source.work)}》</span>
              <span className="llm-batch-meta">
                作者:{b.source.authors.map(sourceAuthorLabel).join("、") || "未知"}
                {b.created_at ? ` · 导入 ${new Date(b.created_at).toLocaleString()}` : ""}
              </span>
              {renderEntityActions(b, { onSourceApprove: (reuse) => approveSource(b.source.work.id, reuse) })}
            </div>

            <div className="llm-batch-body">
              {b.ripples.map((r, ri) => {
                const published = Boolean((r.edge as unknown as Record<string, unknown>).published_to_id);
                const rejected = r.edge.reviewStatus === "rejected";
                const evidence = String((r.edge as unknown as Record<string, unknown>).evidence || "");
                const evidenceSource = String((r.edge as unknown as Record<string, unknown>).evidenceSource || "");
                const note = String((r.edge as unknown as Record<string, unknown>).note || "");
                return (
                  <div className={"llm-ripple" + (published ? " published" : "")} key={ri}>
                    <div className="llm-ripple-grid">
                      <div className="llm-field">
                        <span>目标作品</span>
                        {r.target ? workLabelOf(r.target.work) : "?"}
                      </div>
                      <div className="llm-field">
                        <span>目标作品作者</span>
                        {r.target ? r.target.authors.map(sourceAuthorLabel).join("、") || "—" : "—"}
                      </div>
                      <div className="llm-field full">
                        <span>原文片段</span>
                        <span className="llm-evidence" title={evidence}>
                          {evidence || "—"}
                        </span>
                      </div>
                      <div className="llm-field">
                        <span>出处</span>
                        {evidenceSource || "—"}
                      </div>
                      <div className="llm-field">
                        <span>备注</span>
                        {note || "—"}
                      </div>
                    </div>
                  {(r.hint || r.author_hint || r.edge_hint) && (
                    <p className="llm-hint">
                      {hintText(r.hint)}
                      {hintText(r.author_hint)}
                      {hintText(r.edge_hint)}
                    </p>
                  )}
                  <div className="llm-ripple-actions">
                    {published ? (
                      <span className="llm-published">
                        已发布 #
                        {shortId(String((r.edge as unknown as Record<string, unknown>).published_to_id))}
                      </span>
                    ) : rejected ? (
                      <>
                        <button onClick={() => reopen(r.edge.id)}>重开</button>
                        <button onClick={() => setModal({ kind: "edges", row: r.edge as AdminRow })}>编辑</button>
                      </>
                    ) : (
                      <>
                        {isExact(b.source.hint) && (
                          <button
                            onClick={() => approveRipple(r.edge.id, { sourceWork: b.source.hint?.existing_id })}
                            title={"复用源书 " + b.source.hint?.existing_label}
                          >
                            复用源书
                          </button>
                        )}
                        {isExact(b.source.author_hint) && (
                          <button
                            onClick={() => approveRipple(r.edge.id, { sourceAuthor: b.source.author_hint?.existing_id })}
                            title={"复用源作者 " + b.source.author_hint?.existing_label}
                          >
                            复用源作者
                          </button>
                        )}
                        {isExact(r.hint) && (
                          <button
                            onClick={() => approveRipple(r.edge.id, { targetWork: r.hint?.existing_id })}
                            title={"复用目标作品 " + r.hint?.existing_label + " (免建新行)"}
                          >
                            复用目标作品
                          </button>
                        )}
                        {isExact(r.author_hint) && (
                          <button
                            onClick={() => approveRipple(r.edge.id, { targetAuthor: r.author_hint?.existing_id })}
                            title={"复用目标作者 " + r.author_hint?.existing_label}
                          >
                            复用目标作者
                          </button>
                        )}
                        {isExact(r.edge_hint) && (
                          <button
                            onClick={() => approveRipple(r.edge.id, { edge: r.edge_hint?.existing_id })}
                            title={"复用现有涟漪 " + r.edge_hint?.existing_label}
                          >
                            复用涟漪
                          </button>
                        )}
                        <button className="primary" onClick={() => approveRipple(r.edge.id)}>批准</button>
                        <button onClick={() => setModal({ kind: "edges", row: r.edge as AdminRow })}>编辑</button>
                        <button onClick={() => reject(r.edge.id)}>驳回</button>
                      </>
                    )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))
      )}

      {data && data.published.length > 0 && (
        <div className="llm-published-section">
          <button className="llm-published-toggle" onClick={() => setPublishedOpen((v) => !v)}>
            已发布 ({data.published.length}) {publishedOpen ? "▾" : "▸"}
          </button>
          {publishedOpen && (
            <ul className="llm-published-list">
              {data.published.map((p) => (
                <li key={p.kind + ":" + p.id}>
                  {p.kind === "authors" ? "作者" : p.kind === "works" ? "作品" : "涟漪"}
                  「{p.label}」 → #{shortId(p.public_id)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {confirmClear && (
        <div id="auth-modal">
          <div className="auth-modal-card">
            <h3>清空 AI 草稿</h3>
            <p>
              确定要清空您上传的 AI 草稿吗？将软删除您上传的全部草稿
              （作者/作品/涟漪），其他管理员与公共星云数据不受影响。
            </p>
            <div className="admin-modal-actions">
              <button
                className="del"
                onClick={() => {
                  setConfirmClear(false);
                  clearDrafts();
                }}
              >
                确认
              </button>
              <button onClick={() => setConfirmClear(false)}>取消</button>
            </div>
          </div>
        </div>
      )}

      {modal && (
        <NodeFormModal
          kind={modal.kind}
          mode="edit"
          initial={modal.row}
          apiBase="/api/admin/llm/drafts"
          authorsList={authorsList}
          worksList={worksList}
          edgesList={edgesList}
          isAdmin
          onClose={() => setModal(null)}
          onSaved={() => {
            setModal(null);
            onStatus("草稿已保存");
            reload();
          }}
        />
      )}
    </div>
  );
}
