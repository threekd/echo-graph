import { useCallback, useEffect, useRef, useState } from "react";
import { useApp } from "../store";
import {
  AuthorPicker,
  CodePicker,
  COUNTRY_OPTIONS,
  countryLabel,
  LANG_OPTIONS,
  langLabel,
  authorLabelOf,
  workLabel,
  WorkPicker,
} from "./admin/pickers";
import { applyAdminQuery } from "./admin/query";

type Kind = "authors" | "works" | "edges";

const KINDS: { key: Kind; label: string }[] = [
  { key: "authors", label: "作者" },
  { key: "works", label: "作品" },
  { key: "edges", label: "涟漪" },
];

const COLS: Record<Kind, { key: string; label: string }[]> = {
  authors: [
    { key: "Name_CN", label: "中文名" },
    { key: "originalName", label: "原文名" },
    { key: "nationality", label: "国籍" },
    { key: "reviewStatus", label: "审核状态" },
  ],
  works: [
    { key: "Title_CN", label: "中文名" },
    { key: "originalTitle", label: "原著标题" },
    { key: "author_id", label: "作者" },
    { key: "publicationYear", label: "年份" },
    { key: "reviewStatus", label: "审核状态" },
  ],
  edges: [
    { key: "source_work_id", label: "源作品" },
    { key: "target_work_id", label: "目标作品" },
    { key: "reviewStatus", label: "审核" },
    { key: "evidenceSource", label: "出处" },
  ],
};

// 表单字段配置
const FIELDS: Record<Kind, any[]> = {
  authors: [
    { key: "originalName", label: "原文名", required: true },
    { key: "nationality", label: "国籍", type: "countryPicker" },
    { key: "Name_CN", label: "中文名", required: true },
    { key: "Name_EN", label: "英文名" },
    { key: "birthYear", label: "出生年份", type: "number", min: -9999, max: 9999 },
    { key: "deathYear", label: "去世年份", type: "number", min: -9999, max: 9999 },
    { key: "reviewStatus", label: "审核状态", type: "select", options: ["draft", "reviewed", "rejected"] },
  ],
  works: [
    { key: "language", label: "原著语言", required: true, type: "languagePicker" },
    { key: "originalTitle", label: "原著标题", required: true },
    { key: "Title_CN", label: "中文名", required: true },
    { key: "Title_EN", label: "英文名" },
    { key: "Title_Other", label: "其他标题" },
    { key: "author_id", label: "作者", type: "authorPicker" },
    { key: "publicationYear", label: "出版年份", type: "number" },
    { key: "creationYear", label: "创作年份", type: "number" },
    { key: "genre", label: "体裁", type: "select", options: ["Fiction", "Non-fiction", "Poetry", "Drama"] },
    { key: "reviewStatus", label: "审核状态", type: "select", options: ["draft", "reviewed", "rejected"] },
  ],
  edges: [
    { key: "source_work_id", label: "源作品", required: true, type: "workPicker" },
    { key: "target_work_id", label: "目标作品", required: true, type: "workPicker" },
    { key: "evidence", label: "原文片段", required: true, type: "textarea" },
    { key: "evidenceSource", label: "出处" },
    { key: "note", label: "备注" },
    { key: "reviewStatus", label: "审核", type: "select", options: ["draft", "reviewed", "rejected"] },
  ],
};

// 边有独立 id;source:target 仅作历史数据的兜底复合标识
function edgeKey(r: any): string {
  return (r.source_work_id || "") + ":" + (r.target_work_id || "");
}

