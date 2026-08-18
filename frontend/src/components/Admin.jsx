import { useCallback, useEffect, useRef, useState } from "react";
import { useApp } from "../store.jsx";

const KINDS = [
  { key: "authors", label: "作者" },
  { key: "works", label: "作品" },
  { key: "edges", label: "涟漪" },
];

const COLS = {
  authors: [
    { key: "Name_CN", label: "中文名" },
    { key: "originalName", label: "原文名" },
    { key: "nationality", label: "国籍" },
    { key: "reviewStatus", label: "审核状态" },
  ],
  works: [
    { key: "Title_CN", label: "中文名" },
    { key: "originalTitle", label: "原著标题" },
    { key: "Author", label: "作者" },
    { key: "publicationYear", label: "年份" },
    { key: "reviewStatus", label: "审核状态" },
  ],
  edges: [
    { key: "source_work_id", label: "源作品" },
    { key: "target_work_id", label: "目标作品" },
    { key: "reviewStatus", label: "审核" },
    { key: "deletedAt", label: "删除时间" },
  ],
};

// 表单字段配置
const FIELDS = {
  authors: [
    { key: "originalName", label: "原文名(必填)", required: true },
    { key: "Name_CN", label: "中文名" },
    { key: "Name_EN", label: "英文名" },
    { key: "nationality", label: "国籍" },
    { key: "birthYear", label: "出生年份", type: "number" },
    { key: "deathYear", label: "去世年份", type: "number" },
    { key: "reviewStatus", label: "审核状态", type: "select", options: ["draft", "reviewed", "rejected"] },
  ],
  works: [
    { key: "language", label: "语言(ISO 639-1)", required: true, type: "select", options: ["ar", "de", "el", "en", "es", "fr", "it", "ja", "la", "no", "pt", "ru", "zh", "bn"] },
    { key: "originalTitle", label: "原著标题(必填)", required: true },
    { key: "Title_CN", label: "中文名" },
    { key: "Title_EN", label: "英文名" },
    { key: "Title_Other", label: "其他标题" },
    { key: "Author", label: "作者(逗号分隔多人)" },
    { key: "publicationYear", label: "出版年份", type: "number" },
    { key: "creationYear", label: "创作年份", type: "number" },
    { key: "genre", label: "体裁", type: "select", options: ["Fiction", "Non-fiction", "Poetry", "Drama"] },
    { key: "reviewStatus", label: "审核状态", type: "select", options: ["draft", "reviewed", "rejected"] },
  ],
  edges: [
    { key: "source_work_id", label: "源作品", required: true, type: "workPicker" },
    { key: "target_work_id", label: "目标作品", required: true, type: "workPicker" },
    { key: "evidence", label: "摘抄(必填)", required: true, type: "textarea" },
    { key: "evidenceSource", label: "出处" },
    { key: "evidenceLang", label: "摘抄语言" },
    { key: "note", label: "备注" },
    { key: "reviewStatus", label: "审核", type: "select", options: ["draft", "reviewed", "rejected"] },
  ],
};

function workLabel(w) {
  return w ? (w.Title_CN || "") + " - " + (w.originalTitle || "") : "";
}

// 提及(边)没有独立 id,用 source:target 作为复合标识
function edgeKey(r) {
  return (r.source_work_id || "") + ":" + (r.target_work_id || "");
}

