/* 贡献数据弹窗:普通用户提交涟漪建议,写入待审核收件箱(不进入正式数据)。 */

import { useMemo, useState } from "react";
import { useApp } from "../store";
import { submitContribution } from "../lib/api";

const EMPTY = {
  source_work: "",
  source_author: "",
  target_work: "",
  target_author: "",
  evidence: "",
  evidence_source: "",
  note: "",
  contact: "",
};

// 组合框:可下拉选择已有数据,也允许自由输入新名称
function SuggestionInput({
  value,
  onChange,
  suggestions,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  suggestions: string[];
  placeholder: string;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const q = value.trim().toLowerCase();
  const filtered = q
    ? suggestions.filter((s) => s.toLowerCase().includes(q)).slice(0, 50)
    : suggestions.slice(0, 50);

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
          if (!filtered.length) return;
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((v) => (v + 1) % filtered.length);
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((v) => (v - 1 + filtered.length) % filtered.length);
          } else if (e.key === "Enter" && active >= 0 && filtered[active]) {
            e.preventDefault();
            onChange(filtered[active]);
            setOpen(false);
            setActive(-1);
          }
        }}
      />
      {open && filtered.length > 0 && (
        <ul className="suggest-results">
          {filtered.map((s, i) => (
            <li
              key={s}
              className={i === active ? "active" : undefined}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => { onChange(s); setOpen(false); setActive(-1); }}
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

  // 已有作品/作者名,用于下拉联想(允许自由输入新名称)
  const workSuggestions = useMemo(() => {
    const seen = new Set<string>();
    state.fullData.nodes.forEach((n) => {
      if (n.type !== "work") return;
      [n.label, n.label_en, n.originalTitle].forEach((v) => { if (v) seen.add(String(v)); });
    });
    return Array.from(seen).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
  }, [state.fullData]);

  const authorSuggestions = useMemo(() => {
    const seen = new Set<string>();
    state.fullData.nodes.forEach((n) => {
      if (n.type !== "author") return;
      [n.label, n.label_en, n.originalName].forEach((v) => { if (v) seen.add(String(v)); });
    });
    return Array.from(seen).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
  }, [state.fullData]);

  if (!state.contributeOpen) return null;

  const set = (key: string, value: string) => setForm((f) => ({ ...f, [key]: value }));

  const doSubmit = () => {
    setError("");
    if (
      !form.source_work.trim() ||
      !form.source_author.trim() ||
      !form.target_work.trim() ||
      !form.target_author.trim() ||
      !form.evidence.trim() ||
      !form.evidence_source.trim()
    ) {
      setError("请填写源作品、源作品作者、目标作品、目标作品作者、原文片段与出处");
      return;
    }
    setBusy(true);
    submitContribution(form)
      .then((d) => {
        if (!d || !d.ok) {
          setError((d && d.detail) || "提交失败");
          return;
        }
        setForm({ ...EMPTY });
        dispatch({ type: "SET_CONTRIBUTE", open: false });
        dispatch({ type: "SET_TOAST", msg: d.msg || "提交成功,审核通过后展示" });
      })
      .catch((e) => setError("请求失败: " + e.message))
      .finally(() => setBusy(false));
  };

  return (
    <div id="admin-modal" style={{ display: "flex" }}>
      <div className="admin-modal-card">
        <h3>贡献数据</h3>
        <p className="contribute-hint">
          感谢你的贡献!提交内容会先进入待审核队列,审核通过后才会展示。作品/作者可下拉选择已有数据,也可直接输入新名称。
        </p>
        <div id="admin-form">
          <label>
            <span>源作品(提及方) <span className="req">*</span></span>
            <SuggestionInput
              value={form.source_work}
              onChange={(v) => set("source_work", v)}
              suggestions={workSuggestions}
              placeholder="如:局外人 / L'Étranger"
            />
          </label>
          <label>
            <span>源作品作者 <span className="req">*</span></span>
            <SuggestionInput
              value={form.source_author}
              onChange={(v) => set("source_author", v)}
              suggestions={authorSuggestions}
              placeholder="如:加缪 / Albert Camus"
            />
          </label>
          <label>
            <span>目标作品(被提及方) <span className="req">*</span></span>
            <SuggestionInput
              value={form.target_work}
              onChange={(v) => set("target_work", v)}
              suggestions={workSuggestions}
              placeholder="如:鼠疫 / La Peste"
            />
          </label>
          <label>
            <span>目标作品作者 <span className="req">*</span></span>
            <SuggestionInput
              value={form.target_author}
              onChange={(v) => set("target_author", v)}
              suggestions={authorSuggestions}
              placeholder="如:加缪 / Albert Camus"
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
            <span>出处(章节/页码/译本) <span className="req">*</span></span>
            <input value={form.evidence_source} onChange={(e) => set("evidence_source", e.target.value)} />
          </label>
          <label className="full">
            <span>备注</span>
            <textarea value={form.note} onChange={(e) => set("note", e.target.value)} />
          </label>
          <label>
            <span>联系方式(选填)</span>
            <input
              value={form.contact}
              onChange={(e) => set("contact", e.target.value)}
              placeholder="邮箱 / 社交账号,便于后续联系"
            />
          </label>
        </div>
        {error && <div id="admin-form-errors">{error}</div>}
        <div className="admin-modal-actions">
          <button onClick={doSubmit} disabled={busy}>{busy ? "提交中…" : "提交"}</button>
          <button onClick={() => dispatch({ type: "SET_CONTRIBUTE", open: false })}>取消</button>
        </div>
      </div>
    </div>
  );
}