export default function Admin() {
  const { state, dispatch } = useApp();
  const [kind, setKind] = useState<Kind>("authors");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [textFilters, setTextFilters] = useState<Record<string, string>>({});
  const [warnings, setWarnings] = useState<any>(null);
  const [dupHints, setDupHints] = useState<Record<string, string>>({});
  const [modal, setModal] = useState<any>(null); // { mode: "add" | "edit", row: {} }
  const [form, setForm] = useState<any>({});
  const [formError, setFormError] = useState("");
  const [authOpen, setAuthOpen] = useState(false);
  const [authInput, setAuthInput] = useState("");
  const [authError, setAuthError] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [token, setToken] = useState(() => {
    try { return sessionStorage.getItem("echo_graph_admin_token") || ""; } catch { return ""; }
  });

  const authFetch = useCallback((url: string, options: RequestInit = {}) => {
    const headers = new Headers(options.headers || {});
    if (token) headers.set("Authorization", "Bearer " + token);
    return fetch(url, { ...options, headers });
  }, [token]);

  const handleAuthError = (r: Response): boolean => {
    if (r.status === 401 || r.status === 403) {
      setStatus("管理令牌无效或缺失,请点击「获取授权」重新授权");
      return true;
    }
    return false;
  };

  // 打开授权对话框
  const openAuth = () => {
    setAuthInput("");
    setAuthError("");
    setAuthOpen(true);
  };

  // 校验令牌:有效则保存并授权,「获取授权」变为「已授权」
  const doAuthorize = () => {
    const value = authInput.trim();
    if (!value) {
      setAuthError("请输入令牌");
      return;
    }
    setAuthBusy(true);
    fetch("/api/admin/data", { headers: { Authorization: "Bearer " + value } })
      .then((r) => {
        if (r.status === 401 || r.status === 403) {
          setAuthError("令牌无效,请重试");
          return null;
        }
        if (!r.ok) {
          setAuthError("校验失败(状态码 " + r.status + ")");
          return null;
        }
        return r.json();
      })
      .then((d) => {
        if (!d) return;
        try { sessionStorage.setItem("echo_graph_admin_token", value); } catch { /* ignore */ }
        setToken(value); // token 变化后 load() 会随 useEffect 自动重新拉取数据
        setAuthOpen(false);
        setAuthInput("");
        setStatus("已授权");
      })
      .catch((e) => setAuthError("校验失败: " + e.message))
      .finally(() => setAuthBusy(false));
  };

  const load = useCallback(() => {
    setLoading(true);
    authFetch("/api/admin/data")
      .then((r) => {
        if (!r.ok) {
          handleAuthError(r);
          setLoading(false);
          return null;
        }
        return r.json();
      })
      .then((d) => {
        if (d) {
          setData(d);
          setWarnings(d.warnings || null);
          setLoading(false);
        }
      })
      .catch((e) => { setStatus("加载失败: " + e.message); setLoading(false); });
  }, [authFetch]);

  useEffect(() => { load(); }, [load]);

  // 固定筛选行:实测表头行高度,作为筛选行的 sticky 吸附偏移
  const tableRef = useRef<HTMLTableElement | null>(null);
  useEffect(() => {
    const table = tableRef.current;
    const firstRow = table?.querySelector("thead tr") as HTMLElement | null;
    if (table && firstRow) {
      table.style.setProperty("--filter-sticky-top", firstRow.offsetHeight + "px");
    }
  }, [kind, data]);

  if (!state.adminOpen) return null;

  const allRows: any[] = data ? data[kind] || [] : [];
  const cols = COLS[kind];
  const counts = data ? data.counts || {} : {};

  // 每类数据的可筛选列:select 为精确下拉,text 为按列搜索框
  const filterCols: Record<Kind, { key: string; type: "select" | "text" }[]> = {
    authors: [
      { key: "reviewStatus", type: "select" },
      { key: "nationality", type: "select" },
      { key: "Name_CN", type: "text" },
      { key: "originalName", type: "text" },
    ],
    works: [
      { key: "reviewStatus", type: "select" },
      { key: "genre", type: "select" },
      { key: "language", type: "select" },
      { key: "Title_CN", type: "text" },
      { key: "originalTitle", type: "text" },
      { key: "author_id", type: "text" },
      { key: "publicationYear", type: "text" },
    ],
    edges: [
      { key: "reviewStatus", type: "select" },
      { key: "source_work_id", type: "text" },
      { key: "target_work_id", type: "text" },
      { key: "evidenceSource", type: "text" },
    ],
  };
  const uniqueValues = (key: string): string[] =>
    Array.from(new Set(allRows.map((r) => String(r[key] || "")).filter(Boolean))).sort((a, b) => a.localeCompare(b));

  const toggleSort = (key: string) => {
    setSort((prev) => {
      if (prev && prev.key === key) return prev.dir === 1 ? { key, dir: -1 } : null;
      return { key, dir: 1 };
    });
  };

  const switchKind = (k: Kind) => {
    setKind(k);
    setModal(null);
    setFilters({});
    setTextFilters({});
    setSort(null);
  };

  const openAdd = () => {
    setForm({ reviewStatus: "draft" }); // 新增默认草稿(表单中不展示该字段)
    setFormError("");
    setModal({ mode: "add", row: {} });
  };

  const openEdit = (row: any) => {
    setForm({ ...row });
    setFormError("");
    setModal({ mode: "edit", row });
  };

  const doDelete = (id: string) => {
    if (!window.confirm("确认删除「" + id + "」?(软删除,可恢复)")) return;
    authFetch("/api/admin/" + kind + "/" + encodeURIComponent(id), { method: "DELETE" })
      .then((r) => r.json())
      .then((d) => {
        setStatus(d.ok ? "已软删除" : (d.detail || "删除失败"));
        setWarnings(d.warnings || null);
        load();
      })
      .catch((e) => setStatus("删除失败: " + e.message));
  };

  const doRestore = (id: string) => {
    const row = allRows.find((r) => (r.id || edgeKey(r)) === id);
    if (!row) return;
    authFetch("/api/admin/" + kind + "/" + encodeURIComponent(id), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...row, deletedAt: null }),
    })
      .then((r) => r.json())
      .then((d) => {
        setStatus(d.ok ? "已恢复,需重新导入 Neo4j 后生效" : (d.detail || "恢复失败"));
        setWarnings(d.warnings || null);
        load();
      })
      .catch((e) => setStatus("恢复失败: " + e.message));
  };

  const doImport = () => {
    if (!window.confirm("将 data/real/*.csv 写入 Neo4j(增量合并),继续?")) return;
    setStatus("导入中…");
    authFetch("/api/admin/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ wipe: false, version: "1.1" }),
    })
      .then((r) => r.json())
      .then((d) => {
        setStatus(d.ok ? "导入完成" : (d.detail || "导入失败"));
        setTimeout(() => window.location.reload(), 1200);
      })
      .catch((e) => setStatus("导入失败: " + e.message));
  };

  const saveForm = () => {
    // 前端必填校验
    const fields = FIELDS[kind];
    for (const f of fields) {
      if (f.required && !String(form[f.key] || "").trim()) {
        setFormError("请填写「" + f.label + "」");
        return;
      }
      if (f.type === "number" && (f.min != null || f.max != null) && form[f.key] !== "" && form[f.key] != null) {
        const n = Number(form[f.key]);
        if (!Number.isInteger(n) || n < f.min || n > f.max) {
          setFormError("「" + f.label + "」需为 " + f.min + "–" + f.max + " 之间的整数");
          return;
        }
      }
    }
    setFormError("");
    // 基础清洗:字符串去首尾空白,空串统一归一为 null
    // (同时避免数字/日期字段清空后发送 "" 触发后端 int 解析失败)
    const payload = Object.fromEntries(
      Object.entries(form).map(([k, v]) => [k, typeof v === "string" ? (v.trim() || null) : v])
    );
    const url = modal.mode === "edit"
      ? "/api/admin/" + kind + "/" + encodeURIComponent(modal.row.id || edgeKey(modal.row))
      : "/api/admin/" + kind;
    authFetch(url, {
      method: modal.mode === "edit" ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((r) => r.json().then((d) => ({ ok: r.ok, data: d })))
      .then((res) => {
        if (!res.ok) {
          setFormError(res.data.detail || "保存失败");
          return;
        }
        setModal(null);
        setStatus(modal.mode === "edit" ? "已更新" : "已新增");
        setWarnings(res.data.warnings || null);
        load();
      })
      .catch((e) => setFormError("请求失败: " + e.message));
  };

  const worksList = data ? data.works || [] : [];
  const authorsList = data ? data.authors || [] : [];
  const worksById: Record<string, any> = {};
  const authorsById: Record<string, any> = {};
  worksList.forEach((w: any) => { worksById[w.id] = w; });
  authorsList.forEach((a: any) => { authorsById[a.id] = a; });

  // 单元格显示值(与表格渲染一致,排序/筛选共用)
  const cellValue = (r: any, key: string): string => {
    if (kind === "edges" && (key === "source_work_id" || key === "target_work_id")) {
      const w = worksById[r[key]];
      return w ? workLabel(w) : String(r[key] ?? "");
    }
    if (kind === "works" && key === "author_id") {
      return String(r.author_id || "")
        .split(",")
        .filter(Boolean)
        .map((id: string) => {
          const a = authorsById[id];
          return a ? authorLabelOf(a) : id;
        })
        .join("、");
    }
    const v = r[key];
    return v == null ? "" : String(v);
  };

  const rows = applyAdminQuery(allRows, {
    filters,
    textFilters,
    sort,
    cellValue,
  });

  // ---- 去重即时提示(L2):表单字段失焦 / 涟漪对选定后本地比对 ----
  const dupFields: Record<Kind, string[]> = {
    authors: ["Name_CN", "originalName"],
    works: ["Title_CN", "originalTitle"],
    edges: [],
  };
  const selfId = modal?.mode === "edit" ? modal.row.id : undefined;
  const fieldHasDup = (field: string, value: string): boolean => {
    const list = kind === "authors" ? authorsList : worksList;
    const v = String(value || "").trim().toLowerCase();
    if (!v) return false;
    return list.some((r: any) => r.id !== selfId && String(r[field] || "").trim().toLowerCase() === v);
  };
  const edgePairHasDup = (s: string, t: string): boolean => {
    if (!s || !t || !data) return false;
    return data.edges.some((r: any) => r.id !== selfId && r.source_work_id === s && r.target_work_id === t);
  };
  const edgeDupMsg =
    kind === "edges" && modal && edgePairHasDup(form.source_work_id, form.target_work_id)
      ? "该涟漪关系已存在"
      : "";

  const clearDupHint = (key: string) => {
    setDupHints((h) => {
      if (!h[key]) return h;
      const next = { ...h };
      delete next[key];
      return next;
    });
  };

  return (
    <div id="admin-overlay">
      <div className="admin-shell">
        <div className="admin-head">
          <div className="admin-head-left">
            <h2>数据管理</h2>
            <div className="admin-tabs">
              {KINDS.map((k) => (
                <button
                  key={k.key}
                  className={"admin-tab" + (kind === k.key ? " active" : "")}
                  data-kind={k.key}
                  onClick={() => switchKind(k.key)}
                >
                  {k.label} <span className="cnt">{counts[k.key] != null ? counts[k.key] : (data ? data[k.key].length : "")}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="admin-actions">
            <button id="btn-auth" className={token ? "authed" : ""} onClick={openAuth}>
              {token ? "已授权" : "获取授权"}
            </button>
            <button onClick={openAdd}>＋ 新增</button>
            <button onClick={doImport}>提交</button>
            <button id="admin-close" onClick={() => dispatch({ type: "SET_ADMIN", open: false })}>关闭</button>
          </div>
        </div>
        <div id="admin-status">{status}</div>
        {warnings && Boolean(warnings.duplicateAuthorNames?.length || warnings.duplicateWorkTitles?.length || warnings.duplicateEdgePairs?.length) && (
          <div id="admin-warnings">
            ⚠ 重复提醒:
            {warnings.duplicateAuthorNames?.length ? " 作者名:" + warnings.duplicateAuthorNames.join("、") : ""}
            {warnings.duplicateWorkTitles?.length ? " 作品标题:" + warnings.duplicateWorkTitles.join("、") : ""}
            {warnings.duplicateEdgePairs?.length ? " 涟漪对:" + warnings.duplicateEdgePairs.join("、") : ""}
          </div>
        )}
        {authOpen && (
          <div id="auth-modal">
            <div className="auth-modal-card">
              <h3>请输入令牌</h3>
              <input
                type="password"
                placeholder="管理令牌"
                value={authInput}
                autoFocus
                onChange={(e) => {
                  setAuthInput(e.target.value);
                  setAuthError("");
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") doAuthorize();
                  if (e.key === "Escape") setAuthOpen(false);
                }}
              />
              {authError && <div className="auth-error">{authError}</div>}
              <div className="admin-modal-actions">
                <button onClick={doAuthorize} disabled={authBusy}>{authBusy ? "校验中…" : "确认"}</button>
                <button onClick={() => setAuthOpen(false)}>取消</button>
              </div>
            </div>
          </div>
        )}
        <div className="admin-body">
          {loading ? <p>加载中…</p> : (
            <table id="admin-table" ref={tableRef}>
              <thead>
                <tr>
                  {cols.map((c) => {
                    const active = sort?.key === c.key;
                    const icon = active ? (sort!.dir === 1 ? "▲" : "▼") : "↕";
                    return (
                      <th
                        key={c.key}
                        className={"sortable" + (active ? " active" : "")}
                        onClick={() => toggleSort(c.key)}
                        title="点击排序(再点切换升降序)"
                      >
                        {c.label} <span className="sort-icon">{icon}</span>
                      </th>
                    );
                  })}
                  <th>操作</th>
                </tr>
                <tr className="filter-row">
                  {cols.map((c) => {
                    const fc = filterCols[kind].find((f) => f.key === c.key);
                    if (!fc) {
                      return <td key={c.key} className="filter-cell" />;
                    }
                    if (fc.type === "select") {
                      const options = c.key === "reviewStatus"
                        ? ["draft", "reviewed", "rejected"]
                        : c.key === "genre"
                          ? ["Fiction", "Non-fiction", "Poetry", "Drama"]
                          : uniqueValues(c.key);
                      return (
                        <td key={c.key} className="filter-cell">
                          <select
                            value={filters[c.key] || ""}
                            onChange={(e) => setFilters((f) => ({ ...f, [c.key]: e.target.value }))}
                            title={'筛选「' + c.label + '」'}
                          >
                            <option value="">全部</option>
                            {options.map((o) => <option key={o} value={o}>{o}</option>)}
                          </select>
                        </td>
                      );
                    }
                    return (
                      <td key={c.key} className="filter-cell">
                        <input
                          type="text"
                          placeholder={'搜索' + c.label}
                          value={textFilters[c.key] || ""}
                          onChange={(e) => setTextFilters((f) => ({ ...f, [c.key]: e.target.value }))}
                          title={'搜索「' + c.label + '」'}
                        />
                      </td>
                    );
                  })}
                  <td className="filter-cell" />
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr><td className="empty-cell" colSpan={cols.length + 1}>无匹配记录</td></tr>
                ) : rows.map((r) => (
                  <tr key={r.id || edgeKey(r)} className={r.deletedAt ? "deleted" : ""}>
                    {cols.map((c) => <td key={c.key}>{cellValue(r, c.key)}</td>)}
                    <td>
                      {r.deletedAt
                        ? <button onClick={() => doRestore(r.id || edgeKey(r))}>恢复</button>
                        : (
                          <>
                            <button onClick={() => openEdit(r)}>编辑</button>
                            <button className="del" onClick={() => doDelete(r.id || edgeKey(r))}>删除</button>
                          </>
                        )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {modal && (
        <div id="admin-modal" style={{ display: "flex" }}>
          <div className="admin-modal-card">
            <h3>{modal.mode === "edit" ? "编辑" : "新增"} {KINDS.find((k) => k.key === kind)!.label}</h3>
            <div id="admin-form">
              {FIELDS[kind].map((f) => {
                if (modal.mode === "add" && f.key === "reviewStatus") return null; // 新增弹窗不显示审核状态
                if (f.type === "workPicker") {
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
                      />
                      {edgeDupMsg && <div className="dup-hint">{edgeDupMsg}</div>}
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
                        onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                      />
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
                        {f.options.map((o: any) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    </label>
                  );
                }
                return (
                  <label key={f.key}>
                    <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                    <input
                      type={f.type === "number" ? "number" : "text"}
                      min={f.min}
                      max={f.max}
                      step={f.type === "number" ? (f.step != null ? f.step : 1) : undefined}
                      value={form[f.key] ?? ""}
                      onChange={(e) => {
                        setForm({ ...form, [f.key]: e.target.value });
                        clearDupHint(f.key);
                      }}
                      onBlur={() => {
                        if (!dupFields[kind].includes(f.key)) return;
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
              <button onClick={saveForm}>保存</button>
              <button onClick={() => setModal(null)}>取消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
