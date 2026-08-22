/* 点亮星空:往自己的星云添加数据(登录后可用,不再是贡献收件箱)。
   提交时自动补齐缺失的作者/作品并建立涟漪;下拉框无匹配时第一行提供
   「添加新作品 / 新作者」入口,弹出标准新增弹窗(与数据管理共用)。 */

import { useEffect, useMemo, useState } from "react";
import { useApp, type GraphData, type GraphNode } from "../store";
import { loadGraphData, loadMyRows, type SpaceRows } from "../lib/api";
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
}: {
  value: string;
  onChange: (v: string) => void;
  suggestions: string[];
  placeholder: string;
  onPick?: (label: string) => void;
  addLabel?: string;
  onAdd?: (query: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const q = value.trim().toLowerCase();
  const filtered = q
    ? suggestions.filter((s) => s.toLowerCase().includes(q)).slice(0, 50)
    : suggestions.slice(0, 50);
  const showAdd = Boolean(onAdd && addLabel && q && filtered.length === 0);

  const pick = (label: string) => {
    onChange(label);
    setOpen(false);
    setActive(-1);
    if (onPick) onPick(label);
  };

  return (
    <div className="suggest-input">
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => { onChange(e.target.value); setOpen(true); setActive(-1); }}
        onFocus={() => setOpen(true)}
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
        <ul className="suggest-results">
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
  const [publicData, setPublicData] = useState<GraphData | null>(null);
  // 标准新增弹窗:{ kind, initial, target } —— target 记录从哪个下拉框发起
  const [addModal, setAddModal] = useState<{
    kind: "authors" | "works";
    initial: any;
    target: string;
  } | null>(null);

  // 打开时拉取本人空间行数据 + 公共星云(下拉列表合并两者,供搜索/筛选)
  useEffect(() => {
    if (!state.contributeOpen) return;
    loadMyRows().then(setMyRows).catch(() => setMyRows(null));
    loadGraphData("public").then(setPublicData).catch(() => setPublicData(null));
  }, [state.contributeOpen]);

  const refreshRows = (): Promise<void> =>
    loadMyRows().then(setMyRows).catch(() => setMyRows(null));

  // 行数据 → 图节点形状,复用既有建议文案逻辑
  const authorNodes = useMemo<GraphNode[]>(
    () => (myRows?.authors || []).map((a) => ({
      id: a.id, type: "author", label: a.Name_CN,
      originalName: a.originalName, nationality: a.nationality,
    })),
    [myRows]
  );
  const workNodes = useMemo<GraphNode[]>(
    () => (myRows?.works || []).map((w) => ({
      id: w.id, type: "work", label: w.Title_CN,
      originalTitle: w.originalTitle, language: w.language,
      author_ids: w.author_ids, author: w.author,
    })),
    [myRows]
  );
  const publicAuthorNodes = useMemo<GraphNode[]>(
    () => (publicData?.nodes || []).filter((n): n is GraphNode => n.type === "author"),
    [publicData]
  );
  const publicWorkNodes = useMemo<GraphNode[]>(
    () => (publicData?.nodes || []).filter((n): n is GraphNode => n.type === "work"),
    [publicData]
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
  const publicAuthorsById = useMemo(() => {
    const map: Record<string, GraphNode> = {};
    publicAuthorNodes.forEach((n) => { map[n.id] = n; });
    return map;
  }, [publicAuthorNodes]);
  const publicAuthorsByLabel = useMemo(() => {
    const map = new Map<string, GraphNode>();
    publicAuthorNodes.forEach((n) => {
      const label = authorSuggestionLabel(n);
      if (label && !map.has(label)) map.set(label, n);
    });
    return map;
  }, [publicAuthorNodes]);
  const publicWorksByLabel = useMemo(() => {
    const map = new Map<string, GraphNode>();
    publicWorkNodes.forEach((n) => {
      const label = workSuggestionLabel(n);
      if (label && !map.has(label)) map.set(label, n);
    });
    return map;
  }, [publicWorkNodes]);

  const workSuggestions = useMemo(
    () => {
      const mine = workSuggestionLabels(workNodes);
      return [...mine, ...workSuggestionLabels(publicWorkNodes).filter((l) => !mine.includes(l))];
    },
    [workNodes, publicWorkNodes]
  );
  const authorSuggestions = useMemo(
    () => {
      const mine = authorSuggestionLabels(authorNodes);
      return [...mine, ...authorSuggestionLabels(publicAuthorNodes).filter((l) => !mine.includes(l))];
    },
    [authorNodes, publicAuthorNodes]
  );

  if (!state.contributeOpen) return null;

  const set = (key: string, value: string) => setForm((f) => ({ ...f, [key]: value }));

  // 选中已有作品时自动填充其关联作者(多人用"、"连接;无作者信息时不动)
  const fillWorkAuthor = (which: "source" | "target") => (label: string) => {
    const node = worksByLabel.get(label) || publicWorksByLabel.get(label);
    if (!node) return;
    const names = workAuthorNames(node, { ...authorsById, ...publicAuthorsById });
    if (names.length) set(which === "source" ? "source_author" : "target_author", names.join("、"));
  };

  // 发起「添加新作品 / 新作者」:打开标准新增弹窗,预填当前输入
  const openAddNode = (target: string, kind: "authors" | "works", query: string) => {
    setAddModal({
      kind,
      target,
      initial: kind === "works" ? { Title_CN: query, originalTitle: query } : { Name_CN: query, originalName: query },
    });
  };

  const nodeLabelOf = (kind: "authors" | "works", row: any): string => {
    if (kind === "authors") {
      return authorSuggestionLabel({
        id: row.id, type: "author", label: row.Name_CN,
        originalName: row.originalName, nationality: row.nationality,
      });
    }
    return workSuggestionLabel({
      id: row.id, type: "work", label: row.Title_CN,
      originalTitle: row.originalTitle, language: row.language,
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

  // 复制公共星云作者到本人空间(下拉选中公共数据时的归属要求)
  const copyPublicAuthorNode = async (an: GraphNode): Promise<string> => {
    const existing = authorsByLabel.get(authorSuggestionLabel(an));
    if (existing) return existing.id;
    const row = await postRow("authors", {
      originalName: an.originalName || an.label,
      Name_CN: an.label,
      Name_EN: (an as any).label_en || null,
      nationality: an.nationality || null,
    });
    return row.id;
  };

  // 按标签解析或创建作者:本人空间 > 公共星云(复制) > 新建
  const ensureAuthor = async (label: string): Promise<string> => {
    const existing = authorsByLabel.get(label.trim());
    if (existing) return existing.id;
    const pub = publicAuthorsByLabel.get(label.trim());
    if (pub) return copyPublicAuthorNode(pub);
    const row = await postRow("authors", { originalName: label.trim(), Name_CN: label.trim() });
    return row.id;
  };

  // 按标签解析或创建作品:本人空间 > 公共星云(连同作者一起复制) > 新建
  const ensureWork = async (label: string, typedAuthor: string): Promise<string> => {
    const existing = worksByLabel.get(label.trim());
    if (existing) return existing.id;
    const pub = publicWorksByLabel.get(label.trim());
    if (pub) {
      const authorIds: string[] = [];
      for (const aid of pub.author_ids || []) {
        const an = publicAuthorsById[aid];
        if (an) authorIds.push(await copyPublicAuthorNode(an));
      }
      if (!authorIds.length) {
        authorIds.push(await ensureAuthor(typedAuthor));
      }
      const row = await postRow("works", {
        language: pub.language || "zh",
        originalTitle: pub.originalTitle || pub.label,
        Title_CN: pub.label,
        Title_EN: (pub as any).label_en || null,
        publicationYear: (pub as any).publicationYear || null,
        creationYear: (pub as any).creationYear || null,
        genre: (pub as any).genre || null,
        author_id: authorIds.join(","),
      });
      return row.id;
    }
    const authorId = await ensureAuthor(typedAuthor);
    const row = await postRow("works", {
      language: "zh",
      originalTitle: label.trim(),
      Title_CN: label.trim(),
      author_id: authorId,
    });
    return row.id;
  };

  const doSubmit = async () => {
    setError("");
    if (
      !form.source_work.trim() || !form.source_author.trim() ||
      !form.target_work.trim() || !form.target_author.trim() ||
      !form.evidence.trim() || !form.evidence_source.trim()
    ) {
      setError("请填写源作品、源作品作者、目标作品、目标作品作者、原文片段与出处");
      return;
    }
    setBusy(true);
    try {
      const sourceWorkId = await ensureWork(form.source_work, form.source_author);
      const targetWorkId = await ensureWork(form.target_work, form.target_author);
      if (sourceWorkId === targetWorkId) throw new Error("源作品与目标作品不能相同");
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
        if (state.space === "mine") {
          const data = await loadGraphData("mine");
          dispatch({ type: "SET_DATA", data });
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
            下拉列表合并公共星云与你的数据(选中公共作品/作者会自动复制一份到你的星云);
            搜不到时第一行可打开标准新增弹窗,也可直接输入新名称提交。
          </p>
          <div id="admin-form">
            <label>
              <span>源作品 <span className="req">*</span></span>
              <SuggestionInput
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
                value={form.evidence}
                onChange={(e) => set("evidence", e.target.value)}
                placeholder="作品正文中提及另一部作品的原文片段"
              />
            </label>
            <label>
              <span>出处 <span className="req">*</span></span>
              <input
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
          onSaved={(row) => {
            const label = nodeLabelOf(addModal.kind, row);
            set(addModal.target, label || "");
            setAddModal(null);
            dispatch({ type: "SET_TOAST", msg: "已添加,可继续填写", kind: "success" });
            refreshRows();
          }}
        />
      )}
    </>
  );
}
