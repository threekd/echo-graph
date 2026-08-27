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
  LlmDraftRipple,
  WorkRow,
} from "../../lib/adminTypes";
import { authorLabelOf, workLabel, AuthorPickerSingle, WorkPicker } from "./pickers";
import NodeFormModal, { type NodeKind } from "./NodeFormModal";

const shortId = (id: string): string => (id.length > 8 ? id.slice(0, 8) : id);

function hintText(hint: DedupeHint | null | undefined): string {
  if (!hint) return "";
  if (hint.level === "exact") return "将自动复用现有记录:" + hint.existing_label;
  if (hint.level === "exact_diff_author") return "同名异书:" + hint.existing_label;
  if (hint.level === "edge_duplicate") return "将自动复用现有涟漪:" + hint.existing_label;
  return "可能重复:" + hint.existing_label;
}

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
  const [confirmClear, setConfirmClear] = useState<{ workId: string; title: string } | null>(null);
  const [modal, setModal] = useState<EditModal | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [reuseSource, setReuseSource] = useState<{
    workId: string;
    title: string;
    currentLabel?: string;
  } | null>(null);
  const [reuseWorkId, setReuseWorkId] = useState("");
  const [reuseAuthor, setReuseAuthor] = useState<{
    authorId: string;
    label: string;
    currentLabel?: string;
  } | null>(null);
  const [reuseAuthorId, setReuseAuthorId] = useState("");
  const [batchFilter, setBatchFilter] = useState<Record<string, "approved" | "draft" | "rejected">>({});

  const load = useCallback(() => {
    setLoading(true);
    authFetch("/api/admin/llm/drafts")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((d: LlmDraftsData) => { setData(d); setLoading(false); })
      .catch((e: Error) => { onStatus("AI 草稿加载失败: " + e.message); setLoading(false); });
  }, [authFetch, onStatus]);

  useEffect(() => { load(); }, [load, reloadKey]);

  const reload = () => setReloadKey((k) => k + 1);

  const toggleCollapsed = (workId: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(workId)) next.delete(workId);
      else next.add(workId);
      return next;
    });
  };

  const call = (url: string, options?: RequestInit): Promise<any> =>
    authFetch(url, options).then(async (r) => {
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || "操作失败");
      return d;
    });

  const approveRipple = (edgeId: string) => {
    call("/api/admin/llm/ripples/" + encodeURIComponent(edgeId) + "/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then(() => {
        onStatus("涟漪已发布到公共星云(精确命中时已自动复用)");
        onPublicChanged();
        reload();
      })
      .catch((e: Error) => onStatus(e.message));
  };

  const approveSource = (workId: string) => {
    call("/api/admin/llm/source/" + encodeURIComponent(workId) + "/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then(() => {
        onStatus("源书已发布到公共星云(精确命中时已自动复用)");
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

  const clearDrafts = (workId?: string) => {
    call("/api/admin/llm/drafts/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(workId ? { work_id: workId } : {}),
    })
      .then((d: { counts?: Record<string, number> }) => {
        const c = d.counts || {};
        onStatus(
          (workId ? "该批次 AI 草稿已清空" : "AI 草稿已清空") +
          "(作者 " + (c.authors ?? 0) +
          " · 作品 " + (c.works ?? 0) +
          " · 涟漪 " + (c.edges ?? 0) + ")"
        );
        reload();
      })
      .catch((e: Error) => onStatus(e.message));
  };

  const confirmReuseSource = () => {
    if (!reuseSource || !reuseWorkId) return;
    const source = reuseSource;
    const targetId = reuseWorkId;
    call("/api/admin/llm/drafts/works/" + encodeURIComponent(source.workId) + "/reuse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reuse_id: targetId }),
    })
      .then(() => {
        const w = data?.space.works.find((x) => x.id === targetId);
        onStatus(
          "已复用《" + source.title + "》→ 已有作品《" +
          (w ? workLabel(w) : targetId) + "》，该批次涟漪将自动指向已有源书"
        );
        setReuseSource(null);
        setReuseWorkId("");
        reload();
      })
      .catch((e: Error) => onStatus(e.message));
  };

  const confirmReuseAuthor = () => {
    if (!reuseAuthor || !reuseAuthorId) return;
    const source = reuseAuthor;
    const targetId = reuseAuthorId;
    call("/api/admin/llm/drafts/authors/" + encodeURIComponent(source.authorId) + "/reuse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reuse_id: targetId }),
    })
      .then(() => {
        const a = data?.space.authors.find((x) => x.id === targetId);
        onStatus(
          "已复用作者「" + source.label + "」→ 已有作者「" +
          (a ? authorLabelOf(a) : targetId) + "」，该批次涟漪将自动指向该作者"
        );
        setReuseAuthor(null);
        setReuseAuthorId("");
        reload();
      })
      .catch((e: Error) => onStatus(e.message));
  };

  const counts = data?.counts;
  const reuseLabels = data?.reuse_labels;
  const sourceAuthorLabel = (a: AuthorRow): string => authorLabelOf(a);
  const workLabelOf = (w: WorkRow | undefined | null): string => (w ? workLabel(w) : "?");
  // 批次涟漪状态统计:批准(已发布映射)/ 草稿 / 驳回,按涟漪边计
  const batchStats = (b: LlmDraftBatch) => {
    const edges = b.ripples.map((r) => r.edge as unknown as {
      reviewStatus?: string;
      published_to_id?: string | null;
    });
    const approved = edges.filter((e) => Boolean(e.published_to_id)).length;
    const rejected = edges.filter((e) => e.reviewStatus === "rejected").length;
    const draft = edges.length - approved - rejected;
    return { approved, draft, rejected };
  };

  const rippleStatus = (r: LlmDraftRipple): "approved" | "draft" | "rejected" => {
    const e = r.edge as unknown as { reviewStatus?: string; published_to_id?: string | null };
    if (e.published_to_id) return "approved";
    if (e.reviewStatus === "rejected") return "rejected";
    return "draft";
  };

  const toggleBatchFilter = (workId: string, status: "approved" | "draft" | "rejected") => {
    setBatchFilter((prev) => {
      const next = { ...prev };
      if (next[workId] === status) delete next[workId];
      else next[workId] = status;
      return next;
    });
  };

  const mergeById = <T extends { id: string }>(...lists: T[][]): T[] =>
    Array.from(new Map(lists.flat().map((x) => [x.id, x] as const)).values());

  // 编辑弹窗下拉 = 审核人个人库全量(排除 AI 草稿,data.space)+ 批内 AI 草稿行(去重)
  const batchAuthors: AuthorRow[] = data
    ? data.batches.flatMap((b) => [
        ...b.source.authors,
        ...b.ripples.flatMap((r) => r.target?.authors || []),
      ])
    : [];
  const batchWorks: WorkRow[] = data
    ? data.batches.flatMap((b) => [
        { ...b.source.work, author_id: b.source.authors.map((a) => a.id).join(",") },
        ...b.ripples.flatMap((r) =>
          r.target
            ? [{ ...r.target.work, author_id: r.target.authors.map((a) => a.id).join(",") }]
            : []
        ),
      ])
    : [];
  const authorsList: AuthorRow[] = data ? mergeById(data.space?.authors ?? [], batchAuthors) : [];
  const worksList: WorkRow[] = data ? mergeById(data.space?.works ?? [], batchWorks) : [];
  const edgesList = data ? data.batches.flatMap((b) => b.ripples.map((r) => r.edge)) : [];

  const renderEntityActions = (batch: LlmDraftBatch) => {
    // 源书草稿已发布/已复用(published_to_id 非空):不再显示「批准源书」
    const sourcePublished = Boolean(batch.source.work.published_to_id);
    return (
    <span className="llm-actions">
      <button
        onClick={(e) => {
          e.stopPropagation();
          setModal({
            kind: "works",
            row: { ...batch.source.work, author_id: batch.source.authors.map((a) => a.id).join(",") } as AdminRow,
          });
        }}
      >
        编辑作品
      </button>
      {batch.source.authors.map((a) => (
        <button
          key={a.id}
          onClick={(e) => {
            e.stopPropagation();
            setModal({ kind: "authors", row: a as AdminRow });
          }}
        >
          编辑作者
        </button>
      ))}
      <button
        className="llm-clear"
        title="清空该批次(源书作者/作品与全部涟漪)的 AI 草稿"
        onClick={(e) => {
          e.stopPropagation();
          setConfirmClear({
            workId: batch.source.work.id,
            title: workLabelOf(batch.source.work),
          });
        }}
      >
        清空
      </button>
      {batch.ripples.length === 0 && !sourcePublished && (
        <>
          <button
            className="approve"
            onClick={(e) => {
              e.stopPropagation();
              approveSource(batch.source.work.id);
            }}
          >
            批准源书
          </button>
        </>
      )}
    </span>
    );
  };

  return (
    <div className="llm-drafts">
      <div className="llm-head">
        <p className="llm-tip">
          当前星云现有：
          作者 {data?.space_counts.authors ?? 0} · 作品 {data?.space_counts.works ?? 0}
          {counts
            ? `；草稿：批次 ${counts.batches} · 涟漪 ${counts.ripples}`
            : ""}
        </p>
        <div className="llm-toolbar">
          <span className="llm-toolbar-title">待审核批次</span>
        </div>
      </div>

      {loading ? (
        <p>加载中…</p>
      ) : !data || data.batches.length === 0 ? (
        <p className="llm-empty">暂无待审核的 AI 草稿，可先导入书籍。</p>
      ) : (
        data.batches.map((b) => {
          const workId = b.source.work.id;
          const isCollapsed = collapsed.has(workId);
          return (
          <div className={"llm-batch" + (isCollapsed ? " collapsed" : "")} key={workId}>
            <div
              className="llm-batch-head"
              onClick={() => toggleCollapsed(workId)}
              title={isCollapsed ? "展开该批次" : "收起该批次"}
            >
              <span className={"llm-collapse-indicator" + (isCollapsed ? "" : " open")} aria-hidden="true">▸</span>
              <button
                className="llm-batch-title llm-batch-title-btn"
                title={
                  b.source.work.published_to_id
                    ? "点击更换复用目标(当前已复用)"
                    : "点击选择库中已有作品进行复用(导入重复且未自动识别时,该批次涟漪将自动指向已有源书)"
                }
                onClick={(e) => {
                  e.stopPropagation();
                  setReuseSource({
                    workId: b.source.work.id,
                    title: workLabelOf(b.source.work),
                    currentLabel: b.source.work.published_to_id
                      ? reuseLabels?.works[b.source.work.published_to_id]
                      : undefined,
                  });
                  setReuseWorkId("");
                }}
              >
                《{workLabelOf(b.source.work)}》
                {b.source.work.published_to_id && (
                  <span className="llm-reuse-target">
                    → 已复用《{reuseLabels?.works[b.source.work.published_to_id] ?? "?"}》
                  </span>
                )}
              </button>
              <span className="llm-batch-meta">
                作者:
                {b.source.authors.length
                  ? b.source.authors.map((a, ai) => (
                      <span key={a.id}>
                        {ai > 0 && "、"}
                        <button
                          className="llm-batch-author-btn"
                          title={
                            a.published_to_id
                              ? "点击更换复用目标(当前已复用)"
                              : "点击选择库中已有作者进行复用(导入重复且未自动识别时,该批次涟漪将自动指向该作者)"
                          }
                          onClick={(e) => {
                            e.stopPropagation();
                            setReuseAuthor({
                              authorId: a.id,
                              label: authorLabelOf(a),
                              currentLabel: a.published_to_id
                                ? reuseLabels?.authors[a.published_to_id]
                                : undefined,
                            });
                            setReuseAuthorId("");
                          }}
                        >
                          {sourceAuthorLabel(a)}
                          {a.published_to_id && (
                            <span className="llm-reuse-target">
                              → 已复用《{reuseLabels?.authors[a.published_to_id] ?? "?"}》
                            </span>
                          )}
                        </button>
                      </span>
                    ))
                  : "未知"}
                {b.ripples.length > 0 &&
                  (() => {
                    const s = batchStats(b);
                    const active = batchFilter[b.source.work.id];
                    return (
                      <span className="llm-batch-stats">
                        <button
                          className={"ok" + (active === "approved" ? " active" : "")}
                          title="点击仅显示已批准涟漪,再点取消筛选"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleBatchFilter(b.source.work.id, "approved");
                          }}
                        >
                          批准 {s.approved}
                        </button>
                        <button
                          className={"draft" + (active === "draft" ? " active" : "")}
                          title="点击仅显示草稿涟漪,再点取消筛选"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleBatchFilter(b.source.work.id, "draft");
                          }}
                        >
                          草稿 {s.draft}
                        </button>
                        <button
                          className={"bad" + (active === "rejected" ? " active" : "")}
                          title="点击仅显示驳回涟漪,再点取消筛选"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleBatchFilter(b.source.work.id, "rejected");
                          }}
                        >
                          驳回 {s.rejected}
                        </button>
                      </span>
                    );
                  })()}
              </span>
              {renderEntityActions(b)}
            </div>

            {!isCollapsed && (
            <div className="llm-batch-body">
              {(() => {
                const filter = batchFilter[b.source.work.id];
                const visible = filter ? b.ripples.filter((r) => rippleStatus(r) === filter) : b.ripples;
                // 未处理(草稿)排前,已批准/已驳回沉到卡片底部(稳定排序,保持原相对顺序)
                const ordered = [...visible].sort((a, b) => {
                  const ad = rippleStatus(a) === "draft" ? 0 : 1;
                  const bd = rippleStatus(b) === "draft" ? 0 : 1;
                  return ad - bd;
                });
                return ordered.length === 0 ? (
                  <p className="llm-empty">该批次没有{filter === "approved" ? "已批准" : filter === "rejected" ? "已驳回" : "草稿"}涟漪</p>
                ) : ordered.map((r, ri) => {
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
                    {!published && r.target && (
                      <span className="llm-ripple-actions-left">
                        <button
                          title={"编辑目标作品 " + workLabelOf(r.target.work)}
                          onClick={() => setModal({
                            kind: "works",
                            row: { ...r.target!.work, author_id: r.target!.authors.map((a) => a.id).join(",") } as AdminRow,
                          })}
                        >
                          编辑作品
                        </button>
                        {r.target.authors.map((a) => (
                          <button
                            key={a.id}
                            title={"编辑目标作者 " + sourceAuthorLabel(a)}
                            onClick={() => setModal({ kind: "authors", row: a as AdminRow })}
                          >
                            编辑作者
                          </button>
                        ))}
                        <button
                          title="编辑涟漪(原文片段/出处/备注)"
                          onClick={() => setModal({ kind: "edges", row: r.edge as AdminRow })}
                        >
                          编辑涟漪
                        </button>
                      </span>
                    )}
                    <span className="llm-ripple-actions-right">
                      {published ? (
                        <span className="llm-published">
                          已发布
                          {(() => {
                            const pid = String((r.edge as unknown as Record<string, unknown>).published_to_id);
                            const label = reuseLabels?.works[pid];
                            return label ? "《" + label + "》" : " #" + shortId(pid);
                          })()}
                        </span>
                      ) : rejected ? (
                        <button onClick={() => reopen(r.edge.id)}>重开</button>
                      ) : (
                        <>
                          <button className="approve" onClick={() => approveRipple(r.edge.id)}>批准</button>
                          <button className="reject" onClick={() => reject(r.edge.id)}>驳回</button>
                        </>
                      )}
                    </span>
                  </div>
                  </div>
                );
                });
              })()}
            </div>
            )}
          </div>
          );
        })
      )}

      {confirmClear && (
        <div id="auth-modal">
          <div className="auth-modal-card">
            <h3>清空该批次 AI 草稿</h3>
            <p>
              确定要清空批次《{confirmClear.title}》的 AI 草稿吗？
              将软删除该批次上传的源书作者/作品与全部涟漪
              （作者/作品/涟漪），不影响其他批次与已发布数据。
            </p>
            <div className="admin-modal-actions">
              <button
                className="del"
                onClick={() => {
                  const target = confirmClear;
                  setConfirmClear(null);
                  clearDrafts(target.workId);
                }}
              >
                确认
              </button>
              <button onClick={() => setConfirmClear(null)}>取消</button>
            </div>
          </div>
        </div>
      )}

      {reuseSource && (
        <div id="auth-modal">
          <div className="auth-modal-card">
            <h3>{reuseSource.currentLabel ? "更换复用源书" : "复用已有源书"}</h3>
            <p>
              {reuseSource.currentLabel ? (
                <>
                  批次《{reuseSource.title}》当前已复用《{reuseSource.currentLabel}》。
                  选择新作品后将更新映射（已发布的涟漪不受影响）。
                </>
              ) : (
                <>
                  批次《{reuseSource.title}》与库中已有作品重复且未自动识别？
                  选择已有作品后，该批次所有涟漪将自动指向它（AI 草稿本身不复制、不修改）。
                </>
              )}
            </p>
            <WorkPicker
              value={reuseWorkId}
              onChange={setReuseWorkId}
              worksList={data?.space.works ?? []}
              placeholder="搜索并选择库中已有作品…"
            />
            <div className="admin-modal-actions">
              <button className="approve" disabled={!reuseWorkId} onClick={confirmReuseSource}>
                确认复用
              </button>
              <button
                onClick={() => {
                  setReuseSource(null);
                  setReuseWorkId("");
                }}
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}

      {reuseAuthor && (
        <div id="auth-modal">
          <div className="auth-modal-card">
            <h3>{reuseAuthor.currentLabel ? "更换复用作者" : "复用已有作者"}</h3>
            <p>
              {reuseAuthor.currentLabel ? (
                <>
                  批次源书作者「{reuseAuthor.label}」当前已复用《{reuseAuthor.currentLabel}》。
                  选择新作者后将更新映射（已发布的涟漪不受影响）。
                </>
              ) : (
                <>
                  批次源书作者「{reuseAuthor.label}」与库中已有作者重复且未自动识别？
                  选择已有作者后，该批次涟漪将自动指向它（AI 草稿本身不复制、不修改）。
                </>
              )}
            </p>
            <AuthorPickerSingle
              value={reuseAuthorId}
              onChange={setReuseAuthorId}
              authorsList={data?.space.authors ?? []}
              placeholder="搜索并选择库中已有作者…"
            />
            <div className="admin-modal-actions">
              <button className="approve" disabled={!reuseAuthorId} onClick={confirmReuseAuthor}>
                确认复用
              </button>
              <button
                onClick={() => {
                  setReuseAuthor(null);
                  setReuseAuthorId("");
                }}
              >
                取消
              </button>
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