// 作品选择器:输入筛选,只能点选/回车选择已存在条目(不接收自由输入)
function WorkPicker({ value, onChange, worksList, placeholder }) {
  const [query, setQuery] = useState(() => {
    const w = worksList.find((x) => x.id === value);
    return w ? workLabel(w) : "";
  });
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);
  const lastValue = useRef(value);

  useEffect(() => {
    if (value !== lastValue.current) {
      lastValue.current = value;
      const w = worksList.find((x) => x.id === value);
      if (w) setQuery(workLabel(w));
    }
  }, [value, worksList]);

  const q = query.trim().toLowerCase();
  const filtered = q
    ? worksList.filter((w) =>
        [w.Title_CN, w.originalTitle, w.Title_EN, w.Author].filter(Boolean).join(" ").toLowerCase().includes(q)
      )
    : worksList;

  const pick = (w) => {
    onChange(w.id);
    setQuery(workLabel(w));
    setOpen(false);
  };

  return (
    <div className="work-picker" ref={wrapRef}>
      <input
        type="text"
        value={query}
        placeholder={placeholder}
        onChange={(e) => {
          setQuery(e.target.value);
          if (value) onChange(""); // 手动编辑即取消已选,必须重新选择已存在条目
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          const w = worksList.find((x) => x.id === value);
          setQuery(w ? workLabel(w) : "");
          setOpen(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
          if (e.key === "Enter" && open && filtered.length) {
            e.preventDefault();
            pick(filtered[0]);
          }
        }}
      />
      {open && filtered.length > 0 && (
        <ul className="work-picker-results" style={{ display: "block" }}>
          {filtered.slice(0, 80).map((w) => (
            <li
              key={w.id}
              onMouseDown={(e) => {
                e.preventDefault(); // 先于 blur 触发,避免失焦清空
                pick(w);
              }}
            >
              {workLabel(w)}
            </li>
          ))}
        </ul>
      )}
      {open && q && filtered.length === 0 && (
        <div className="work-picker-warn">没有匹配的作品,只能选择已存在条目</div>
      )}
    </div>
  );
}

