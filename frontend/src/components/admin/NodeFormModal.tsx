/* 标准节点表单弹窗:新增/编辑作者、作品、涟漪(数据管理与点亮星空共用)。
   通过 apiBase 区分空间:/api/me(个人空间)或 /api/admin(公共星云)。 */

import { useState } from "react";
import type { AdminRow, AuthorRow, EdgeRow, WorkRow } from "../../lib/adminTypes";
import {
  AuthorPicker,
  CodePicker,
  COUNTRY_OPTIONS,
  countryLabel,
  LANG_OPTIONS,
  langLabel,
  WorkPicker,
} from "./pickers";

export type NodeKind = "authors" | "works" | "edges";

// 本空间已有数据的联想下拉:输入时列出已有作者/作品,选中时提示数据已存在(新增必然是新的)
function OwnSuggestField<T extends AdminRow>({
  value,
  onChange,
  options,
  getLabel,
  getFill,
  placeholder,
  maxLength,
  onPickExisting,
}: {
  value: string;
  onChange: (v: string) => void;
  options: T[];
  getLabel: (item: T) => string;
  getFill?: (item: T) => string;
  placeholder?: string;
  maxLength?: number;
  onPickExisting: (item: T) => void;
}) {
  const [open, setOpen] = useState(false);
  const q = value.trim().toLowerCase();
  const filtered = q ? options.filter((o) => getLabel(o).toLowerCase().includes(q)).slice(0, 50) : [];
  return (
    <div className="suggest-input">
      <input
        value={value}
        placeholder={placeholder}
        maxLength={maxLength}
        onChange={(e) => { onChange(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && filtered.length > 0 && (
        <ul className="suggest-results">
          {filtered.map((o) => (
            <li
              key={o.id}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                onChange(getFill ? getFill(o) : getLabel(o));
                onPickExisting(o);
                setOpen(false);
              }}
            >
              {getLabel(o)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const ownAuthorLabel = (a: AuthorRow) =>
  [a.originalName || "", a.Name_CN || ""].filter(Boolean).join(" · ");
const ownWorkLabel = (w: WorkRow) =>
  [w.originalTitle || "", w.Title_CN || ""].filter(Boolean).join(" · ");

const KIND_LABELS: Record<NodeKind, string> = {
  authors: "作者",
  works: "作品",
  edges: "涟漪",
};

interface FieldDef {
  key: string;
  label: string;
  required?: boolean;
  type?:
    | "number"
    | "select"
    | "textarea"
    | "workPicker"
    | "authorPicker"
    | "languagePicker"
    | "countryPicker"
    | "divider"
    | "readingStatus"
    | "recommendation";
  options?: string[];
  min?: number;
  max?: number;
  step?: number;
  maxLength?: number;
}

// 表单字段配置(与后端字段一一对应)
const FIELDS: Record<NodeKind, FieldDef[]> = {
  authors: [
    { key: "originalName", label: "原文名", required: true },
    { key: "nationality", label: "国家", type: "countryPicker" },
    { key: "Name_CN", label: "中文名", required: true },
    { key: "Name_EN", label: "英文名" },
    { key: "birthYear", label: "出生年份", type: "number", min: -9999, max: 9999 },
    { key: "deathYear", label: "去世年份", type: "number", min: -9999, max: 9999 },
    { key: "note", label: "备注", type: "textarea" },
    { key: "reviewStatus", label: "审核状态", type: "select", options: ["draft", "reviewed", "rejected"] },
  ],
  works: [
    { key: "originalTitle", label: "原著标题", required: true, maxLength: 200 },
    { key: "language", label: "原著语言", required: true, type: "languagePicker" },
    { key: "Title_CN", label: "中文名", required: true },
    { key: "Title_EN", label: "英文名" },
    { key: "Title_Other", label: "其他标题" },
    { key: "author_id", label: "作者", required: true, type: "authorPicker" },
    { key: "publicationYear", label: "出版年份", type: "number" },
    { key: "genre", label: "体裁", type: "select", options: ["Fiction", "Non-fiction", "Poetry", "Drama"] },
    { key: "readingStatus", label: "阅读状态", type: "readingStatus" },
    { key: "recommendation", label: "评分", type: "recommendation" },
    { key: "review", label: "评价", type: "textarea", maxLength: 2000 },
    { key: "note", label: "备注", type: "textarea" },
    { key: "reviewStatus", label: "审核状态", type: "select", options: ["draft", "reviewed", "rejected"] },
  ],
  edges: [
    { key: "source_work_id", label: "源作品", required: true, type: "workPicker" },
    { key: "target_work_id", label: "目标作品", required: true, type: "workPicker" },
    { key: "evidence", label: "原文片段", required: true, type: "textarea" },
    { key: "evidenceSource", label: "出处", required: true },
    { key: "note", label: "备注" },
    { key: "reviewStatus", label: "审核", type: "select", options: ["draft", "reviewed", "rejected"] },
  ],
};

const DUP_FIELDS: Record<NodeKind, string[]> = {
  authors: ["Name_CN", "originalName"],
  works: ["Title_CN", "originalTitle"],
  edges: [],
};

export default function NodeFormModal({
  kind,
  mode,
  initial,
  apiBase,
  authorsList,
  worksList,
  edgesList,
  isAdmin,
  onClose,
  onSaved,
  onReload,
  onDelete,
  onAuthorAdded,
  onWorkAdded,
}: {
  kind: NodeKind;
  mode: "add" | "edit";
  initial: Partial<AdminRow>;
  apiBase: string;
  authorsList: AuthorRow[];
  worksList: WorkRow[];
  edgesList: EdgeRow[];
  isAdmin: boolean;
  onClose: () => void;
  onSaved: (row: AdminRow) => void;
  onReload?: () => void;
  onDelete?: (row: AdminRow) => void;
  onAuthorAdded?: (row: AuthorRow) => void;
  onWorkAdded?: (row: WorkRow) => void;
}) {
  const [form, setForm] = useState<any>({ ...initial });
  const [formError, setFormError] = useState("");
  const [dupHints, setDupHints] = useState<Record<string, string>>({});
  const [confirmReload, setConfirmReload] = useState(false);
  // 新增作品时搜不到作者:内嵌「添加新作者」弹窗(与点亮星空同一模式)
  const [authorAdd, setAuthorAdd] = useState<string | null>(null);
  // 新增涟漪时源/目标作品搜不到:内嵌「添加新作品」弹窗(与点亮星空同一模式)
  const [workAdd, setWorkAdd] = useState<{ field: string; query: string } | null>(null);

  // 普通用户空间:审核状态与备注隐藏(用户输入即确认);作者/作品提供可见性,
  // 作品额外提供评分(推荐/不推荐)与评价(长文本);admin 保持策展语义。
  const fields = FIELDS[kind].filter(
    (f) => !(!isAdmin && (f.key === "reviewStatus" || f.key === "note"))
  );
  if (!isAdmin && kind === "works") {
    // 客观信息(标题/语言/作者/年份/体裁)之后,用细分隔线划出「个人笔记」分组
    fields.push({ key: "__divider", label: "个人笔记", type: "divider" });
    fields.push({ key: "readingStatus", label: "阅读状态", type: "readingStatus" });
    fields.push({ key: "recommendation", label: "评分", type: "recommendation" });
    fields.push({ key: "review", label: "评价", type: "textarea", maxLength: 2000 });
  }

  const selfId = mode === "edit" ? initial.id : undefined;
  const fieldHasDup = (field: string, value: string): boolean => {
    const list = kind === "authors" ? authorsList : worksList;
    const v = String(value || "").trim().toLowerCase();
    if (!v) return false;
    return list.some(
      (r) =>
        (r as unknown as Record<string, unknown>).id !== selfId &&
        String((r as unknown as Record<string, unknown>)[field] || "").trim().toLowerCase() === v
    );
  };
  const edgePairHasDup = (s: string, t: string): boolean => {
    if (!s || !t) return false;
    // 编辑模式排除自身:同一对关系不能与「其他」涟漪重复
    return edgesList.some(
      (r) => r.id !== selfId && r.source_work_id === s && r.target_work_id === t
    );
  };

  const clearDupHint = (key: string) => {
    setDupHints((h) => {
      if (!h[key]) return h;
      const next = { ...h };
      delete next[key];
      return next;
    });
  };

  // 选中本空间已有数据:提示已存在(新增必然是新的),不阻止继续修改
  const markExisting = (field: string, label: string) =>
    setDupHints((h) => ({
      ...h,
      [field]: `「${label}」已存在,请勿重复新增(可到数据管理编辑)`,
    }));

  const save = () => {
    for (const f of fields) {
      if (f.required && !String(form[f.key] || "").trim()) {
        setFormError("请填写「" + f.label + "」");
        return;
      }
      if (
        f.type === "number" &&
        (f.min != null || f.max != null) &&
        form[f.key] !== "" &&
        form[f.key] != null
      ) {
        const n = Number(form[f.key]);
        if (
          !Number.isInteger(n)
          || (f.min != null && n < f.min)
          || (f.max != null && n > f.max)
        ) {
          setFormError("「" + f.label + "」需为 " + f.min + "–" + f.max + " 之间的整数");
          return;
        }
      }
    }
    // 新增时,原文名/原著标题命中本空间已有数据 → 禁止保存(选中下拉即触发)
    if (mode === "add") {
      const dupField =
        kind === "authors" ? "originalName" : kind === "works" ? "originalTitle" : null;
      if (dupField) {
        const list = kind === "authors" ? authorsList : worksList;
        const v = String(form[dupField] || "").trim().toLowerCase();
        const hit = list.some(
          (r) =>
            !(r as unknown as Record<string, unknown>).deletedAt &&
            String((r as unknown as Record<string, unknown>)[dupField] || "").trim().toLowerCase() === v
        );
        if (v && hit) {
          const msg = "该数据已存在,请勿重复新增(可到数据管理编辑)";
          setDupHints((h) => ({ ...h, [dupField]: msg }));
          setFormError(msg);
          return;
        }
      }
    }
    setFormError("");
    const payload = Object.fromEntries(
      Object.entries(form).map(([k, v]) => [k, typeof v === "string" ? (v.trim() || null) : v])
    );
    const url = mode === "edit"
      ? apiBase + "/" + kind + "/" + encodeURIComponent(initial.id!)
      : apiBase + "/" + kind;
    fetch(url, {
      method: mode === "edit" ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((r) => r.json().then((d) => ({ ok: r.ok, status: r.status, data: d })))
      .then((res) => {
        if (!res.ok) {
          if (res.status === 409) {
            setFormError(res.data.detail || "数据已被其他人修改");
            setConfirmReload(true);
            return;
          }
          setFormError(res.data.detail || "保存失败");
          return;
        }
        onSaved(res.data.row);
      })
      .catch((e) => setFormError("请求失败: " + e.message));
  };

  return (
    <div id="admin-modal" style={{ display: "flex" }}>
      <div className="admin-modal-card">
        <h3>
          {mode === "edit" ? "编辑" : "新增"} {KIND_LABELS[kind]}
        </h3>
        <div id="admin-form">
          {fields.map((f) => {
            if (mode === "add" && f.key === "reviewStatus") return null; // 新增弹窗不显示审核状态
            if (kind === "authors" && f.key === "originalName" && mode === "add") {
              return (
                <label key={f.key}>
                  <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                  <OwnSuggestField
                    value={form[f.key] || ""}
                    options={authorsList.filter((a) => !a.deletedAt)}
                    getLabel={ownAuthorLabel}
                    getFill={(a) => a.originalName || ownAuthorLabel(a)}
                    placeholder="输入原文名(已有数据会提示)"
                    onChange={(v) => { setForm({ ...form, [f.key]: v }); clearDupHint(f.key); }}
                    onPickExisting={(o) => markExisting(f.key, o.originalName || ownAuthorLabel(o))}
                  />
                  {dupHints[f.key] && <div className="dup-hint">{dupHints[f.key]}</div>}
                </label>
              );
            }
            if (kind === "works" && f.key === "originalTitle" && mode === "add") {
              return (
                <label key={f.key}>
                  <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                  <OwnSuggestField
                    value={form[f.key] || ""}
                    options={worksList.filter((w) => !w.deletedAt)}
                    getLabel={ownWorkLabel}
                    getFill={(w) => w.originalTitle || ownWorkLabel(w)}
                    placeholder="输入原著标题(已有数据会提示)"
                    maxLength={200}
                    onChange={(v) => { setForm({ ...form, [f.key]: v }); clearDupHint(f.key); }}
                    onPickExisting={(o) => markExisting(f.key, o.originalTitle || ownWorkLabel(o))}
                  />
                  {dupHints[f.key] && <div className="dup-hint">{dupHints[f.key]}</div>}
                </label>
              );
            }
            if (f.type === "workPicker") {
              const dup =
                kind === "edges" && edgePairHasDup(form.source_work_id, form.target_work_id)
                  ? "该涟漪关系已存在"
                  : "";
              return (
                <label key={f.key}>
                  <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                  <WorkPicker
                    value={form[f.key] || ""}
                    onChange={(v) => {
                      setForm({ ...form, [f.key]: v });
                      clearDupHint(f.key);
                    }}
                    worksList={worksList}
                    placeholder="输入筛选并选择…"
                    onAddNew={(query) => setWorkAdd({ field: f.key, query })}
                  />
                  {dup && <div className="dup-hint">{dup}</div>}
                </label>
              );
            }
            if (f.type === "authorPicker") {
              return (
                <label key={f.key}>
                  <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                  <AuthorPicker
                    value={form[f.key] || ""}
                    onChange={(v) => setForm({ ...form, [f.key]: v })}
                    authorsList={authorsList}
                    placeholder="输入筛选作者,可多选…"
                    onAddNew={(query) => setAuthorAdd(query)}
                  />
                </label>
              );
            }
            if (f.type === "languagePicker") {
              return (
                <label key={f.key}>
                  <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                  <CodePicker
                    value={form[f.key] || ""}
                    onChange={(v) => setForm({ ...form, [f.key]: v })}
                    options={LANG_OPTIONS}
                    getLabel={langLabel}
                    placeholder="输入中文或代码筛选…"
                    emptyWarn="没有匹配的语言,只能选择列表中的语言"
                  />
                </label>
              );
            }
            if (f.type === "countryPicker") {
              return (
                <label key={f.key}>
                  <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                  <CodePicker
                    value={form[f.key] || ""}
                    onChange={(v) => setForm({ ...form, [f.key]: v })}
                    options={COUNTRY_OPTIONS}
                    getLabel={countryLabel}
                    placeholder="输入中文或代码筛选…"
                    emptyWarn="没有匹配的国家/地区,只能选择列表中的国家/地区"
                  />
                </label>
              );
            }
            if (f.type === "textarea") {
              return (
                <label key={f.key} className="full">
                  <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                  <textarea
                    value={form[f.key] || ""}
                    maxLength={f.maxLength}
                    onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                  />
                </label>
              );
            }
            if (f.type === "recommendation") {
              return (
                <label key={f.key}>
                  <span>{f.label}</span>
                  <select
                    value={form[f.key] || ""}
                    onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                  >
                    <option value="">请选择…</option>
                    <option value="recommend">推荐</option>
                    <option value="not_recommend">不推荐</option>
                  </select>
                </label>
              );
            }
            if (f.type === "divider") {
              return (
                <div key={f.key} className="form-divider" role="separator">
                  <span>{f.label}</span>
                </div>
              );
            }
            if (f.type === "readingStatus") {
              return (
                <label key={f.key}>
                  <span>{f.label}</span>
                  <select
                    value={form[f.key] || ""}
                    onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                  >
                    <option value="">请选择…</option>
                    <option value="read">已读</option>
                    <option value="reading">在读</option>
                    <option value="unread">未读</option>
                  </select>
                </label>
              );
            }
            if (f.type === "select") {
              return (
                <label key={f.key}>
                  <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                  <select
                    value={form[f.key] || ""}
                    onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                  >
                    <option value="">请选择…</option>
                    {(f.options || []).map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                </label>
              );
            }
            return (
              <label key={f.key}>
                <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                <input
                  type={f.type === "number" ? "number" : "text"}
                  maxLength={f.maxLength}
                  min={f.min}
                  max={f.max}
                  step={f.type === "number" ? (f.step != null ? f.step : 1) : undefined}
                  value={form[f.key] ?? ""}
                  onChange={(e) => {
                    setForm({ ...form, [f.key]: e.target.value });
                    clearDupHint(f.key);
                  }}
                  onBlur={() => {
                    if (!DUP_FIELDS[kind].includes(f.key)) return;
                    const msg = fieldHasDup(f.key, form[f.key]) ? "该「" + f.label + "」已存在" : "";
                    setDupHints((h) => {
                      const next = { ...h };
                      if (msg) next[f.key] = msg;
                      else delete next[f.key];
                      return next;
                    });
                  }}
                />
                {dupHints[f.key] && <div className="dup-hint">{dupHints[f.key]}</div>}
              </label>
            );
          })}
        </div>
        {formError && <div id="admin-form-errors">{formError}</div>}
        <div className="admin-modal-actions">
          {mode === "edit" && onDelete && (
            <button className="del" onClick={() => onDelete(initial as AdminRow)}>删除</button>
          )}
          <div className="admin-modal-actions-right">
            <button onClick={save}>保存</button>
            <button onClick={onClose}>取消</button>
          </div>
        </div>
      </div>
      {confirmReload && (
        <div id="auth-modal">
          <div className="auth-modal-card">
            <h3>版本冲突</h3>
            <p>数据已被其他人修改,是否重新加载最新数据?(你的修改将丢失)</p>
            <div className="admin-modal-actions">
              <button
                onClick={() => {
                  setConfirmReload(false);
                  if (onReload) onReload();
                }}
              >
                确认
              </button>
              <button onClick={() => setConfirmReload(false)}>取消</button>
            </div>
          </div>
        </div>
      )}
      {authorAdd && (
        <NodeFormModal
          kind="authors"
          mode="add"
          initial={{ originalName: authorAdd }} // 只预填原著名,中文名留空由用户填写
          apiBase={apiBase}
          authorsList={authorsList}
          worksList={worksList}
          edgesList={edgesList}
          isAdmin={isAdmin}
          onClose={() => setAuthorAdd(null)}
          onSaved={(row) => {
            const prev = String(form.author_id || "").trim();
            // 新作者加入当前作品:多作者用逗号拼接(与 AuthorPicker 的 value 格式一致)
            setForm({ ...form, author_id: prev ? `${prev},${row.id}` : row.id });
            if (onAuthorAdded) onAuthorAdded(row as AuthorRow); // 通知父级刷新作者列表,让新作者立即可见
            setAuthorAdd(null);
          }}
        />
      )}
      {workAdd && (
        <NodeFormModal
          kind="works"
          mode="add"
          initial={{ originalTitle: workAdd.query }} // 只预填原著标题,其余由用户填写
          apiBase={apiBase}
          authorsList={authorsList}
          worksList={worksList}
          edgesList={edgesList}
          isAdmin={isAdmin}
          onClose={() => setWorkAdd(null)}
          onSaved={(row) => {
            // 新作品填入当前涟漪的源/目标字段,立即可作为引用目标
            setForm({ ...form, [workAdd.field]: row.id });
            if (onWorkAdded) onWorkAdded(row as WorkRow); // 通知父级刷新作品列表
            setWorkAdd(null);
          }}
        />
      )}
    </div>
  );
}
