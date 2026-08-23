/* 点亮星空:往自己的星云添加涟漪(登录后可用,不再是贡献收件箱)。
   作品/作者只接受「本人星云已有数据」;输入未知名称时提交会被拦截,
   自动弹出标准新增弹窗(与数据管理共用),必须按新增页面完整填写后才允许保存,
   不允许静默补建最小字段的空白行。 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { AdminRow, AuthorRow, WorkRow } from "../lib/adminTypes";
import { useApp, type GraphNode } from "../store";
import { loadMyRows, type SpaceRows } from "../lib/api";
import { refreshSpaceGraph } from "../lib/graph";
import {
  authorSuggestionLabel,
  authorSuggestionLabels,
  workAuthorNames,
  workSuggestionLabel,
  workSuggestionLabels,
} from "../lib/contributeSuggestions";
import NodeFormModal from "./admin/NodeFormModal";

const EMPTY = {
  source_work: "",
  source_author: "",
  target_work: "",
  target_author: "",
  evidence: "",
  evidence_source: "",
  note: "",
};

// 组合框:可下拉选择已有数据,也允许自由输入新名称;无匹配时提供「添加新节点」入口
function SuggestionInput({
  value,
  onChange,
  suggestions,
  placeholder,
  onPick,
  addLabel,
  onAdd,
  id,
  missing,
}: {
  value: string;
  onChange: (v: string) => void;
  suggestions: string[];
  placeholder: string;
  onPick?: (label: string) => void;
  addLabel?: string;
  onAdd?: (query: string) => void;
  id?: string;
  missing?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [dir, setDir] = useState<"up" | "down">("down");
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const q = value.trim().toLowerCase();
  const filtered = q
    ? suggestions.filter((s) => s.toLowerCase().includes(q)).slice(0, 50)
    : suggestions.slice(0, 50);
  const showAdd = Boolean(onAdd && addLabel && q && filtered.length === 0);

  // 按剩余空间决定下拉方向,避免溢出弹窗卡片触发滚动条导致整体布局抖动
  const openList = () => {
    const el = wrapRef.current;
    if (!el) {
      setOpen(true);
      return;
    }
    const rect = el.getBoundingClientRect();
    const card = el.closest(".admin-modal-card");
    const cardRect = card ? card.getBoundingClientRect() : { top: 0, bottom: window.innerHeight };
    const below = cardRect.bottom - rect.bottom;
    const above = rect.top - cardRect.top;
    setDir(above > below ? "up" : "down");
    setOpen(true);
  };

  const pick = (label: string) => {
    onChange(label);
    setOpen(false);
    setActive(-1);
    if (onPick) onPick(label);
  };

  return (
    <div className={"suggest-input" + (missing ? " missing" : "")} ref={wrapRef}>
      <input
        id={id}
        value={value}
        placeholder={placeholder}
        onChange={(e) => { onChange(e.target.value); setOpen(true); setActive(-1); }}
        onFocus={openList}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "Escape") { setOpen(false); return; }
          if (showAdd && filtered.length === 0 && e.key === "Enter") {
            e.preventDefault();
            setOpen(false);
            onAdd!(value.trim());
            return;
          }
          if (!filtered.length) return;
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((v) => (v + 1) % filtered.length);
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((v) => (v - 1 + filtered.length) % filtered.length);
          } else if (e.key === "Enter" && active >= 0 && filtered[active]) {
            e.preventDefault();
            pick(filtered[active]);
          }
        }}
      />
      {open && (filtered.length > 0 || showAdd) && (
        <ul className={"suggest-results" + (dir === "up" ? " up" : "")}>
          {showAdd && (
            <li
              className="add-option"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => { setOpen(false); onAdd!(value.trim()); }}
            >
              ＋ {addLabel}
            </li>
          )}
          {filtered.map((s, i) => (
            <li
              key={s}
              className={i === active ? "active" : undefined}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => pick(s)}
            >
              {s}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function Contribute() {
  const { state, dispatch } = useApp();
  const [form, setForm] = useState({ ...EMPTY });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [myRows, setMyRows] = useState<SpaceRows | null>(null);
  // 提交时缺失的必填项(用于逐字段提示与高亮)
  const [missingKeys, setMissingKeys] = useState<string[]>([]);
  // 标准新增弹窗:{ kind, initial, target } —— target 记录从哪个下拉框发起
  const [addModal, setAddModal] = useState<{
    kind: "authors" | "works";
    initial: Partial<AdminRow>;
    target: string;
  } | null>(null);
  // 本次会话中通过新增弹窗创建的行(标签 -> id),保证刚创建后立即提交也能解析
  const createdRef = useRef<Map<string, string>>(new Map());
  // 新增弹窗内创建的作者(id -> 展示名),用于把新作品的作者回填到主表单
  const createdAuthorNamesRef = useRef<Map<string, string>>(new Map());

  // 打开时拉取本人空间行数据(下拉列表只来自本人数据,与数据管理页一致)
  useEffect(() => {
    if (!state.contributeOpen) return;
    loadMyRows().then(setMyRows).catch(() => setMyRows(null));
  }, [state.contributeOpen]);

  const refreshRows = (): Promise<void> =>
    loadMyRows().then(setMyRows).catch(() => setMyRows(null));

  // 行数据 → 图节点形状,复用既有建议文案逻辑
  const authorNodes = useMemo<GraphNode[]>(
    () => (myRows?.authors || [])
      .filter((a) => !a.deletedAt) // 软删除行不进联想下拉
      .map((a) => ({
        id: a.id, type: "author", label: a.Name_CN,
        originalName: a.originalName, nationality: a.nationality,
      })),
    [myRows]
  );
  const workNodes = useMemo<GraphNode[]>(
    () => (myRows?.works || [])
      .filter((w) => !w.deletedAt) // 软删除行不进联想下拉
      .map((w) => ({
        id: w.id, type: "work", label: w.Title_CN,
        originalTitle: w.originalTitle, language: w.language,
        author_ids: w.author_ids,
      })),
    [myRows]
  );
  const authorsById = useMemo(() => {
    const map: Record<string, GraphNode> = {};
    authorNodes.forEach((n) => { map[n.id] = n; });
    return map;
  }, [authorNodes]);
  const authorsByLabel = useMemo(() => {
    const map = new Map<string, GraphNode>();
    authorNodes.forEach((n) => {
      const label = authorSuggestionLabel(n);
      if (label && !map.has(label)) map.set(label, n);
    });
    return map;
  }, [authorNodes]);
  const worksByLabel = useMemo(() => {
    const map = new Map<string, GraphNode>();
    workNodes.forEach((n) => {
      const label = workSuggestionLabel(n);
      if (label && !map.has(label)) map.set(label, n);
    });
    return map;
  }, [workNodes]);
  const workSuggestions = useMemo(() => workSuggestionLabels(workNodes), [workNodes]);
  const authorSuggestions = useMemo(() => authorSuggestionLabels(authorNodes), [authorNodes]);

  if (!state.contributeOpen) return null;

  const set = (key: string, value: string) => {
    setForm((f) => ({ ...f, [key]: value }));
    if (value.trim()) {
      // 已填写的字段从缺失清单移除,并清掉旧错误提示
      setMissingKeys((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : prev));
      if (error) setError("");
    }
  };

  // 必填项:key 与表单字段一致,label 用于提示文案
  const REQUIRED_FIELDS: { key: keyof typeof EMPTY; label: string }[] = [
    { key: "source_work", label: "源作品" },
    { key: "source_author", label: "源作品作者" },
    { key: "target_work", label: "目标作品" },
    { key: "target_author", label: "目标作品作者" },
    { key: "evidence", label: "原文片段" },
    { key: "evidence_source", label: "出处" },
  ];

  // 选中已有作品时自动填充其关联作者(多人用"、"连接;无作者信息时不动)
  const fillWorkAuthor = (which: "source" | "target") => (label: string) => {
    const node = worksByLabel.get(label);
    if (!node) return;
    const names = workAuthorNames(node, authorsById);
    if (names.length) set(which === "source" ? "source_author" : "target_author", names.join("、"));
  };

  // 发起「添加新作品 / 新作者」:打开标准新增弹窗,预填当前输入;
  // 新增作品时若对应的作者已是本空间已有数据,一并预填作者关联
  const openAddNode = (target: string, kind: "authors" | "works", query: string) => {
    if (kind === "works") {
      const authorField = target === "source_work" ? "source_author" : "target_author";
      const author = authorsByLabel.get(String(form[authorField] || "").trim());
      setAddModal({
        kind,
        target,
        initial: {
          originalTitle: query,
          author_id: author ? author.id : undefined, // 仅当作者已存在时可预填
        },
      });
      return;
    }
    setAddModal({
      kind,
      target,
      initial: { originalName: query }, // 新增作者只预填原著名,中文名留空由用户填写
    });
  };

  const nodeLabelOf = (kind: "authors" | "works", row: AdminRow): string => {
    if (kind === "authors") {
      const a = row as AuthorRow;
      return authorSuggestionLabel({
        id: a.id, type: "author", label: a.Name_CN,
        originalName: a.originalName, nationality: a.nationality,
      });
    }
    const w = row as WorkRow;
    return workSuggestionLabel({
      id: w.id, type: "work", label: w.Title_CN,
      originalTitle: w.originalTitle, language: w.language,
    });
  };

  const postRow = async (path: string, body: any): Promise<any> => {
    const r = await fetch("/api/me/" + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "保存失败");
    return d.row;
  };

  // 按标签解析作者:只接受本人星云已有数据(新增必须走标准新增弹窗)
  const ensureAuthor = (label: string): string | null => {
    const key = label.trim();
    const existing = authorsByLabel.get(key);
    if (existing) return existing.id;
    return createdRef.current.get(key) || null;
  };

  // 按标签解析作品:同上,只接受已有数据
  const ensureWork = (label: string): string | null => {
    const key = label.trim();
    const existing = worksByLabel.get(key);
    if (existing) return existing.id;
    return createdRef.current.get(key) || null;
  };

  const doSubmit = async () => {
    setError("");
    const missing = REQUIRED_FIELDS.filter((f) => !String(form[f.key] || "").trim()).map((f) => f.key);
    if (missing.length) {
      const labels = REQUIRED_FIELDS.filter((f) => missing.includes(f.key)).map((f) => f.label);
      setMissingKeys(missing);
      setError("请填写:" + labels.map((l) => `「${l}」`).join("、"));
      // 聚焦第一个缺失输入框,便于直接补填
      const first = REQUIRED_FIELDS.find((f) => missing.includes(f.key));
      if (first) {
        setTimeout(() => document.getElementById("field-" + first.key)?.focus(), 0);
      }
      return;
    }
    setMissingKeys([]);
    const sourceWorkId = ensureWork(form.source_work);
    if (!sourceWorkId) {
      setError(`「${form.source_work.trim()}」不是已存在的作品,请在弹出的新增窗口中完整填写后保存`);
      openAddNode("source_work", "works", form.source_work.trim());
      return;
    }
    const sourceAuthorId = ensureAuthor(form.source_author);
    if (!sourceAuthorId) {
      setError(`「${form.source_author.trim()}」不是已存在的作者,请在弹出的新增窗口中完整填写后保存`);
      openAddNode("source_author", "authors", form.source_author.trim());
      return;
    }
    const targetWorkId = ensureWork(form.target_work);
    if (!targetWorkId) {
      setError(`「${form.target_work.trim()}」不是已存在的作品,请在弹出的新增窗口中完整填写后保存`);
      openAddNode("target_work", "works", form.target_work.trim());
      return;
    }
    const targetAuthorId = ensureAuthor(form.target_author);
    if (!targetAuthorId) {
      setError(`「${form.target_author.trim()}」不是已存在的作者,请在弹出的新增窗口中完整填写后保存`);
      openAddNode("target_author", "authors", form.target_author.trim());
      return;
    }
    if (sourceWorkId === targetWorkId) {
      setError("源作品与目标作品不能相同");
      return;
    }
    setBusy(true);
    try {
      await postRow("edges", {
        source_work_id: sourceWorkId,
        target_work_id: targetWorkId,
        evidence: form.evidence,
        evidenceSource: form.evidence_source,
        note: form.note || null,
      });
      setForm({ ...EMPTY });
      dispatch({ type: "SET_CONTRIBUTE", open: false });
      const fresh = await loadMyRows();
      setMyRows(fresh);
      try {
        // 写入本人星云后刷新图谱(admin 的「我的星云」与公共星云同源)
        if (state.space === "mine" || (state.user?.role === "admin" && state.space === "public")) {
          refreshSpaceGraph();
        }
      } catch {
        /* 图谱视图刷新失败不影响添加结果 */
      }
      dispatch({ type: "SET_TOAST", msg: "已添加到你的星云", kind: "success" });
    } catch (e: any) {
      setError(e && e.message ? e.message : "添加失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div id="admin-modal" style={{ display: "flex" }}>
        <div className="admin-modal-card">
          <h3>点亮星空(添加到我的星云)</h3>
          <p className="contribute-hint">
            以下内容会直接加入你的星云(仅本人可见),之后可在「数据管理」中继续编辑。
            下拉列表来自你自己的星云数据;搜不到时第一行「添加新作品 / 新作者」
            会打开标准新增页面——新名称必须按新增页面完整填写后才会保存,不会自动创建。
          </p>
          <div id="admin-form">
            <label>
              <span>源作品 <span className="req">*</span></span>
              <SuggestionInput
                id="field-source_work"
                missing={missingKeys.includes("source_work")}
                value={form.source_work}
                onChange={(v) => set("source_work", v)}
                suggestions={workSuggestions}
                placeholder=""
                onPick={fillWorkAuthor("source")}
                addLabel={"添加新作品「" + form.source_work.trim() + "」"}
                onAdd={(q) => openAddNode("source_work", "works", q)}
              />
            </label>
            <label>
              <span>源作品作者 <span className="req">*</span></span>
              <SuggestionInput
                id="field-source_author"
                missing={missingKeys.includes("source_author")}
                value={form.source_author}
                onChange={(v) => set("source_author", v)}
                suggestions={authorSuggestions}
                placeholder=""
                addLabel={"添加新作者「" + form.source_author.trim() + "」"}
                onAdd={(q) => openAddNode("source_author", "authors", q)}
              />
            </label>
            <label>
              <span>目标作品 <span className="req">*</span></span>
              <SuggestionInput
                id="field-target_work"
                missing={missingKeys.includes("target_work")}
                value={form.target_work}
                onChange={(v) => set("target_work", v)}
                suggestions={workSuggestions}
                placeholder=""
                onPick={fillWorkAuthor("target")}
                addLabel={"添加新作品「" + form.target_work.trim() + "」"}
                onAdd={(q) => openAddNode("target_work", "works", q)}
              />
            </label>
            <label>
              <span>目标作品作者 <span className="req">*</span></span>
              <SuggestionInput
                id="field-target_author"
                missing={missingKeys.includes("target_author")}
                value={form.target_author}
                onChange={(v) => set("target_author", v)}
                suggestions={authorSuggestions}
                placeholder=""
                addLabel={"添加新作者「" + form.target_author.trim() + "」"}
                onAdd={(q) => openAddNode("target_author", "authors", q)}
              />
            </label>
            <label className="full">
              <span>原文片段 <span className="req">*</span></span>
              <textarea
                id="field-evidence"
                className={missingKeys.includes("evidence") ? "missing" : undefined}
                value={form.evidence}
                onChange={(e) => set("evidence", e.target.value)}
                placeholder="作品正文中提及另一部作品的原文片段"
              />
            </label>
            <label>
              <span>出处 <span className="req">*</span></span>
              <input
                id="field-evidence_source"
                className={missingKeys.includes("evidence_source") ? "missing" : undefined}
                value={form.evidence_source}
                onChange={(e) => set("evidence_source", e.target.value)}
                placeholder="章节-译本"
              />
            </label>
            <label className="full">
              <span>备注</span>
              <textarea
                value={form.note}
                onChange={(e) => set("note", e.target.value)}
                placeholder="补充说明(可选)"
              />
            </label>
          </div>
          {error && <div id="admin-form-errors">{error}</div>}
          <div className="admin-modal-actions">
            <button onClick={doSubmit} disabled={busy}>{busy ? "添加中…" : "添加到我的星云"}</button>
            <button onClick={() => dispatch({ type: "SET_CONTRIBUTE", open: false })}>取消</button>
          </div>
        </div>
      </div>
      {addModal && (
        <NodeFormModal
          kind={addModal.kind}
          mode="add"
          initial={addModal.initial}
          apiBase="/api/me"
          authorsList={myRows?.authors || []}
          worksList={myRows?.works || []}
          edgesList={myRows?.edges || []}
          isAdmin={false}
          onClose={() => setAddModal(null)}
          onAuthorAdded={(row) => {
            // 登记本次会话新建的作者,便于新作品的作者回填与提交时解析
            const a = row as AuthorRow;
            const label = authorSuggestionLabel({
              id: a.id, type: "author", label: a.Name_CN,
              originalName: a.originalName, nationality: a.nationality,
            });
            if (label) {
              createdRef.current.set(label, a.id);
              createdAuthorNamesRef.current.set(a.id, label);
            }
            refreshRows();
          }}
          onSaved={(row) => {
            const label = nodeLabelOf(addModal.kind, row);
            if (label) createdRef.current.set(label, row.id);
            set(addModal.target, label || "");
            // 新增作品后把其作者回填到对应的作者输入框(避免二次手填)
            if (addModal.kind === "works") {
              const w = row as WorkRow;
              const authorField = addModal.target === "source_work" ? "source_author" : "target_author";
              const names = (w.author_ids || [])
                .map((id) => {
                  const n = authorsById[id];
                  return n ? authorSuggestionLabel(n) : (createdAuthorNamesRef.current.get(id) || "");
                })
                .filter(Boolean);
              if (names.length) set(authorField, names.join("、"));
            }
            setAddModal(null);
            dispatch({ type: "SET_TOAST", msg: "已添加,可继续填写", kind: "success" });
            refreshRows();
          }}
        />
      )}
    </>
  );
}