export default function Admin() {
  const { state, dispatch } = useApp();
  const [kind, setKind] = useState("authors");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [modal, setModal] = useState(null); // { mode: "add" | "edit", row: {} }
  const [form, setForm] = useState({});
  const [formError, setFormError] = useState("");
  const [token, setToken] = useState(() => {
    try { return sessionStorage.getItem("echo_graph_admin_token") || ""; } catch { return ""; }
  });

  const authFetch = useCallback((url, options = {}) => {
    const headers = new Headers(options.headers || {});
    if (token) headers.set("Authorization", "Bearer " + token);
    return fetch(url, { ...options, headers });
  }, [token]);

  const handleAuthError = (r) => {
    if (r.status === 401 || r.status === 403) {
      setStatus("管理令牌无效或缺失,请在上方输入令牌后保存");
      return true;
    }
    return false;
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
      .then((d) => { if (d) { setData(d); setLoading(false); } })
      .catch((e) => { setStatus("加载失败: " + e.message); setLoading(false); });
  }, [authFetch]);

  useEffect(() => { load(); }, [load]);

  if (!state.adminOpen) return null;

  const allRows = data ? data[kind] || [] : [];
  const rows = search.trim()
    ? allRows.filter((r) => Object.values(r).some((v) => v != null && String(v).toLowerCase().includes(search.toLowerCase())))
    : allRows;
  const cols = COLS[kind];
  const counts = data ? data.counts || {} : {};

  const switchKind = (k) => {
    setKind(k);
    setSearch("");
    setModal(null);
  };

  const openAdd = () => {
    setForm({ reviewStatus: "draft" }); // 新增默认草稿(表单中不展示该字段)
    setFormError("");
    setModal({ mode: "add", row: {} });
  };

  const openEdit = (row) => {
    setForm({ ...row });
    setFormError("");
    setModal({ mode: "edit", row });
  };

  const doDelete = (id) => {
    if (!window.confirm("确认删除「" + id + "」?(软删除,可恢复)")) return;
    authFetch("/api/admin/" + kind + "/" + encodeURIComponent(id), { method: "DELETE" })
      .then((r) => r.json())
      .then((d) => { setStatus(d.ok ? "已软删除" : (d.detail || "删除失败")); load(); })
      .catch((e) => setStatus("删除失败: " + e.message));
  };

  const doRestore = (id) => {
    const row = allRows.find((r) => (r.id || edgeKey(r)) === id);
    if (!row) return;
    authFetch("/api/admin/" + kind + "/" + encodeURIComponent(id), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...row, deletedAt: null }),
    })
      .then((r) => r.json())
      .then((d) => { setStatus(d.ok ? "已恢复" : (d.detail || "恢复失败")); load(); })
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

  const exportJson = () => {
    authFetch("/api/admin/export/json")
      .then((r) => {
        if (!r.ok) {
          handleAuthError(r);
          return null;
        }
        return r.blob();
      })
      .then((blob) => {
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "echo-graph-data.json";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      })
      .catch((e) => setStatus("导出失败: " + e.message));
  };

  const exportCsv = () => {
    authFetch("/api/admin/export/csv/" + kind)
      .then((r) => {
        if (!r.ok) {
          handleAuthError(r);
          return null;
        }
        return r.blob();
      })
      .then((blob) => {
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = kind + ".csv";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      })
      .catch((e) => setStatus("导出失败: " + e.message));
  };

  const saveForm = () => {
    // 前端必填校验
    const fields = FIELDS[kind];
    for (const f of fields) {
      if (f.required && !String(form[f.key] || "").trim()) {
        setFormError("请填写「" + f.label + "」");
        return;
      }
    }
    setFormError("");
    const url = modal.mode === "edit"
      ? "/api/admin/" + kind + "/" + encodeURIComponent(modal.row.id || edgeKey(modal.row))
      : "/api/admin/" + kind;
    authFetch(url, {
      method: modal.mode === "edit" ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    })
      .then((r) => r.json().then((d) => ({ ok: r.ok, data: d })))
      .then((res) => {
        if (!res.ok) {
          setFormError(res.data.detail || "保存失败");
          return;
        }
        setModal(null);
        setStatus(modal.mode === "edit" ? "已更新" : "已新增");
        load();
      })
      .catch((e) => setFormError("请求失败: " + e.message));
  };

  const worksList = data ? data.works || [] : [];
  const worksById = {};
  worksList.forEach((w) => { worksById[w.id] = w; });

  return (
    <div id="admin-overlay">
      <div className="admin-shell">
        <div className="admin-head">
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
          <div className="admin-actions">
            <input
              placeholder="搜索…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <input
              type="password"
              placeholder="管理令牌"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              style={{ width: "10em" }}
            />
            <button
              onClick={() => {
                try { sessionStorage.setItem("echo_graph_admin_token", token); } catch { /* ignore */ }
                setStatus("令牌已保存");
                load();
              }}
            >
              保存令牌
            </button>
            <button onClick={openAdd}>＋ 新增</button>
            <button onClick={doImport}>导入到 Neo4j</button>
            <button onClick={exportJson}>导出 JSON</button>
            <button onClick={exportCsv}>导出 CSV</button>
            <button id="admin-close" onClick={() => dispatch({ type: "SET_ADMIN", open: false })}>关闭</button>
          </div>
        </div>
        <div id="admin-status">{status}</div>
        <div className="admin-body">
          {loading ? <p>加载中…</p> : (
            <table id="admin-table">
              <thead>
                <tr>
                  {cols.map((c) => <th key={c.key}>{c.label}</th>)}
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id || edgeKey(r)} className={r.deletedAt ? "deleted" : ""}>
                    {cols.map((c) => {
                      let val = r[c.key] ?? "";
                      if (kind === "edges" && (c.key === "source_work_id" || c.key === "target_work_id")) {
                        const w = worksById[r[c.key]];
                        val = w ? workLabel(w) : String(val);
                      }
                      return <td key={c.key}>{String(val)}</td>;
                    })}
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
            <h3>{modal.mode === "edit" ? "编辑" : "新增"} {KINDS.find((k) => k.key === kind).label}</h3>
            <div id="admin-form">
              {FIELDS[kind].map((f) => {
                if (modal.mode === "add" && f.key === "reviewStatus") return null; // 新增弹窗不显示审核状态
                if (f.type === "workPicker") {
                  return (
                    <label key={f.key}>
                      <span>{f.label}</span>
                      <WorkPicker
                        value={form[f.key] || ""}
                        onChange={(v) => setForm({ ...form, [f.key]: v })}
                        worksList={worksList}
                        placeholder="输入筛选并选择…"
                      />
                    </label>
                  );
                }
                if (f.type === "textarea") {
                  return (
                    <label key={f.key} className="full">
                      <span>{f.label}</span>
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
                      <span>{f.label}</span>
                      <select
                        value={form[f.key] || ""}
                        onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                      >
                        <option value="">请选择…</option>
                        {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    </label>
                  );
                }
                return (
                  <label key={f.key}>
                    <span>{f.label}</span>
                    <input
                      type={f.type === "number" ? "number" : "text"}
                      value={form[f.key] ?? ""}
                      onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                    />
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
